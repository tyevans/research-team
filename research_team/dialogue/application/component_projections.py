"""Shared component extraction, projection, and validation for dialogue surfaces."""

from typing import Any

from research_team.platform.components import View, parse_document, project


def parse_and_project(text: str, view: View = "learner") -> dict[str, Any]:
    """Parse and project a dialogue or answer document.

    `path=""` because ephemeral dialogue turns have no file. `Document.path` is
    a label used in error messages and derived ids -- `derive_id` hashes it with
    the block's index -- so an empty one is stable and honest rather than a
    fabricated filename.
    """
    return project(parse_document(text, path=""), view=view)


def extract_components_from_doc(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract all parsed and projected component blocks from a projected document."""
    return [b for b in doc.get("blocks", []) if b.get("kind") == "component"]


def extract_prose_from_doc(doc: dict[str, Any]) -> str:
    """Extract markdown text without component blocks from a projected document."""
    paragraphs = [
        b["text"]
        for b in doc.get("blocks", [])
        if b.get("kind") == "markdown" and b.get("text")
    ]
    return "\n\n".join(paragraphs)


def has_components_in_doc(doc: dict[str, Any]) -> bool:
    """Check if the projected document contains any components."""
    return any(b.get("kind") == "component" for b in doc.get("blocks", []))


def has_gradeable_components_in_doc(doc: dict[str, Any]) -> bool:
    """Check if the projected document contains any gradeable components."""
    components = extract_components_from_doc(doc)
    return any(c.get("gradeable", False) for c in components)


def extract_component_ids_from_doc(doc: dict[str, Any]) -> list[str]:
    """Return all component IDs present in the projected document."""
    return [c["id"] for c in extract_components_from_doc(doc) if "id" in c]


def extract_component_types_from_doc(doc: dict[str, Any]) -> list[str]:
    """Return all component types present in the projected document."""
    return [c["type"] for c in extract_components_from_doc(doc) if "type" in c]


def validate_components_in_doc(
    doc: dict[str, Any],
    allowed_types: tuple[str, ...],
    context_name: str | None = None,
) -> list[str]:
    """Return a list of errors if any component has errors or is not an allowed type."""
    errors: list[str] = []
    components = extract_components_from_doc(doc)
    for c in components:
        comp_type = c.get("type", "")
        if comp_type not in allowed_types:
            if context_name:
                errors.append(f"component type '{comp_type}' is not allowed in {context_name}")
            else:
                errors.append(f"component type '{comp_type}' is not allowed")
        for err in c.get("errors", []):
            errors.append(f"component {c.get('id', '')}: {err.get('message', 'error')}")
    return errors
