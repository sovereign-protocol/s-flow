"""Versioned public facade exposed by S-Flow."""

from __future__ import annotations

from sovereign import ProtocolNode

from .logic import FlowLogic


FLOW_FACADE_API_VERSION = 1


class FlowFacade:
    def __init__(self, logic: FlowLogic):
        self._logic = logic

    def processes(self) -> list[ProtocolNode]:
        return self._logic.processes()

    def templates(self) -> list[dict[str, str]]:
        return self._logic.templates()

    def process_summary(self, process: ProtocolNode) -> dict:
        return self._logic.process_summary(process)

    def decision_result(self, process_uuid: str) -> dict | None:
        return self._logic.decision_result(process_uuid)

    def collaboration_context(
        self, process_uuid: str, network: dict | None = None,
    ) -> dict:
        return self._logic.collaboration_context(process_uuid, network)

    def create_process(
        self, title: str, definition_id: str, definition_version: str,
    ):
        return self._logic.create_process(
            title, definition_id, definition_version,
        )

    def create_integrative_election(
        self,
        title: str,
        participant_uuids: list[str],
        facilitator_uuid: str,
        eligible_candidate_uuids: list[str] | None = None,
        definition_version: str = "0.2.0",
    ):
        return self._logic.create_integrative_election(
            title,
            participant_uuids,
            facilitator_uuid,
            eligible_candidate_uuids,
            definition_version,
        )

    def rename_process(
        self, process_uuid: str, title: str,
        expected_content_hash: str | None = None,
    ):
        return self._logic.rename_process(
            process_uuid, title, expected_content_hash,
        )

    def delete_process(self, process_uuid: str):
        return self._logic.delete_process(process_uuid)

    def leave_process(self, process_uuid: str):
        return self._logic.leave_process(process_uuid)

    def return_to_setup(self, process_uuid: str):
        return self._logic.return_to_setup(process_uuid)

    def start_process(self, process_uuid: str):
        return self._logic.start_process(process_uuid)

    def set_assignment(
        self, process_uuid: str, identity_uuid: str, role: str,
        required: bool | None = None,
    ):
        return self._logic.set_assignment(
            process_uuid, identity_uuid, role, required,
        )

    def delete_assignment(self, process_uuid: str, assignment_uuid: str):
        return self._logic.delete_assignment(process_uuid, assignment_uuid)

    def submit_task(
        self,
        process_uuid: str,
        task_id: str,
        response: dict,
        expected_runtime_content_hash: str | None = None,
    ):
        return self._logic.submit_task(
            process_uuid,
            task_id,
            response,
            expected_runtime_content_hash,
        )

    def go_back(self, process_uuid: str):
        return self._logic.go_back(process_uuid)

    def create_agenda_item(
        self, process_uuid: str, text: str, priority: str | None = None,
    ):
        return self._logic.create_agenda_item(process_uuid, text, priority)

    def delete_agenda_item(self, item_uuid: str):
        return self._logic.delete_agenda_item(item_uuid)

    def set_agenda_item_priority(
        self, item_uuid: str, priority: str | None,
    ):
        return self._logic.set_agenda_item_priority(item_uuid, priority)

    def move_agenda_item(self, item_uuid: str, index: int):
        return self._logic.move_agenda_item(item_uuid, index)

    def accept_peer_node(
        self, source_addr: str, node_uuid: str,
        adopt_absence: bool = False,
    ):
        return self._logic.accept_peer_node(
            source_addr, node_uuid, adopt_absence,
        )

    def rollback_peer_node(
        self, source_addr: str, node_uuid: str,
        rollback_absence: bool = False,
    ):
        return self._logic.rollback_peer_node(
            source_addr, node_uuid, rollback_absence,
        )
