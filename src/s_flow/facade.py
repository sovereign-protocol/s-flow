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

    def process_summary(self, process: ProtocolNode) -> dict:
        return self._logic.process_summary(process)

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

    def rename_process(
        self, process_uuid: str, title: str,
        expected_content_hash: str | None = None,
    ):
        return self._logic.rename_process(
            process_uuid, title, expected_content_hash,
        )

    def delete_process(self, process_uuid: str):
        return self._logic.delete_process(process_uuid)

    def start_process(self, process_uuid: str):
        return self._logic.start_process(process_uuid)

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
