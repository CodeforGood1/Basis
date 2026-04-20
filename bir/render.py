"""
Canonical BIR rendering utilities.

Phase 1 uses plain dictionaries/lists so tests can snapshot stable structure
without depending on repr() formatting.
"""

from dataclasses import is_dataclass, fields


def render_bir(node):
    """Render a BIR node into plain Python structures with stable field order."""
    if is_dataclass(node):
        rendered = {}
        for field_info in fields(node):
            rendered[field_info.name] = render_bir(getattr(node, field_info.name))
        return rendered

    if isinstance(node, list):
        return [render_bir(item) for item in node]

    return node
