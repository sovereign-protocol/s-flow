"""Core-backed process topics for S-Flow."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone

from sovereign import ApplicationRegistration, ProtocolNode, Session, SessionResult

from .workflow import bundled_workflow_templates

from .workflow_adapter import (
    RESPONSE_TYPE,
    RUNTIME_STATE_TYPE,
    CoreWorkflowAdapter,
)


FLOW_APPLICATION_ID = "flow"
FLOW_APP_NAME = "S-Flow"
PROCESS_TYPE = "flow_process"
SNAPSHOT_FORMAT = "s-protocol.item-snapshot"
SNAPSHOT_FORMAT_VERSION = 1
ASSIGNMENT_TYPE = "flow_assignment"

ROLE_TYPES = frozenset({
    "facilitator",
    "proposer",
    "requiredParticipant",
    "optionalParticipant",
    "observer",
})
DISPLAYED_TRANSITION_TYPES = frozenset({PROCESS_TYPE, ASSIGNMENT_TYPE})
DECISION_RESULT_CONTRACT_ID = "s-flow.decision-result"
DECISION_RESULT_CONTRACT_VERSION = 1


def canonical_decision_result_hash(result: dict) -> str:
    """Hash every v1 result field except the hash itself."""
    unsigned = {
        key: copy.deepcopy(value)
        for key, value in result.items()
        if key != "result_hash"
    }
    encoded = json.dumps(
        unsigned,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


class FlowLogic:
    def __init__(self, session: Session, config: dict | None = None,
                 collaboration=None):
        self.session = session
        self.config = config or {}
        self.collaboration = collaboration
        self.workflow = CoreWorkflowAdapter(session)
        self.session.identity
        with self.session.lock:
            self.session.application_metadata(FLOW_APPLICATION_ID)

    def application_registration(self) -> ApplicationRegistration:
        return ApplicationRegistration(
            FLOW_APPLICATION_ID,
            frozenset({PROCESS_TYPE}),
            self.processes,
            self.accept_process_invitation,
            assignment_scoped=True,
            mount_invitation=True,
            on_peer_update=self.on_peer_update,
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

    @staticmethod
    def templates() -> list[dict[str, str]]:
        return bundled_workflow_templates()

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
                "workflow_generation": 0,
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

    def export_snapshot(
        self, process_uuid: str, name: str = "", description: str = "",
    ) -> SessionResult:
        process = self._node(process_uuid, PROCESS_TYPE)
        if not process:
            return SessionResult("error", reason="process not found")
        source_name = str(process.data.get("title") or "Untitled flow")
        return SessionResult("ok", value={
            "format": SNAPSHOT_FORMAT,
            "format_version": SNAPSHOT_FORMAT_VERSION,
            "item_type": "flow",
            "name": str(name or "").strip() or f"{source_name} snapshot",
            "description": str(description or "").strip(),
            "saved_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "source_name": source_name,
            "content": {
                "definition_id": str(process.data.get("definition_id") or ""),
                "definition_version": str(process.data.get("definition_version") or ""),
                "role_presentation_required": bool(
                    process.data.get("role_presentation_required", False)
                ),
            },
        })

    def create_from_snapshot(
        self, document: dict, title: str = "",
    ) -> SessionResult:
        error = self._snapshot_error(document, "flow")
        if error:
            return SessionResult("error", reason=error)
        content = document["content"]
        requested = str(title or "").strip() or str(
            document.get("source_name") or document.get("name") or "Untitled flow"
        )
        created = self.create_process(
            requested,
            str(content.get("definition_id") or ""),
            str(content.get("definition_version") or ""),
        )
        if created.status != "ok":
            return created
        process = self._node(created.value, PROCESS_TYPE)
        if process and content.get("role_presentation_required"):
            updated = self.session.modify(
                process.uuid,
                {**process.data, "role_presentation_required": True},
                process.weights,
            )
            if updated.status != "ok":
                return updated
            created.effects = [*created.effects, *updated.effects]
        return created

    @staticmethod
    def _snapshot_error(document: object, item_type: str) -> str:
        if not isinstance(document, dict):
            return "snapshot file is invalid"
        if document.get("format") != SNAPSHOT_FORMAT:
            return "not an S-Protocol item snapshot"
        if document.get("format_version") != SNAPSHOT_FORMAT_VERSION:
            return "snapshot version is not supported"
        if document.get("item_type") != item_type:
            return f"snapshot does not contain a {item_type}"
        if not isinstance(document.get("content"), dict):
            return "snapshot content is invalid"
        return ""

    def create_integrative_election(
        self,
        title: str,
        participant_uuids: list[str],
        facilitator_uuid: str,
        eligible_candidate_uuids: list[str] | None = None,
        definition_version: str = "0.2.0",
    ) -> SessionResult:
        """Create, configure, and start an election through one facade call."""
        participants = list(dict.fromkeys(
            str(actor or "").strip()
            for actor in participant_uuids
            if str(actor or "").strip()
        ))
        facilitator = str(facilitator_uuid or "").strip()
        candidates = list(dict.fromkeys(
            str(actor or "").strip()
            for actor in (
                eligible_candidate_uuids
                if eligible_candidate_uuids is not None
                else participants
            )
            if str(actor or "").strip()
        ))
        if not participants:
            return SessionResult(
                "error", reason="an election requires participants",
            )
        if not facilitator:
            return SessionResult(
                "error", reason="an election requires a facilitator",
            )
        if not candidates:
            return SessionResult(
                "error", reason="an election requires eligible candidates",
            )
        created = self.create_process(
            title, "integrative-election", definition_version,
        )
        if created.status != "ok":
            return created
        process_uuid = created.value
        process = self._node(process_uuid, PROCESS_TYPE)
        effects = list(created.effects)

        def fail(result: SessionResult) -> SessionResult:
            self._remove_local_process(process)
            return result

        for assignment in list(self.assignments(process)):
            removed = self.session.delete(assignment.uuid)
            if removed.status != "ok":
                return fail(removed)
            effects.extend(removed.effects)
        assigned = self.set_assignment(
            process_uuid, facilitator, "facilitator", True,
        )
        if assigned.status != "ok":
            return fail(assigned)
        effects.extend(assigned.effects)
        for actor_uuid in participants:
            assigned = self.set_assignment(
                process_uuid, actor_uuid, "requiredParticipant", True,
            )
            if assigned.status != "ok":
                return fail(assigned)
            effects.extend(assigned.effects)
        configured = self.configure_election(
            process_uuid, candidates, False,
        )
        if configured.status != "ok":
            return fail(configured)
        effects.extend(configured.effects)
        started = self.start_process(process_uuid)
        if started.status != "ok":
            return fail(started)
        effects.extend(started.effects)
        return SessionResult(
            "ok", value=process_uuid, effects=effects,
        )

    def accept_process_invitation(self, subtree: ProtocolNode) -> SessionResult:
        if subtree.data.get("type") != PROCESS_TYPE:
            return SessionResult(
                "error", reason="invited topic is not a S-Flow process",
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
        if not self._is_process_owner(process):
            return SessionResult(
                "error", reason="only the process creator can delete it",
            )
        return self._remove_local_process(process)

    def leave_process(self, process_uuid: str) -> SessionResult:
        """Stop holding a flow somebody else runs. They keep it.

        Leaving is not deleting, and this used to take the creator's path: end
        sharing, then write a deletion. That was correct only by arithmetic -
        the tombstone did not travel because the peer set had just been
        emptied, and it was pruned locally for the same reason. Nothing about
        the intent said so, and the release of the channels is an effect the
        runtime delivers afterwards, so a poll landing in between had a
        tombstone to publish.

        A drop states it instead: no deletion is written at all, the others
        see this client stop publishing - which is what they also see when
        somebody closes their laptop - and a peer who still runs it offers it
        back as an invitation.
        """
        process = self._node(process_uuid, PROCESS_TYPE)
        if not process:
            return SessionResult("error", reason="process not found")
        if self._is_process_owner(process):
            return SessionResult(
                "error", reason="the process creator must delete it instead",
            )
        dropped = self.session.drop_topic(process.uuid)
        if dropped.status != "ok":
            return dropped
        remaining = [
            item for item in self.processes() if item.uuid != process.uuid
        ]
        self._remember_process(remaining[0].uuid if remaining else "")
        return dropped

    def _remove_local_process(self, process: ProtocolNode) -> SessionResult:
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

    def return_to_setup(self, process_uuid: str) -> SessionResult:
        process = self._node(process_uuid, PROCESS_TYPE)
        if not process:
            return SessionResult("error", reason="process not found")
        if not self._is_process_owner(process):
            return SessionResult(
                "error", reason="only the process creator can return to setup",
            )
        state = self.workflow.state_node(process)
        if not state:
            return SessionResult("error", reason="process is already in setup")

        removed = self.session.delete(state.uuid)
        if removed.status != "ok":
            return removed
        generation = int(process.data.get("workflow_generation", 0) or 0) + 1
        updated = self.session.modify(
            process.uuid,
            {
                **process.data,
                "lifecycle": "setup",
                "last_completed": "",
                "current_stage": "Configure participants",
                "workflow_generation": generation,
            },
            process.weights,
        )
        if updated.status != "ok":
            return updated
        return SessionResult(
            "ok",
            value=process.uuid,
            effects=[*removed.effects, *updated.effects],
        )

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
        if not self._is_process_owner(process):
            return SessionResult(
                "error", reason="only the process creator can assign participants",
            )
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

    def delete_assignment(
        self, process_uuid: str, assignment_uuid: str,
    ) -> SessionResult:
        process = self._node(process_uuid, PROCESS_TYPE)
        assignment = self._node(assignment_uuid, ASSIGNMENT_TYPE)
        if not process or not assignment or assignment.parent_uuid != process.uuid:
            return SessionResult("error", reason="assignment not found")
        if not self._is_process_owner(process):
            return SessionResult(
                "error", reason="only the process creator can assign participants",
            )
        if self.workflow.state_node(process):
            return SessionResult(
                "error", reason="assign participants before starting the process",
            )
        return self.session.delete(assignment.uuid)

    def start_process(self, process_uuid: str) -> SessionResult:
        process = self._node(process_uuid, PROCESS_TYPE)
        if not process:
            return SessionResult("error", reason="process not found")
        if not self._is_process_owner(process):
            return SessionResult(
                "error", reason="only the process creator can start it",
            )
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
        if not self._is_process_owner(process):
            return SessionResult(
                "error", reason="only the process creator can configure it",
            )
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

    def go_back(self, process_uuid: str) -> SessionResult:
        process = self._node(process_uuid, PROCESS_TYPE)
        if not process:
            return SessionResult("error", reason="process not found")
        return self.workflow.retract_last_response(process)

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

    def _agenda_items(self, topic_uuid: str):
        return self.session.agenda_projection(topic_uuid)

    def delete_agenda_item(self, item_uuid: str) -> SessionResult:
        if not self.owns_node(item_uuid):
            return SessionResult("error", reason="agenda item not found")
        return self.session.delete_agenda_item(item_uuid)

    def update_agenda_item(self, item_uuid: str, text: str) -> SessionResult:
        if not self.owns_node(item_uuid):
            return SessionResult("error", reason="agenda item not found")
        return self.session.update_agenda_item_text(item_uuid, text)

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
        events = self.transition_events(selected) if selected else []
        return {
            "process": selected.to_dict() if selected else None,
            "processes": [self.process_summary(item) for item in processes],
            "assignments": assignments,
            "known_identities": identities,
            "agenda_items": [
                item.to_dict() for item in
                (self._agenda_items(selected.uuid) if selected else [])
            ],
            "identity_uuid": self.session.identity.uuid,
            "network": network or {},
            "peers": {
                addr: tree.to_dict()
                for addr, tree in sorted(
                    self.session.peer_perspectives_for_topic(
                        selected.uuid if selected else None,
                    ).items(),
                )
            },
            "transition_events": events,
            "transition_by_node": self.transition_by_node(events),
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
            "application_id": FLOW_APPLICATION_ID,
            "definition_id": process.data.get("definition_id") or "",
            "definition_version": process.data.get("definition_version") or "",
            "lifecycle": process.data.get("lifecycle") or "setup",
            "last_completed": process.data.get("last_completed") or "",
            "current_stage": process.data.get("current_stage") or "",
            "required_from_me": required_from_me,
            "assignment_count": len(assignments),
            "agenda_count": len(self._agenda_items(process.uuid)),
            "content_hash": process.content_hash,
            "can_delete": self._is_process_owner(process),
            "can_leave": not self._is_process_owner(process),
        }

    def decision_result(self, process_uuid: str) -> dict | None:
        """Return the stable, detached result contract for one process.

        The contract is available before completion so a consumer can
        distinguish an incomplete process from a missing or malformed one.
        Application internals, runtime nodes and event history stay private.
        """
        process = self._node(process_uuid, PROCESS_TYPE)
        if process is None:
            return None
        projection = self.workflow.projection(
            process, self.session.identity.uuid,
        )
        assignments = sorted(
            (
                {
                    "identity_uuid": str(
                        assignment.data.get("identity_uuid") or ""
                    ),
                    "role": str(assignment.data.get("role") or ""),
                    "required": bool(assignment.data.get("required")),
                }
                for assignment in self.assignments(process)
                if assignment.data.get("role") != "facilitator"
            ),
            key=lambda item: (
                item["identity_uuid"], item["role"], not item["required"],
            ),
        )
        facilitators = sorted({
            str(assignment.data.get("identity_uuid") or "")
            for assignment in self.assignments(process)
            if assignment.data.get("role") == "facilitator"
            and assignment.data.get("identity_uuid")
        })
        current = projection.get("current_status") or {}
        position = projection.get("position") or {}
        current_stages = position.get("current_stages") or []
        current_stage = ", ".join(
            str(stage.get("name") or stage.get("id") or "")
            for stage in current_stages
            if isinstance(stage, dict)
            and (stage.get("name") or stage.get("id"))
        )
        last_completed = position.get("last_completed_stage") or {}
        result = {
            "contract_id": DECISION_RESULT_CONTRACT_ID,
            "contract_version": DECISION_RESULT_CONTRACT_VERSION,
            "process_uuid": process.uuid,
            "definition_id": str(process.data.get("definition_id") or ""),
            "definition_version": str(
                process.data.get("definition_version") or ""
            ),
            "lifecycle": str(
                projection.get("status")
                or process.data.get("lifecycle")
                or ""
            ),
            "current_stage": current_stage,
            "last_completed_stage": str(
                last_completed.get("name")
                or last_completed.get("id")
                or ""
            ),
            "terminal_outcome": projection.get("outcome"),
            "selected_candidate_uuid": (
                current.get("elected_candidate_id")
            ),
            "participant_snapshot": assignments,
            "facilitator_uuid": (
                facilitators[0] if len(facilitators) == 1 else None
            ),
        }
        return {
            **result,
            "result_hash": canonical_decision_result_hash(result),
        }

    def collaboration_context(
        self, process_uuid: str, network: dict | None = None,
    ) -> dict:
        process = self._node(process_uuid, PROCESS_TYPE)
        if not process:
            return {}
        events = self.transition_events(process)
        return {
            "agenda_items": [
                item.to_dict()
                for item in self._agenda_items(process.uuid)
            ],
            "transition_events": events,
            "transition_by_node": self.transition_by_node(events),
            "identity_uuid": self.session.identity.uuid,
            "known_identities": self.session.known_identities(),
            "workflow": self.workflow.projection(
                process, self.session.identity.uuid,
            ),
            "network": network or {},
        }

    def on_peer_update(self) -> SessionResult:
        changed = False
        effects = []
        for process in self.processes():
            if self.workflow.is_runtime_owner(process):
                for addr in self.session.peer_addresses(process.uuid):
                    if not self.session.peer_discusses_node(addr, process.uuid):
                        continue
                    for event in self.session.analyze_peer_transitions(
                        addr, process.uuid,
                    ):
                        if event.get("type") != "local_missing_node":
                            continue
                        peer_node = self.session.get_cached_peer_subtree(
                            addr, str(event.get("node_uuid") or ""),
                        )
                        if not peer_node or peer_node.data.get("type") != RESPONSE_TYPE:
                            continue
                        result = self.workflow.ingest_peer_response(
                            process, addr, peer_node,
                        )
                        if result.status != "ok":
                            self.session.trace_event(
                                "flow.response_ingest_failed",
                                process_uuid=process.uuid,
                                peer_addr=addr,
                                response_node_uuid=peer_node.uuid,
                                reason=str(result.reason or ""),
                            )
                            continue
                        changed = bool(result.value) or changed
                        effects.extend(result.effects)
                continue

            owner_id = str(process.data.get("created_by_identity_uuid") or "")
            owner_addr = next(
                (
                    addr for addr in self.session.peer_addresses(process.uuid)
                    if (
                        (identity := self.session.peer_identity(addr))
                        and identity.uuid == owner_id
                    )
                ),
                None,
            )
            if not owner_addr:
                continue
            owner_key = self.session.peer_identity_key_for_address(owner_addr)

            self.publish_adoption_metadata(process, owner_key)
            changed = self.session.reconcile_peer_changes(
                owner_addr, process.uuid,
            ) or changed
        return SessionResult("ok", value=changed, effects=effects)

    def publish_adoption_metadata(
        self, process: ProtocolNode, owner_key: str | None = None,
    ) -> None:
        """Declare how this process's nodes are handled, for Core to enforce.

        What is declarable today is authorship: the process itself, its
        assignments and its runtime state are the owner's to write, so every
        held node of those types names the owner's key. Responses are anyone's
        and stay unconstrained.

        A node this client does not hold is classified at first sight, since a
        parent's `additions` cannot tell an incoming response from an incoming
        assignment. See Core's DESIGN_ADOPTION_METADATA.md.
        """
        self.session.set_topic_adoption_default(
            process.uuid, adopt="auto", additions="auto",
        )
        self.session.set_adoption_classifier(
            process.uuid,
            lambda node, default, key=owner_key: (
                self._classify_incoming_node(key, node)
            ),
        )
        # Agendas are Session's: projected from each author's perspective,
        # never adopted, so a copy of one has no business in this tree.
        self.session.set_adoption_metadata_for_subtree(
            process.uuid, adopt="never", additions="never",
            node_type="agenda_item",
        )
        if not owner_key:
            return
        for node_type in (PROCESS_TYPE, ASSIGNMENT_TYPE, RUNTIME_STATE_TYPE):
            self.session.set_adoption_metadata_for_subtree(
                process.uuid, author=owner_key, node_type=node_type,
            )

    @staticmethod
    def _classify_incoming_node(owner_key: str | None, node) -> dict | None:
        """How a node this process does not yet hold is to be handled.

        A response is anyone's to write. The process itself, its assignments
        and its runtime state are the owner's alone. Nothing else belongs in
        this topic at all.
        """
        node_type = node.data.get("type")
        if node_type == RESPONSE_TYPE:
            return {"adopt": "auto", "additions": "auto", "author": "any"}
        if node_type in {PROCESS_TYPE, ASSIGNMENT_TYPE, RUNTIME_STATE_TYPE}:
            return {
                "adopt": "auto",
                "additions": "auto",
                "author": owner_key or "any",
            }
        return {"adopt": "never", "additions": "never"}

    def transition_events(self, process: ProtocolNode) -> list[dict]:
        events = []
        for addr in self.session.peer_addresses(process.uuid):
            if not self.session.peer_discusses_node(addr, process.uuid):
                continue
            for event in self.session.analyze_peer_transitions(addr, process.uuid):
                node_uuid = str(event.get("node_uuid") or "")
                local = self.session.protocol.index.get(node_uuid)
                peer = self.session.get_cached_peer_subtree(addr, node_uuid)
                node = local or peer
                if not node or node.data.get("type") not in DISPLAYED_TRANSITION_TYPES:
                    continue
                if event.get("type") == "in_agreement":
                    continue
                event = dict(event)
                event["changes"] = self.describe_peer_changes(
                    addr,
                    node_uuid,
                    authored_locally=event.get("type") in {
                        "local_made_changes", "peer_missing_node",
                    },
                )
                events.append(event)
        return events

    def transition_by_node(self, events: list[dict]) -> dict:
        grouped: dict[str, dict] = {}
        for event in events:
            node_uuid = str(event.get("node_uuid") or "")
            if not node_uuid:
                continue
            info = {
                key: event.get(key)
                for key in (
                    "type", "stage", "peer_addr", "origin_identity",
                    "local_revision_origin", "peer_revision_origin",
                    "local_state_hash", "peer_state_hash", "local_base_hash",
                    "peer_base_hash", "local_revision", "peer_revision",
                    "peer_observed_local_revision",
                )
            }
            info["changes"] = list(event.get("changes") or [])
            info["reaction"] = self.session.reaction_for_event(event)
            info["priority"] = self.session.transition_rank(event)
            current = grouped.get(node_uuid)
            if current is None:
                grouped[node_uuid] = {**info, "events": [dict(info)]}
                continue
            current.setdefault("events", []).append(dict(info))
            if self.session.transition_rank(event) > tuple(
                current.get("priority") or (0, 0)
            ):
                events_for_node = current["events"]
                current.update(info)
                current["events"] = events_for_node
        return grouped

    def describe_peer_changes(
        self, peer_addr: str, node_uuid: str, *, authored_locally: bool,
    ) -> list[dict]:
        local = self.session.protocol.index.get(node_uuid)
        peer = self.session.get_cached_peer_subtree(peer_addr, node_uuid)
        authored = local if authored_locally else peer
        counter = peer if authored_locally else local
        node = authored or counter
        if not node:
            return []
        label = (
            "Process" if node.data.get("type") == PROCESS_TYPE
            else "Participant assignment"
        )
        if authored is None or authored.deleted:
            return [{
                "node_label": label,
                "authored_act": "deleted",
                "authored_noun": "deletion",
            }]
        if counter is None or counter.deleted:
            return [{
                "node_label": label,
                "authored_act": "created",
                "authored_noun": "creation",
            }]
        changes = []
        if (
            node.data.get("type") != PROCESS_TYPE
            and authored.parent_uuid != counter.parent_uuid
        ):
            changes.append({
                "node_label": label,
                "authored_act": "moved",
                "authored_noun": "move",
            })
        ignored = {"type", "last_completed", "current_stage", "lifecycle", "outcome"}
        fields = sorted(
            (set(authored.data) | set(counter.data)) - ignored
        )
        changed_fields = [
            field for field in fields
            if authored.data.get(field) != counter.data.get(field)
        ]
        if changed_fields:
            names = {
                "title": "title",
                "identity_uuid": "participant",
                "role": "role",
                "required": "requirement",
            }
            changes.append({
                "node_label": label,
                "authored_act": "modified",
                "authored_noun": "modification",
                "authored_detail": ", ".join(
                    names.get(field, field.replace("_", " "))
                    for field in changed_fields
                ),
            })
        return changes

    def accept_peer_node(
        self, source_addr: str, node_uuid: str, adopt_absence: bool = False,
    ) -> SessionResult:
        if not self._owns_reactable_node(node_uuid, source_addr, adopt_absence):
            return SessionResult("error", reason="node is not part of S-Flow")
        return self.session.accept_peer_node(
            source_addr, node_uuid, adopt_absence,
        )

    def rollback_peer_node(
        self, source_addr: str, node_uuid: str, rollback_absence: bool = False,
    ) -> SessionResult:
        if not self._owns_reactable_node(node_uuid, source_addr, False):
            return SessionResult("error", reason="node is not part of S-Flow")
        return self.session.rollback_peer_node(
            source_addr, node_uuid, rollback_absence,
        )

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

    def _owns_reactable_node(
        self, node_uuid: str, peer_addr: str, allow_absence: bool,
    ) -> bool:
        local = self.session.protocol.index.get(node_uuid)
        if local and local.data.get("type") in DISPLAYED_TRANSITION_TYPES:
            return self._local_process_topic(node_uuid) is not None
        if allow_absence:
            return False
        peer = self.session.get_cached_peer_subtree(peer_addr, node_uuid)
        if not peer or peer.data.get("type") not in DISPLAYED_TRANSITION_TYPES:
            return False
        return any(
            self._node(topic_uuid, PROCESS_TYPE)
            for topic_uuid in self.session.peer_topics_for_node(
                peer_addr, node_uuid,
            )
        )

    def _is_process_owner(self, process: ProtocolNode) -> bool:
        return (
            process.data.get("created_by_identity_uuid")
            == self.session.identity.uuid
        )

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
                    and parent.data.get("type") == "flow_app"
                    and parent.data.get("name") == FLOW_APP_NAME
                ) else None
            current = self.session.protocol.index.get(current.parent_uuid)
        return None

    def _metadata(self) -> dict:
        with self.session.lock:
            return copy.deepcopy(
                self.session.application_metadata(FLOW_APPLICATION_ID),
            )

    def _remember_process(self, process_uuid: str) -> None:
        with self.session.lock:
            metadata = self.session.application_metadata(
                FLOW_APPLICATION_ID,
            )
            metadata["selected_process_uuid"] = process_uuid

    def _container(self) -> ProtocolNode:
        return self._folder(
            self._apps_folder(), FLOW_APP_NAME, "flow_app",
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
                if child.data.get("type") == "flow_app"
                and child.data.get("name") == FLOW_APP_NAME
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
