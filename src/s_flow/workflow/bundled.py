"""Access to the reference definitions shipped with the runtime."""

from __future__ import annotations

from functools import lru_cache
from importlib.resources import as_file, files

from .loader import load_workflow
from .model import WorkflowDefinition


TEMPLATE_FILES = {
    "integrativeElection": "integrative-election.bpmn",
    "integrative-election": "integrative-election.bpmn",
    "integrativeDecisionMaking": "integrative-decision-making.bpmn",
    "integrative-decision-making": "integrative-decision-making.bpmn",
    "idmp": "integrative-decision-making.bpmn",
    "minimalConsent": "minimal-consent-decision.bpmn",
    "minimal-consent": "minimal-consent-decision.bpmn",
}

CANONICAL_TEMPLATE_IDS = (
    "integrative-election",
    "integrative-decision-making",
    "minimal-consent",
)


@lru_cache(maxsize=None)
def load_bundled_workflow(template_id: str) -> WorkflowDefinition:
    filename = TEMPLATE_FILES.get(str(template_id or "").strip())
    if not filename:
        raise ValueError(f"Unknown bundled workflow template {template_id!r}.")
    resource = files("s_flow.workflow").joinpath("templates", filename)
    with as_file(resource) as path:
        return load_workflow(path)


def bundled_workflow_templates() -> list[dict[str, str]]:
    templates = []
    for template_id in CANONICAL_TEMPLATE_IDS:
        definition = load_bundled_workflow(template_id)
        profile = (definition.process_extensions.get("profile") or [{}])[0]
        templates.append({
            "id": template_id,
            "version": definition.template_version,
            "name": definition.name,
            "description": str(profile.get("description") or ""),
        })
    return templates
