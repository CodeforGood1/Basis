"""
Helpers for rendering resource-oriented BASIS MLIR attributes.
"""

import json
from typing import Iterable, Optional


def render_resource_attr(
    *,
    stack_max: Optional[int] = None,
    heap_max: Optional[int] = None,
    storage_max: Optional[int] = None,
    code_size_estimate: Optional[int] = None,
    deepest_call_path: Optional[Iterable[str]] = None,
) -> str:
    items = []
    if stack_max is not None:
        items.append(f"stack_max = {stack_max}")
    if heap_max is not None:
        items.append(f"heap_max = {heap_max}")
    if storage_max is not None:
        items.append(f"storage_max = {storage_max}")
    if code_size_estimate is not None:
        items.append(f"code_size_estimate = {code_size_estimate}")
    if deepest_call_path is not None:
        rendered_path = ", ".join(json.dumps(item) for item in deepest_call_path)
        items.append(f"deepest_call_path = [{rendered_path}]")
    return "#basis.resource<" + ", ".join(items) + ">"
