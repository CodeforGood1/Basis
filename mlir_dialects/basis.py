"""
Textual BASIS MLIR dialect model and renderer.

This is intentionally a structured, human-readable bridge artifact rather than a
full dependency on the upstream MLIR Python bindings. Phase 6 can lower this
model to stricter MLIR/LLVM dialects without changing the frontend contract.
"""

from dataclasses import dataclass, field
import json
from typing import Dict, List, Optional

from bir.model import Type


@dataclass(frozen=True)
class BasisMlirField:
    name: str
    type_text: str


@dataclass(frozen=True)
class BasisMlirImport:
    module_name: str
    items: List[str] = field(default_factory=list)
    is_wildcard: bool = False


@dataclass(frozen=True)
class BasisMlirStruct:
    name: str
    visibility: str
    fields: List[BasisMlirField] = field(default_factory=list)


@dataclass(frozen=True)
class BasisMlirGlobal:
    name: str
    visibility: str
    type_text: str
    initializer: Optional[str] = None


@dataclass(frozen=True)
class BasisMlirExtern:
    name: str
    visibility: str
    params: List[BasisMlirField]
    returns: str
    attrs: Dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class BasisMlirOp:
    op_name: str
    operands: List[str] = field(default_factory=list)
    result: Optional[str] = None
    result_type: Optional[str] = None
    attrs: Dict[str, str] = field(default_factory=dict)
    successors: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class BasisMlirBlock:
    label: str
    ops: List[BasisMlirOp] = field(default_factory=list)


@dataclass(frozen=True)
class BasisMlirFunction:
    name: str
    visibility: str
    params: List[BasisMlirField]
    returns: str
    attrs: Dict[str, str] = field(default_factory=dict)
    blocks: List[BasisMlirBlock] = field(default_factory=list)


@dataclass(frozen=True)
class BasisMlirModule:
    name: str
    source_path: str
    attrs: Dict[str, str] = field(default_factory=dict)
    imports: List[BasisMlirImport] = field(default_factory=list)
    structs: List[BasisMlirStruct] = field(default_factory=list)
    globals: List[BasisMlirGlobal] = field(default_factory=list)
    externs: List[BasisMlirExtern] = field(default_factory=list)
    functions: List[BasisMlirFunction] = field(default_factory=list)


@dataclass(frozen=True)
class BasisMlirProgram:
    name: str
    target: str
    profile: str
    entry: str
    attrs: Dict[str, str] = field(default_factory=dict)
    modules: List[BasisMlirModule] = field(default_factory=list)


def render_basis_type(type_node: Type) -> str:
    scalar_types = {
        "i8": "i8",
        "i16": "i16",
        "i32": "i32",
        "i64": "i64",
        "u8": "!basis.u8",
        "u16": "!basis.u16",
        "u32": "!basis.u32",
        "u64": "!basis.u64",
        "bool": "i1",
        "f32": "f32",
        "f64": "f64",
        "void": "none",
    }
    if type_node.kind in scalar_types:
        return scalar_types[type_node.kind]
    if type_node.kind == "ptr":
        assert type_node.elem is not None
        inner = render_basis_type(type_node.elem)
        if type_node.volatile:
            return f"!basis.ptr<volatile {inner}>"
        return f"!basis.ptr<{inner}>"
    if type_node.kind == "array":
        assert type_node.elem is not None and type_node.len is not None
        return f"!basis.array<{type_node.len} x {render_basis_type(type_node.elem)}>"
    if type_node.kind == "struct":
        if not type_node.name:
            raise ValueError("struct types must preserve a name for MLIR rendering")
        field_parts = ", ".join(f"{field.name}: {render_basis_type(field.type)}" for field in type_node.fields)
        return f'!basis.struct<{json.dumps(type_node.name)}, {{{field_parts}}}>'
    raise ValueError(f"unsupported BIR type kind '{type_node.kind}'")


def render_basis_mlir_program(program: BasisMlirProgram) -> str:
    lines: List[str] = []
    _line(
        lines,
        0,
        f"basis.program @{program.name} attributes {_render_attrs(program.attrs)} {{",
    )
    for module in program.modules:
        _render_module(lines, 1, module)
    _line(lines, 0, "}")
    return "\n".join(lines) + "\n"


def _render_module(lines: List[str], indent: int, module: BasisMlirModule):
    _line(lines, indent, f"basis.module @{module.name} attributes {_render_attrs(module.attrs)} {{")
    for import_decl in module.imports:
        attrs = {
            "items": _render_array([json.dumps(item) for item in import_decl.items]),
            "wildcard": str(import_decl.is_wildcard).lower(),
        }
        _line(lines, indent + 1, f"basis.import @{import_decl.module_name} attributes {_render_attrs(attrs)}")

    for struct_def in module.structs:
        _line(
            lines,
            indent + 1,
            f'basis.struct @{struct_def.name} attributes {{visibility = {json.dumps(struct_def.visibility)}}} {{',
        )
        for field in struct_def.fields:
            _line(lines, indent + 2, f"basis.field @{field.name} : {field.type_text}")
        _line(lines, indent + 1, "}")

    for global_value in module.globals:
        attrs = {"visibility": json.dumps(global_value.visibility)}
        if global_value.initializer is not None:
            attrs["initializer"] = json.dumps(global_value.initializer)
        _line(
            lines,
            indent + 1,
            f"basis.global @{global_value.name} : {global_value.type_text} attributes {_render_attrs(attrs)}",
        )

    for extern_fn in module.externs:
        params = ", ".join(f"%{param.name}: {param.type_text}" for param in extern_fn.params)
        _line(
            lines,
            indent + 1,
            f"basis.extern @{extern_fn.name}({params}) -> {extern_fn.returns} attributes {_render_attrs(extern_fn.attrs)}",
        )

    for function in module.functions:
        params = ", ".join(f"%{param.name}: {param.type_text}" for param in function.params)
        _line(
            lines,
            indent + 1,
            f"basis.func @{function.name}({params}) -> {function.returns} attributes {_render_attrs(function.attrs)} {{",
        )
        for block in function.blocks:
            _line(lines, indent + 2, f"^{block.label}:")
            for op in block.ops:
                _line(lines, indent + 3, _render_op(op))
        _line(lines, indent + 1, "}")
    _line(lines, indent, "}")


def _render_op(op: BasisMlirOp) -> str:
    if op.op_name == "basis.br":
        return f"basis.br ^{op.successors[0]}"
    if op.op_name == "basis.cond_br":
        return f"basis.cond_br {op.operands[0]}, ^{op.successors[0]}, ^{op.successors[1]}"
    if op.op_name == "basis.ret":
        suffix = f" : {op.result_type}" if op.result_type else ""
        if op.operands:
            return f"basis.ret {op.operands[0]}{suffix}"
        return "basis.ret"
    if op.op_name == "basis.unreachable":
        return "basis.unreachable"

    lhs = f"%{op.result} = " if op.result else ""
    operands = ", ".join(op.operands)
    attrs = f" attributes {_render_attrs(op.attrs)}" if op.attrs else ""
    type_suffix = f" : {op.result_type}" if op.result_type else ""
    if operands:
        return f"{lhs}{op.op_name} {operands}{attrs}{type_suffix}"
    return f"{lhs}{op.op_name}{attrs}{type_suffix}"


def _render_attrs(attrs: Dict[str, str]) -> str:
    if not attrs:
        return "{}"
    parts = [f"{key} = {attrs[key]}" for key in sorted(attrs)]
    return "{ " + ", ".join(parts) + " }"


def _render_array(items: List[str]) -> str:
    return "[" + ", ".join(items) + "]"


def _line(lines: List[str], indent: int, text: str):
    lines.append(("    " * indent) + text)
