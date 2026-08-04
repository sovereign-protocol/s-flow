"""Adapter between the generic workflow interpreter and Sovereign Core nodes."""

from __future__ import annotations

import copy
from typing import Any

from .workflow import (
    WorkflowEngine,
    WorkflowError,
    instance_from_dict,
    instance_to_dict,
    load_bundled_workflow,
)
from .workflow.schema_validation import schema_document
from sovereign import ProtocolNode, Session, SessionResult


RUNTIME_STATE_TYPE = "flow_runtime_state"
RESPONSE_TYPE = "flow_response"
HANDLED_RESPONSE_IDS = "handledResponseNodeUuids"
RETRACTED_RESPONSE_IDS = "retractedResponseNodeUuids"


class CoreWorkflowAdapter:
    def __init__(self, session: Session):
        self.session = session

    def definition(self, process: ProtocolNode):
        definition = load_bundled_workflow(
            str(process.data.get("definition_id") or ""),
        )
        expected = str(process.data.get("definition_version") or "")
        if definition.template_version != expected:
            raise ValueError(
                "Process definition version is not available in this application."
            )
        return definition

    def state_node(self, process: ProtocolNode) -> ProtocolNode | None:
        return next(
            (
                child for child in process.live_children()
                if child.data.get("type") == RUNTIME_STATE_TYPE
            ),
            None,
        )

    def response_nodes(self, process: ProtocolNode) -> list[ProtocolNode]:
        generation = int(process.data.get("workflow_generation", 0) or 0)
        return sorted(
            (
                child for child in process.live_children()
                if child.data.get("type") == RESPONSE_TYPE
                and int(child.data.get("workflow_generation", 0) or 0)
                == generation
            ),
            key=lambda node: (node.created_at, node.uuid),
        )

    def is_runtime_owner(
        self, process: ProtocolNode, state: ProtocolNode | None = None,
    ) -> bool:
        state = state or self.state_node(process)
        owner = (
            state.data.get("owner_identity_uuid") if state
            else process.data.get("created_by_identity_uuid")
        )
        return bool(owner and owner == self.session.identity.uuid)

    def load(self, process: ProtocolNode):
        state = self.state_node(process)
        if not state:
            return None
        return instance_from_dict(
            self.definition(process),
            dict(state.data.get("state") or {}),
        )

    def start(self, process: ProtocolNode) -> SessionResult:
        if self.state_node(process):
            return SessionResult("error", reason="process is already started")
        try:
            definition = self.definition(process)
            engine = WorkflowEngine(definition)
            instance = engine.create_instance(
                process.uuid,
                self._role_assignments(process, definition),
                data=self._initial_instance_data(process),
            )
            engine.start(instance)
        except (WorkflowError, ValueError) as exc:
            return SessionResult("error", reason=str(exc))

        created = self.session.create_child(
            process.uuid,
            {
                "type": RUNTIME_STATE_TYPE,
                "owner_identity_uuid": process.data.get(
                    "created_by_identity_uuid",
                ),
                "workflow_generation": int(
                    process.data.get("workflow_generation", 0) or 0,
                ),
                "state": instance_to_dict(instance),
            },
            {},
        )
        if created.status != "ok":
            return created
        updated = self._update_process_position(process, engine, instance)
        if updated.status != "ok":
            return updated
        return SessionResult(
            "ok",
            value=created.value.uuid,
            effects=[*created.effects, *updated.effects],
        )

    def submit(
        self,
        process: ProtocolNode,
        user_id: str,
        task_id: str,
        response: dict[str, Any],
        expected_runtime_content_hash: str | None = None,
    ) -> SessionResult:
        state = self.state_node(process)
        if not state:
            return SessionResult("error", reason="process is not started")
        if (
            expected_runtime_content_hash is not None
            and expected_runtime_content_hash != state.content_hash
        ):
            return SessionResult(
                "error", reason="process advanced while you were responding",
            )
        try:
            instance = instance_from_dict(
                self.definition(process),
                dict(state.data.get("state") or {}),
            )
            retracted = set(instance.data.get(RETRACTED_RESPONSE_IDS) or [])
            if any(
                node.uuid not in retracted
                and node.data.get("task_id") == task_id
                and node.data.get("identity_uuid") == user_id
                for node in self.response_nodes(process)
            ):
                return SessionResult(
                    "error", reason="a response is already pending for this task",
                )
            engine = WorkflowEngine(instance.definition)
            engine.submit(instance, user_id, task_id, dict(response or {}))
        except (WorkflowError, ValueError) as exc:
            return SessionResult("error", reason=str(exc))

        recorded = self.session.create_child(
            process.uuid,
            {
                "type": RESPONSE_TYPE,
                "task_id": task_id,
                "identity_uuid": user_id,
                "response": dict(response or {}),
                "runtime_before_hash": state.content_hash,
                "event_sequence": len(instance.events),
                "status": (
                    "applied" if self.is_runtime_owner(process, state)
                    else "submitted"
                ),
                "author_identity_key": self.session.identity.data.get(
                    "identity_key",
                ),
                "workflow_generation": int(
                    process.data.get("workflow_generation", 0) or 0,
                ),
            },
            {},
        )
        if recorded.status != "ok":
            return recorded
        if not self.is_runtime_owner(process, state):
            return SessionResult(
                "ok", value=recorded.value.uuid, effects=list(recorded.effects),
            )

        handled = instance.data.setdefault(HANDLED_RESPONSE_IDS, [])
        handled.append(recorded.value.uuid)
        saved = self.session.modify(
            state.uuid,
            {**state.data, "state": instance_to_dict(instance)},
            state.weights,
        )
        if saved.status != "ok":
            return saved
        updated = self._update_process_position(process, engine, instance)
        if updated.status != "ok":
            return updated
        return SessionResult(
            "ok",
            value=recorded.value.uuid,
            effects=[
                *recorded.effects,
                *saved.effects,
                *updated.effects,
            ],
        )

    def retract_last_response(self, process: ProtocolNode) -> SessionResult:
        """Retract the latest applied response and rebuild authoritative state.

        Response records stay immutable and visible.  Retraction is workflow
        meaning, not Core node rollback: the runtime records the retracted
        response UUID and deterministically replays every earlier response.
        """
        state = self.state_node(process)
        if not state or not self.is_runtime_owner(process, state):
            return SessionResult(
                "error", reason="only the process creator can go back",
            )
        try:
            current = instance_from_dict(
                self.definition(process),
                dict(state.data.get("state") or {}),
            )
            handled = list(current.data.get(HANDLED_RESPONSE_IDS) or [])
            if not handled:
                return SessionResult("error", reason="there is no response to retract")
            response_by_uuid = {
                node.uuid: node for node in self.response_nodes(process)
            }
            retracted_uuid = handled.pop()
            retracted_node = response_by_uuid.get(retracted_uuid)
            if not retracted_node:
                return SessionResult(
                    "error", reason="the latest response record is unavailable",
                )

            engine = WorkflowEngine(current.definition)
            rebuilt = engine.create_instance(
                process.uuid,
                current.role_assignments,
                data=self._initial_instance_data(process),
            )
            engine.start(rebuilt)
            for response_uuid in handled:
                node = response_by_uuid.get(response_uuid)
                if not node:
                    raise ValueError(
                        f"Cannot replay missing response {response_uuid}.",
                    )
                engine.submit(
                    rebuilt,
                    str(node.data.get("identity_uuid") or ""),
                    str(node.data.get("task_id") or ""),
                    dict(node.data.get("response") or {}),
                )
            rebuilt.data[HANDLED_RESPONSE_IDS] = handled
            retracted = list(current.data.get(RETRACTED_RESPONSE_IDS) or [])
            if retracted_uuid not in retracted:
                retracted.append(retracted_uuid)
            rebuilt.data[RETRACTED_RESPONSE_IDS] = retracted
            rebuilt.emit(
                "information",
                "The latest response was retracted; the process returned to the previous input.",
                retracted_node.data.get("task_id"),
                responseNodeUuid=retracted_uuid,
                retractedBy=self.session.identity.uuid,
            )
        except (WorkflowError, ValueError) as exc:
            return SessionResult("error", reason=str(exc))

        saved = self.session.modify(
            state.uuid,
            {**state.data, "state": instance_to_dict(rebuilt)},
            state.weights,
        )
        if saved.status != "ok":
            return saved
        current_process = self.session.protocol.index.get(process.uuid) or process
        updated = self._update_process_position(
            current_process, engine, rebuilt,
        )
        if updated.status != "ok":
            return updated
        return SessionResult(
            "ok",
            value=retracted_uuid,
            effects=[*saved.effects, *updated.effects],
        )

    def ingest_peer_response(
        self,
        process: ProtocolNode,
        source_addr: str,
        response_node: ProtocolNode,
    ) -> SessionResult:
        """Adopt and apply one immutable response authored by its peer.

        The runtime is creator-owned.  A participant therefore publishes only
        a response node; the creator validates its Core identity and applies it
        as a workflow command.  The whole-runtime hash is deliberately not an
        applicability condition here: parallel round responses commonly share
        the same pre-response runtime revision.
        """
        state = self.state_node(process)
        if not state or not self.is_runtime_owner(process, state):
            return SessionResult("error", reason="only the runtime owner ingests responses")
        if response_node.data.get("type") != RESPONSE_TYPE:
            return SessionResult("error", reason="node is not a workflow response")
        if int(response_node.data.get("workflow_generation", 0) or 0) != int(
            process.data.get("workflow_generation", 0) or 0
        ):
            return SessionResult(
                "error", reason="response belongs to an earlier workflow run",
            )

        peer_identity = self.session.peer_identity(source_addr)
        peer_identity_key = self.session.peer_identity_key_for_address(source_addr)
        claimed_identity = str(response_node.data.get("identity_uuid") or "")
        claimed_key = str(response_node.data.get("author_identity_key") or "")
        if (
            not peer_identity
            or peer_identity.uuid != claimed_identity
            or not peer_identity_key
            or claimed_key != peer_identity_key
            or response_node.revision_origin != peer_identity_key
        ):
            return SessionResult("error", reason="response authorship does not match its peer")

        effects = []
        local_response = self.session.protocol.index.get(response_node.uuid)
        if local_response is None:
            adopted = self.session.accept_peer_node(
                source_addr, response_node.uuid,
            )
            if adopted.status != "ok":
                return adopted
            effects.extend(adopted.effects)

        try:
            instance = instance_from_dict(
                self.definition(process),
                dict(state.data.get("state") or {}),
            )
            handled = instance.data.setdefault(HANDLED_RESPONSE_IDS, [])
            if response_node.uuid in handled:
                return SessionResult("ok", value=False, effects=effects)
            engine = WorkflowEngine(instance.definition)
            engine.submit(
                instance,
                claimed_identity,
                str(response_node.data.get("task_id") or ""),
                dict(response_node.data.get("response") or {}),
            )
            handled.append(response_node.uuid)
        except (WorkflowError, ValueError) as exc:
            return SessionResult("error", reason=str(exc), effects=effects)

        saved = self.session.modify(
            state.uuid,
            {**state.data, "state": instance_to_dict(instance)},
            state.weights,
        )
        if saved.status != "ok":
            return saved
        current_process = self.session.protocol.index.get(process.uuid) or process
        updated = self._update_process_position(
            current_process, engine, instance,
        )
        if updated.status != "ok":
            return updated
        return SessionResult(
            "ok",
            value=True,
            effects=[*effects, *saved.effects, *updated.effects],
        )

    def acknowledge_information(
        self, process: ProtocolNode, user_id: str,
    ) -> SessionResult:
        state = self.state_node(process)
        if not state:
            return SessionResult("error", reason="process is not started")
        try:
            instance = instance_from_dict(
                self.definition(process),
                dict(state.data.get("state") or {}),
            )
            engine = WorkflowEngine(instance.definition)
            engine.acknowledge_information(instance, user_id)
        except ValueError as exc:
            return SessionResult("error", reason=str(exc))
        return self.session.modify(
            state.uuid,
            {**state.data, "state": instance_to_dict(instance)},
            state.weights,
        )

    def projection(self, process: ProtocolNode, user_id: str) -> dict:
        state = self.state_node(process)
        if not state:
            return {
                "runtime_content_hash": None,
                "position": {
                    "last_completed_stage": None,
                    "current_stages": [{
                        "id": "setup",
                        "name": "Configure participants",
                    }],
                    "recent_activity": None,
                },
                "personal": {
                    "primary_state": (
                        "inputRequired"
                        if self._is_facilitator(process, user_id)
                        else "waiting"
                    ),
                    "tasks": [],
                    "waiting_reason": (
                        None if self._is_facilitator(process, user_id)
                        else {
                            "type": "facilitatorStart",
                            "dependencies": self._facilitators(process),
                        }
                    ),
                    "information_items": [],
                },
                "definition": self._definition_projection(process),
                "artifacts": {},
                "history": [],
                "can_return_to_setup": False,
            }
        instance = instance_from_dict(
            self.definition(process),
            dict(state.data.get("state") or {}),
        )
        engine = WorkflowEngine(instance.definition)
        position = engine.position(instance)
        personal = engine.personal_projection(instance, user_id)
        handled = set(instance.data.get(HANDLED_RESPONSE_IDS) or [])
        retracted = set(instance.data.get(RETRACTED_RESPONSE_IDS) or [])
        pending_task_ids = {
            str(node.data.get("task_id") or "")
            for node in self.response_nodes(process)
            if node.data.get("identity_uuid") == user_id
            and node.uuid not in handled
            and node.uuid not in retracted
        }
        tasks = [
            self._task_projection(instance, task)
            for task in personal.tasks
            if task["id"] not in pending_task_ids
        ]
        waiting_reason = personal.waiting_reason
        if pending_task_ids and not tasks:
            waiting_reason = {
                "type": "responsePending",
                "dependencies": [],
            }
        return {
            "runtime_content_hash": state.content_hash,
            "position": {
                "last_completed_stage": position.last_completed_stage,
                "current_stages": position.current_stages,
                "recent_activity": position.recent_activity,
            },
            "personal": {
                "primary_state": (
                    personal.primary_state if tasks
                    else "waiting" if pending_task_ids
                    else personal.primary_state
                ),
                "tasks": tasks,
                "waiting_reason": waiting_reason,
                "information_items": personal.information_items,
            },
            "status": instance.status,
            "outcome": instance.outcome,
            "can_go_back": (
                self.is_runtime_owner(process, state)
                and bool(instance.data.get(HANDLED_RESPONSE_IDS))
            ),
            "can_return_to_setup": (
                self.is_runtime_owner(process, state)
                and instance.status == "active"
            ),
            "definition": self._definition_projection(process),
            "artifacts": {
                artifact_id: {
                    "id": artifact.id,
                    "lifecycle_state": artifact.lifecycle_state,
                    "current_revision_id": artifact.current_revision_id,
                    "revisions": [
                        {
                            "id": revision.id,
                            "supersedes": revision.supersedes,
                            "content": dict(revision.content),
                            "created_by": revision.created_by,
                            "sequence": revision.sequence,
                        }
                        for revision in artifact.revisions
                    ],
                }
                for artifact_id, artifact in instance.artifacts.items()
            },
            "history": [
                {
                    "sequence": event.sequence,
                    "type": event.type,
                    "node_id": event.node_id,
                    "message": event.message,
                    "data": dict(event.data),
                }
                for event in instance.events
            ],
            "current_status": self._current_status_projection(instance),
        }

    def _task_projection(self, instance, task: dict[str, Any]) -> dict[str, Any]:
        projected = dict(task)
        task_state = instance.tasks.get(task["id"])
        metadata = dict(task.get("metadata") or {})
        projected["response_defaults"] = dict(
            metadata.get("responseDefaults") or {},
        )
        if metadata.get("context"):
            projected["context"] = dict(metadata["context"])
        if task_state and task_state.schema_ref:
            document, schema = schema_document(
                instance.definition, task_state.schema_ref,
            )
            projected["response_schema"] = self._expanded_schema(
                document, schema,
            )
        return projected

    @staticmethod
    def _current_status_projection(instance) -> dict[str, Any]:
        nominations = dict(instance.data.get("currentNominations") or {})
        reasons = dict(instance.data.get("currentNominationReasons") or {})
        return {
            "nominations": [
                {
                    "user_id": user_id,
                    "candidate_id": candidate_id,
                    "reason": reasons.get(user_id, ""),
                }
                for user_id, candidate_id in nominations.items()
            ],
            "proposed_candidate_id": instance.data.get("proposedCandidate"),
            "elected_candidate_id": instance.data.get("electedCandidate"),
            "excluded_candidate_ids": list(
                instance.data.get("excludedCandidates") or [],
            ),
            "rounds": [
                dict(round_record)
                for round_record in instance.data.get("publishedRounds") or []
            ],
            "objections": [
                {
                    "id": item.id,
                    "author_id": item.author_id,
                    "statement": item.payload.get("statement", ""),
                    "state": item.state,
                    "decision": item.decision,
                }
                for item in instance.work_items.values()
                if item.item_type in {"objection", "potentialObjection"}
            ],
        }

    @classmethod
    def _expanded_schema(cls, document: dict, value: Any) -> Any:
        if isinstance(value, list):
            return [cls._expanded_schema(document, item) for item in value]
        if not isinstance(value, dict):
            return copy.deepcopy(value)
        reference = value.get("$ref")
        if isinstance(reference, str) and reference.startswith("#/"):
            target: Any = document
            for raw_part in reference[2:].split("/"):
                part = raw_part.replace("~1", "/").replace("~0", "~")
                target = target[part]
            siblings = {
                key: item for key, item in value.items() if key != "$ref"
            }
            expanded = cls._expanded_schema(document, target)
            return {**expanded, **cls._expanded_schema(document, siblings)}
        return {
            key: cls._expanded_schema(document, item)
            for key, item in value.items()
        }

    @staticmethod
    def _initial_instance_data(process: ProtocolNode) -> dict[str, Any]:
        return {
            "rolePresentationRequired": bool(
                process.data.get("role_presentation_required", False),
            ),
            "eligibilityMode": "closed",
            "eligibleCandidates": list(
                process.data.get("eligible_candidates") or [],
            ),
        }

    def _definition_projection(self, process: ProtocolNode) -> dict[str, Any]:
        definition = self.definition(process)
        return {
            "id": definition.template_id,
            "version": definition.template_version,
            "name": definition.name,
            "description": (
                (definition.process_extensions.get("profile") or [{}])[0]
                .get("description", "")
            ),
            "rounds": [
                {
                    "node_id": node.id,
                    "name": node.name,
                    "ordering": round_spec.get("ordering", "parallel"),
                    "publication": round_spec.get("publication", "immediate"),
                }
                for node in definition.nodes.values()
                if (round_spec := node.extension("humanRound"))
            ],
        }

    @staticmethod
    def _assignments(process: ProtocolNode) -> list[ProtocolNode]:
        return [
            child for child in process.live_children()
            if child.data.get("type") == "flow_assignment"
        ]

    def _role_assignments(self, process: ProtocolNode, definition) -> dict:
        assignments: dict[str, list[str]] = {}
        for item in self._assignments(process):
            role = str(item.data.get("role") or "")
            identity = str(item.data.get("identity_uuid") or "")
            if role not in definition.roles or not identity:
                continue
            assignments.setdefault(role, [])
            if identity not in assignments[role]:
                assignments[role].append(identity)
        return assignments

    def _facilitators(self, process: ProtocolNode) -> list[str]:
        return [
            str(item.data.get("identity_uuid"))
            for item in self._assignments(process)
            if item.data.get("role") == "facilitator"
            and item.data.get("identity_uuid")
        ]

    def _is_facilitator(self, process: ProtocolNode, user_id: str) -> bool:
        return user_id in self._facilitators(process)

    def _update_process_position(
        self, process: ProtocolNode, engine: WorkflowEngine, instance,
    ) -> SessionResult:
        position = engine.position(instance)
        current = (
            position.current_stages[0]["name"]
            if position.current_stages else ""
        )
        last = (
            position.last_completed_stage["name"]
            if position.last_completed_stage else ""
        )
        return self.session.modify(
            process.uuid,
            {
                **process.data,
                "lifecycle": instance.status,
                "outcome": instance.outcome,
                "last_completed": last,
                "current_stage": current,
            },
            process.weights,
        )
