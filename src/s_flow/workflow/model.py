from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


JsonObject = dict[str, Any]
Predicate = Callable[["WorkflowInstance"], bool]
Operation = Callable[["WorkflowInstance"], None]


@dataclass(frozen=True)
class RoleDefinition:
    id: str
    kind: str
    minimum: int
    maximum: str


@dataclass(frozen=True)
class FlowDefinition:
    id: str
    source: str
    target: str
    guard: str | None = None


@dataclass
class NodeDefinition:
    id: str
    name: str
    kind: str
    container_id: str
    extensions: dict[str, list[JsonObject]] = field(default_factory=dict)
    outgoing: list[str] = field(default_factory=list)

    def extension(self, name: str) -> JsonObject | None:
        values = self.extensions.get(name, [])
        return values[0] if values else None


@dataclass
class WorkflowDefinition:
    id: str
    name: str
    source_path: Path
    template_id: str
    template_version: str
    roles: dict[str, RoleDefinition]
    outcomes: set[str]
    artifacts: dict[str, JsonObject]
    nodes: dict[str, NodeDefinition]
    flows: dict[str, FlowDefinition]
    starts_by_container: dict[str, str]
    subprocess_containers: set[str]
    process_extensions: dict[str, list[JsonObject]]
    schemas: dict[Path, JsonObject]


@dataclass
class UserTask:
    id: str
    node_id: str
    visit: int
    user_id: str
    kind: str
    status: str
    schema_ref: str | None = None
    required: bool = True
    metadata: JsonObject = field(default_factory=dict)
    response: JsonObject | None = None


@dataclass
class WorkItem:
    id: str
    item_type: str
    author_id: str
    payload: JsonObject
    source_revision_id: str | None
    applicable_revision_id: str | None
    source_node_id: str
    source_visit: int
    state: str = "open"
    decision: str | None = None


@dataclass
class QueueState:
    subprocess_id: str
    item_ids: list[str]
    index: int = 0

    @property
    def current_item_id(self) -> str | None:
        if self.index >= len(self.item_ids):
            return None
        return self.item_ids[self.index]


@dataclass
class ArtifactRevision:
    id: str
    supersedes: str | None
    content: JsonObject
    created_by: str
    sequence: int


@dataclass
class ArtifactState:
    id: str
    lifecycle_state: str = "draft"
    current_revision_id: str | None = None
    revisions: list[ArtifactRevision] = field(default_factory=list)


@dataclass(frozen=True)
class RuntimeEvent:
    sequence: int
    type: str
    node_id: str | None
    message: str
    data: JsonObject = field(default_factory=dict)


@dataclass
class WorkflowInstance:
    id: str
    definition: WorkflowDefinition
    role_assignments: dict[str, list[str]]
    status: str = "created"
    outcome: str | None = None
    current_node_id: str | None = None
    subprocess_stack: list[str] = field(default_factory=list)
    active_queues: dict[str, QueueState] = field(default_factory=dict)
    tasks: dict[str, UserTask] = field(default_factory=dict)
    node_visits: dict[str, int] = field(default_factory=dict)
    node_outputs: dict[str, list[JsonObject]] = field(default_factory=dict)
    work_items: dict[str, WorkItem] = field(default_factory=dict)
    artifacts: dict[str, ArtifactState] = field(default_factory=dict)
    data: JsonObject = field(default_factory=dict)
    events: list[RuntimeEvent] = field(default_factory=list)
    information_cursor: dict[str, int] = field(default_factory=dict)
    last_completed_stage_id: str | None = None
    recent_activity: str | None = None
    blocked_reason: JsonObject | None = None

    def role_users(self, role: str) -> list[str]:
        if role == "objector":
            item = self.current_work_item()
            return [item.author_id] if item else []
        return list(self.role_assignments.get(role, []))

    def current_work_item(self) -> WorkItem | None:
        if not self.subprocess_stack:
            return None
        subprocess_id = self.subprocess_stack[-1]
        queue = self.active_queues.get(subprocess_id)
        if not queue or not queue.current_item_id:
            return None
        return self.work_items[queue.current_item_id]

    def emit(
        self,
        event_type: str,
        message: str,
        node_id: str | None = None,
        **data: Any,
    ) -> None:
        self.events.append(
            RuntimeEvent(
                sequence=len(self.events) + 1,
                type=event_type,
                node_id=node_id,
                message=message,
                data=data,
            )
        )


@dataclass(frozen=True)
class ProcessPosition:
    last_completed_stage: JsonObject | None
    current_stages: list[JsonObject]
    recent_activity: str | None


@dataclass(frozen=True)
class PersonalProjection:
    primary_state: str
    tasks: list[JsonObject]
    waiting_reason: JsonObject | None
    information_items: list[JsonObject]


class WorkflowError(RuntimeError):
    pass


class DefinitionError(WorkflowError):
    pass


class ResponseValidationError(WorkflowError):
    pass


class TaskActionError(WorkflowError):
    pass
