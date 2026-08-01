"""Adapter between the generic workflow interpreter and Sovereign Core nodes."""

from __future__ import annotations

from typing import Any

from .workflow import (
    WorkflowEngine,
    WorkflowError,
    instance_from_dict,
    instance_to_dict,
    load_bundled_workflow,
)
from sovereign import ProtocolNode, Session, SessionResult


RUNTIME_STATE_TYPE = "flow_runtime_state"
RESPONSE_TYPE = "flow_response"


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
                data={
                    "rolePresentationRequired": bool(
                        process.data.get("role_presentation_required", False),
                    ),
                    "eligibilityMode": "closed",
                    "eligibleCandidates": list(
                        process.data.get("eligible_candidates") or [],
                    ),
                },
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
                "status": "applied",
            },
            {},
        )
        if recorded.status != "ok":
            return recorded
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
            }
        instance = instance_from_dict(
            self.definition(process),
            dict(state.data.get("state") or {}),
        )
        engine = WorkflowEngine(instance.definition)
        position = engine.position(instance)
        personal = engine.personal_projection(instance, user_id)
        return {
            "runtime_content_hash": state.content_hash,
            "position": {
                "last_completed_stage": position.last_completed_stage,
                "current_stages": position.current_stages,
                "recent_activity": position.recent_activity,
            },
            "personal": {
                "primary_state": personal.primary_state,
                "tasks": personal.tasks,
                "waiting_reason": personal.waiting_reason,
                "information_items": personal.information_items,
            },
            "status": instance.status,
            "outcome": instance.outcome,
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
