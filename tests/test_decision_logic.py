import unittest

from sovereign import ProtocolNode, Session

from s_decision.application import APPLICATION_MANIFEST
from s_decision.logic import (
    ASSIGNMENT_TYPE,
    decision_APPLICATION_ID,
    PROCESS_TYPE,
    decisionLogic,
)
from s_decision.workflow_adapter import RESPONSE_TYPE, RUNTIME_STATE_TYPE


class decisionLogicTests(unittest.TestCase):
    def setUp(self):
        self.session = Session("local")
        self.logic = decisionLogic(self.session)

    def test_manifest_and_topic_registration(self):
        registration = self.logic.application_registration()

        self.assertEqual(APPLICATION_MANIFEST.display_name, "S-decision")
        self.assertEqual(APPLICATION_MANIFEST.application_id, "decision")
        self.assertEqual(registration.application_id, decision_APPLICATION_ID)
        self.assertEqual(registration.root_types, frozenset({PROCESS_TYPE}))
        self.assertTrue(registration.assignment_scoped)
        self.assertTrue(registration.mount_invitation)

    def test_create_process_is_a_core_topic_with_facilitator_assignment(self):
        created = self.logic.create_process(
            "Elect secretary", "integrative-election", "0.2.0",
        )

        self.assertEqual(created.status, "ok")
        process = self.session.protocol.index[created.value]
        self.assertEqual(process.data["type"], PROCESS_TYPE)
        self.assertEqual(process.data["lifecycle"], "setup")
        self.assertEqual([item.uuid for item in self.logic.processes()], [process.uuid])
        assignments = self.logic.assignments(process)
        self.assertEqual(
            {item.data["role"] for item in assignments},
            {"facilitator", "requiredParticipant"},
        )
        self.assertTrue(all(
            item.data["type"] == ASSIGNMENT_TYPE
            and item.data["identity_uuid"] == self.session.identity.uuid
            for item in assignments
        ))

    def test_process_payload_uses_core_identities_and_agenda(self):
        process_uuid = self.logic.create_process("Consent policy").value
        agenda = self.logic.create_agenda_item(
            process_uuid, "Clarify the scope", "high",
        )

        payload = self.logic.process_payload(process_uuid)

        self.assertEqual(agenda.status, "ok")
        self.assertEqual(payload["process"]["uuid"], process_uuid)
        self.assertEqual(payload["agenda_items"][0]["data"]["priority"], "high")
        self.assertEqual(payload["known_identities"][0]["uuid"], self.session.identity.uuid)
        self.assertEqual(payload["processes"][0]["required_from_me"], "Configure participants")

    def test_stale_rename_is_rejected_by_content_hash(self):
        process_uuid = self.logic.create_process("Original").value
        process = self.session.protocol.index[process_uuid]
        stale_hash = process.content_hash
        self.logic.rename_process(process_uuid, "New title", stale_hash)

        rejected = self.logic.rename_process(
            process_uuid, "Overwrite", stale_hash,
        )

        self.assertEqual(rejected.status, "error")
        self.assertIn("changed while you were editing", rejected.reason)

    def test_invited_process_mounts_as_a_local_topic(self):
        host = Session("host")
        host_logic = decisionLogic(host)
        process_uuid = host_logic.create_process("Shared election").value
        subtree = ProtocolNode.from_dict(
            host.protocol.index[process_uuid].to_dict(),
        )

        accepted = self.logic.accept_process_invitation(subtree)

        self.assertEqual(accepted.status, "ok")
        self.assertEqual(self.logic.processes()[0].uuid, process_uuid)
        self.assertIn(process_uuid, self.session.active_topic_ids())

    def test_delete_releases_and_removes_process_topic(self):
        process_uuid = self.logic.create_process("Temporary").value

        deleted = self.logic.delete_process(process_uuid)

        self.assertEqual(deleted.status, "ok")
        self.assertEqual(self.logic.processes(), [])

    def test_start_and_submit_are_restored_from_core_nodes(self):
        process_uuid = self.logic.create_process("Elect secretary").value

        started = self.logic.start_process(process_uuid)
        payload = self.logic.process_payload(process_uuid)
        workflow = payload["workflow"]
        task = workflow["personal"]["tasks"][0]
        submitted = self.logic.submit_task(
            process_uuid,
            task["id"],
            {"candidateId": self.session.identity.uuid},
            workflow["runtime_content_hash"],
        )

        self.assertEqual(started.status, "ok")
        self.assertEqual(submitted.status, "ok")
        process = self.session.protocol.index[process_uuid]
        self.assertEqual(
            len([
                child for child in process.live_children()
                if child.data.get("type") == RUNTIME_STATE_TYPE
            ]),
            1,
        )
        self.assertEqual(
            len([
                child for child in process.live_children()
                if child.data.get("type") == RESPONSE_TYPE
            ]),
            1,
        )

        restored_logic = decisionLogic(self.session)
        restored = restored_logic.process_payload(process_uuid)["workflow"]
        self.assertEqual(restored["position"]["last_completed_stage"]["id"], "Task_Nominate")
        self.assertEqual(
            restored["personal"]["tasks"][0]["nodeId"],
            "Task_ShareReasons",
        )

    def test_runtime_hash_rejects_a_stale_response(self):
        process_uuid = self.logic.create_process("Elect secretary").value
        self.logic.start_process(process_uuid)
        workflow = self.logic.process_payload(process_uuid)["workflow"]
        task = workflow["personal"]["tasks"][0]
        stale_hash = workflow["runtime_content_hash"]
        self.logic.submit_task(
            process_uuid,
            task["id"],
            {"candidateId": self.session.identity.uuid},
            stale_hash,
        )
        next_task = self.logic.process_payload(process_uuid)[
            "workflow"
        ]["personal"]["tasks"][0]

        rejected = self.logic.submit_task(
            process_uuid,
            next_task["id"],
            {"statement": "A good fit."},
            stale_hash,
        )

        self.assertEqual(rejected.status, "error")
        self.assertIn("advanced while you were responding", rejected.reason)


if __name__ == "__main__":
    unittest.main()
