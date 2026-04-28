"""
Structured LLVM IR model and renderer for the Phase 7 backend.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass(frozen=True)
class LlvmIrGlobal:
    name: str
    type_text: str
    initializer: str
    linkage: str = "internal"
    is_constant: bool = False
    align: Optional[int] = None


@dataclass(frozen=True)
class LlvmIrDeclare:
    name: str
    returns: str
    params: List[str]
    attrs: Dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class LlvmIrInstruction:
    result: Optional[str]
    text: str
    comment: Optional[str] = None


@dataclass(frozen=True)
class LlvmIrBlock:
    label: str
    instructions: List[LlvmIrInstruction] = field(default_factory=list)


@dataclass(frozen=True)
class LlvmIrFunction:
    name: str
    returns: str
    params: List[str]
    linkage: str = "internal"
    attrs: Dict[str, str] = field(default_factory=dict)
    blocks: List[LlvmIrBlock] = field(default_factory=list)


@dataclass(frozen=True)
class LlvmIrModule:
    source_filename: str
    target_triple: str
    identified_types: Dict[str, str] = field(default_factory=dict)
    globals: List[LlvmIrGlobal] = field(default_factory=list)
    declarations: List[LlvmIrDeclare] = field(default_factory=list)
    functions: List[LlvmIrFunction] = field(default_factory=list)
    named_metadata: Dict[str, List[str]] = field(default_factory=dict)


def render_llvm_ir(module: LlvmIrModule) -> str:
    lines: List[str] = []
    lines.append(f'source_filename = "{module.source_filename}"')
    lines.append(f'target triple = "{module.target_triple}"')
    lines.append("")

    for name in sorted(module.identified_types):
        lines.append(f"%{name} = type {module.identified_types[name]}")
    if module.identified_types:
        lines.append("")

    for global_value in module.globals:
        qualifier = "constant" if global_value.is_constant else "global"
        align = f", align {global_value.align}" if global_value.align is not None else ""
        lines.append(
            f"@{global_value.name} = {global_value.linkage} {qualifier} {global_value.type_text} {global_value.initializer}{align}"
        )
    if module.globals:
        lines.append("")

    for declare in module.declarations:
        attr_suffix = _render_fn_attrs(declare.attrs)
        params = ", ".join(declare.params)
        lines.append(f"declare {declare.returns} @{declare.name}({params}){attr_suffix}")
    if module.declarations:
        lines.append("")

    for function in module.functions:
        attr_suffix = _render_fn_attrs(function.attrs)
        params = ", ".join(function.params)
        lines.append(f"define {function.linkage} {function.returns} @{function.name}({params}){attr_suffix} {{")
        for block in function.blocks:
            lines.append(f"{block.label}:")
            for instruction in block.instructions:
                if instruction.result:
                    body = f"  %{instruction.result} = {instruction.text}"
                else:
                    body = f"  {instruction.text}"
                if instruction.comment:
                    body = f"{body} ; {instruction.comment}"
                lines.append(body)
        lines.append("}")
        lines.append("")

    for metadata_name, entries in sorted(module.named_metadata.items()):
        rendered_entries = ", ".join(entries)
        lines.append(f"!{metadata_name} = !{{{rendered_entries}}}")

    return "\n".join(lines).rstrip() + "\n"


def _render_fn_attrs(attrs: Dict[str, str]) -> str:
    if not attrs:
        return ""
    parts = [value for _, value in sorted(attrs.items()) if value]
    if not parts:
        return ""
    return " " + " ".join(parts)
