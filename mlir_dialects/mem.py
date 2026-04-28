"""
Helpers for rendering memory-oriented metadata in BASIS MLIR.
"""

from typing import Optional


def render_memory_attr(
    *,
    allocates_max: Optional[int],
    storage_bytes: Optional[int],
    storage_objects: Optional[int],
) -> str:
    allocates_text = "none" if allocates_max is None else str(allocates_max)
    storage_bytes_text = "none" if storage_bytes is None else str(storage_bytes)
    storage_objects_text = "none" if storage_objects is None else str(storage_objects)
    return (
        "#basis.mem<"
        f"allocates_max = {allocates_text}, "
        f"storage_bytes = {storage_bytes_text}, "
        f"storage_objects = {storage_objects_text}"
        ">"
    )


def render_pointer_qualifier_attr(*, is_volatile: bool) -> str:
    return f"#basis.mem<volatile = {str(is_volatile).lower()}>"
