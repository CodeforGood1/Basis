"""
Helpers for rendering bounded-control metadata in BASIS MLIR.
"""

from typing import Optional


def render_control_attr(*, recursion_max: Optional[int], block_count: int) -> str:
    recursion_text = "none" if recursion_max is None else str(recursion_max)
    return f"#basis.control<bounded = true, recursion_max = {recursion_text}, blocks = {block_count}>"
