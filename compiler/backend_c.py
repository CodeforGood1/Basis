"""
BASIS C backend driven by BIR.

This backend consumes validated BIR, preserving the frontend as the semantic
source of truth while keeping C emission as the stable default path.
"""

import base64
import json
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from diagnostics import DiagnosticEngine
from bir.model import (
    Extern,
    Field,
    Function,
    Global,
    Instruction,
    Module,
    Param,
    Program,
    StructDef,
    Terminator,
    Type,
    ValueRef,
)


class BirCBackendError(ValueError):
    """Raised when valid BIR cannot be emitted as C."""


class BirCBackend:
    RUNTIME_HELPERS = {
        "print_str": 'static void print_str(const char* s) { printf("%s", s); }',
        "print_i8": 'static void print_i8(int8_t x) { printf("%d", (int)x); }',
        "print_i16": 'static void print_i16(int16_t x) { printf("%d", (int)x); }',
        "print_i32": 'static void print_i32(int32_t x) { printf("%d", x); }',
        "print_i64": 'static void print_i64(int64_t x) { printf("%lld", (long long)x); }',
        "print_u8": 'static void print_u8(uint8_t x) { printf("%u", (unsigned)x); }',
        "print_u16": 'static void print_u16(uint16_t x) { printf("%u", (unsigned)x); }',
        "print_u32": 'static void print_u32(uint32_t x) { printf("%u", x); }',
        "print_u64": 'static void print_u64(uint64_t x) { printf("%llu", (unsigned long long)x); }',
        "print_f32": 'static void print_f32(float x) { printf("%g", (double)x); }',
        "print_f64": 'static void print_f64(double x) { printf("%g", x); }',
        "print_bool": 'static void print_bool(bool x) { printf("%s", x ? "true" : "false"); }',
        "print_char": 'static void print_char(char c) { printf("%c", c); }',
        "print_ptr": 'static void print_ptr(void* p) { printf("%p", p); }',
        "print_int": 'static void print_int(int32_t x) { print_i32(x); }',
        "print_uint": 'static void print_uint(uint32_t x) { print_u32(x); }',
        "read_i32": 'static int32_t read_i32(void) { int32_t x; scanf("%d", &x); return x; }',
        "read_i64": 'static int64_t read_i64(void) { int64_t x; scanf("%lld", (long long*)&x); return x; }',
        "read_u32": 'static uint32_t read_u32(void) { uint32_t x; scanf("%u", &x); return x; }',
        "read_u64": 'static uint64_t read_u64(void) { uint64_t x; scanf("%llu", (unsigned long long*)&x); return x; }',
        "read_f32": 'static float read_f32(void) { float x; scanf("%f", &x); return x; }',
        "read_f64": 'static double read_f64(void) { double x; scanf("%lf", &x); return x; }',
        "read_char": 'static char read_char(void) { char c; scanf(" %c", &c); return c; }',
        "read_str": 'static void read_str(char* buf, int32_t max_len) { scanf("%*s"); fgets(buf, max_len, stdin); }',
        "read_line": 'static void read_line(char* buf, int32_t max_len) { int c; while ((c = getchar()) == \'\\n\' || c == \'\\r\'); ungetc(c, stdin); fgets(buf, max_len, stdin); int len = strlen(buf); if (len > 0 && buf[len-1] == \'\\n\') buf[len-1] = \'\\0\'; }',
    }

    HELPER_DEPS = {
        "print_int": {"print_i32"},
        "print_uint": {"print_u32"},
    }

    def __init__(self, diag_engine: DiagnosticEngine, export_all: bool = False):
        self.diag = diag_engine
        self.export_all = export_all
        self.program: Optional[Program] = None
        self.modules: Dict[str, Module] = {}
        self.import_graph: Dict[str, Set[str]] = {}

    def generate_all(self, program: Program, output_dir: Path) -> bool:
        self.program = program
        self.modules = {module.name: module for module in program.modules}
        self.import_graph = {
            module.name: {import_decl.module_name for import_decl in module.imports}
            for module in program.modules
        }

        if not self._validate_imports():
            return False
        if not self._check_import_cycles():
            return False

        output_dir.mkdir(parents=True, exist_ok=True)

        for module in program.modules:
            if self._should_emit_header(module):
                header_path = output_dir / f"{module.name}.h"
                header_path.write_text(self._generate_header(module), encoding="utf-8")

            impl_path = output_dir / f"{module.name}.c"
            impl_path.write_text(self._generate_implementation(module), encoding="utf-8")

        return True

    def _should_emit_header(self, module: Module) -> bool:
        return module.name != "main"

    def _validate_imports(self) -> bool:
        valid = True
        for module_name, imports in self.import_graph.items():
            for imported in imports:
                if imported not in self.modules:
                    self.diag.error(
                        "E_UNKNOWN_MODULE",
                        f"module '{module_name}' imports unknown module '{imported}'",
                        1,
                        1,
                    )
                    valid = False
        return valid

    def _check_import_cycles(self) -> bool:
        def visit(node: str, path: List[str]) -> bool:
            if node in path:
                cycle = path + [node]
                self.diag.error(
                    "E_CYCLIC_IMPORT",
                    f"cyclic import detected: {' -> '.join(cycle)}",
                    1,
                    1,
                )
                return False

            new_path = path + [node]
            for dep in self.import_graph.get(node, set()):
                if not visit(dep, new_path):
                    return False
            return True

        return all(visit(module_name, []) for module_name in self.modules)

    def _generate_header(self, module: Module) -> str:
        lines: List[str] = []
        guard = f"{module.name.upper()}_H"

        lines.append(f"#ifndef {guard}")
        lines.append(f"#define {guard}")
        lines.append("")
        lines.append("#include <stdint.h>")
        lines.append("#include <stdbool.h>")
        lines.append("#ifndef BASIS_INTERRUPT")
        lines.append("#define BASIS_INTERRUPT")
        lines.append("#endif")
        lines.append("#ifndef BASIS_TASK")
        lines.append("#define BASIS_TASK")
        lines.append("#endif")
        lines.append("#ifndef BASIS_REGION")
        lines.append("#define BASIS_REGION(name)")
        lines.append("#endif")
        lines.append("")

        imports = self.import_graph.get(module.name, set())
        for imported in sorted(imports):
            if imported != "main":
                lines.append(f'#include "{imported}.h"')
        if imports:
            lines.append("")

        for struct_def in module.structs:
            if self._should_export(struct_def.visibility):
                lines.extend(self._emit_struct_decl(struct_def))
                lines.append("")

        for global_value in module.globals:
            if not self._should_export(global_value.visibility):
                continue
            qualifier = "extern "
            if global_value.initializer is not None:
                qualifier += "const "
            lines.append(f"{qualifier}{self._emit_type(global_value.type)} {global_value.name};")

        if module.globals:
            exported_globals = [g for g in module.globals if self._should_export(g.visibility)]
            if exported_globals:
                lines.append("")

        for function in module.functions:
            if self._should_export(function.visibility):
                lines.append(self._emit_function_decl(function))

        lines.append("")
        lines.append(f"#endif /* {guard} */")
        return "\n".join(lines)

    def _generate_implementation(self, module: Module) -> str:
        lines: List[str] = []
        if self._should_emit_header(module):
            lines.append(f'#include "{module.name}.h"')
        lines.append("#include <stdint.h>")
        lines.append("#include <stdbool.h>")
        lines.append("#include <stdlib.h>")
        lines.append("#include <stdio.h>")
        lines.append("#include <string.h>")
        lines.append("#ifndef BASIS_INTERRUPT")
        lines.append("#define BASIS_INTERRUPT")
        lines.append("#endif")
        lines.append("#ifndef BASIS_TASK")
        lines.append("#define BASIS_TASK")
        lines.append("#endif")
        lines.append("#ifndef BASIS_REGION")
        lines.append("#define BASIS_REGION(name)")
        lines.append("#endif")
        lines.append("")

        used_helpers = self._collect_used_helpers(module)
        if used_helpers:
            lines.append("// BASIS runtime helpers")
            for helper_name in self.RUNTIME_HELPERS:
                if helper_name in used_helpers:
                    lines.append(self.RUNTIME_HELPERS[helper_name])
            lines.append("")

        if self._needs_bounds_check(module):
            lines.append("// BASIS runtime bounds checking")
            lines.append("static void _basis_bounds_check(int32_t index, int32_t size) {")
            lines.append("    if (index < 0 || index >= size) {")
            lines.append('        fprintf(stderr, "BASIS RUNTIME ERROR: array index %d out of bounds (size %d)\\n", index, size);')
            lines.append("        exit(1);")
            lines.append("    }")
            lines.append("}")
            lines.append("")

        imports = self.import_graph.get(module.name, set())
        for imported in sorted(imports):
            if imported != module.name and imported != "main":
                lines.append(f'#include "{imported}.h"')
        if imports:
            lines.append("")

        private_structs = [struct_def for struct_def in module.structs if not self._should_export(struct_def.visibility)]
        if private_structs:
            for struct_def in private_structs:
                lines.extend(self._emit_struct_decl(struct_def))
                lines.append("")

        extern_statics = [global_value for global_value in module.globals if global_value.initializer is None]
        for extern_static in extern_statics:
            lines.append(f"extern {self._emit_type(extern_static.type)} {extern_static.name};")
        if extern_statics:
            lines.append("")

        helper_names = used_helpers
        for extern_fn in module.externs:
            if extern_fn.name in helper_names:
                continue
            if not extern_fn.symbol_name or extern_fn.symbol_name == extern_fn.name:
                continue
            extern_name = extern_fn.symbol_name or extern_fn.name
            lines.append(f"extern {self._emit_extern_decl(extern_fn, emit_name=extern_name)};")
        if module.externs:
            lines.append("")

        for global_value in module.globals:
            if global_value.initializer is None:
                continue
            storage = "const " if self._should_export(global_value.visibility) else "static const "
            lines.append(
                f"{storage}{self._emit_type(global_value.type)} {global_value.name} = {global_value.initializer};"
            )
        if any(global_value.initializer is not None for global_value in module.globals):
            lines.append("")

        for function in module.functions:
            if self._should_export(function.visibility):
                continue
            lines.append(self._emit_function_decl(function, force_static=True))
        if module.functions:
            private_functions = [fn for fn in module.functions if not self._should_export(fn.visibility)]
            if private_functions:
                lines.append("")

        module_context = ModuleEmissionContext(module=module, helper_names=helper_names)
        for function in module.functions:
            lines.extend(self._emit_function_impl(module_context, function))

        return "\n".join(lines)

    def _emit_struct_decl(self, struct_def: StructDef) -> List[str]:
        lines = [f"typedef struct {struct_def.name} {struct_def.name};", f"struct {struct_def.name} {{"]
        for field in struct_def.fields:
            lines.append(f"    {self._emit_field_decl(field)};")
        lines.append("};")
        return lines

    def _emit_field_decl(self, field: Field) -> str:
        if field.type.kind == "array":
            base = self._emit_type(field.type.elem)
            return f"{base} {field.name}[{field.type.len}]"
        return f"{self._emit_type(field.type)} {field.name}"

    def _emit_function_decl(
        self,
        function: Function,
        *,
        force_static: bool = False,
    ) -> str:
        prefix = self._function_prefix(function, force_static=force_static)
        params = ", ".join(self._emit_param_decl(param) for param in function.params) or "void"
        return f"{prefix}{self._emit_type(function.returns)} {function.name}({params});"

    def _emit_extern_decl(self, extern_fn: Extern, *, emit_name: Optional[str] = None) -> str:
        params = ", ".join(self._emit_param_decl(param) for param in extern_fn.params) or "void"
        return f"{self._emit_type(extern_fn.returns)} {emit_name or extern_fn.name}({params})"

    def _emit_param_decl(self, param: Param) -> str:
        if param.type.kind == "array":
            return f"{self._emit_type(param.type.elem)}* {param.name}"
        return f"{self._emit_type(param.type)} {param.name}"

    def _function_prefix(self, function: Function, *, force_static: bool = False) -> str:
        parts: List[str] = []
        if force_static:
            parts.append("static")
        if function.attrs.region_name:
            parts.append(f'BASIS_REGION("{function.attrs.region_name}")')
        if function.attrs.inline_hint:
            if not parts or parts[-1] != "static":
                parts.append("static")
            parts.append("inline")
        if function.attrs.task_stack is not None:
            parts.append("BASIS_TASK")
        if function.attrs.interrupt:
            parts.append("BASIS_INTERRUPT")
        return (" ".join(parts) + " ") if parts else ""

    def _emit_type(self, type_node: Type) -> str:
        type_map = {
            "i8": "int8_t",
            "i16": "int16_t",
            "i32": "int32_t",
            "i64": "int64_t",
            "u8": "uint8_t",
            "u16": "uint16_t",
            "u32": "uint32_t",
            "u64": "uint64_t",
            "f32": "float",
            "f64": "double",
            "bool": "bool",
            "void": "void",
        }
        if type_node.kind in type_map:
            return type_map[type_node.kind]
        if type_node.kind == "struct":
            if not type_node.name:
                raise BirCBackendError("struct types must preserve a name for C emission")
            return type_node.name
        if type_node.kind == "ptr":
            if type_node.elem is None:
                raise BirCBackendError("pointer types require an element type")
            pointee = self._emit_type(type_node.elem)
            qualifier = "volatile " if type_node.volatile else ""
            return f"{qualifier}{pointee}*"
        if type_node.kind == "array":
            if type_node.elem is None or type_node.len is None:
                raise BirCBackendError("array types require elem and len")
            return self._emit_type(type_node.elem)
        raise BirCBackendError(f"unsupported BIR type kind '{type_node.kind}'")

    def _should_export(self, visibility: str) -> bool:
        return visibility == "public" or self.export_all or visibility == "entry"

    def _collect_used_helpers(self, module: Module) -> Set[str]:
        used: Set[str] = set()
        all_helpers = set(self.RUNTIME_HELPERS.keys())
        for function in module.functions:
            for block in function.blocks:
                for instruction in block.instructions:
                    if instruction.kind != "call" or not instruction.opcode:
                        continue
                    if instruction.opcode in all_helpers:
                        used.add(instruction.opcode)
                        for dependency in self.HELPER_DEPS.get(instruction.opcode, ()):
                            used.add(dependency)
        return used

    def _needs_bounds_check(self, module: Module) -> bool:
        for function in module.functions:
            value_types = self._build_value_type_table(module, function)
            for block in function.blocks:
                for instruction in block.instructions:
                    if instruction.kind != "extract" or instruction.opcode != "index":
                        continue
                    base_type = value_types.get(instruction.operands[0].name)
                    if base_type is None or base_type.kind != "array":
                        continue
                    if not self._is_literal_ref(instruction.operands[1].name):
                        return True
        return False

    def _emit_function_impl(self, context: "ModuleEmissionContext", function: Function) -> List[str]:
        emitter = FunctionEmitter(context=context, backend=self, function=function)
        return emitter.emit()

    def _build_value_type_table(self, module: Module, function: Function) -> Dict[str, Type]:
        value_types: Dict[str, Type] = {}
        for param in function.params:
            value_types[param.name] = param.type
        for global_value in module.globals:
            value_types[global_value.name] = global_value.type
        for instruction_block in function.blocks:
            for instruction in instruction_block.instructions:
                if instruction.result is not None:
                    value_types[instruction.result.name] = instruction.type
                if instruction.kind in {"store", "load"} and instruction.operands:
                    target_name = instruction.operands[0].name
                    if target_name.startswith("slot_"):
                        value_types.setdefault(target_name, instruction.type)
        return value_types

    def _is_literal_ref(self, name: str) -> bool:
        return name.startswith("literal_")

    def decode_literal(self, ref: ValueRef) -> str:
        name = ref.name
        if name.startswith("literal_string_b64_"):
            encoded = name[len("literal_string_b64_") :]
            padding = "=" * ((4 - len(encoded) % 4) % 4)
            raw = base64.urlsafe_b64decode(encoded + padding).decode("utf-8")
            return json.dumps(raw)

        if not name.startswith("literal_"):
            raise BirCBackendError(f"value '{name}' is not a literal")

        _, literal_kind, raw_value = name.split("_", 2)
        if literal_kind == "bool":
            return "true" if raw_value == "true" else "false"
        if literal_kind in {"int", "float"}:
            return raw_value.replace("neg_", "-")
        if literal_kind.startswith("i") or literal_kind.startswith("u") or literal_kind.startswith("f"):
            return raw_value.replace("neg_", "-")
        raise BirCBackendError(f"unsupported literal reference '{name}'")


class ModuleEmissionContext:
    def __init__(self, module: Module, helper_names: Set[str]):
        self.module = module
        self.helper_names = helper_names
        self.extern_map = {extern_fn.name: extern_fn for extern_fn in module.externs}


class FunctionEmitter:
    def __init__(self, context: ModuleEmissionContext, backend: BirCBackend, function: Function):
        self.context = context
        self.backend = backend
        self.function = function
        self.lines: List[str] = []
        self.indent = 0
        self.value_types = backend._build_value_type_table(context.module, function)
        self.local_decls = self._collect_local_decls()

    def emit(self) -> List[str]:
        prefix = self.backend._function_prefix(
            self.function,
            force_static=not self.backend._should_export(self.function.visibility),
        )
        params = ", ".join(self.backend._emit_param_decl(param) for param in self.function.params) or "void"
        self._line(f"{prefix}{self.backend._emit_type(self.function.returns)} {self.function.name}({params}) {{")
        self.indent += 1

        for declaration in self.local_decls:
            self._line(declaration)
        if self.local_decls:
            self._line("")

        for block in self.function.blocks:
            self.indent -= 1
            self._line(f"{block.name}:")
            self.indent += 1
            for instruction in block.instructions:
                self._emit_instruction(instruction)
            self._emit_terminator(block.terminator)

        self.indent -= 1
        self._line("}")
        self._line("")
        return self.lines

    def _collect_local_decls(self) -> List[str]:
        declared: Dict[str, Type] = {}
        for block in self.function.blocks:
            for instruction in block.instructions:
                if instruction.result is not None:
                    declared.setdefault(instruction.result.name, instruction.type)
                if instruction.kind in {"store", "load"} and instruction.operands:
                    target_name = instruction.operands[0].name
                    if target_name.startswith("slot_"):
                        declared.setdefault(target_name, instruction.type)

        declarations: List[str] = []
        for name, type_node in declared.items():
            declarations.append(self._declare_value(type_node, name))
        return declarations

    def _declare_value(self, type_node: Type, name: str) -> str:
        if type_node.kind == "array":
            if type_node.elem is None or type_node.len is None:
                raise BirCBackendError(f"array local '{name}' is missing shape")
            return f"{self.backend._emit_type(type_node.elem)} {name}[{type_node.len}];"
        return f"{self.backend._emit_type(type_node)} {name};"

    def _emit_instruction(self, instruction: Instruction):
        if instruction.kind == "math":
            self._emit_math(instruction)
            return
        if instruction.kind == "compare":
            self._emit_binary_assign(instruction, operator=instruction.opcode or "==")
            return
        if instruction.kind == "cast":
            operand = self._render_value(instruction.operands[0])
            self._assign_result(instruction, f"(({self.backend._emit_type(instruction.type)})({operand}))")
            return
        if instruction.kind == "call":
            self._emit_call(instruction)
            return
        if instruction.kind == "load":
            self._emit_load(instruction)
            return
        if instruction.kind == "store":
            self._emit_store(instruction)
            return
        if instruction.kind == "assign":
            self._emit_assign(instruction)
            return
        if instruction.kind == "extract":
            self._emit_extract(instruction)
            return
        if instruction.kind == "insert":
            self._emit_insert(instruction)
            return
        if instruction.kind == "address_of":
            operand = self._render_value(instruction.operands[0])
            self._assign_result(instruction, f"(&{operand})")
            return
        if instruction.kind == "phi":
            raise BirCBackendError(
                f"function '{self.context.module.name}::{self.function.name}' uses phi nodes, which the C backend does not emit yet"
            )
        raise BirCBackendError(
            f"function '{self.context.module.name}::{self.function.name}' contains unsupported instruction kind '{instruction.kind}'"
        )

    def _emit_math(self, instruction: Instruction):
        if instruction.opcode is None:
            raise BirCBackendError("math instruction is missing an opcode")
        if len(instruction.operands) == 1:
            operand = self._render_value(instruction.operands[0])
            self._assign_result(instruction, f"({instruction.opcode}{operand})")
            return
        self._emit_binary_assign(instruction, operator=instruction.opcode)

    def _emit_binary_assign(self, instruction: Instruction, *, operator: str):
        if len(instruction.operands) != 2:
            raise BirCBackendError(f"binary instruction '{instruction.kind}' expected two operands")
        left = self._render_value(instruction.operands[0])
        right = self._render_value(instruction.operands[1])
        self._assign_result(instruction, f"({left} {operator} {right})")

    def _emit_call(self, instruction: Instruction):
        if instruction.opcode is None:
            raise BirCBackendError("call instruction is missing a callee opcode")
        callee_name = instruction.opcode
        extern_decl = self.context.extern_map.get(callee_name)
        if extern_decl is not None and callee_name not in self.context.helper_names:
            callee_name = extern_decl.symbol_name or extern_decl.name

        args = ", ".join(self._render_value(arg) for arg in instruction.operands[1:])
        if instruction.result is None:
            self._line(f"{callee_name}({args});")
            return
        if instruction.type.kind == "array":
            raise BirCBackendError("functions cannot return arrays by value in the C backend")
        self._line(f"{instruction.result.name} = {callee_name}({args});")

    def _emit_load(self, instruction: Instruction):
        if instruction.result is None:
            raise BirCBackendError("load instruction requires a result")
        source_ref = instruction.operands[0]
        if instruction.opcode == "*":
            pointer_expr = self._render_value(source_ref)
            if instruction.type.kind == "array":
                self._line(f"memcpy({instruction.result.name}, *{pointer_expr}, sizeof({instruction.result.name}));")
                return
            self._line(f"{instruction.result.name} = *{pointer_expr};")
            return

        source_expr = self._render_slot_lvalue(source_ref)
        if instruction.type.kind == "array":
            self._line(f"memcpy({instruction.result.name}, {source_expr}, sizeof({instruction.result.name}));")
            return
        self._line(f"{instruction.result.name} = {source_expr};")

    def _emit_store(self, instruction: Instruction):
        target_ref = instruction.operands[0]
        value_ref = instruction.operands[1]
        value_expr = self._render_value(value_ref)

        if instruction.opcode == "*=":
            pointer_expr = self._render_value(target_ref)
            self._line(f"*{pointer_expr} = {value_expr};")
            return
        if instruction.opcode == "field_store":
            pointer_expr = self._render_value(target_ref)
            self._line(f"*{pointer_expr} = {value_expr};")
            return

        target_expr = self._render_slot_lvalue(target_ref)
        if instruction.type.kind == "array":
            self._line(f"memcpy({target_expr}, {value_expr}, sizeof({target_expr}));")
            return
        self._line(f"{target_expr} = {value_expr};")

    def _emit_assign(self, instruction: Instruction):
        if instruction.result is None:
            raise BirCBackendError("assign instruction requires a result")
        if instruction.opcode == "array_literal":
            self._line(f"memset({instruction.result.name}, 0, sizeof({instruction.result.name}));")
            return
        if instruction.opcode == "array_repeat":
            if instruction.type.len is None:
                raise BirCBackendError("array_repeat requires a concrete array length")
            default_value = self._render_value(instruction.operands[0])
            loop_var = f"basis_i_{instruction.result.name}"
            self._line(f"for (int32_t {loop_var} = 0; {loop_var} < {instruction.type.len}; {loop_var}++) {{")
            self.indent += 1
            self._line(f"{instruction.result.name}[{loop_var}] = {default_value};")
            self.indent -= 1
            self._line("}")
            return
        if instruction.opcode and instruction.opcode.startswith("struct_literal:"):
            struct_name = instruction.opcode.split(":", 1)[1]
            self._line(f"{instruction.result.name} = ({struct_name}){{0}};")
            return
        raise BirCBackendError(f"unsupported assign opcode '{instruction.opcode}'")

    def _emit_extract(self, instruction: Instruction):
        if instruction.result is None:
            raise BirCBackendError("extract instruction requires a result")
        base_ref = instruction.operands[0]
        if instruction.opcode == "index":
            base_expr = self._render_value(base_ref)
            index_ref = instruction.operands[1]
            index_expr = self._render_value(index_ref)
            base_type = self.value_types.get(base_ref.name)
            if base_type is not None and base_type.kind == "array" and base_type.len is not None:
                if not self.backend._is_literal_ref(index_ref.name):
                    self._line(f"_basis_bounds_check({index_expr}, {base_type.len});")
            self._line(f"{instruction.result.name} = {base_expr}[{index_expr}];")
            return
        base_expr = self._render_value(base_ref)
        if instruction.type.kind == "array":
            self._line(f"memcpy({instruction.result.name}, {base_expr}.{instruction.opcode}, sizeof({instruction.result.name}));")
            return
        self._line(f"{instruction.result.name} = {base_expr}.{instruction.opcode};")

    def _emit_insert(self, instruction: Instruction):
        if instruction.result is None:
            raise BirCBackendError("insert instruction requires a result")
        base_ref = instruction.operands[0]
        base_expr = self._render_value(base_ref)
        if instruction.opcode == "index":
            index_ref = instruction.operands[1]
            value_ref = instruction.operands[2]
            index_expr = self._render_value(index_ref)
            value_expr = self._render_value(value_ref)
            self._line(f"memcpy({instruction.result.name}, {base_expr}, sizeof({instruction.result.name}));")
            if instruction.type.len is not None and not self.backend._is_literal_ref(index_ref.name):
                self._line(f"_basis_bounds_check({index_expr}, {instruction.type.len});")
            self._line(f"{instruction.result.name}[{index_expr}] = {value_expr};")
            return

        value_expr = self._render_value(instruction.operands[1])
        self._line(f"{instruction.result.name} = {base_expr};")
        field_type = self._struct_field_type(base_ref.name, instruction.opcode)
        if field_type is not None and field_type.kind == "array":
            self._line(
                f"memcpy({instruction.result.name}.{instruction.opcode}, {value_expr}, sizeof({instruction.result.name}.{instruction.opcode}));"
            )
            return
        self._line(f"{instruction.result.name}.{instruction.opcode} = {value_expr};")

    def _emit_terminator(self, terminator: Terminator):
        if terminator.kind == "ret":
            if terminator.operands:
                self._line(f"return {self._render_value(terminator.operands[0])};")
            else:
                self._line("return;")
            return
        if terminator.kind == "br":
            self._line(f"goto {terminator.targets[0]};")
            return
        if terminator.kind == "cond_br":
            condition = self._render_value(terminator.operands[0])
            self._line(f"if ({condition}) goto {terminator.targets[0]};")
            self._line(f"goto {terminator.targets[1]};")
            return
        if terminator.kind == "unreachable":
            self._line("abort();")
            return
        raise BirCBackendError(f"unsupported terminator kind '{terminator.kind}'")

    def _assign_result(self, instruction: Instruction, value_expr: str):
        if instruction.result is None:
            raise BirCBackendError(f"instruction '{instruction.kind}' requires a result")
        if instruction.type.kind == "array":
            self._line(f"memcpy({instruction.result.name}, {value_expr}, sizeof({instruction.result.name}));")
            return
        self._line(f"{instruction.result.name} = {value_expr};")

    def _render_value(self, ref: ValueRef) -> str:
        name = ref.name
        if self.backend._is_literal_ref(name):
            return self.backend.decode_literal(ref)
        if name == "void":
            return "0"
        if name.startswith("slot_"):
            slot_type = self.value_types.get(name)
            if slot_type is None:
                raise BirCBackendError(f"missing type for slot '{name}'")
            if slot_type.kind == "array":
                return name
            return f"&{name}"
        return name

    def _render_slot_lvalue(self, ref: ValueRef) -> str:
        return ref.name

    def _struct_field_type(self, base_name: str, field_name: str) -> Optional[Type]:
        base_type = self.value_types.get(base_name)
        if base_type is None or base_type.kind != "struct":
            return None
        for field in base_type.fields:
            if field.name == field_name:
                return field.type
        return None

    def _line(self, text: str):
        indent = "    " * self.indent if text else ""
        self.lines.append(f"{indent}{text}" if text else "")
