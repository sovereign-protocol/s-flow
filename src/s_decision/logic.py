"""Core-backed process topics for S-decision."""

from __future__ import annotations

import copy

from sovereign import ApplicationRegistration, ProtocolNode, Session, SessionResult

from .workflow_adapter import (
    RESPONSE_TYPE,
    RUNTIME_STATE_TYPE,
    CoreWorkflowAdapter,
)


decision_APPLICATION_ID = "decision"
decision_APP_NAME = "S-decision"
PROCESS_TYPE = "decision_process"
ASSIGNMENT_TYPE = "decision_assignment"

ROLE_TYPES = frozenset({
    "facilitator",
    "proposer",
    "requiredParticipant",
    "optionalParticipant",
    "observer",
})


class decisionLogic:
    def __init__(self, session: Session, config: dict | None = None,
                 collaboration=None):
        self.session = session
        self.config = config or {}
        self.collaboration = collaboration
        self.workflow = CoreWorkflowAdapter(session)
        self.session.identity
        with self.session.lock:
            self.session.application_metadata(decision_APPLICATION_ID)

    def application_registration(self) -> ApplicationRegistration:
        return ApplicationRegistration(
            decision_APPLICATION_ID,
            frozenset({PROCESS_TYPE}),
            self.processes,
            self.accept_process_invitation,
            assignment_scoped=True,
            mount_invitation=True,
        )

    def processes(self) -> list[ProtocolNode]:
        container = self._find_container()
        if not container:
            return []
        return sorted(
            [
                child for child in container.live_children()
                if child.data.get("type") == PROCESS_TYPE
            ],
            key=lambda node: (
                str(node.data.get("title") or ""),
                node.created_at,
            ),
        )

    def create_process(
        self,
        title: str,
        definition_id: str = "integrative-election",
        definition_version: str = "0.2.0",
    ) -> SessionResult:
        normalized_title = str(title or "").strip()
        normalized_definition = str(definition_id or "").strip()
        normalized_version = str(definition_version or "").strip()
        if not normalized_title:
            return SessionResult("error", reason="process title is required")
        if not normalized_definition:
            return SessionResult("error", reason="definition id is required")
        if not normalized_version:
            return SessionResult("error", reason="definition version is required")

        created = self.session.create_child(
            self._container().uuid,
            {
                "type": PROCESS_TYPE,
                "title": normalized_title,
                "definition_id": normalized_definition,
                "definition_version": normalized_version,
                "lifecycle": "setup",
                "last_completed": "",
                "current_stage": "Configure participants",
                "created_by_identity_uuid": self.session.identity.uuid,
                "role_presentation_required": False,
                "eligible_candidates": [self.session.identity.uuid],
            },
            {},
        )
        if created.status != "ok":
            return created
        process = created.value
        try:
            definition = self.workflow.definition(process)
        except ValueError as exc:
            self.session.delete(process.uuid)
            return SessionResult("error", reason=str(exc))
        effects = list(created.effects)
        for role in definition.roles.values():
            if role.kind == "dynamicItemActor" or role.minimum < 1:
                continue
            assigned = self.session.create_child(
                process.uuid,
                {
                    "type": ASSIGNMENT_TYPE,
                    "identity_uuid": self.session.identity.uuid,
                    "role": role.id,
                    "required": role.minimum > 0,
                    "effective_from_round": 0,
                },
                {},
            )
            if assigned.status != "ok":
                self.session.delete(process.uuid)
                return assigned
            effects.extend(assigned.effects)
        self._remember_process(process.uuid)
        return SessionResult(
            "ok",
            value=process.uuid,
            effects=effects,
        )

    def accept_process_invitation(self, subtree: ProtocolNode) -> SessionResult:
        if subtree.data.get("type") != PROCESS_TYPE:
            return SessionResult(
                "error", reason="invited topic is not a S-decision process",
            )
        result = self.session.accept_topic_invitation(
            subtree, self._container().uuid,
        )
        if result.status == "ok":
            self._remember_process(result.value)
        return result

    def select_process(self, process_uuid: str) -> SessionResult:
        process = self._node(process_uuid, PROCESS_TYPE)
        if not process:
            return SessionResult("error", reason="process not found")
        self._remember_process(process.uuid)
        return SessionResult("ok", value=process.uuid)

    def rename_process(
        self,
        process_uuid: str,
        title: str,
        expected_content_hash: str | None = None,
    ) -> SessionResult:
        process = self._node(process_uuid, PROCESS_TYPE)
        if not process:
            return SessionResult("error", reason="process not found")
        if (
            expected_content_hash is not None
            and expected_content_hash != process.content_hash
        ):
            return SessionResult(
                "error", reason="process changed while you were editing",
            )
        normalized = str(title or "").strip()
        if not normalized:
            return SessionResult("error", reason="process title is required")
        return self.session.modify(
            process.uuid,
            {**process.data, "title": normalized},
            process.weights,
        )

    def delete_process(self, process_uuid: str) -> SessionResult:
        process = self._node(process_uuid, PROCESS_TYPE)
        if not process:
            return SessionResult("error", reason="process not found")
        release = self.session.end_topic_sharing(process.uuid)
        deleted = self.session.delete(process.uuid)
        if deleted.status != "ok":
            return deleted
        deleted.effects = [*release.effects, *deleted.effects]
        remaining = [
            item for item in self.processes() if item.uuid != process.uuid
        ]
        self._remember_process(remaining[0].uuid if remaining else "")
        return deleted

    def assignments(self, process: ProtocolNode) -> list[ProtocolNode]:
        return sorted(
            [
                child for child in process.live_children()
                if child.data.get("type") == ASSIGNMENT_TYPE
            ],
            key=lambda node: (
                str(node.data.get("role") or ""),
                str(node.data.get("identity_uuid") or ""),
            ),
        )

    def set_assignment(
        self,
        process_uuid: str,
        identity_uuid: str,
        role: str,
        required: bool | None = None,
    ) -> SessionResult:
        process = self._node(process_uuid, PROCESS_TYPE)
        if not process:
            return SessionResult("error", reason="process not found")
        if self.workflow.state_node(process):
            return SessionResult(
                "error",
                reason="assign participants before starting the process",
            )
        normalized_identity = str(identity_uuid or "").strip()
        if not normalized_identity:
            return SessionResult("error", reason="identity is required")
        try:
            definition = self.workflow.definition(process)
        except ValueError as exc:
            return SessionResult("error", reason=str(exc))
        if role not in definition.roles or role not in ROLE_TYPES:
            return SessionResult("error", reason="unknown process role")
        required_value = (
            role in {"facilitator", "requiredParticipant"}
            if required is None else bool(required)
        )
        existing = next(
            (
                item for item in self.assignments(process)
                if (
                    item.data.get("identity_uuid") == normalized_identity
                    and item.data.get("role") == role
                )
            ),
            None,
        )
        data = {
            "type": ASSIGNMENT_TYPE,
            "identity_uuid": normalized_identity,
            "role": role,
            "required": required_value,
            "effective_from_round": 0,
        }
        if existing:
            return self.session.modify(existing.uuid, data, existing.weights)
        return self.session.create_child(process.uuid, data, {})

    def start_process(self, process_uuid: str) -> SessionResult:
        process = self._node(process_uuid, PROCESS_TYPE)
        if not process:
            return SessionResult("error", reason="process not found")
        return self.workflow.start(process)

    def configure_election(
        self,
        process_uuid: str,
        eligible_candidates: list[str],
        role_presentation_required: bool = False,
    ) -> SessionResult:
        process = self._node(process_uuid, PROCESS_TYPE)
        if not process:
            return SessionResult("error", reason="process not found")
        if self.workflow.state_node(process):
            return SessionResult(
                "error", reason="configure candidates before starting the process",
            )
        candidates = list(dict.fromkeys(
            str(item or "").strip()
            for item in eligible_candidates
            if str(item or "").strip()
        ))
        if process.data.get("definition_id") == "integrative-election" and not candidates:
            return SessionResult(
                "error", reason="at least one eligible candidate is required",
            )
        return self.session.modify(
            process.uuid,
            {
                **process.data,
                "eligible_candidates": candidates,
                "role_presentation_required": bool(
                    role_presentation_required,
                ),
            },
            process.weights,
        )

    def submit_task(
        self,
        process_uuid: str,
        task_id: str,
        response: dict,
        expected_runtime_content_hash: str | None = None,
    ) -> SessionResult:
        process = self._node(process_uuid, PROCESS_TYPE)
        if not process:
            return SessionResult("error", reason="process not found")
        return self.workflow.submit(
            process,
            self.session.identity.uuid,
            task_id,
            response,
            expected_runtime_content_hash,
        )

    def acknowledge_information(self, process_uuid: str) -> SessionResult:
        process = self._node(process_uuid, PROCESS_TYPE)
        if not process:
            return SessionResult("error", reason="process not found")
        return self.workflow.acknowledge_information(
            process, self.session.identity.uuid,
        )

    def create_agenda_item(
        self, process_uuid: str, text: str, priority: str | None = None,
    ) -> SessionResult:
        if not self._node(process_uuid, PROCESS_TYPE):
            return SessionResult("error", reason="process not found")
        return self.session.create_agenda_item(process_uuid, text, priority)

    def delete_agenda_item(self, item_uuid: str) -> SessionResult:
        if not self.owns_node(item_uuid):
            return SessionResult("error", reason="agenda item not found")
        return self.session.delete_agenda_item(item_uuid)

    def set_agenda_item_priority(
        self, item_uuid: str, priority: str | None,
    ) -> SessionResult:
        if not self.owns_node(item_uuid):
            return SessionResult("error", reason="agenda item not found")
        return self.session.set_agenda_item_priority(item_uuid, priority)

    def move_agenda_item(self, item_uuid: str, index: int) -> SessionResult:
        if not self.owns_node(item_uuid):
            return SessionResult("error", reason="agenda item not found")
        return self.session.move_agenda_item(item_uuid, index)

    def process_payload(
        self, requested_uuid: str | None = None, network: dict | None = None,
    ) -> dict:
        processes = self.processes()
        selected = self._selected_process(requested_uuid, processes)
        identities = self.session.known_identities()
        people_by_uuid = {
            item.get("uuid"): item for item in identities if item.get("uuid")
        }
        assignments = (
            [
                {
                    **item.to_dict(),
                    "person": copy.deepcopy(
                        people_by_uuid.get(item.data.get("identity_uuid"), {}),
                    ),
                }
                for item in self.assignments(selected)
            ]
            if selected else []
        )
        return {
            "process": selected.to_dict() if selected else None,
            "processes": [self.process_summary(item) for item in processes],
            "assignments": assignments,
            "known_identities": identities,
            "agenda_items": [
                item.to_dict() for item in
                (self.session.agenda_items(selected.uuid) if selected else [])
            ],
            "identity_uuid": self.session.identity.uuid,
            "network": network or {},
            "workflow": (
                self.workflow.projection(
                    selected, self.session.identity.uuid,
                )
                if selected else None
            ),
        }

    def process_snapshot(self, requested_uuid: str | None = None) -> dict:
        payload = self.process_payload(requested_uuid, {})
        process = payload.get("process") or {}
        return {"payload": payload, "topic_uuid": process.get("uuid")}

    @staticmethod
    def merge_process_observation(snapshot: dict, network: dict) -> dict:
        payload = snapshot["payload"]
        payload["network"] = network
        return payload

    def process_summary(self, process: ProtocolNode) -> dict:
        own_identity = self.session.identity.uuid
        assignments = self.assignments(process)
        own = next(
            (
                item for item in assignments
                if item.data.get("identity_uuid") == own_identity
            ),
            None,
        )
        role = own.data.get("role") if own else None
        projection = self.workflow.projection(process, own_identity)
        personal = projection["personal"]
        required_from_me = {
            "inputRequired": "Provide input",
            "information": "Review information",
            "waiting": "Wait",
        }.get(personal["primary_state"], "Wait")
        if (
            process.data.get("lifecycle") == "setup"
            and any(
                item.data.get("role") == "facilitator"
                and item.data.get("identity_uuid") == own_identity
                for item in assignments
            )
        ):
            required_from_me = "Configure participants"
        return {
            "uuid": process.uuid,
            "title": process.data.get("title") or "Untitled process",
            "application_id": decision_APPLICATION_ID,
            "definition_id": process.data.get("definition_id") or "",
            "definition_version": process.data.get("definition_version") or "",
            "lifecycle": process.data.get("lifecycle") or "setup",
            "last_completed": process.data.get("last_completed") or "",
            "current_stage": process.data.get("current_stage") or "",
            "required_from_me": required_from_me,
            "assignment_count": len(assignments),
            "agenda_count": len(self.session.agenda_items(process.uuid)),
            "content_hash": process.content_hash,
        }

    def collaboration_context(
        self, process_uuid: str, network: dict | None = None,
    ) -> dict:
        process = self._node(process_uuid, PROCESS_TYPE)
        if not process:
            return {}
        return {
            "agenda_items": [
                item.to_dict()
                for item in self.session.agenda_items(process.uuid)
            ],
            "transition_events": [],
            "transition_by_node": {},
            "identity_uuid": self.session.identity.uuid,
            "known_identities": self.session.known_identities(),
            "workflow": self.workflow.projection(
                process, self.session.identity.uuid,
            ),
            "network": network or {},
        }

    def owns_node(self, node_uuid: str) -> bool:
        node = self.session.protocol.index.get(node_uuid)
        if not node or node.data.get("type") not in {
            PROCESS_TYPE,
            ASSIGNMENT_TYPE,
            RUNTIME_STATE_TYPE,
            RESPONSE_TYPE,
            "agenda_item",
        }:
            return False
        return self._local_process_topic(node_uuid) is not None

    def _selected_process(
        self, requested_uuid: str | None, processes: list[ProtocolNode],
    ) -> ProtocolNode | None:
        selected_uuid = (
            requested_uuid
            or self._metadata().get("selected_process_uuid")
        )
        selected = (
            self._node(selected_uuid, PROCESS_TYPE) if selected_uuid else None
        )
        return selected or (processes[0] if processes else None)

    def _node(self, node_uuid: str | None, node_type: str) -> ProtocolNode | None:
        node = self.session.protocol.index.get(node_uuid) if node_uuid else None
        return (
            node
            if node and not node.deleted and node.data.get("type") == node_type
            else None
        )

    def _local_process_topic(self, node_uuid: str) -> ProtocolNode | None:
        current = self.session.protocol.index.get(node_uuid)
        seen = set()
        while current and current.uuid not in seen:
            seen.add(current.uuid)
            if current.data.get("type") == PROCESS_TYPE:
                parent = self.session.protocol.index.get(current.parent_uuid)
                return current if (
                    parent
                    and parent.data.get("type") == "decision_app"
                    and parent.data.get("name") == decision_APP_NAME
                ) else None
            current = self.session.protocol.index.get(current.parent_uuid)
        return None

    def _metadata(self) -> dict:
        with self.session.lock:
            return copy.deepcopy(
                self.session.application_metadata(decision_APPLICATION_ID),
            )

    def _remember_process(self, process_uuid: str) -> None:
        with self.session.lock:
            metadata = self.session.application_metadata(
                decision_APPLICATION_ID,
            )
            metadata["selected_process_uuid"] = process_uuid

    def _container(self) -> ProtocolNode:
        return self._folder(
            self._apps_folder(), decision_APP_NAME, "decision_app",
        )

    def _find_container(self) -> ProtocolNode | None:
        apps = next(
            (
                child for child in self.session.protocol.root.live_children()
                if child.data.get("type") == "folder"
                and child.data.get("name") == "apps"
            ),
            None,
        )
        if not apps:
            return None
        return next(
            (
                child for child in apps.live_children()
                if child.data.get("type") == "decision_app"
                and child.data.get("name") == decision_APP_NAME
            ),
            None,
        )

    def _apps_folder(self) -> ProtocolNode:
        return self._folder(self.session.protocol.root, "apps")

    def _folder(
        self, parent: ProtocolNode, name: str, node_type: str = "folder",
    ) -> ProtocolNode:
        for child in parent.live_children():
            if (
                child.data.get("name") == name
                and child.data.get("type") in {"folder", node_type}
            ):
                return child
        return self.session.create_child(
            parent.uuid, {"type": node_type, "name": name}, {},
        ).value
