"""JSON-safe serialization for workflow instance runtime state."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .model import (
    ArtifactRevision,
    ArtifactState,
    QueueState,
    RuntimeEvent,
    UserTask,
    WorkItem,
    WorkflowDefinition,
    WorkflowInstance,
)


SERIALIZATION_VERSION = 1


def instance_to_dict(instance: WorkflowInstance) -> dict[str, Any]:
    return {
        "serializationVersion": SERIALIZATION_VERSION,
        "instanceId": instance.id,
        "definitionId": instance.definition.template_id,
        "definitionVersion": instance.definition.template_version,
        "roleAssignments": {
            role: list(users)
            for role, users in instance.role_assignments.items()
        },
        "status": instance.status,
        "outcome": instance.outcome,
        "currentNodeId": instance.current_node_id,
        "subprocessStack": list(instance.subprocess_stack),
        "activeQueues": {
            key: asdict(value)
            for key, value in instance.active_queues.items()
        },
        "tasks": {
            key: asdict(value) for key, value in instance.tasks.items()
        },
        "nodeVisits": dict(instance.node_visits),
        "nodeOutputs": {
            key: [dict(item) for item in values]
            for key, values in instance.node_outputs.items()
        },
        "workItems": {
            key: asdict(value) for key, value in instance.work_items.items()
        },
        "artifacts": {
            key: asdict(value) for key, value in instance.artifacts.items()
        },
        "data": dict(instance.data),
        "events": [asdict(value) for value in instance.events],
        "informationCursor": dict(instance.information_cursor),
        "lastCompletedStageId": instance.last_completed_stage_id,
        "recentActivity": instance.recent_activity,
        "blockedReason": (
            dict(instance.blocked_reason)
            if instance.blocked_reason is not None else None
        ),
    }


def instance_from_dict(
    definition: WorkflowDefinition,
    payload: dict[str, Any],
) -> WorkflowInstance:
    if payload.get("serializationVersion") != SERIALIZATION_VERSION:
        raise ValueError("Unsupported workflow state serialization version.")
    if payload.get("definitionId") != definition.template_id:
        raise ValueError("Workflow state references another definition.")
    if payload.get("definitionVersion") != definition.template_version:
        raise ValueError("Workflow state references another definition version.")

    artifacts = {
        key: ArtifactState(
            id=value["id"],
            lifecycle_state=value.get("lifecycle_state", "draft"),
            current_revision_id=value.get("current_revision_id"),
            revisions=[
                ArtifactRevision(**revision)
                for revision in value.get("revisions", [])
            ],
        )
        for key, value in payload.get("artifacts", {}).items()
    }
    return WorkflowInstance(
        id=str(payload["instanceId"]),
        definition=definition,
        role_assignments={
            role: list(users)
            for role, users in payload.get("roleAssignments", {}).items()
        },
        status=str(payload.get("status", "created")),
        outcome=payload.get("outcome"),
        current_node_id=payload.get("currentNodeId"),
        subprocess_stack=list(payload.get("subprocessStack", [])),
        active_queues={
            key: QueueState(**value)
            for key, value in payload.get("activeQueues", {}).items()
        },
        tasks={
            key: UserTask(**value)
            for key, value in payload.get("tasks", {}).items()
        },
        node_visits={
            key: int(value)
            for key, value in payload.get("nodeVisits", {}).items()
        },
        node_outputs={
            key: [dict(item) for item in values]
            for key, values in payload.get("nodeOutputs", {}).items()
        },
        work_items={
            key: WorkItem(**value)
            for key, value in payload.get("workItems", {}).items()
        },
        artifacts=artifacts,
        data=dict(payload.get("data", {})),
        events=[
            RuntimeEvent(**value) for value in payload.get("events", [])
        ],
        information_cursor={
            key: int(value)
            for key, value in payload.get("informationCursor", {}).items()
        },
        last_completed_stage_id=payload.get("lastCompletedStageId"),
        recent_activity=payload.get("recentActivity"),
        blocked_reason=(
            dict(payload["blockedReason"])
            if payload.get("blockedReason") is not None else None
        ),
    )
