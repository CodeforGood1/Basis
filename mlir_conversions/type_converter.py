"""
Type conversion helpers for Phase 6 BASIS->LLVM-dialect lowering.
"""

from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass(frozen=True)
class LoweredTypeInfo:
    original: str
    llvm: str
    category: str
    signedness: Optional[str] = None
    bit_width: Optional[int] = None


def lower_basis_type(type_text: str) -> LoweredTypeInfo:
    scalars = {
        "i1": LoweredTypeInfo(original=type_text, llvm="i1", category="bool"),
        "i8": LoweredTypeInfo(original=type_text, llvm="i8", category="int", signedness="signed", bit_width=8),
        "i16": LoweredTypeInfo(original=type_text, llvm="i16", category="int", signedness="signed", bit_width=16),
        "i32": LoweredTypeInfo(original=type_text, llvm="i32", category="int", signedness="signed", bit_width=32),
        "i64": LoweredTypeInfo(original=type_text, llvm="i64", category="int", signedness="signed", bit_width=64),
        "!basis.u8": LoweredTypeInfo(original=type_text, llvm="i8", category="int", signedness="unsigned", bit_width=8),
        "!basis.u16": LoweredTypeInfo(original=type_text, llvm="i16", category="int", signedness="unsigned", bit_width=16),
        "!basis.u32": LoweredTypeInfo(original=type_text, llvm="i32", category="int", signedness="unsigned", bit_width=32),
        "!basis.u64": LoweredTypeInfo(original=type_text, llvm="i64", category="int", signedness="unsigned", bit_width=64),
        "f32": LoweredTypeInfo(original=type_text, llvm="f32", category="float", bit_width=32),
        "f64": LoweredTypeInfo(original=type_text, llvm="f64", category="float", bit_width=64),
        "none": LoweredTypeInfo(original=type_text, llvm="void", category="void"),
    }
    if type_text in scalars:
        return scalars[type_text]

    if type_text.startswith("!basis.ptr<") and type_text.endswith(">"):
        inner = type_text[len("!basis.ptr<") : -1].strip()
        if inner.startswith("volatile "):
            inner = inner[len("volatile ") :].strip()
        inner_info = lower_basis_type(inner)
        return LoweredTypeInfo(original=type_text, llvm=f"!llvm.ptr<{inner_info.llvm}>", category="pointer")

    if type_text.startswith("!basis.array<") and type_text.endswith(">"):
        payload = type_text[len("!basis.array<") : -1]
        len_text, elem_text = _split_once_top_level(payload, " x ")
        elem_info = lower_basis_type(elem_text.strip())
        return LoweredTypeInfo(
            original=type_text,
            llvm=f"!llvm.array<{len_text.strip()} x {elem_info.llvm}>",
            category="array",
        )

    if type_text.startswith("!basis.struct<") and type_text.endswith(">"):
        payload = type_text[len("!basis.struct<") : -1]
        name_text, fields_text = _split_once_top_level(payload, ", ")
        field_items = _parse_struct_fields(fields_text.strip())
        lowered_fields = ", ".join(lower_basis_type(field_type).llvm for _, field_type in field_items)
        return LoweredTypeInfo(
            original=type_text,
            llvm=f"!llvm.struct<{name_text.strip()}, ({lowered_fields})>",
            category="struct",
        )

    raise ValueError(f"unsupported BASIS MLIR type '{type_text}'")


def _parse_struct_fields(fields_text: str) -> List[Tuple[str, str]]:
    if not (fields_text.startswith("{") and fields_text.endswith("}")):
        raise ValueError(f"invalid BASIS struct field payload '{fields_text}'")
    inner = fields_text[1:-1].strip()
    if not inner:
        return []
    parts = _split_top_level(inner, ", ")
    items: List[Tuple[str, str]] = []
    for part in parts:
        name, value = _split_once_top_level(part, ": ")
        items.append((name.strip(), value.strip()))
    return items


def _split_once_top_level(text: str, needle: str) -> Tuple[str, str]:
    depth_angle = 0
    depth_brace = 0
    in_string = False
    for index, char in enumerate(text):
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "<":
            depth_angle += 1
        elif char == ">":
            depth_angle -= 1
        elif char == "{":
            depth_brace += 1
        elif char == "}":
            depth_brace -= 1
        if depth_angle == 0 and depth_brace == 0 and text.startswith(needle, index):
            return text[:index], text[index + len(needle) :]
    raise ValueError(f"unable to split '{text}' on top-level '{needle}'")


def _split_top_level(text: str, needle: str) -> List[str]:
    parts: List[str] = []
    cursor = 0
    while cursor < len(text):
        try:
            left, right = _split_once_top_level(text[cursor:], needle)
        except ValueError:
            parts.append(text[cursor:])
            break
        parts.append(left)
        cursor += len(left) + len(needle)
        if not right:
            break
        text = right
        cursor = 0
    return parts
