"""
Phase 2 partial lowering from validated BASIS frontend state into BIR.

This stage deliberately builds a stable lowering surface before broadening
statement coverage. The lowering entrypoint consumes validated frontend state,
preserves analysis output into BIR, verifies the result immediately, and keeps
unsupported control flow explicit rather than silently approximating it.

Scope for this stage:
- lower program/module/function/extern metadata from validated frontend state
- lower structured function bodies into explicit BIR blocks and terminators
- lower mutable locals through scoped local-slot bindings
- keep the architecture extensible for later backend lowering

Unsupported today:
- indirect calls
- complex address-of forms that do not map to an addressable storage slot or pointer
"""

import base64
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from ast_defs import (
    AddressOfExpr,
    Annotation,
    ArrayLiteralExpr,
    ArrayRepeatExpr,
    AssignmentExpr,
    BinaryExpr,
    Block as AstBlock,
    BreakStmt,
    CallExpr,
    CastExpr,
    ConstDecl,
    ContinueStmt,
    Declaration,
    DereferenceExpr,
    ExprStmt,
    Expression,
    FieldAccessExpr,
    ForStmt,
    FunctionDecl,
    IdentifierExpr,
    IfStmt,
    ImportDecl,
    IndexExpr,
    LetDecl,
    LiteralExpr,
    Module as AstModule,
    ReturnStmt,
    SourceSpan,
    Statement,
    StructDecl,
    StructLiteralExpr,
    Type as AstType,
    UnaryExpr,
    WhileStmt,
    ExternStaticDecl,
)
from bir.model import (
    Block,
    Diagnostic,
    Extern,
    Function,
    FunctionAttrs,
    FunctionEffects,
    FunctionResources,
    Global,
    Import,
    Instruction,
    InstructionMetadata,
    Module,
    ModuleAttrs,
    ModuleResources,
    Param,
    Program,
    ProgramRuntime,
    SourceLoc,
    StructDef,
    SymbolRef,
    Terminator,
    Type,
    ValueRef,
)
from bir.verify import verify_program
from consteval import BoolConstant, ConstantEvaluator, FloatConstant, IntConstant
from ffi_policy import FfiResolvedExtern
from loop_analysis import LoopAnalyzer
from resource_analysis import FunctionResource, ProgramResourceAnalyzer
from typecheck import (
    ArrayType as ResolvedArrayType,
    BasisType,
    BoolType,
    FloatType,
    IntType,
    PointerType as ResolvedPointerType,
    StructType,
    TypeChecker,
    VoidType,
    VolatilePointerType,
)


class BirLoweringError(ValueError):
    """Raised when validated frontend state cannot yet be lowered into BIR."""


@dataclass(frozen=True)
class LoweringInput:
    program_name: str
    target: str
    profile: str
    entry_module: str
    entry_function: str
    runtime: ProgramRuntime
    modules: Dict[str, AstModule]
    module_paths: Dict[str, str]
    type_checkers: Dict[str, TypeChecker]
    const_evaluators: Dict[str, ConstantEvaluator]
    program_resources: ProgramResourceAnalyzer
    loop_analyzers: Optional[Dict[str, LoopAnalyzer]] = None
    module_order: Optional[List[str]] = None
    ffi_bindings: Optional[Dict[str, FfiResolvedExtern]] = None


@dataclass(frozen=True)
class ModuleLoweringContext:
    name: str
    module: AstModule
    source_path: str
    type_checker: TypeChecker
    const_eval: ConstantEvaluator
    loop_analyzer: Optional[LoopAnalyzer] = None


def _lower_resolved_type(type_node: BasisType) -> Type:
    if isinstance(type_node, IntType):
        return Type(kind=type_node.name)
    if isinstance(type_node, FloatType):
        return Type(kind=type_node.name)
    if isinstance(type_node, BoolType):
        return Type(kind="bool")
    if isinstance(type_node, VoidType):
        return Type(kind="void")
    if isinstance(type_node, ResolvedPointerType):
        return Type(kind="ptr", elem=_lower_resolved_type(type_node.pointee))
    if isinstance(type_node, VolatilePointerType):
        return Type(kind="ptr", elem=_lower_resolved_type(type_node.pointee), volatile=True)
    if isinstance(type_node, ResolvedArrayType):
        if type_node.size is None:
            raise BirLoweringError("BIR lowering requires concrete array sizes")
        return Type(
            kind="array",
            elem=_lower_resolved_type(type_node.element),
            len=type_node.size,
        )
    if isinstance(type_node, StructType):
        from bir.model import Field

        return Type(
            kind="struct",
            name=type_node.name,
            fields=[
                Field(name=field_name, type=_lower_resolved_type(field_type))
                for field_name, field_type in type_node.fields.items()
            ],
        )
    raise BirLoweringError(f"unsupported resolved type '{type_node.__class__.__name__}'")


def _source_loc_from_span(span: SourceSpan, path: str) -> SourceLoc:
    return SourceLoc(
        path=path,
        line=span.start_line,
        column=span.start_col,
        end_line=span.end_line,
        end_column=span.end_col,
    )


def lower_validated_program(input_data: LoweringInput) -> Program:
    """Lower validated frontend state into BIR and verify the result."""
    lowerer = BirLowerer(input_data)
    program = lowerer.lower_program()
    verify_program(program)
    return program


class BirLowerer:
    def __init__(self, input_data: LoweringInput):
        self.input = input_data
        self.function_resources = self.input.program_resources.get_all_resources()
        self.module_contexts = self._build_module_contexts()
        self.struct_type_index: Dict[str, StructType] = {}
        for type_checker in self.input.type_checkers.values():
            for struct_name, struct_type in type_checker.struct_types.items():
                self.struct_type_index.setdefault(struct_name, struct_type)

    def lower_program(self) -> Program:
        modules = [self._lower_module(context) for context in self.module_contexts]
        diagnostics = self._lower_program_diagnostics()

        return Program(
            name=self.input.program_name,
            target=self.input.target,
            profile=self.input.profile,
            entry=SymbolRef(self.input.entry_module, self.input.entry_function),
            runtime=self.input.runtime,
            modules=modules,
            diagnostics=diagnostics,
        )

    def _build_module_contexts(self) -> List[ModuleLoweringContext]:
        ordered_names = self.input.module_order or list(self.input.modules.keys())
        missing = [name for name in ordered_names if name not in self.input.modules]
        if missing:
            raise BirLoweringError(f"module_order contains unknown modules: {', '.join(missing)}")

        contexts: List[ModuleLoweringContext] = []
        for module_name in ordered_names:
            contexts.append(
                ModuleLoweringContext(
                    name=module_name,
                    module=self.input.modules[module_name],
                    source_path=self.input.module_paths.get(module_name, f"<{module_name}>"),
                    type_checker=self.input.type_checkers[module_name],
                    const_eval=self.input.const_evaluators[module_name],
                    loop_analyzer=(self.input.loop_analyzers or {}).get(module_name),
                )
            )
        return contexts

    def _lower_program_diagnostics(self) -> List[Diagnostic]:
        diagnostics = []
        for diag in getattr(self.input.program_resources.diag, "diagnostics", []):
            diagnostics.append(
                Diagnostic(
                    severity=diag.severity,
                    code=diag.err_code,
                    message=diag.message,
                    source_loc=SourceLoc(
                        path=diag.filename,
                        line=diag.line,
                        column=diag.column,
                        end_line=diag.line,
                        end_column=diag.column + max(diag.length - 1, 0),
                    ),
                )
            )
        return diagnostics

    def _lower_module(self, context: ModuleLoweringContext) -> Module:
        imports: List[Import] = []
        structs: List[StructDef] = []
        globals_list: List[Global] = []
        functions: List[Function] = []
        externs: List[Extern] = []
        exports: List[SymbolRef] = []

        module_stack = 0
        module_heap = 0
        module_storage = 0
        module_deepest_path: List[SymbolRef] = []

        for decl in context.module.declarations:
            if isinstance(decl, ImportDecl):
                imports.append(
                    Import(
                        module_name=decl.module_name,
                        items=list(decl.items or []),
                        is_wildcard=decl.is_wildcard,
                    )
                )
            elif isinstance(decl, StructDecl):
                structs.append(self._lower_struct(decl, context.type_checker))
                if decl.visibility == "public":
                    exports.append(SymbolRef(context.name, decl.name))
            elif isinstance(decl, ConstDecl):
                globals_list.append(self._lower_const(decl, context))
                if decl.visibility == "public":
                    exports.append(SymbolRef(context.name, decl.name))
            elif isinstance(decl, ExternStaticDecl):
                globals_list.append(self._lower_extern_static(decl, context.type_checker))
                exports.append(SymbolRef(context.name, decl.name))
            elif isinstance(decl, FunctionDecl):
                qualified_name = self._qualified_name(context.name, decl.name)
                resource = self.function_resources.get(qualified_name)
                if resource is None:
                    raise BirLoweringError(f"missing function resource summary for '{qualified_name}'")

                if decl.is_extern:
                    extern = self._lower_extern(context, decl, resource)
                    externs.append(extern)
                    if decl.visibility == "public":
                        exports.append(SymbolRef(context.name, decl.name))
                    continue

                function = self._lower_function(context, decl, resource)
                functions.append(function)
                if function.visibility == "public":
                    exports.append(SymbolRef(context.name, decl.name))
                if function.visibility == "entry":
                    exports.append(SymbolRef(context.name, decl.name))

                module_stack = max(module_stack, function.resources.stack_max or 0)
                module_heap = max(module_heap, function.resources.heap_max or 0)
                module_storage = max(module_storage, resource.storage_bytes)
                if resource.call_path and len(resource.call_path) >= len(module_deepest_path):
                    module_deepest_path = [self._symbol_ref_from_qualified_name(name) for name in resource.call_path]

        attrs = ModuleAttrs(
            max_memory=context.module.max_memory_bytes or 0,
            max_storage=self._directive_int(context.module.directives, "max_storage"),
            max_storage_objects=self._directive_int(context.module.directives, "max_storage_objects"),
            strict=bool(context.module.directives.get("strict")),
        )

        resources = ModuleResources(
            stack_max=module_stack,
            heap_max=module_heap,
            storage_max=module_storage,
            code_size_estimate=0,
            deepest_call_path=module_deepest_path,
        )

        return Module(
            name=context.name,
            source_path=context.source_path,
            attrs=attrs,
            imports=imports,
            structs=structs,
            exports=exports,
            globals=globals_list,
            functions=functions,
            externs=externs,
            resources=resources,
        )

    def _lower_struct(self, decl: StructDecl, type_checker: TypeChecker) -> StructDef:
        resolved = type_checker.struct_types.get(decl.name)
        if resolved is None:
            raise BirLoweringError(f"missing struct type information for '{decl.name}'")

        from bir.model import Field

        return StructDef(
            name=decl.name,
            visibility=decl.visibility or "private",
            fields=[
                Field(name=field_name, type=_lower_resolved_type(field_type))
                for field_name, field_type in resolved.fields.items()
            ],
        )

    def _lower_const(
        self,
        decl: ConstDecl,
        context: ModuleLoweringContext,
    ) -> Global:
        return Global(
            name=decl.name,
            visibility=decl.visibility or "private",
            type=self._lower_ast_type(context.type_checker, decl.type),
            initializer=self._render_constant(context.const_eval, decl.value),
        )

    def _lower_extern_static(self, decl: ExternStaticDecl, type_checker: TypeChecker) -> Global:
        return Global(
            name=decl.name,
            visibility="public",
            type=self._lower_ast_type(type_checker, decl.type),
            initializer=None,
        )

    def _lower_function(
        self,
        context: ModuleLoweringContext,
        decl: FunctionDecl,
        resource: FunctionResource,
    ) -> Function:
        visibility = (
            "entry"
            if decl.name == self.input.entry_function and context.name == self.input.entry_module
            else (decl.visibility or "private")
        )
        body_lowerer = FunctionBodyLowerer(
            module_name=context.name,
            source_path=context.source_path,
            function_decl=decl,
            type_checker=context.type_checker,
            const_eval=context.const_eval,
            loop_analyzer=context.loop_analyzer,
            fallback_struct_types=self.struct_type_index,
        )

        return Function(
            name=decl.name,
            visibility=visibility,
            params=[self._lower_param(context.type_checker, param) for param in decl.params],
            returns=self._lower_ast_type(context.type_checker, decl.return_type),
            attrs=self._lower_function_attrs(decl.annotations, resource, context.const_eval),
            effects=self._lower_function_effects(resource),
            resources=FunctionResources(
                stack_max=resource.stack_bytes,
                heap_max=resource.heap_bytes,
            ),
            blocks=body_lowerer.lower_body(),
        )

    def _lower_extern(
        self,
        context: ModuleLoweringContext,
        decl: FunctionDecl,
        resource: FunctionResource,
    ) -> Extern:
        binding = (self.input.ffi_bindings or {}).get(f"{context.name}::{decl.name}")
        return Extern(
            name=decl.name,
            visibility=decl.visibility or "private",
            params=[self._lower_param(context.type_checker, param) for param in decl.params],
            returns=self._lower_ast_type(context.type_checker, decl.return_type),
            abi="c",
            symbol_name=decl.extern_symbol or decl.name,
            attrs=self._lower_function_attrs(decl.annotations, resource, context.const_eval),
            effects=self._lower_function_effects(resource),
            resources=FunctionResources(
                stack_max=resource.stack_bytes,
                heap_max=resource.heap_bytes,
            ),
            library_id=(binding.library_id if binding is not None else None),
            trust_level=(binding.trust if binding is not None else None),
            requires_wrappers=(binding.requires_wrappers if binding is not None else False),
            strict_allowed=(binding.strict_allowed if binding is not None else True),
        )

    def _lower_param(self, type_checker: TypeChecker, param) -> Param:
        return Param(name=param.name, type=self._lower_ast_type(type_checker, param.type))

    def _lower_function_attrs(
        self,
        annotations: List[Annotation],
        resource: FunctionResource,
        const_eval: ConstantEvaluator,
    ) -> FunctionAttrs:
        recursion_annotation = self._annotation_int(annotations, "recursion", ("max", "value"), const_eval)
        task_stack_annotation = self._annotation_int(annotations, "task", ("stack", "value"), const_eval)
        task_priority_annotation = self._annotation_int_optional(annotations, "task", ("priority",), const_eval)
        allocates_annotation = self._annotation_int_optional(annotations, "allocates", ("max", "bytes", "value"), const_eval)

        if self._has_annotation(annotations, "deterministic"):
            deterministic_attr = True
        elif self._has_annotation(annotations, "nondeterministic"):
            deterministic_attr = False
        else:
            deterministic_attr = None

        region_name = None
        region_annotation = self._find_annotation(annotations, "region")
        if region_annotation is not None and region_annotation.arguments:
            region_expr = region_annotation.arguments.get("value")
            if isinstance(region_expr, LiteralExpr) and region_expr.kind == "string":
                region_name = region_expr.value

        return FunctionAttrs(
            recursion_max=recursion_annotation or resource.recursion_depth,
            interrupt=self._has_annotation(annotations, "interrupt"),
            task_stack=task_stack_annotation or (resource.task_stack_bytes if resource.task_stack_bytes > 0 else None),
            task_priority=task_priority_annotation,
            inline_hint=self._has_annotation(annotations, "inline"),
            region_name=region_name,
            deterministic=deterministic_attr,
            blocking=self._has_annotation(annotations, "blocking"),
            allocates_max=allocates_annotation,
            reentrant=True if self._has_annotation(annotations, "reentrant") else None,
            isr_safe=True if self._has_annotation(annotations, "isr_safe") else None,
            uses_timer=self._has_annotation(annotations, "uses_timer"),
            may_fail=self._has_annotation(annotations, "may_fail"),
            storage_bytes=self._annotation_int_optional(annotations, "storage", ("max_bytes", "bytes", "value"), const_eval),
            storage_objects=self._annotation_int_optional(annotations, "storage", ("max_objects", "objects"), const_eval),
        )

    def _lower_function_effects(self, resource: FunctionResource) -> FunctionEffects:
        return FunctionEffects(
            deterministic=resource.deterministic,
            blocking=resource.blocking,
            allocates=resource.heap_bytes if resource.heap_bytes > 0 else None,
            uses_storage=(resource.storage_bytes > 0 or resource.storage_objects > 0),
            isr_safe=resource.isr_safe,
        )

    def _lower_ast_type(self, type_checker: TypeChecker, type_node: AstType) -> Type:
        resolved = type_checker._resolve_type(type_node)
        if resolved is None and hasattr(type_node, "name"):
            resolved = self.struct_type_index.get(type_node.name)
        if resolved is None:
            raise BirLoweringError("type lowering requires a resolved type")
        return _lower_resolved_type(resolved)

    def _directive_int(self, directives: Dict[str, object], name: str) -> Optional[int]:
        value = directives.get(name)
        return value if isinstance(value, int) else None

    def _has_annotation(self, annotations: List[Annotation], name: str) -> bool:
        return any(annotation.name == name for annotation in annotations)

    def _find_annotation(self, annotations: List[Annotation], name: str) -> Optional[Annotation]:
        for annotation in annotations:
            if annotation.name == name:
                return annotation
        return None

    def _annotation_int(
        self,
        annotations: List[Annotation],
        name: str,
        keys: Tuple[str, ...],
        const_eval: ConstantEvaluator,
    ) -> Optional[int]:
        annotation = self._find_annotation(annotations, name)
        if annotation is None or not annotation.arguments:
            return None
        for key in keys:
            expr = annotation.arguments.get(key)
            if expr is None:
                continue
            value = const_eval.eval_constant(expr)
            if isinstance(value, IntConstant):
                return value.value
        return None

    def _annotation_int_optional(
        self,
        annotations: List[Annotation],
        name: str,
        keys: Tuple[str, ...],
        const_eval: ConstantEvaluator,
    ) -> Optional[int]:
        try:
            return self._annotation_int(annotations, name, keys, const_eval)
        except Exception:
            return None

    def _render_constant(self, const_eval: ConstantEvaluator, expr: Expression) -> Optional[str]:
        try:
            value = const_eval.eval_constant(expr)
        except Exception:
            return None
        if isinstance(value, IntConstant):
            return str(value.value)
        if isinstance(value, FloatConstant):
            return str(value.value)
        if isinstance(value, BoolConstant):
            return "true" if value.value else "false"
        return None

    def _qualified_name(self, module_name: str, function_name: str) -> str:
        return f"{module_name}::{function_name}"

    def _symbol_ref_from_qualified_name(self, qualified_name: str) -> SymbolRef:
        module_name, function_name = qualified_name.split("::", 1)
        return SymbolRef(module_name, function_name)


@dataclass(frozen=True)
class SlotBinding:
    slot: ValueRef
    type: Type


@dataclass
class PendingBlock:
    name: str
    instructions: List[Instruction]
    terminator: Optional[Terminator] = None


@dataclass(frozen=True)
class LoopControlFrame:
    break_target: str
    continue_target: str


class FunctionBodyLowerer:
    def __init__(
        self,
        module_name: str,
        source_path: str,
        function_decl: FunctionDecl,
        type_checker: TypeChecker,
        const_eval: ConstantEvaluator,
        loop_analyzer: Optional[LoopAnalyzer],
        fallback_struct_types: Optional[Dict[str, StructType]] = None,
    ):
        self.module_name = module_name
        self.source_path = source_path
        self.function_decl = function_decl
        self.type_checker = type_checker
        self.const_eval = const_eval
        self.loop_analyzer = loop_analyzer
        self.fallback_struct_types = fallback_struct_types or {}
        self.blocks: List[PendingBlock] = []
        self.current_block: Optional[PendingBlock] = None
        self.scope_stack: List[Dict[str, SlotBinding]] = []
        self.loop_stack: List[LoopControlFrame] = []
        self.temp_index = 0
        self.block_index = 0
        self.slot_index = 0

    def lower_body(self) -> List[Block]:
        if self.function_decl.body is None:
            raise BirLoweringError(f"function '{self.module_name}::{self.function_decl.name}' has no body to lower")

        self._push_scope()
        entry_block = self._create_block("entry", explicit_name="entry")
        self._switch_to_block(entry_block)
        self._initialize_param_slots()
        self._lower_statements(self.function_decl.body.statements)
        self._pop_scope()

        if self.current_block is not None and self.current_block.terminator is None:
            self._terminate("ret")

        return [
            Block(
                name=block.name,
                instructions=block.instructions,
                terminator=block.terminator or Terminator(kind="unreachable"),
            )
            for block in self.blocks
        ]

    def _lower_statement(self, stmt: Statement):
        if isinstance(stmt, LetDecl):
            slot_type = self._resolve_ast_type(stmt.type)
            binding = self._declare_slot(stmt.name, slot_type)
            if stmt.initializer is not None:
                value_ref, value_type = self._lower_expression(stmt.initializer)
                self._emit_instruction(
                    kind="store",
                    opcode="let",
                    result=None,
                    operands=[binding.slot, value_ref],
                    type=value_type,
                    span=stmt.span,
                    resource_note="let binding",
                )
            return

        if isinstance(stmt, ExprStmt):
            self._lower_expression(stmt.expression)
            return

        if isinstance(stmt, ReturnStmt):
            operands: List[ValueRef] = []
            if stmt.value is not None:
                value_ref, _ = self._lower_expression(stmt.value)
                operands.append(value_ref)
            self._terminate("ret", operands=operands)
            return

        if isinstance(stmt, AstBlock):
            self._push_scope()
            self._lower_statements(stmt.statements)
            self._pop_scope()
            return

        if isinstance(stmt, IfStmt):
            self._lower_if(stmt)
            return

        if isinstance(stmt, ForStmt):
            self._lower_for(stmt)
            return

        if isinstance(stmt, BreakStmt):
            if not self.loop_stack:
                raise BirLoweringError(
                    f"function '{self.module_name}::{self.function_decl.name}' uses break outside a loop"
                )
            self._terminate("br", targets=[self.loop_stack[-1].break_target])
            return

        if isinstance(stmt, ContinueStmt):
            if not self.loop_stack:
                raise BirLoweringError(
                    f"function '{self.module_name}::{self.function_decl.name}' uses continue outside a loop"
                )
            self._terminate("br", targets=[self.loop_stack[-1].continue_target])
            return

        if isinstance(stmt, WhileStmt):
            raise BirLoweringError(
                f"function '{self.module_name}::{self.function_decl.name}' uses '{stmt.__class__.__name__}', "
                "which is not lowered in Phase 2 partial lowering yet"
            )

        raise BirLoweringError(
            f"function '{self.module_name}::{self.function_decl.name}' contains unsupported statement '{stmt.__class__.__name__}'"
        )

    def _lower_statements(self, statements: List[Statement]):
        for statement in statements:
            if self._is_current_block_terminated():
                break
            self._lower_statement(statement)

    def _lower_if(self, stmt: IfStmt):
        merge_block = self._create_block("if_end")
        then_block = self._create_block("if_then")
        false_entry = self._create_block("if_false") if (stmt.elif_branches or stmt.else_block) else merge_block

        condition_ref, _ = self._lower_expression(stmt.condition)
        self._terminate("cond_br", operands=[condition_ref], targets=[then_block.name, false_entry.name])

        self._switch_to_block(then_block)
        self._push_scope()
        self._lower_statements(stmt.then_block.statements)
        self._pop_scope()
        if not self._is_current_block_terminated():
            self._terminate("br", targets=[merge_block.name])

        if stmt.elif_branches:
            self._lower_elif_chain(stmt.elif_branches, stmt.else_block, false_entry, merge_block)
        elif stmt.else_block:
            self._switch_to_block(false_entry)
            self._push_scope()
            self._lower_statements(stmt.else_block.statements)
            self._pop_scope()
            if not self._is_current_block_terminated():
                self._terminate("br", targets=[merge_block.name])

        self._switch_to_block(merge_block)

    def _lower_elif_chain(
        self,
        elif_branches,
        else_block: Optional[AstBlock],
        entry_block: PendingBlock,
        merge_block: PendingBlock,
    ):
        current_condition_block = entry_block

        for index, branch in enumerate(elif_branches):
            self._switch_to_block(current_condition_block)
            condition_ref, _ = self._lower_expression(branch.condition)
            then_block = self._create_block(f"elif_then_{index}")
            has_more = index < len(elif_branches) - 1
            if has_more:
                false_block = self._create_block(f"elif_cond_{index + 1}")
            elif else_block is not None:
                false_block = self._create_block("if_else")
            else:
                false_block = merge_block

            self._terminate("cond_br", operands=[condition_ref], targets=[then_block.name, false_block.name])

            self._switch_to_block(then_block)
            self._push_scope()
            self._lower_statements(branch.block.statements)
            self._pop_scope()
            if not self._is_current_block_terminated():
                self._terminate("br", targets=[merge_block.name])

            current_condition_block = false_block

        if else_block is not None:
            self._switch_to_block(current_condition_block)
            self._push_scope()
            self._lower_statements(else_block.statements)
            self._pop_scope()
            if not self._is_current_block_terminated():
                self._terminate("br", targets=[merge_block.name])

    def _lower_for(self, stmt: ForStmt):
        loop_note = self._loop_resource_note(stmt)
        iterator_type = self._expression_type(stmt.range_start)
        start_ref, _ = self._lower_expression(stmt.range_start)
        end_ref, _ = self._lower_expression(stmt.range_end)

        self._push_scope()
        iterator_binding = self._declare_slot(stmt.iterator_name, iterator_type)
        self._emit_instruction(
            kind="store",
            opcode="for_init",
            result=None,
            operands=[iterator_binding.slot, start_ref],
            type=iterator_type,
            span=stmt.span,
            resource_note=loop_note,
        )

        cond_block = self._create_block("for_cond")
        body_block = self._create_block("for_body")
        continue_block = self._create_block("for_continue")
        exit_block = self._create_block("for_exit")

        self._terminate("br", targets=[cond_block.name])

        self._switch_to_block(cond_block)
        iter_ref = self._emit_instruction(
            kind="load",
            opcode="iter",
            result=self._new_temp(),
            operands=[iterator_binding.slot],
            type=iterator_type,
            span=stmt.span,
            resource_note=loop_note,
        )
        condition_ref = self._emit_instruction(
            kind="compare",
            opcode="<",
            result=self._new_temp(),
            operands=[iter_ref, end_ref],
            type=Type(kind="bool"),
            span=stmt.span,
            resource_note=loop_note,
        )
        self._terminate("cond_br", operands=[condition_ref], targets=[body_block.name, exit_block.name])

        self.loop_stack.append(LoopControlFrame(break_target=exit_block.name, continue_target=continue_block.name))
        self._switch_to_block(body_block)
        self._push_scope()
        self._lower_statements(stmt.body.statements)
        self._pop_scope()
        if not self._is_current_block_terminated():
            self._terminate("br", targets=[continue_block.name])
        self.loop_stack.pop()

        self._switch_to_block(continue_block)
        iter_update_ref = self._emit_instruction(
            kind="load",
            opcode="iter",
            result=self._new_temp(),
            operands=[iterator_binding.slot],
            type=iterator_type,
            span=stmt.span,
            resource_note=loop_note,
        )
        next_ref = self._emit_instruction(
            kind="math",
            opcode="+",
            result=self._new_temp(),
            operands=[iter_update_ref, self._unit_value_ref(iterator_type)],
            type=iterator_type,
            span=stmt.span,
            resource_note=loop_note,
        )
        self._emit_instruction(
            kind="store",
            opcode="for_next",
            result=None,
            operands=[iterator_binding.slot, next_ref],
            type=iterator_type,
            span=stmt.span,
            resource_note=loop_note,
        )
        self._terminate("br", targets=[cond_block.name])

        self._switch_to_block(exit_block)
        self._pop_scope()

    def _lower_expression(self, expr: Expression) -> Tuple[ValueRef, Type]:
        if isinstance(expr, IdentifierExpr):
            expr_type = self._expression_type(expr)
            binding = self._lookup_slot(expr.name)
            if binding is None:
                return ValueRef(expr.name), expr_type
            result = self._new_temp()
            self._emit_instruction(
                kind="load",
                opcode="var",
                result=result,
                operands=[binding.slot],
                type=binding.type,
                span=expr.span,
                resource_note="load local",
            )
            return result, expr_type

        if isinstance(expr, LiteralExpr):
            return self._literal_value_ref(expr), self._expression_type(expr)

        if isinstance(expr, BinaryExpr):
            left_ref, _ = self._lower_expression(expr.left)
            right_ref, _ = self._lower_expression(expr.right)
            result = self._new_temp()
            kind = "compare" if expr.operator in {"==", "!=", "<", "<=", ">", ">="} else "math"
            result_type = self._expression_type(expr)
            self._emit_instruction(
                kind=kind,
                opcode=expr.operator,
                result=result,
                operands=[left_ref, right_ref],
                type=result_type,
                span=expr.span,
            )
            return result, result_type

        if isinstance(expr, UnaryExpr):
            operand_ref, _ = self._lower_expression(expr.operand)
            result = self._new_temp()
            result_type = self._expression_type(expr)
            self._emit_instruction(
                kind="math",
                opcode=expr.operator,
                result=result,
                operands=[operand_ref],
                type=result_type,
                span=expr.span,
            )
            return result, result_type

        if isinstance(expr, CastExpr):
            operand_ref, _ = self._lower_expression(expr.expression)
            result = self._new_temp()
            result_type = self._expression_type(expr)
            self._emit_instruction(
                kind="cast",
                opcode="cast",
                result=result,
                operands=[operand_ref],
                type=result_type,
                span=expr.span,
            )
            return result, result_type

        if isinstance(expr, CallExpr):
            if not isinstance(expr.callee, IdentifierExpr):
                raise BirLoweringError(
                    f"function '{self.module_name}::{self.function_decl.name}' uses an indirect call, "
                    "which is not lowered in Phase 2 partial lowering yet"
                )
            callee_ref = ValueRef(expr.callee.name)
            arg_refs = []
            for argument in expr.arguments:
                arg_ref, _ = self._lower_expression(argument)
                arg_refs.append(arg_ref)
            result_type = self._expression_type(expr)
            result = None if result_type.kind == "void" else self._new_temp()
            self._emit_instruction(
                kind="call",
                opcode=callee_ref.name,
                result=result,
                operands=[callee_ref] + arg_refs,
                type=result_type,
                span=expr.span,
            )
            return result or ValueRef("void"), result_type

        if isinstance(expr, AssignmentExpr):
            assigned_ref, assigned_type = self._lower_assignment(expr)
            return assigned_ref, assigned_type

        if isinstance(expr, AddressOfExpr):
            result_type = self._expression_type(expr)
            if isinstance(expr.operand, IdentifierExpr):
                binding = self._lookup_slot(expr.operand.name)
                if binding is not None:
                    return binding.slot, result_type
            if isinstance(expr.operand, DereferenceExpr):
                operand_ref, _ = self._lower_expression(expr.operand.operand)
                return operand_ref, result_type

            operand_ref, _ = self._lower_expression(expr.operand)
            result = self._new_temp()
            self._emit_instruction(
                kind="address_of",
                opcode="&",
                result=result,
                operands=[operand_ref],
                type=result_type,
                span=expr.span,
            )
            return result, result_type

        if isinstance(expr, DereferenceExpr):
            operand_ref, _ = self._lower_expression(expr.operand)
            result = self._new_temp()
            result_type = self._expression_type(expr)
            self._emit_instruction(
                kind="load",
                opcode="*",
                result=result,
                operands=[operand_ref],
                type=result_type,
                span=expr.span,
            )
            return result, result_type

        if isinstance(expr, FieldAccessExpr):
            base_ref, _ = self._lower_expression(expr.base)
            if expr.base_is_pointer:
                deref_type = self._base_struct_type(expr.base)
                deref_ref = self._emit_instruction(
                    kind="load",
                    opcode="*",
                    result=self._new_temp(),
                    operands=[base_ref],
                    type=deref_type,
                    span=expr.span,
                )
                base_ref = deref_ref
            result = self._new_temp()
            result_type = self._expression_type(expr)
            self._emit_instruction(
                kind="extract",
                opcode=expr.field_name,
                result=result,
                operands=[base_ref],
                type=result_type,
                span=expr.span,
            )
            return result, result_type

        if isinstance(expr, IndexExpr):
            base_ref, _ = self._lower_expression(expr.base)
            index_ref, _ = self._lower_expression(expr.index)
            result = self._new_temp()
            result_type = self._expression_type(expr)
            self._emit_instruction(
                kind="extract",
                opcode="index",
                result=result,
                operands=[base_ref, index_ref],
                type=result_type,
                span=expr.span,
            )
            return result, result_type

        if isinstance(expr, ArrayLiteralExpr):
            return self._lower_array_literal(expr)

        if isinstance(expr, ArrayRepeatExpr):
            return self._lower_array_repeat(expr)

        if isinstance(expr, StructLiteralExpr):
            return self._lower_struct_literal(expr)

        raise BirLoweringError(
            f"function '{self.module_name}::{self.function_decl.name}' contains unsupported expression '{expr.__class__.__name__}'"
        )

    def _expression_type(self, expr: Expression) -> Type:
        expr_type = self.type_checker.expr_types.get(id(expr))
        if expr_type is None:
            if isinstance(expr, LiteralExpr):
                return self._literal_type(expr)
            if isinstance(expr, IdentifierExpr):
                binding = self._lookup_slot(expr.name)
                if binding is not None:
                    return binding.type
                symbol = self.type_checker.module_scope.lookup(expr.name)
                decl_node = getattr(symbol, "decl_node", None) if symbol is not None else None
                if decl_node is not None and hasattr(decl_node, "type"):
                    return self._resolve_ast_type(decl_node.type)
            if isinstance(expr, CallExpr) and isinstance(expr.callee, IdentifierExpr):
                symbol = self.type_checker.module_scope.lookup(expr.callee.name)
                decl_node = getattr(symbol, "decl_node", None) if symbol is not None else None
                if decl_node is not None and hasattr(decl_node, "return_type"):
                    return self._resolve_ast_type(decl_node.return_type)
            if isinstance(expr, AddressOfExpr):
                return Type(kind="ptr", elem=self._expression_type(expr.operand))
            if isinstance(expr, DereferenceExpr):
                operand_type = self._expression_type(expr.operand)
                if operand_type.kind == "ptr" and operand_type.elem is not None:
                    return operand_type.elem
            if isinstance(expr, IndexExpr):
                base_type = self._expression_type(expr.base)
                if base_type.kind == "array" and base_type.elem is not None:
                    return base_type.elem
                if base_type.kind == "ptr" and base_type.elem is not None:
                    return base_type.elem
            raise BirLoweringError(
                f"missing resolved expression type for '{expr.__class__.__name__}' in '{self.module_name}::{self.function_decl.name}'"
            )
        return self._lower_resolved_type(expr_type)

    def _literal_type(self, expr: LiteralExpr) -> Type:
        if expr.kind == "int":
            return Type(kind="i32")
        if expr.kind == "float":
            return Type(kind="f64")
        if expr.kind == "bool":
            return Type(kind="bool")
        if expr.kind == "string":
            return Type(kind="ptr", elem=Type(kind="u8"))
        raise BirLoweringError(
            f"literal kind '{expr.kind}' is not lowered in '{self.module_name}::{self.function_decl.name}'"
        )

    def _lower_resolved_type(self, type_node: BasisType) -> Type:
        return _lower_resolved_type(type_node)

    def _resolve_ast_type(self, type_node: AstType) -> Type:
        resolved = self.type_checker._resolve_type(type_node)
        if resolved is None and hasattr(type_node, "name"):
            resolved = self.fallback_struct_types.get(type_node.name)
        if resolved is None:
            raise BirLoweringError(
                f"function '{self.module_name}::{self.function_decl.name}' contains an unresolved type"
            )
        return self._lower_resolved_type(resolved)

    def _lower_array_literal(self, expr: ArrayLiteralExpr) -> Tuple[ValueRef, Type]:
        result_type = self._expression_type(expr)
        current_ref = self._emit_instruction(
            kind="assign",
            opcode="array_literal",
            result=self._new_temp(),
            operands=[],
            type=result_type,
            span=expr.span,
        )

        for index, element in enumerate(expr.elements):
            element_ref, _ = self._lower_expression(element)
            current_ref = self._emit_instruction(
                kind="insert",
                opcode="index",
                result=self._new_temp(),
                operands=[current_ref, ValueRef(f"literal_i32_{index}"), element_ref],
                type=result_type,
                span=element.span,
            )

        return current_ref, result_type

    def _lower_array_repeat(self, expr: ArrayRepeatExpr) -> Tuple[ValueRef, Type]:
        result_type = self._expression_type(expr)
        default_ref, _ = self._lower_expression(expr.value)
        current_ref = self._emit_instruction(
            kind="assign",
            opcode="array_repeat",
            result=self._new_temp(),
            operands=[default_ref],
            type=result_type,
            span=expr.span,
        )

        for override in expr.overrides:
            index_ref, _ = self._lower_expression(override.index)
            override_ref, _ = self._lower_expression(override.value)
            current_ref = self._emit_instruction(
                kind="insert",
                opcode="index",
                result=self._new_temp(),
                operands=[current_ref, index_ref, override_ref],
                type=result_type,
                span=override.span,
            )

        return current_ref, result_type

    def _lower_struct_literal(self, expr: StructLiteralExpr) -> Tuple[ValueRef, Type]:
        result_type = self._expression_type(expr)
        current_ref = self._emit_instruction(
            kind="assign",
            opcode=f"struct_literal:{expr.struct_name}",
            result=self._new_temp(),
            operands=[],
            type=result_type,
            span=expr.span,
        )

        for field_init in expr.field_inits:
            field_ref, _ = self._lower_expression(field_init.value)
            current_ref = self._emit_instruction(
                kind="insert",
                opcode=field_init.field_name,
                result=self._new_temp(),
                operands=[current_ref, field_ref],
                type=result_type,
                span=field_init.span,
            )

        return current_ref, result_type

    def _literal_value_ref(self, expr: LiteralExpr) -> ValueRef:
        if expr.kind == "string":
            encoded = base64.urlsafe_b64encode(expr.value.encode("utf-8")).decode("ascii").rstrip("=")
            return ValueRef(f"literal_string_b64_{encoded}")
        safe_value = (
            expr.value.replace("-", "neg_")
            .replace(".", "_")
            .replace("\"", "")
            .replace("'", "")
        )
        return ValueRef(f"literal_{expr.kind}_{safe_value}")

    def _new_temp(self) -> ValueRef:
        value = ValueRef(f"tmp{self.temp_index}")
        self.temp_index += 1
        return value

    def _new_slot(self, name: str) -> ValueRef:
        value = ValueRef(f"slot_{name}_{self.slot_index}")
        self.slot_index += 1
        return value

    def _create_block(self, stem: str, explicit_name: Optional[str] = None) -> PendingBlock:
        block = PendingBlock(name=explicit_name or f"{stem}_{self.block_index}", instructions=[])
        if explicit_name is None:
            self.block_index += 1
        self.blocks.append(block)
        return block

    def _switch_to_block(self, block: PendingBlock):
        self.current_block = block

    def _push_scope(self):
        self.scope_stack.append({})

    def _pop_scope(self):
        if not self.scope_stack:
            raise BirLoweringError("internal lowering error: scope stack underflow")
        self.scope_stack.pop()

    def _declare_slot(self, name: str, slot_type: Type) -> SlotBinding:
        if not self.scope_stack:
            raise BirLoweringError("internal lowering error: no scope available for local declaration")
        binding = SlotBinding(slot=self._new_slot(name), type=slot_type)
        self.scope_stack[-1][name] = binding
        return binding

    def _lookup_slot(self, name: str) -> Optional[SlotBinding]:
        for scope in reversed(self.scope_stack):
            binding = scope.get(name)
            if binding is not None:
                return binding
        return None

    def _initialize_param_slots(self):
        for param in self.function_decl.params:
            binding = self._declare_slot(param.name, self._resolve_ast_type(param.type))
            self._emit_instruction(
                kind="store",
                opcode="param_init",
                result=None,
                operands=[binding.slot, ValueRef(param.name)],
                type=binding.type,
                span=param.span,
                resource_note="parameter slot",
            )

    def _is_current_block_terminated(self) -> bool:
        return self.current_block is not None and self.current_block.terminator is not None

    def _terminate(self, kind: str, operands: Optional[List[ValueRef]] = None, targets: Optional[List[str]] = None):
        if self.current_block is None:
            raise BirLoweringError("internal lowering error: missing active block")
        if self.current_block.terminator is not None:
            raise BirLoweringError(
                f"internal lowering error: block '{self.current_block.name}' already terminated"
            )
        self.current_block.terminator = Terminator(kind=kind, operands=operands or [], targets=targets or [])

    def _emit_instruction(
        self,
        *,
        kind: str,
        opcode: Optional[str],
        result: Optional[ValueRef],
        operands: List[ValueRef],
        type: Type,
        span: SourceSpan,
        effect_note: Optional[str] = None,
        resource_note: Optional[str] = None,
    ) -> Optional[ValueRef]:
        if self.current_block is None:
            raise BirLoweringError("internal lowering error: missing active block")
        if self.current_block.terminator is not None:
            raise BirLoweringError(
                f"internal lowering error: cannot emit into terminated block '{self.current_block.name}'"
            )

        self.current_block.instructions.append(
            Instruction(
                kind=kind,
                opcode=opcode,
                result=result,
                operands=operands,
                type=type,
                metadata=self._metadata(span, effect_note=effect_note, resource_note=resource_note),
            )
        )
        return result

    def _lower_assignment(self, expr: AssignmentExpr) -> Tuple[ValueRef, Type]:
        target_type = self._expression_type(expr.target)

        if expr.operator == "=":
            value_ref, value_type = self._lower_expression(expr.value)
        else:
            current_ref, current_type = self._lower_expression(expr.target)
            value_ref, value_type = self._lower_expression(expr.value)
            value_type = current_type
            result_ref = self._new_temp()
            self._emit_instruction(
                kind="math",
                opcode=expr.operator[:-1],
                result=result_ref,
                operands=[current_ref, value_ref],
                type=current_type,
                span=expr.span,
            )
            value_ref = result_ref

        self._store_target(expr.target, value_ref, target_type)
        return value_ref, value_type

    def _store_target(self, target: Expression, value_ref: ValueRef, value_type: Type):
        if isinstance(target, IdentifierExpr):
            binding = self._lookup_slot(target.name)
            target_ref = binding.slot if binding is not None else ValueRef(target.name)
            self._emit_instruction(
                kind="store",
                opcode="=",
                result=None,
                operands=[target_ref, value_ref],
                type=value_type,
                span=target.span,
            )
            return

        if isinstance(target, DereferenceExpr):
            pointer_ref, _ = self._lower_expression(target.operand)
            self._emit_instruction(
                kind="store",
                opcode="*=",
                result=None,
                operands=[pointer_ref, value_ref],
                type=value_type,
                span=target.span,
            )
            return

        if isinstance(target, FieldAccessExpr):
            self._store_field_target(target, value_ref, value_type)
            return

        if isinstance(target, IndexExpr):
            self._store_index_target(target, value_ref, value_type)
            return

        raise BirLoweringError(
            f"function '{self.module_name}::{self.function_decl.name}' cannot assign to '{target.__class__.__name__}'"
        )

    def _store_field_target(self, target: FieldAccessExpr, field_value_ref: ValueRef, field_value_type: Type):
        if target.base_is_pointer:
            pointer_ref, _ = self._lower_expression(target.base)
            base_type = self._base_struct_type(target.base)
            current_struct_ref = self._emit_instruction(
                kind="load",
                opcode="*",
                result=self._new_temp(),
                operands=[pointer_ref],
                type=base_type,
                span=target.span,
            )
            updated_struct_ref = self._emit_instruction(
                kind="insert",
                opcode=target.field_name,
                result=self._new_temp(),
                operands=[current_struct_ref, field_value_ref],
                type=base_type,
                span=target.span,
            )
            self._emit_instruction(
                kind="store",
                opcode="field_store",
                result=None,
                operands=[pointer_ref, updated_struct_ref],
                type=base_type,
                span=target.span,
            )
            return

        base_value_ref, base_value_type = self._lower_expression(target.base)
        updated_base_ref = self._emit_instruction(
            kind="insert",
            opcode=target.field_name,
            result=self._new_temp(),
            operands=[base_value_ref, field_value_ref],
            type=base_value_type,
            span=target.span,
        )
        self._store_target(target.base, updated_base_ref, base_value_type)

    def _store_index_target(self, target: IndexExpr, element_value_ref: ValueRef, element_value_type: Type):
        base_ref, base_type = self._lower_expression(target.base)
        index_ref, _ = self._lower_expression(target.index)
        updated_base_ref = self._emit_instruction(
            kind="insert",
            opcode="index",
            result=self._new_temp(),
            operands=[base_ref, index_ref, element_value_ref],
            type=base_type,
            span=target.span,
        )
        self._store_target(target.base, updated_base_ref, base_type)

    def _base_struct_type(self, expr: Expression) -> Type:
        expr_type = self.type_checker.expr_types.get(id(expr))
        if expr_type is None:
            raise BirLoweringError(
                f"missing resolved base type for '{expr.__class__.__name__}' in '{self.module_name}::{self.function_decl.name}'"
            )
        if hasattr(expr_type, "pointee"):
            expr_type = expr_type.pointee
        return self._lower_resolved_type(expr_type)

    def _loop_resource_note(self, stmt: ForStmt) -> Optional[str]:
        if self.loop_analyzer is None:
            return None
        bound = self.loop_analyzer.get_loop_bound(stmt)
        if bound is None:
            raise BirLoweringError(
                f"function '{self.module_name}::{self.function_decl.name}' is lowering a for-loop without an analyzed bound"
            )
        suffix = " constant" if bound.is_constant else " symbolic"
        return f"bounded loop max={bound.max_iterations}{suffix}"

    def _unit_value_ref(self, value_type: Type) -> ValueRef:
        if value_type.kind in {"i8", "i16", "i32", "i64", "u8", "u16", "u32", "u64"}:
            return ValueRef(f"literal_{value_type.kind}_1")
        raise BirLoweringError(
            f"function '{self.module_name}::{self.function_decl.name}' cannot increment non-integer loop type '{value_type.kind}'"
        )

    def _metadata(
        self,
        span: SourceSpan,
        *,
        effect_note: Optional[str] = None,
        resource_note: Optional[str] = None,
    ) -> InstructionMetadata:
        effect_notes = [effect_note] if effect_note else []
        resource_notes = [resource_note] if resource_note else []
        return InstructionMetadata(
            source_loc=_source_loc_from_span(span, self.source_path),
            effect_notes=effect_notes,
            resource_notes=resource_notes,
        )
