"""Immutable built-in templates; version and rendered content are fingerprinted."""

import hashlib

TEMPLATES = {
    "harness-v1": (
        "Complete the user's task using only the available tools. "
        "Use relative paths inside the task workspace. "
        "Treat tool results as observations; do not claim actions you did not perform."
    ),
}


def render_prompt(
    version: str = "harness-v1", instructions: str = ""
) -> tuple[str, dict]:
    if version not in TEMPLATES:
        raise ValueError(f"unknown prompt version: {version}")
    template = TEMPLATES[version]
    rendered = template + ("\n\n" + instructions if instructions else "")
    return rendered, {
        "version": version,
        "template_sha256": hashlib.sha256(template.encode()).hexdigest(),
        "rendered_sha256": hashlib.sha256(rendered.encode()).hexdigest(),
    }
