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


@lru_cache(maxsize=None)
def load_bundled_workflow(template_id: str) -> WorkflowDefinition:
    filename = TEMPLATE_FILES.get(str(template_id or "").strip())
    if not filename:
        raise ValueError(f"Unknown bundled workflow template {template_id!r}.")
    resource = files("s_decision.workflow").joinpath("templates", filename)
    with as_file(resource) as path:
        return load_workflow(path)
