import unittest

from sovereign import ProtocolNode, Session

from s_flow.application import APPLICATION_MANIFEST
from s_flow.logic import (
    ASSIGNMENT_TYPE,
    FLOW_APPLICATION_ID,
    PROCESS_TYPE,
    FlowLogic,
    canonical_decision_result_hash,
)
from s_flow.workflow_adapter import (
    RESPONSE_TYPE,
    RETRACTED_RESPONSE_IDS,
    RUNTIME_STATE_TYPE,
)


class FlowLogicTests(unittest.TestCase):
    def setUp(self):
        self.session = Session("local")
        self.logic = FlowLogic(self.session)

    def test_manifest_and_topic_registration(self):
        registration = self.logic.application_registration()

        self.assertEqual(APPLICATION_MANIFEST.display_name, "S-Flow")
        self.assertEqual(APPLICATION_MANIFEST.application_id, "flow")
        self.assertEqual(registration.application_id, FLOW_APPLICATION_ID)
        self.assertEqual(registration.root_types, frozenset({PROCESS_TYPE}))
        self.assertTrue(registration.assignment_scoped)
        self.assertTrue(registration.mount_invitation)

    def test_template_catalog_uses_bundled_definitions(self):
        templates = self.logic.templates()
        self.assertEqual(
            [item["id"] for item in templates],
            [
                "integrative-election",
                "integrative-decision-making",
                "minimal-consent",
            ],
        )
        self.assertTrue(all(item["name"] for item in templates))
        self.assertTrue(all(item["description"] for item in templates))

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

    def test_saved_snapshot_restores_flow_in_fresh_setup_state(self):
        created = self.logic.create_process(
            "Election", "integrative-election", "0.2.0",
        )
        self.logic.start_process(created.value)
        saved = self.logic.save_snapshot(
            created.value, "Election baseline", "Reusable election",
        )
        self.logic.delete_process(created.value)

        restored = self.logic.create_from_snapshot(saved.value, "Next election")

        self.assertEqual(saved.status, "ok", saved.reason)
        self.assertEqual(self.logic.snapshots()[0]["description"], "Reusable election")
        process = self.session.protocol.index[restored.value]
        self.assertEqual(process.data["title"], "Next election")
        self.assertEqual(process.data["lifecycle"], "setup")
        self.assertIsNone(self.logic.workflow.state_node(process))
        self.assertNotEqual(restored.value, created.value)
        self.assertEqual(self.logic.delete_snapshot(saved.value).status, "ok")
        self.assertEqual(self.logic.snapshots(), [])

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

    def test_an_agenda_item_author_can_update_its_text(self):
        process_uuid = self.logic.create_process("Consent policy").value
        item = self.logic.create_agenda_item(
            process_uuid, "First wording",
        ).value

        result = self.logic.update_agenda_item(item.uuid, "Revised wording")

        self.assertEqual(result.status, "ok")
        self.assertEqual(
            self.session.protocol.index[item.uuid].data["text"],
            "Revised wording",
        )

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

    def test_selected_process_survives_later_refreshes(self):
        first_uuid = self.logic.create_process("First").value
        second_uuid = self.logic.create_process("Second").value

        self.assertEqual(self.logic.select_process(first_uuid).status, "ok")

        self.assertEqual(
            self.logic.process_payload()["process"]["uuid"],
            first_uuid,
        )
        self.assertNotEqual(first_uuid, second_uuid)

    def test_invited_process_mounts_as_a_local_topic(self):
        host = Session("host")
        host_logic = FlowLogic(host)
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

    def test_invitee_can_leave_but_cannot_delete_shared_process(self):
        host = Session("host")
        host_logic = FlowLogic(host)
        process_uuid = host_logic.create_process("Shared flow").value
        subtree = ProtocolNode.from_dict(
            host.protocol.index[process_uuid].to_dict(),
        )
        self.assertEqual(
            self.logic.accept_process_invitation(subtree).status, "ok",
        )

        rejected = self.logic.delete_process(process_uuid)
        left = self.logic.leave_process(process_uuid)

        self.assertEqual(rejected.status, "error")
        self.assertIn("creator", rejected.reason)
        self.assertEqual(left.status, "ok")
        self.assertEqual(self.logic.processes(), [])
        self.assertNotIn(process_uuid, self.session.active_topic_ids())

    def test_return_to_setup_reopens_participants_and_starts_a_new_run(self):
        process_uuid = self.logic.create_process(
            "Consent policy", "minimal-consent", "0.2.0",
        ).value
        self.assertEqual(self.logic.start_process(process_uuid).status, "ok")
        workflow = self.logic.process_payload(process_uuid)["workflow"]
        submitted = self.logic.submit_task(
            process_uuid,
            workflow["personal"]["tasks"][0]["id"],
            {"proposal": "Initial proposal"},
            workflow["runtime_content_hash"],
        )
        self.assertEqual(submitted.status, "ok")

        returned = self.logic.return_to_setup(process_uuid)
        setup = self.logic.process_payload(process_uuid)

        self.assertEqual(returned.status, "ok")
        self.assertEqual(setup["process"]["data"]["lifecycle"], "setup")
        self.assertEqual(setup["workflow"]["personal"]["tasks"], [])
        self.assertEqual(
            setup["workflow"]["position"]["current_stages"][0]["id"],
            "setup",
        )
        self.assertEqual(
            setup["process"]["data"]["workflow_generation"], 1,
        )
        self.assertEqual(self.logic.start_process(process_uuid).status, "ok")
        restarted = self.logic.process_payload(process_uuid)["workflow"]
        self.assertEqual(
            restarted["personal"]["tasks"][0]["nodeId"],
            "Task_CreateProposal",
        )

    def test_start_and_submit_are_restored_from_core_nodes(self):
        process_uuid = self.logic.create_process("Elect secretary").value

        started = self.logic.start_process(process_uuid)
        payload = self.logic.process_payload(process_uuid)
        workflow = payload["workflow"]
        nomination_round = next(
            item for item in workflow["definition"]["rounds"]
            if item["node_id"] == "Task_Nominate"
        )
        self.assertEqual(nomination_round["ordering"], "parallel")
        self.assertEqual(nomination_round["publication"], "onRoundComplete")
        task = workflow["personal"]["tasks"][0]
        submitted = self.logic.submit_task(
            process_uuid,
            task["id"],
            {
                "candidateId": self.session.identity.uuid,
                "reason": "Relevant experience",
            },
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

        restored_logic = FlowLogic(self.session)
        restored = restored_logic.process_payload(process_uuid)["workflow"]
        self.assertEqual(restored["position"]["last_completed_stage"]["id"], "Task_Nominate")
        self.assertEqual(
            restored["personal"]["tasks"][0]["nodeId"],
            "Task_ChangeNominations",
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
            {
                "candidateId": self.session.identity.uuid,
                "reason": "Relevant experience",
            },
            stale_hash,
        )
        next_task = self.logic.process_payload(process_uuid)[
            "workflow"
        ]["personal"]["tasks"][0]

        rejected = self.logic.submit_task(
            process_uuid,
            next_task["id"],
            {"decision": "keep"},
            stale_hash,
        )

        self.assertEqual(rejected.status, "error")
        self.assertIn("advanced while you were responding", rejected.reason)

    def test_integrative_election_exposes_stable_terminal_result(self):
        process_uuid = self.logic.create_process("Elect secretary").value
        identity_uuid = self.session.identity.uuid
        self.assertEqual(self.logic.start_process(process_uuid).status, "ok")
        responses = {
            "Task_Nominate": {
                "candidateId": identity_uuid,
                "reason": "Available",
            },
            "Task_ChangeNominations": {"decision": "keep"},
            "Task_ObjectionRound": {"decision": "noObjection"},
        }
        while True:
            workflow = self.logic.process_payload(process_uuid)["workflow"]
            if workflow["status"] == "completed":
                break
            task = workflow["personal"]["tasks"][0]
            self.assertEqual(self.logic.submit_task(
                process_uuid,
                task["id"],
                responses[task["nodeId"]],
                workflow["runtime_content_hash"],
            ).status, "ok")

        result = self.logic.decision_result(process_uuid)

        self.assertEqual(result["contract_id"], "s-flow.decision-result")
        self.assertEqual(result["contract_version"], 1)
        self.assertEqual(result["process_uuid"], process_uuid)
        self.assertEqual(result["definition_id"], "integrative-election")
        self.assertEqual(result["definition_version"], "0.2.0")
        self.assertEqual(result["lifecycle"], "completed")
        self.assertEqual(result["current_stage"], "")
        self.assertTrue(result["last_completed_stage"])
        self.assertEqual(result["terminal_outcome"], "elected")
        self.assertEqual(result["selected_candidate_uuid"], identity_uuid)
        self.assertEqual(result["facilitator_uuid"], identity_uuid)
        self.assertEqual(result["participant_snapshot"], [{
            "identity_uuid": identity_uuid,
            "role": "requiredParticipant",
            "required": True,
        }])
        self.assertEqual(
            result["result_hash"], canonical_decision_result_hash(result),
        )

    def test_facade_election_command_freezes_roles_and_starts_process(self):
        facilitator = "facilitator-actor"
        participants = ["member-b", "member-a", "member-b"]

        created = self.logic.create_integrative_election(
            "Elect Identity",
            participants,
            facilitator,
            ["member-a", "member-b"],
        )

        self.assertEqual(created.status, "ok")
        result = self.logic.decision_result(created.value)
        self.assertEqual(result["lifecycle"], "active")
        self.assertTrue(result["current_stage"])
        self.assertEqual(result["facilitator_uuid"], facilitator)
        self.assertEqual(result["participant_snapshot"], [
            {
                "identity_uuid": "member-a",
                "role": "requiredParticipant",
                "required": True,
            },
            {
                "identity_uuid": "member-b",
                "role": "requiredParticipant",
                "required": True,
            },
        ])
        process = self.session.protocol.index[created.value]
        self.assertEqual(process.data["eligible_candidates"], [
            "member-a", "member-b",
        ])
        self.assertEqual(
            self.logic.set_assignment(
                created.value, "late-member", "requiredParticipant", True,
            ).status,
            "error",
        )

    def test_incomplete_process_has_a_hashable_non_terminal_result(self):
        process_uuid = self.logic.create_process("Not started").value

        result = self.logic.decision_result(process_uuid)

        self.assertEqual(result["lifecycle"], "setup")
        self.assertIsNone(result["terminal_outcome"])
        self.assertIsNone(result["selected_candidate_uuid"])
        self.assertEqual(
            result["result_hash"], canonical_decision_result_hash(result),
        )
        self.assertIsNone(self.logic.decision_result("missing"))

    def test_go_back_retracts_response_and_reopens_same_input(self):
        process_uuid = self.logic.create_process(
            "Consent policy", "minimal-consent", "0.2.0",
        ).value
        self.assertEqual(self.logic.start_process(process_uuid).status, "ok")
        workflow = self.logic.process_payload(process_uuid)["workflow"]
        task = workflow["personal"]["tasks"][0]
        submitted = self.logic.submit_task(
            process_uuid,
            task["id"],
            {"proposal": "Policy A"},
            workflow["runtime_content_hash"],
        )
        self.assertEqual(submitted.status, "ok")

        returned = self.logic.go_back(process_uuid)

        self.assertEqual(returned.status, "ok")
        reopened = self.logic.process_payload(process_uuid)["workflow"]
        self.assertEqual(
            reopened["personal"]["tasks"][0]["nodeId"],
            "Task_CreateProposal",
        )
        self.assertFalse(reopened["can_go_back"])
        process = self.session.protocol.index[process_uuid]
        instance = self.logic.workflow.load(process)
        self.assertIn(submitted.value, instance.data[RETRACTED_RESPONSE_IDS])
        self.assertEqual(
            self.logic.submit_task(
                process_uuid,
                reopened["personal"]["tasks"][0]["id"],
                {"proposal": "Policy A, corrected"},
                reopened["runtime_content_hash"],
            ).status,
            "ok",
        )


if __name__ == "__main__":
    unittest.main()
