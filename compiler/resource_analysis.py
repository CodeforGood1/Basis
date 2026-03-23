"""
BASIS Program Resource Analysis
Builds a whole-program call graph and computes stack, heap, determinism,
and ISR-safety metadata for every function.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from ast_defs import (
    AddressOfExpr,
    Annotation,
    AssignmentExpr,
    BinaryExpr,
    Block,
    CallExpr,
    CastExpr,
    DereferenceExpr,
    ExprStmt,
    Expression,
    FieldAccessExpr,
    ForStmt,
    FunctionDecl,
    IdentifierExpr,
    IfStmt,
    IndexExpr,
    LetDecl,
    LiteralExpr,
    Module,
    ReturnStmt,
    SourceSpan,
    UnaryExpr,
    WhileStmt,
    parse_int_literal,
)
from consteval import ConstantEvaluator, IntConstant
from diagnostics import DiagnosticEngine
from loop_analysis import LoopAnalyzer
from sema import Scope
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
)


@dataclass
class FunctionResource:
    frame_stack_bytes: int
    stack_bytes: int
    heap_bytes: int
    recursion_depth: Optional[int]
    deterministic: bool
    isr_safe: bool
    blocking: bool
    allocates: bool
    is_interrupt: bool
    call_path: List[str] = field(default_factory=list)


@dataclass
class FunctionInfo:
    qualified_name: str
    module_name: str
    decl: FunctionDecl
    scope: Scope
    type_checker: TypeChecker
    const_eval: ConstantEvaluator
    loop_analyzer: LoopAnalyzer
    frame_stack_bytes: int = 0
    stack_bytes: int = 0
    local_heap_bytes: int = 0
    total_heap_bytes: int = 0
    recursion_depth: Optional[int] = None
    deterministic: bool = True
    isr_safe: bool = False
    blocking: bool = False
    allocates: bool = False
    is_interrupt: bool = False
    direct_calls: Set[str] = field(default_factory=set)
    call_path: List[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.decl.name

    @property
    def is_extern(self) -> bool:
        return self.decl.is_extern


@dataclass
class CallComponent:
    members: List[str]
    is_recursive: bool
    recursion_depth: Optional[int] = None
    outgoing_components: Set[int] = field(default_factory=set)


@dataclass(frozen=True)
class EffectSummary:
    deterministic: bool
    isr_safe: bool
    blocking: bool
    allocates: bool


class CallGraph:
    """Whole-program function call graph."""

    def __init__(self):
        self.calls: Dict[str, Set[str]] = {}

    def add_node(self, node: str):
        self.calls.setdefault(node, set())

    def add_call(self, caller: str, callee: str):
        self.add_node(caller)
        self.add_node(callee)
        self.calls[caller].add(callee)

    def neighbors(self, node: str) -> Set[str]:
        return self.calls.get(node, set())

    def nodes(self) -> List[str]:
        return sorted(self.calls.keys())

    def strongly_connected_components(self) -> List[List[str]]:
        """Tarjan SCC decomposition."""
        index = 0
        stack: List[str] = []
        indices: Dict[str, int] = {}
        lowlinks: Dict[str, int] = {}
        on_stack: Set[str] = set()
        components: List[List[str]] = []

        def strongconnect(node: str):
            nonlocal index

            indices[node] = index
            lowlinks[node] = index
            index += 1
            stack.append(node)
            on_stack.add(node)

            for neighbor in sorted(self.neighbors(node)):
                if neighbor not in indices:
                    strongconnect(neighbor)
                    lowlinks[node] = min(lowlinks[node], lowlinks[neighbor])
                elif neighbor in on_stack:
                    lowlinks[node] = min(lowlinks[node], indices[neighbor])

            if lowlinks[node] == indices[node]:
                component: List[str] = []
                while stack:
                    member = stack.pop()
                    on_stack.remove(member)
                    component.append(member)
                    if member == node:
                        break
                components.append(sorted(component))

        for node in self.nodes():
            if node not in indices:
                strongconnect(node)

        return components


class ProgramResourceAnalyzer:
    _DIRECT_ALLOCATORS = {
        "alloc",
        "malloc",
        "alloc_bytes",
        "alloc_u8",
        "alloc_i32",
        "alloc_u32",
        "alloc_i64",
        "alloc_zeroed",
    }
    _ALLOC_WRAPPERS = {
        "alloc_bytes",
        "alloc_u8",
        "alloc_i32",
        "alloc_u32",
        "alloc_i64",
        "alloc_zeroed",
        "free_bytes",
        "mem_copy",
        "mem_zero",
        "mem_set",
    }

    def __init__(
        self,
        diag_engine: DiagnosticEngine,
        modules: Dict[str, Module],
        module_scopes: Dict[str, Scope],
        type_checkers: Dict[str, TypeChecker],
        const_evaluators: Dict[str, ConstantEvaluator],
        loop_analyzers: Dict[str, LoopAnalyzer],
    ):
        self.diag = diag_engine
        self.modules = modules
        self.module_scopes = module_scopes
        self.type_checkers = type_checkers
        self.const_evaluators = const_evaluators
        self.loop_analyzers = loop_analyzers

        self.functions: Dict[str, FunctionInfo] = {}
        self.resources: Dict[str, FunctionResource] = {}
        self.call_graph = CallGraph()

        self.components: List[CallComponent] = []
        self.function_to_component: Dict[str, int] = {}

        self._node_stack_cache: Dict[str, Tuple[int, List[str]]] = {}
        self._component_stack_cache: Dict[int, Tuple[int, List[str]]] = {}
        self._component_effect_cache: Dict[int, EffectSummary] = {}
        self._heap_cache: Dict[str, int] = {}

        self.total_stack_bytes = 0
        self.total_heap_bytes = 0
        self.deepest_stack_path: List[str] = []

    def analyze(self) -> bool:
        self._collect_functions()
        self._build_call_graph()
        self._build_components()
        self._compute_frame_sizes()
        self._validate_recursive_components()
        self._compute_stack_usage()
        self._compute_local_heap_usage()
        self._validate_recursive_heap_usage()
        self._compute_total_heap_usage()
        self._validate_effect_contracts()
        self._compute_effects()
        self._validate_effect_assertions()
        self._validate_interrupts()
        self._apply_stack_budgets()
        self._finalize_resources()
        return not self.diag.has_errors()

    def get_resource(self, qualified_name: str) -> Optional[FunctionResource]:
        return self.resources.get(qualified_name)

    def get_all_resources(self) -> Dict[str, FunctionResource]:
        return self.resources.copy()

    def get_module_resources(self, module_name: str) -> Dict[str, FunctionResource]:
        prefix = f"{module_name}::"
        return {
            qualified_name[len(prefix):]: resource
            for qualified_name, resource in self.resources.items()
            if qualified_name.startswith(prefix)
        }

    def get_total_stack(self) -> int:
        return self.total_stack_bytes

    def get_total_heap(self) -> int:
        return self.total_heap_bytes

    def get_deepest_stack_path(self) -> List[str]:
        return list(self.deepest_stack_path)

    def get_recursive_cycles(self) -> List[List[str]]:
        return [list(component.members) for component in self.components if component.is_recursive]

    def _collect_functions(self):
        for module_name, module in self.modules.items():
            for decl in module.declarations:
                if not isinstance(decl, FunctionDecl):
                    continue

                qualified_name = self._qualified_name(module_name, decl.name)
                info = FunctionInfo(
                    qualified_name=qualified_name,
                    module_name=module_name,
                    decl=decl,
                    scope=self.module_scopes[module_name],
                    type_checker=self.type_checkers[module_name],
                    const_eval=self.const_evaluators[module_name],
                    loop_analyzer=self.loop_analyzers[module_name],
                    is_interrupt=self._has_annotation(decl.annotations, "interrupt"),
                )
                self.functions[qualified_name] = info
                self.call_graph.add_node(qualified_name)

    def _build_call_graph(self):
        for info in self.functions.values():
            if info.decl.body:
                self._extract_calls(info, info.decl.body)

    def _extract_calls(self, info: FunctionInfo, node):
        if isinstance(node, CallExpr):
            target = self._resolve_call_target(info.module_name, node)
            if target:
                info.direct_calls.add(target)
                self.call_graph.add_call(info.qualified_name, target)
            for argument in node.arguments:
                self._extract_calls(info, argument)
            return

        if isinstance(node, Block):
            for statement in node.statements:
                self._extract_calls(info, statement)
        elif isinstance(node, LetDecl):
            if node.initializer:
                self._extract_calls(info, node.initializer)
        elif isinstance(node, ForStmt):
            self._extract_calls(info, node.range_start)
            self._extract_calls(info, node.range_end)
            self._extract_calls(info, node.body)
        elif isinstance(node, WhileStmt):
            self._extract_calls(info, node.condition)
            self._extract_calls(info, node.body)
        elif isinstance(node, IfStmt):
            self._extract_calls(info, node.condition)
            self._extract_calls(info, node.then_block)
            for branch in node.elif_branches:
                self._extract_calls(info, branch.condition)
                self._extract_calls(info, branch.block)
            if node.else_block:
                self._extract_calls(info, node.else_block)
        elif isinstance(node, ExprStmt):
            self._extract_calls(info, node.expression)
        elif isinstance(node, ReturnStmt):
            if node.value:
                self._extract_calls(info, node.value)
        elif isinstance(node, BinaryExpr):
            self._extract_calls(info, node.left)
            self._extract_calls(info, node.right)
        elif isinstance(node, UnaryExpr):
            self._extract_calls(info, node.operand)
        elif isinstance(node, AssignmentExpr):
            self._extract_calls(info, node.target)
            self._extract_calls(info, node.value)
        elif isinstance(node, IndexExpr):
            self._extract_calls(info, node.base)
            self._extract_calls(info, node.index)
        elif isinstance(node, FieldAccessExpr):
            self._extract_calls(info, node.base)
        elif isinstance(node, CastExpr):
            self._extract_calls(info, node.expression)
        elif isinstance(node, AddressOfExpr):
            self._extract_calls(info, node.operand)
        elif isinstance(node, DereferenceExpr):
            self._extract_calls(info, node.operand)

    def _resolve_call_target(self, module_name: str, call: CallExpr) -> Optional[str]:
        if isinstance(call.callee, IdentifierExpr):
            symbol = self.module_scopes[module_name].lookup(call.callee.name)
            if symbol and isinstance(symbol.decl_node, FunctionDecl):
                target_module = symbol.module_name or module_name
                return self._qualified_name(target_module, symbol.decl_node.name)
        return None

    def _build_components(self):
        for index, members in enumerate(self.call_graph.strongly_connected_components()):
            recursive = len(members) > 1
            if not recursive and members:
                recursive = members[0] in self.call_graph.neighbors(members[0])

            component = CallComponent(members=members, is_recursive=recursive)
            self.components.append(component)
            for member in members:
                self.function_to_component[member] = index

        for index, component in enumerate(self.components):
            for member in component.members:
                for callee in self.call_graph.neighbors(member):
                    target = self.function_to_component[callee]
                    if target != index:
                        component.outgoing_components.add(target)

    def _compute_frame_sizes(self):
        for info in self.functions.values():
            if info.is_extern:
                stack_value = self._required_stack_annotation(info)
                info.frame_stack_bytes = stack_value or 0
            else:
                info.frame_stack_bytes = self._calculate_stack_usage(info)

    def _validate_recursive_components(self):
        for component in self.components:
            if not component.is_recursive:
                continue

            depths: Set[int] = set()
            for member in component.members:
                info = self.functions[member]
                depth = self._recursion_annotation(info)
                if depth is None:
                    self._error(
                        "E_MISSING_RECURSION_ANNOTATION",
                        f"recursive cycle requires @recursion(max=N): {' -> '.join(component.members)}",
                        info.decl.span,
                        info.module_name,
                    )
                    continue
                depths.add(depth)
                info.recursion_depth = depth

            if len(depths) > 1:
                info = self.functions[component.members[0]]
                self._error(
                    "E_RECURSION_DEPTH_MISMATCH",
                    f"recursive cycle members must use the same @recursion(max=N): {' -> '.join(component.members)}",
                    info.decl.span,
                    info.module_name,
                )
            elif depths:
                component.recursion_depth = next(iter(depths))

    def _compute_stack_usage(self):
        for qualified_name, info in self.functions.items():
            stack_bytes, path = self._node_stack(qualified_name)
            info.stack_bytes = stack_bytes
            info.call_path = path

    def _node_stack(self, qualified_name: str) -> Tuple[int, List[str]]:
        if qualified_name in self._node_stack_cache:
            return self._node_stack_cache[qualified_name]

        component_index = self.function_to_component[qualified_name]
        component = self.components[component_index]
        if component.is_recursive:
            result = self._component_stack(component_index)
            self._node_stack_cache[qualified_name] = result
            return result

        info = self.functions[qualified_name]
        best_stack = 0
        best_path: List[str] = []
        for callee in sorted(info.direct_calls):
            callee_stack, callee_path = self._node_stack(callee)
            if callee_stack > best_stack:
                best_stack = callee_stack
                best_path = callee_path

        result = (info.frame_stack_bytes + best_stack, [qualified_name] + best_path)
        self._node_stack_cache[qualified_name] = result
        return result

    def _component_stack(self, component_index: int) -> Tuple[int, List[str]]:
        if component_index in self._component_stack_cache:
            return self._component_stack_cache[component_index]

        component = self.components[component_index]
        cycle_stack = sum(
            self.functions[member].frame_stack_bytes
            for member in component.members
        )
        if component.recursion_depth:
            cycle_stack *= component.recursion_depth

        best_stack = 0
        best_path: List[str] = []
        for target in sorted(component.outgoing_components):
            if self.components[target].is_recursive:
                target_stack, target_path = self._component_stack(target)
            else:
                target_stack, target_path = self._node_stack(self.components[target].members[0])
            if target_stack > best_stack:
                best_stack = target_stack
                best_path = target_path

        label = self._recursive_label(component)
        result = (cycle_stack + best_stack, [label] + best_path)
        self._component_stack_cache[component_index] = result
        return result

    def _recursive_label(self, component: CallComponent) -> str:
        depth = component.recursion_depth or 1
        return f"[recursive {' -> '.join(component.members)} x{depth}]"

    def _compute_local_heap_usage(self):
        for info in self.functions.values():
            if info.is_extern or not info.decl.body or info.name in self._ALLOC_WRAPPERS:
                info.local_heap_bytes = 0
                continue

            tracked_values: Dict[str, int] = {}
            info.local_heap_bytes = self._calculate_heap_usage(
                info,
                info.decl.body,
                include_calls=False,
                tracked_values=tracked_values,
                bounded_params=self._bounded_params(info.decl),
                visiting={info.qualified_name},
            )

    def _validate_recursive_heap_usage(self):
        for component in self.components:
            if not component.is_recursive:
                continue
            for member in component.members:
                info = self.functions[member]
                if info.local_heap_bytes > 0:
                    self._error(
                        "E_RECURSIVE_HEAP",
                        f"recursive function '{info.name}' cannot allocate heap memory",
                        info.decl.span,
                        info.module_name,
                    )

    def _compute_total_heap_usage(self):
        for qualified_name, info in self.functions.items():
            info.total_heap_bytes = self._heap_for_function(qualified_name, visiting=set())

    def _heap_for_function(self, qualified_name: str, visiting: Set[str]) -> int:
        if qualified_name in self._heap_cache:
            return self._heap_cache[qualified_name]

        if qualified_name in visiting:
            return 0

        info = self.functions[qualified_name]
        if info.is_extern:
            extern_heap = self._extern_heap_budget(info)
            self._heap_cache[qualified_name] = extern_heap
            return extern_heap

        if not info.decl.body or info.name in self._ALLOC_WRAPPERS:
            self._heap_cache[qualified_name] = 0
            return 0

        tracked_values: Dict[str, int] = {}
        total_heap = self._calculate_heap_usage(
            info,
            info.decl.body,
            include_calls=True,
            tracked_values=tracked_values,
            bounded_params=self._bounded_params(info.decl),
            visiting=visiting | {qualified_name},
        )
        self._heap_cache[qualified_name] = total_heap
        return total_heap

    def _extern_heap_budget(self, info: FunctionInfo) -> int:
        allocates_annotation = self._find_annotation(info.decl.annotations, "allocates")
        if allocates_annotation is None:
            return 0

        if info.name in self._DIRECT_ALLOCATORS:
            return 0

        if allocates_annotation.arguments:
            budget = self._annotation_int_value(info, allocates_annotation, ("max", "bytes", "value"))
            return budget or 0

        return 0

    def _calculate_heap_usage(
        self,
        info: FunctionInfo,
        node,
        include_calls: bool,
        tracked_values: Dict[str, int],
        bounded_params: Dict[str, int],
        visiting: Set[str],
    ) -> int:
        total = 0

        if isinstance(node, Block):
            for statement in node.statements:
                total += self._calculate_heap_usage(
                    info, statement, include_calls, tracked_values, bounded_params, visiting
                )

        elif isinstance(node, ForStmt):
            loop_bound = info.loop_analyzer.get_loop_bound(node)
            if not loop_bound:
                self._error(
                    "E_UNBOUNDED_LOOP",
                    "for loop bound could not be determined during heap analysis",
                    node.span,
                    info.module_name,
                )
                return total

            body_heap = self._calculate_heap_usage(
                info,
                node.body,
                include_calls,
                tracked_values.copy(),
                bounded_params,
                visiting,
            )
            total += body_heap * loop_bound.max_iterations

        elif isinstance(node, WhileStmt):
            self._error(
                "E_WHILE_REMOVED",
                "while loops are not part of BASIS",
                node.span,
                info.module_name,
            )

        elif isinstance(node, IfStmt):
            branch_max = self._calculate_heap_usage(
                info,
                node.then_block,
                include_calls,
                tracked_values.copy(),
                bounded_params,
                visiting,
            )
            for branch in node.elif_branches:
                branch_max = max(
                    branch_max,
                    self._calculate_heap_usage(
                        info,
                        branch.block,
                        include_calls,
                        tracked_values.copy(),
                        bounded_params,
                        visiting,
                    ),
                )
            if node.else_block:
                branch_max = max(
                    branch_max,
                    self._calculate_heap_usage(
                        info,
                        node.else_block,
                        include_calls,
                        tracked_values.copy(),
                        bounded_params,
                        visiting,
                    ),
                )
            total += branch_max

        elif isinstance(node, ExprStmt):
            total += self._expr_heap(info, node.expression, include_calls, tracked_values, bounded_params, visiting)

        elif isinstance(node, LetDecl):
            if node.initializer:
                total += self._expr_heap(info, node.initializer, include_calls, tracked_values, bounded_params, visiting)
                init_value = self._evaluate_alloc_size(info, node.initializer, tracked_values, bounded_params)
                if init_value is not None:
                    tracked_values[node.name] = init_value

        elif isinstance(node, ReturnStmt):
            if node.value:
                total += self._expr_heap(info, node.value, include_calls, tracked_values, bounded_params, visiting)

        return total

    def _expr_heap(
        self,
        info: FunctionInfo,
        expr: Expression,
        include_calls: bool,
        tracked_values: Dict[str, int],
        bounded_params: Dict[str, int],
        visiting: Set[str],
    ) -> int:
        total = 0

        if isinstance(expr, CallExpr):
            direct_alloc = self._direct_alloc_bytes(info, expr, tracked_values, bounded_params)
            if direct_alloc is not None:
                total += direct_alloc
            elif include_calls:
                callee = self._resolve_call_target(info.module_name, expr)
                if callee and callee not in visiting:
                    total += self._heap_for_function(callee, visiting)

            for argument in expr.arguments:
                total += self._expr_heap(info, argument, include_calls, tracked_values, bounded_params, visiting)

        elif isinstance(expr, BinaryExpr):
            total += self._expr_heap(info, expr.left, include_calls, tracked_values, bounded_params, visiting)
            total += self._expr_heap(info, expr.right, include_calls, tracked_values, bounded_params, visiting)

        elif isinstance(expr, UnaryExpr):
            total += self._expr_heap(info, expr.operand, include_calls, tracked_values, bounded_params, visiting)

        elif isinstance(expr, AssignmentExpr):
            total += self._expr_heap(info, expr.target, include_calls, tracked_values, bounded_params, visiting)
            total += self._expr_heap(info, expr.value, include_calls, tracked_values, bounded_params, visiting)

        return total

    def _direct_alloc_bytes(
        self,
        info: FunctionInfo,
        expr: CallExpr,
        tracked_values: Dict[str, int],
        bounded_params: Dict[str, int],
    ) -> Optional[int]:
        if not isinstance(expr.callee, IdentifierExpr):
            return None

        callee_name = expr.callee.name
        if callee_name not in self._DIRECT_ALLOCATORS:
            return None

        if callee_name == "alloc" and len(expr.arguments) >= 2:
            alloc_size = self._evaluate_alloc_size(info, expr.arguments[1], tracked_values, bounded_params)
            if alloc_size is None:
                self._error(
                    "E_UNBOUNDED_HEAP",
                    "allocation size must be a compile-time constant or bounded parameter",
                    expr.arguments[1].span,
                    info.module_name,
                )
                return 0
            return alloc_size

        if callee_name in ("malloc", "alloc_bytes", "alloc_u8", "alloc_zeroed") and len(expr.arguments) >= 1:
            alloc_size = self._evaluate_alloc_size(info, expr.arguments[0], tracked_values, bounded_params)
            if alloc_size is None:
                self._error(
                    "E_UNBOUNDED_HEAP",
                    "allocation size must be a compile-time constant or bounded parameter",
                    expr.arguments[0].span,
                    info.module_name,
                )
                return 0
            return alloc_size

        if callee_name == "alloc_i32" and len(expr.arguments) >= 1:
            count = self._evaluate_alloc_size(info, expr.arguments[0], tracked_values, bounded_params)
            if count is None:
                self._error(
                    "E_UNBOUNDED_HEAP",
                    "allocation size must be a compile-time constant or bounded parameter",
                    expr.arguments[0].span,
                    info.module_name,
                )
                return 0
            return count * 4

        if callee_name == "alloc_u32" and len(expr.arguments) >= 1:
            count = self._evaluate_alloc_size(info, expr.arguments[0], tracked_values, bounded_params)
            if count is None:
                self._error(
                    "E_UNBOUNDED_HEAP",
                    "allocation size must be a compile-time constant or bounded parameter",
                    expr.arguments[0].span,
                    info.module_name,
                )
                return 0
            return count * 4

        if callee_name == "alloc_i64" and len(expr.arguments) >= 1:
            count = self._evaluate_alloc_size(info, expr.arguments[0], tracked_values, bounded_params)
            if count is None:
                self._error(
                    "E_UNBOUNDED_HEAP",
                    "allocation size must be a compile-time constant or bounded parameter",
                    expr.arguments[0].span,
                    info.module_name,
                )
                return 0
            return count * 8

        return None

    def _evaluate_alloc_size(
        self,
        info: FunctionInfo,
        expr: Expression,
        tracked_values: Dict[str, int],
        bounded_params: Dict[str, int],
    ) -> Optional[int]:
        if isinstance(expr, LiteralExpr) and expr.kind == "int":
            return parse_int_literal(expr.value)

        if isinstance(expr, CastExpr):
            return self._evaluate_alloc_size(info, expr.expression, tracked_values, bounded_params)

        if isinstance(expr, IdentifierExpr):
            if expr.name in bounded_params:
                return bounded_params[expr.name]
            if expr.name in tracked_values:
                return tracked_values[expr.name]
            if expr.name in info.const_eval.const_values:
                value = info.const_eval.const_values[expr.name]
                if isinstance(value, IntConstant):
                    return value.value

        if isinstance(expr, BinaryExpr):
            left_value = self._evaluate_alloc_size(info, expr.left, tracked_values, bounded_params)
            right_value = self._evaluate_alloc_size(info, expr.right, tracked_values, bounded_params)
            if left_value is not None and right_value is not None:
                if expr.operator == "+":
                    return left_value + right_value
                if expr.operator == "-":
                    return left_value - right_value
                if expr.operator == "*":
                    return left_value * right_value
                if expr.operator == "/":
                    return left_value // right_value

        return None

    def _bounded_params(self, decl: FunctionDecl) -> Dict[str, int]:
        bounded: Dict[str, int] = {}
        for param in decl.params:
            if param.name.endswith("_bounded"):
                bounded[param.name] = 1000
        return bounded

    def _validate_effect_contracts(self):
        for info in self.functions.values():
            has_deterministic = self._has_annotation(info.decl.annotations, "deterministic")
            has_nondeterministic = self._has_annotation(info.decl.annotations, "nondeterministic")
            has_blocking = self._has_annotation(info.decl.annotations, "blocking")
            has_isr_safe = self._has_annotation(info.decl.annotations, "isr_safe")
            allocates_annotation = self._find_annotation(info.decl.annotations, "allocates")

            if has_deterministic and has_nondeterministic:
                self._error(
                    "E_EFFECT_CONFLICT",
                    f"function '{info.name}' cannot be both @deterministic and @nondeterministic",
                    info.decl.span,
                    info.module_name,
                )

            if has_isr_safe and has_nondeterministic:
                self._error(
                    "E_EFFECT_CONFLICT",
                    f"function '{info.name}' cannot be both @isr_safe and @nondeterministic",
                    info.decl.span,
                    info.module_name,
                )

            if has_isr_safe and has_blocking:
                self._error(
                    "E_EFFECT_CONFLICT",
                    f"function '{info.name}' cannot be both @isr_safe and @blocking",
                    info.decl.span,
                    info.module_name,
                )

            if has_isr_safe and allocates_annotation is not None:
                self._error(
                    "E_EFFECT_CONFLICT",
                    f"function '{info.name}' cannot be both @isr_safe and @allocates",
                    info.decl.span,
                    info.module_name,
                )

            if not info.is_extern:
                continue

            if not has_deterministic and not has_nondeterministic:
                self._error(
                    "E_EXTERN_EFFECT_REQUIRED",
                    f"extern function '{info.name}' must declare @deterministic or @nondeterministic",
                    info.decl.span,
                    info.module_name,
                )

            if allocates_annotation is not None and info.name not in self._DIRECT_ALLOCATORS:
                if not allocates_annotation.arguments:
                    self._error(
                        "E_EXTERN_ALLOCATES_BUDGET_REQUIRED",
                        f"extern function '{info.name}' uses @allocates and requires @allocates(max=N) for heap budgeting",
                        allocates_annotation.span,
                        info.module_name,
                    )
                else:
                    self._annotation_int_value(info, allocates_annotation, ("max", "bytes", "value"))

    def _compute_effects(self):
        for component_index in range(len(self.components)):
            summary = self._component_effects(component_index)
            component = self.components[component_index]
            for member in component.members:
                info = self.functions[member]
                info.deterministic = summary.deterministic
                info.isr_safe = summary.isr_safe
                info.blocking = summary.blocking
                info.allocates = summary.allocates

    def _component_effects(self, component_index: int) -> EffectSummary:
        if component_index in self._component_effect_cache:
            return self._component_effect_cache[component_index]

        component = self.components[component_index]
        deterministic = True
        isr_safe = True
        blocking = False
        allocates = False

        for member in component.members:
            info = self.functions[member]
            base_effects = self._base_effects(info)
            deterministic = deterministic and base_effects.deterministic
            isr_safe = isr_safe and base_effects.isr_safe
            blocking = blocking or base_effects.blocking
            allocates = allocates or base_effects.allocates

        for target in component.outgoing_components:
            target_effects = self._component_effects(target)
            deterministic = deterministic and target_effects.deterministic
            isr_safe = isr_safe and target_effects.isr_safe
            blocking = blocking or target_effects.blocking
            allocates = allocates or target_effects.allocates

        isr_safe = isr_safe and deterministic and not blocking and not allocates

        summary = EffectSummary(
            deterministic=deterministic,
            isr_safe=isr_safe,
            blocking=blocking,
            allocates=allocates,
        )
        self._component_effect_cache[component_index] = summary
        return summary

    def _base_effects(self, info: FunctionInfo) -> EffectSummary:
        has_deterministic = self._has_annotation(info.decl.annotations, "deterministic")
        has_nondeterministic = self._has_annotation(info.decl.annotations, "nondeterministic")
        has_blocking = self._has_annotation(info.decl.annotations, "blocking")
        has_isr_safe = self._has_annotation(info.decl.annotations, "isr_safe")
        has_allocates = self._find_annotation(info.decl.annotations, "allocates") is not None

        if info.is_extern:
            deterministic = has_deterministic and not has_nondeterministic
            return EffectSummary(
                deterministic=deterministic,
                isr_safe=has_isr_safe,
                blocking=has_blocking,
                allocates=has_allocates,
            )

        deterministic = not has_nondeterministic
        allocates = has_allocates or info.local_heap_bytes > 0
        isr_safe = deterministic and not has_blocking and not allocates
        return EffectSummary(
            deterministic=deterministic,
            isr_safe=isr_safe,
            blocking=has_blocking,
            allocates=allocates,
        )

    def _validate_effect_assertions(self):
        for info in self.functions.values():
            if info.is_extern:
                continue

            if self._has_annotation(info.decl.annotations, "deterministic") and not info.deterministic:
                self._error(
                    "E_DETERMINISM_CONTRACT",
                    f"function '{info.name}' is annotated @deterministic but calls non-deterministic code",
                    info.decl.span,
                    info.module_name,
                )

            if self._has_annotation(info.decl.annotations, "isr_safe") and not info.isr_safe:
                self._error(
                    "E_ISR_SAFETY_CONTRACT",
                    f"function '{info.name}' is annotated @isr_safe but is not ISR-safe",
                    info.decl.span,
                    info.module_name,
                )

    def _validate_interrupts(self):
        for info in self.functions.values():
            if not info.is_interrupt:
                continue

            if info.is_extern:
                self._error(
                    "E_INTERRUPT_EXTERN",
                    "@interrupt functions cannot be extern",
                    info.decl.span,
                    info.module_name,
                )

            if info.decl.visibility != "public":
                self._error(
                    "E_INTERRUPT_VISIBILITY",
                    "@interrupt functions must be public so the target HAL can bind them",
                    info.decl.span,
                    info.module_name,
                )

            if info.decl.params:
                self._error(
                    "E_INTERRUPT_SIGNATURE",
                    "@interrupt functions must not take parameters",
                    info.decl.span,
                    info.module_name,
                )

            return_type = info.type_checker._resolve_type(info.decl.return_type)
            if return_type and not isinstance(return_type, VoidType):
                self._error(
                    "E_INTERRUPT_SIGNATURE",
                    "@interrupt functions must return void",
                    info.decl.return_type.span,
                    info.module_name,
                )

            if info.recursion_depth is not None:
                self._error(
                    "E_INTERRUPT_RECURSION",
                    "@interrupt functions cannot be recursive",
                    info.decl.span,
                    info.module_name,
                )

            if info.total_heap_bytes > 0:
                self._error(
                    "E_INTERRUPT_HEAP",
                    "@interrupt functions cannot allocate heap memory",
                    info.decl.span,
                    info.module_name,
                )

            if info.blocking:
                self._error(
                    "E_INTERRUPT_BLOCKING",
                    "@interrupt functions cannot call blocking code",
                    info.decl.span,
                    info.module_name,
                )

            if not info.deterministic:
                self._error(
                    "E_INTERRUPT_NONDETERMINISTIC",
                    "@interrupt functions can only call deterministic code",
                    info.decl.span,
                    info.module_name,
                )

            if not info.isr_safe:
                self._error(
                    "E_INTERRUPT_UNSAFE_CALL",
                    "@interrupt functions can only call ISR-safe code",
                    info.decl.span,
                    info.module_name,
                )

    def _apply_stack_budgets(self):
        for info in self.functions.values():
            stack_budget = self._optional_stack_annotation(info)
            if stack_budget is not None and info.stack_bytes > stack_budget:
                self._warning(
                    "W_STACK_BUDGET_EXCEEDED",
                    f"function '{info.name}' uses {info.stack_bytes}B stack, exceeds @stack({stack_budget}) budget",
                    info.decl.span,
                    info.module_name,
                )

    def _finalize_resources(self):
        self.resources.clear()
        self.total_stack_bytes = 0
        self.total_heap_bytes = 0
        self.deepest_stack_path = []

        for qualified_name, info in self.functions.items():
            call_path = [self._display_name(item) for item in info.call_path]
            resource = FunctionResource(
                frame_stack_bytes=info.frame_stack_bytes,
                stack_bytes=info.stack_bytes,
                heap_bytes=info.total_heap_bytes,
                recursion_depth=info.recursion_depth,
                deterministic=info.deterministic,
                isr_safe=info.isr_safe,
                blocking=info.blocking,
                allocates=info.allocates,
                is_interrupt=info.is_interrupt,
                call_path=call_path,
            )
            self.resources[qualified_name] = resource

            self.total_stack_bytes = max(self.total_stack_bytes, resource.stack_bytes)
            self.total_heap_bytes += resource.heap_bytes
            if resource.stack_bytes == self.total_stack_bytes:
                self.deepest_stack_path = list(call_path)

    def _calculate_stack_usage(self, info: FunctionInfo) -> int:
        total = 0

        for param in info.decl.params:
            param_type = info.type_checker._resolve_type(param.type)
            if param_type:
                total += self._sizeof(param_type)

        if info.decl.body:
            total += self._calculate_block_stack(info, info.decl.body)

        return total

    def _calculate_block_stack(self, info: FunctionInfo, block: Block) -> int:
        total = 0

        for statement in block.statements:
            if isinstance(statement, LetDecl):
                var_type = info.type_checker._resolve_type(statement.type)
                if var_type:
                    total += self._sizeof(var_type)

            elif isinstance(statement, Block):
                total += self._calculate_block_stack(info, statement)

            elif isinstance(statement, IfStmt):
                branch_max = self._calculate_block_stack(info, statement.then_block)
                for branch in statement.elif_branches:
                    branch_max = max(branch_max, self._calculate_block_stack(info, branch.block))
                if statement.else_block:
                    branch_max = max(branch_max, self._calculate_block_stack(info, statement.else_block))
                total += branch_max

            elif isinstance(statement, ForStmt):
                total += 4
                total += self._calculate_block_stack(info, statement.body)

            elif isinstance(statement, WhileStmt):
                self._error(
                    "E_WHILE_REMOVED",
                    "while loops are not part of BASIS",
                    statement.span,
                    info.module_name,
                )

        return total

    def _sizeof(self, resolved_type: BasisType) -> int:
        if isinstance(resolved_type, IntType):
            return resolved_type.bits // 8
        if isinstance(resolved_type, FloatType):
            return resolved_type.bits // 8
        if isinstance(resolved_type, BoolType):
            return 1
        if isinstance(resolved_type, ResolvedPointerType):
            return 4
        if isinstance(resolved_type, ResolvedArrayType):
            element_size = self._sizeof(resolved_type.element)
            element_count = resolved_type.size if resolved_type.size is not None else 1
            return element_size * element_count
        if isinstance(resolved_type, StructType):
            return sum(self._sizeof(field_type) for field_type in resolved_type.fields.values())
        return 0

    def _required_stack_annotation(self, info: FunctionInfo) -> Optional[int]:
        stack_value = self._optional_stack_annotation(info)
        if stack_value is None:
            self._error(
                "E_EXTERN_STACK_REQUIRED",
                f"extern function '{info.name}' requires @stack(N)",
                info.decl.span,
                info.module_name,
            )
        return stack_value

    def _optional_stack_annotation(self, info: FunctionInfo) -> Optional[int]:
        annotation = self._find_annotation(info.decl.annotations, "stack")
        if annotation is None:
            return None
        return self._annotation_int_value(info, annotation, ("value",))

    def _recursion_annotation(self, info: FunctionInfo) -> Optional[int]:
        annotation = self._find_annotation(info.decl.annotations, "recursion")
        if annotation is None:
            return None
        return self._annotation_int_value(info, annotation, ("max", "value"))

    def _annotation_int_value(
        self,
        info: FunctionInfo,
        annotation: Annotation,
        keys: Tuple[str, ...],
    ) -> Optional[int]:
        argument = None
        for key in keys:
            if annotation.arguments and key in annotation.arguments:
                argument = annotation.arguments[key]
                break

        if argument is None:
            self._error(
                "E_INVALID_ANNOTATION",
                f"@{annotation.name} requires an integer argument",
                annotation.span,
                info.module_name,
            )
            return None

        try:
            value = info.const_eval.eval_constant(argument)
        except Exception:
            value = None

        if not isinstance(value, IntConstant):
            self._error(
                "E_INVALID_ANNOTATION",
                f"@{annotation.name} requires a compile-time integer constant",
                annotation.span,
                info.module_name,
            )
            return None

        if value.value <= 0:
            self._error(
                "E_INVALID_ANNOTATION",
                f"@{annotation.name} value must be positive",
                annotation.span,
                info.module_name,
            )
            return None

        return value.value

    def _find_annotation(self, annotations: List[Annotation], name: str) -> Optional[Annotation]:
        for annotation in annotations:
            if annotation.name == name:
                return annotation
        return None

    def _has_annotation(self, annotations: List[Annotation], name: str) -> bool:
        return self._find_annotation(annotations, name) is not None

    def _qualified_name(self, module_name: str, function_name: str) -> str:
        return f"{module_name}::{function_name}"

    def _display_name(self, item: str) -> str:
        return item

    def _error(self, code: str, message: str, span: SourceSpan, module_name: str):
        self.diag.error(
            code,
            message,
            span.start_line,
            span.start_col,
            filename=f"<{module_name}>",
        )

    def _warning(self, code: str, message: str, span: SourceSpan, module_name: str):
        self.diag.warning(
            code,
            message,
            span.start_line,
            span.start_col,
            filename=f"<{module_name}>",
        )


def analyze_program_resources(
    modules: Dict[str, Module],
    diag: DiagnosticEngine,
    module_scopes: Dict[str, Scope],
    type_checkers: Dict[str, TypeChecker],
    const_evaluators: Dict[str, ConstantEvaluator],
    loop_analyzers: Dict[str, LoopAnalyzer],
) -> ProgramResourceAnalyzer:
    analyzer = ProgramResourceAnalyzer(
        diag,
        modules,
        module_scopes,
        type_checkers,
        const_evaluators,
        loop_analyzers,
    )
    analyzer.analyze()
    return analyzer
