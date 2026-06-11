from __future__ import annotations

from typing import Any


def render_nested_templates(value: Any, variables: dict[str, str]) -> Any:
    if isinstance(value, str):
        rendered = value
        for key, replacement in variables.items():
            rendered = rendered.replace(f"{{{{{key}}}}}", replacement)
        return rendered
    if isinstance(value, list):
        return [render_nested_templates(item, variables) for item in value]
    if isinstance(value, dict):
        return {key: render_nested_templates(item, variables) for key, item in value.items()}
    return value
