"""
Helpers for rendering interrupt/task execution metadata in BASIS MLIR.
"""

import json
from typing import Optional


def render_execution_attr(
    *,
    interrupt: bool,
    task_stack: Optional[int],
    task_priority: Optional[int],
    region_name: Optional[str],
    inline_hint: bool,
    reentrant: Optional[bool],
    uses_timer: bool,
    may_fail: bool,
) -> str:
    task_stack_text = "none" if task_stack is None else str(task_stack)
    task_priority_text = "none" if task_priority is None else str(task_priority)
    reentrant_text = "none" if reentrant is None else str(reentrant).lower()
    region_text = "none" if region_name is None else json.dumps(region_name)
    return (
        "#basis.isr<"
        f"interrupt = {str(interrupt).lower()}, "
        f"task_stack = {task_stack_text}, "
        f"task_priority = {task_priority_text}, "
        f"region = {region_text}, "
        f"inline = {str(inline_hint).lower()}, "
        f"reentrant = {reentrant_text}, "
        f"uses_timer = {str(uses_timer).lower()}, "
        f"may_fail = {str(may_fail).lower()}"
        ">"
    )
