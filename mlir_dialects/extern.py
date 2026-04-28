"""
Helpers for rendering extern/effect attributes in BASIS MLIR.
"""

import json
from typing import Optional


def render_extern_attr(*, abi: str, symbol_name: Optional[str]) -> str:
    items = [f"abi = {json.dumps(abi)}"]
    if symbol_name:
        items.append(f"symbol = {json.dumps(symbol_name)}")
    return "#basis.extern<" + ", ".join(items) + ">"


def render_effects_attr(
    *,
    deterministic: bool,
    blocking: bool,
    allocates: Optional[int],
    uses_storage: bool,
    isr_safe: bool,
) -> str:
    allocates_text = "none" if allocates is None else str(allocates)
    return (
        "#basis.effects<"
        f"deterministic = {str(deterministic).lower()}, "
        f"blocking = {str(blocking).lower()}, "
        f"allocates = {allocates_text}, "
        f"uses_storage = {str(uses_storage).lower()}, "
        f"isr_safe = {str(isr_safe).lower()}"
        ">"
    )
