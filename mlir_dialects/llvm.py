"""
Textual LLVM-dialect-style MLIR model and renderer for the Phase 6 pipeline.

This is still an internal staged representation. It keeps the Phase 5 BASIS
dialect authoritative and lowers toward an LLVM-shaped IR without bypassing
frontend or BIR semantics.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass(frozen=True)
class LlvmMlirParam:
    name: str
    type_text: str


@dataclass(frozen=True)
class LlvmMlirTypeDecl:
    name: str
    body: str


@dataclass(frozen=True)
class LlvmMlirGlobal:
    name: str
    type_text: str
    attrs: Dict[str, str] = field(default_factory=dict)
    initializer: Optional[str] = None


@dataclass(frozen=True)
class LlvmMlirExtern:
    name: str
    params: List[LlvmMlirParam]
    returns: str
    attrs: Dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class LlvmMlirOp:
    op_name: str
    operands: List[str] = field(default_factory=list)
    result: Optional[str] = None
    result_type: Optional[str] = None
    attrs: Dict[str, str] = field(default_factory=dict)
    successors: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class LlvmMlirBlock:
    label: str
    ops: List[LlvmMlirOp] = field(default_factory=list)


@dataclass(frozen=True)
class LlvmMlirFunction:
    name: str
    params: List[LlvmMlirParam]
    returns: str
    attrs: Dict[str, str] = field(default_factory=dict)
    blocks: List[LlvmMlirBlock] = field(default_factory=list)


@dataclass(frozen=True)
class LlvmMlirModule:
    name: str
    attrs: Dict[str, str] = field(default_factory=dict)
    type_decls: List[LlvmMlirTypeDecl] = field(default_factory=list)
    globals: List[LlvmMlirGlobal] = field(default_factory=list)
    externs: List[LlvmMlirExtern] = field(default_factory=list)
    functions: List[LlvmMlirFunction] = field(default_factory=list)


@dataclass(frozen=True)
class LlvmMlirProgram:
    name: str
    target: str
    profile: str
    entry: str
    attrs: Dict[str, str] = field(default_factory=dict)
    modules: List[LlvmMlirModule] = field(default_factory=list)


def render_llvm_mlir_program(program: LlvmMlirProgram) -> str:
    lines: List[str] = []
    _line(lines, 0, f"builtin.module attributes {_render_attrs(program.attrs)} {{")
    for module in program.modules:
        _render_module(lines, 1, module)
    _line(lines, 0, "}")
    return "\n".join(lines) + "\n"


def _render_module(lines: List[str], indent: int, module: LlvmMlirModule):
    _line(lines, indent, f"llvm.module @{module.name} attributes {_render_attrs(module.attrs)} {{")
    for type_decl in module.type_decls:
        _line(lines, indent + 1, f"llvm.type @{type_decl.name} = {type_decl.body}")
    for global_value in module.globals:
        attrs = dict(global_value.attrs)
        if global_value.initializer is not None:
            attrs["initializer"] = global_value.initializer
        _line(
            lines,
            indent + 1,
            f"llvm.mlir.global @{global_value.name} : {global_value.type_text} attributes {_render_attrs(attrs)}",
        )
    for extern_fn in module.externs:
        params = ", ".join(f"%{param.name}: {param.type_text}" for param in extern_fn.params) or ""
        _line(
            lines,
            indent + 1,
            f"llvm.func @{extern_fn.name}({params}) -> {extern_fn.returns} attributes {_render_attrs(extern_fn.attrs)}",
        )
    for function in module.functions:
        params = ", ".join(f"%{param.name}: {param.type_text}" for param in function.params) or ""
        _line(
            lines,
            indent + 1,
            f"llvm.func @{function.name}({params}) -> {function.returns} attributes {_render_attrs(function.attrs)} {{",
        )
        for block in function.blocks:
            _line(lines, indent + 2, f"^{block.label}:")
            for op in block.ops:
                _line(lines, indent + 3, _render_op(op))
        _line(lines, indent + 1, "}")
    _line(lines, indent, "}")


def _render_op(op: LlvmMlirOp) -> str:
    if op.op_name == "llvm.br":
        return f"llvm.br ^{op.successors[0]}"
    if op.op_name == "llvm.cond_br":
        return f"llvm.cond_br {op.operands[0]}, ^{op.successors[0]}, ^{op.successors[1]}"
    if op.op_name == "llvm.return":
        if op.operands:
            suffix = f" : {op.result_type}" if op.result_type else ""
            return f"llvm.return {op.operands[0]}{suffix}"
        return "llvm.return"
    if op.op_name == "llvm.unreachable":
        return "llvm.unreachable"

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


def _line(lines: List[str], indent: int, text: str):
    lines.append(("    " * indent) + text)
