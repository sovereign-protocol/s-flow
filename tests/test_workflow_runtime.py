from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from s_flow.workflow import (  # noqa: E402
    ResponseValidationError,
    TaskActionError,
    WorkflowEngine,
    instance_from_dict,
    instance_to_dict,
    load_bundled_workflow,
    load_workflow,
)


TEMPLATES = PROJECT_ROOT / "src" / "s_flow" / "workflow" / "templates"


def open_task(instance, user_id: str, node_id: str):
    matches = [
        task
        for task in instance.tasks.values()
        if task.user_id == user_id
        and task.node_id == node_id
        and task.status == "open"
    ]
    if len(matches) != 1:
        raise AssertionError(
            f"Expected one open task for {user_id} at {node_id}; found {len(matches)}."
        )
    return matches[0]


class LoaderTests(unittest.TestCase):
    def test_all_reference_templates_load(self):
        names = {
            "integrative-election.bpmn": "integrativeElection",
            "integrative-decision-making.bpmn": "integrativeDecisionMaking",
            "minimal-consent-decision.bpmn": "minimalConsent",
        }
        for filename, template_id in names.items():
            with self.subTest(filename=filename):
                definition = load_workflow(TEMPLATES / filename)
                self.assertEqual(definition.template_id, template_id)
                self.assertTrue(definition.nodes)
                self.assertTrue(definition.flows)

    def test_bundled_template_and_instance_state_round_trip(self):
        definition = load_bundled_workflow("minimal-consent")
        engine = WorkflowEngine(definition)
        instance = engine.create_instance(
            "round-trip",
            {
                "proposer": ["alice"],
                "requiredParticipant": ["alice"],
            },
        )
        engine.start(instance)

        restored = instance_from_dict(
            definition, instance_to_dict(instance),
        )

        self.assertEqual(restored.id, instance.id)
        self.assertEqual(restored.current_node_id, instance.current_node_id)
        self.assertEqual(
            sorted(restored.tasks),
            sorted(instance.tasks),
        )
        self.assertEqual(
            engine.personal_projection(restored, "alice"),
            engine.personal_projection(instance, "alice"),
        )


class MinimalConsentRuntimeTests(unittest.TestCase):
    def setUp(self):
        definition = load_workflow(TEMPLATES / "minimal-consent-decision.bpmn")
        self.engine = WorkflowEngine(definition)
        self.roles = {
            "proposer": ["alice"],
            "requiredParticipant": ["alice", "ben", "cara"],
        }

    def create_started(self):
        instance = self.engine.create_instance("consent-1", self.roles)
        self.engine.start(instance)
        return instance

    def submit_proposal(self, instance, content="Use proposal P1"):
        task = open_task(instance, "alice", "Task_CreateProposal")
        self.engine.submit(instance, "alice", task.id, {"proposal": content})

    def submit_consent_round(self, instance, responses):
        for user_id, response in responses:
            task = open_task(instance, user_id, "Task_ConsentRound")
            self.engine.submit(instance, user_id, task.id, response)

    def test_unanimous_consent_adopts_exact_revision(self):
        instance = self.create_started()
        self.assertEqual(
            self.engine.personal_projection(instance, "alice").primary_state,
            "inputRequired",
        )

        self.submit_proposal(instance)
        self.engine.acknowledge_information(instance, "alice")

        alice_task = open_task(instance, "alice", "Task_ConsentRound")
        self.engine.submit(instance, "alice", alice_task.id, {"decision": "consent"})
        alice_projection = self.engine.personal_projection(instance, "alice")
        self.assertEqual(alice_projection.primary_state, "waiting")
        self.assertEqual(alice_projection.waiting_reason["type"], "actorTask")
        self.assertEqual(
            set(alice_projection.waiting_reason["dependencies"]),
            {"ben", "cara"},
        )

        self.submit_consent_round(
            instance,
            [
                ("ben", {"decision": "consent"}),
                ("cara", {"decision": "consent"}),
            ],
        )

        self.assertEqual(instance.status, "completed")
        self.assertEqual(instance.outcome, "adopted")
        artifact = instance.artifacts["proposal"]
        self.assertEqual(artifact.lifecycle_state, "adopted")
        self.assertEqual(artifact.current_revision_id, "proposal-r1")

    def test_objection_requires_new_complete_round(self):
        instance = self.create_started()
        self.submit_proposal(instance, "P1")
        self.submit_consent_round(
            instance,
            [
                ("alice", {"decision": "consent"}),
                ("ben", {"decision": "objection", "statement": "Risk"}),
                ("cara", {"decision": "consent"}),
            ],
        )

        revision_task = open_task(instance, "alice", "Task_RevisionDecision")
        self.engine.submit(
            instance,
            "alice",
            revision_task.id,
            {"decision": "amend", "proposal": "P2"},
        )

        artifact = instance.artifacts["proposal"]
        self.assertEqual(len(artifact.revisions), 2)
        self.assertEqual(artifact.current_revision_id, "proposal-r2")
        for user_id in ("alice", "ben", "cara"):
            open_task(instance, user_id, "Task_ConsentRound")

        self.submit_consent_round(
            instance,
            [
                ("alice", {"decision": "consent"}),
                ("ben", {"decision": "consent"}),
                ("cara", {"decision": "consent"}),
            ],
        )
        self.assertEqual(instance.outcome, "adopted")
        self.assertEqual(artifact.current_revision_id, "proposal-r2")

    def test_invalid_objection_does_not_complete_task(self):
        instance = self.create_started()
        self.submit_proposal(instance)
        task = open_task(instance, "ben", "Task_ConsentRound")
        with self.assertRaises(ResponseValidationError):
            self.engine.submit(instance, "ben", task.id, {"decision": "objection"})
        self.assertEqual(task.status, "open")


class ElectionRuntimeTests(unittest.TestCase):
    def setUp(self):
        definition = load_workflow(TEMPLATES / "integrative-election.bpmn")
        self.engine = WorkflowEngine(definition)
        self.roles = {
            "facilitator": ["farah"],
            "requiredParticipant": ["alice", "ben", "cara"],
        }

    def create_started(self):
        instance = self.engine.create_instance(
            "election-1",
            self.roles,
            data={
                "rolePresentationRequired": False,
                "eligibilityMode": "closed",
                "eligibleCandidates": ["dana", "eli"],
            },
        )
        self.engine.start(instance)
        return instance

    def complete_initial_rounds(self, instance):
        nominations = {"alice": "dana", "ben": "eli", "cara": "eli"}
        for user_id, candidate_id in nominations.items():
            task = open_task(instance, user_id, "Task_Nominate")
            self.engine.submit(
                instance,
                user_id,
                task.id,
                {"candidateId": candidate_id},
            )

        ben_projection = self.engine.personal_projection(instance, "ben")
        self.assertEqual(ben_projection.waiting_reason["type"], "priorTurn")

        for user_id in ("alice", "ben", "cara"):
            task = open_task(instance, user_id, "Task_ShareReasons")
            self.engine.submit(
                instance,
                user_id,
                task.id,
                {"statement": f"{nominations[user_id]} is suitable"},
            )

        for user_id in ("alice", "ben", "cara"):
            task = open_task(instance, user_id, "Task_ChangeNominations")
            self.engine.submit(
                instance,
                user_id,
                task.id,
                {"decision": "keep"},
            )

        self.assertEqual(instance.data["proposedCandidate"], "eli")

    def submit_objection_round(self, instance, responses):
        for user_id, response in responses:
            task = open_task(instance, user_id, "Task_ObjectionRound")
            self.engine.submit(instance, user_id, task.id, response)

    def test_no_objection_elects_candidate(self):
        instance = self.create_started()
        self.complete_initial_rounds(instance)
        self.submit_objection_round(
            instance,
            [
                ("alice", {"decision": "noObjection"}),
                ("ben", {"decision": "noObjection"}),
                ("cara", {"decision": "noObjection"}),
            ],
        )
        self.assertEqual(instance.outcome, "elected")
        self.assertEqual(instance.data["electedCandidate"], "eli")

    def test_valid_objection_excludes_and_forces_changes(self):
        instance = self.create_started()
        self.complete_initial_rounds(instance)
        self.submit_objection_round(
            instance,
            [
                ("alice", {"decision": "noObjection"}),
                ("ben", {"decision": "noObjection"}),
                ("cara", {"decision": "objection", "statement": "Material risk"}),
            ],
        )

        message = self.engine.post_message(
            instance,
            "cara",
            "The proposed candidate cannot fulfil the role during the required period.",
        )
        self.assertEqual(message["authorId"], "cara")

        close_task = open_task(instance, "farah", "Task_DiscussObjection")
        self.engine.submit(instance, "farah", close_task.id, {"action": "close"})

        item = instance.current_work_item()
        self.assertIsNotNone(item)
        validity_task = open_task(instance, "farah", "Task_RecordValidity")
        self.engine.submit(
            instance,
            "farah",
            validity_task.id,
            {
                "objectionId": item.id,
                "decision": "valid",
                "note": "Recorded after facilitation",
            },
        )

        self.assertIn("eli", instance.data["excludedCandidates"])

        alice_task = open_task(instance, "alice", "Task_ChangeNominations")
        self.engine.submit(
            instance,
            "alice",
            alice_task.id,
            {"decision": "keep"},
        )

        ben_task = open_task(instance, "ben", "Task_ChangeNominations")
        with self.assertRaises(TaskActionError):
            self.engine.submit(
                instance,
                "ben",
                ben_task.id,
                {"decision": "keep"},
            )
        self.engine.submit(
            instance,
            "ben",
            ben_task.id,
            {"decision": "change", "candidateId": "dana", "reason": "Eli excluded"},
        )

        cara_task = open_task(instance, "cara", "Task_ChangeNominations")
        self.engine.submit(
            instance,
            "cara",
            cara_task.id,
            {"decision": "change", "candidateId": "dana", "reason": "Eli excluded"},
        )

        self.assertEqual(instance.data["proposedCandidate"], "dana")
        self.submit_objection_round(
            instance,
            [
                ("alice", {"decision": "noObjection"}),
                ("ben", {"decision": "noObjection"}),
                ("cara", {"decision": "noObjection"}),
            ],
        )
        self.assertEqual(instance.outcome, "elected")
        self.assertEqual(instance.data["electedCandidate"], "dana")


class IDMPRuntimeTests(unittest.TestCase):
    def setUp(self):
        definition = load_workflow(TEMPLATES / "integrative-decision-making.bpmn")
        self.engine = WorkflowEngine(definition)
        self.roles = {
            "facilitator": ["farah"],
            "proposer": ["alice"],
            "requiredParticipant": ["alice", "ben", "cara"],
        }

    def create_started(self):
        instance = self.engine.create_instance("idmp-1", self.roles)
        self.engine.start(instance)
        return instance

    def advance_to_first_objection_round(self, instance):
        proposal_task = open_task(instance, "alice", "Task_PresentProposal")
        self.engine.submit(
            instance,
            "alice",
            proposal_task.id,
            {"tension": "Unclear ownership", "proposal": "Create an accountability"},
        )
        for user_id in ("ben", "cara"):
            task = open_task(instance, user_id, "Task_ClarifyingQuestions")
            self.engine.submit(instance, user_id, task.id, {"action": "done"})
        close_task = open_task(instance, "farah", "Task_ClarifyingQuestions")
        self.engine.submit(instance, "farah", close_task.id, {"action": "close"})
        for user_id in ("ben", "cara"):
            task = open_task(instance, user_id, "Task_ReactionRound")
            self.engine.submit(instance, user_id, task.id, {"action": "pass"})
        option_task = open_task(instance, "alice", "Task_OptionToClarify")
        self.engine.submit(
            instance,
            "alice",
            option_task.id,
            {"decision": "continue"},
        )

    def test_question_tasks_and_no_objection_adoption(self):
        instance = self.create_started()
        proposal_task = open_task(instance, "alice", "Task_PresentProposal")
        self.engine.submit(
            instance,
            "alice",
            proposal_task.id,
            {"tension": "Unclear ownership", "proposal": "Create an accountability"},
        )

        ben_task = open_task(instance, "ben", "Task_ClarifyingQuestions")
        self.engine.submit(
            instance,
            "ben",
            ben_task.id,
            {"action": "question", "text": "Which role?"},
        )
        ben_done = open_task(instance, "ben", "Task_ClarifyingQuestions")
        self.engine.submit(instance, "ben", ben_done.id, {"action": "done"})

        cara_task = open_task(instance, "cara", "Task_ClarifyingQuestions")
        self.engine.submit(
            instance,
            "cara",
            cara_task.id,
            {"action": "question", "text": "What scope?"},
        )
        cara_done = open_task(instance, "cara", "Task_ClarifyingQuestions")
        self.engine.submit(instance, "cara", cara_done.id, {"action": "done"})

        alice_answers = [
            task
            for task in instance.tasks.values()
            if task.user_id == "alice"
            and task.node_id == "Task_ClarifyingQuestions"
            and task.status == "open"
        ]
        self.assertEqual(len(alice_answers), 2)
        self.engine.submit(
            instance,
            "alice",
            alice_answers[0].id,
            {"action": "answer", "text": "Operations"},
        )
        self.engine.submit(
            instance,
            "alice",
            alice_answers[1].id,
            {"action": "decline"},
        )

        position = self.engine.position(instance)
        self.assertEqual(position.last_completed_stage["id"], "Task_PresentProposal")
        close_task = open_task(instance, "farah", "Task_ClarifyingQuestions")
        self.engine.submit(instance, "farah", close_task.id, {"action": "close"})

        for user_id, response in (
            ("ben", {"action": "reaction", "text": "Useful"}),
            ("cara", {"action": "pass"}),
        ):
            task = open_task(instance, user_id, "Task_ReactionRound")
            self.engine.submit(instance, user_id, task.id, response)

        option_task = open_task(instance, "alice", "Task_OptionToClarify")
        self.engine.submit(
            instance,
            "alice",
            option_task.id,
            {"decision": "continue"},
        )

        for user_id in ("alice", "ben", "cara"):
            task = open_task(instance, user_id, "Task_IDMPObjectionRound")
            self.engine.submit(
                instance,
                user_id,
                task.id,
                {"decision": "noObjection"},
            )

        self.assertEqual(instance.outcome, "adopted")
        self.assertEqual(instance.artifacts["proposal"].lifecycle_state, "adopted")

    def test_proposer_can_withdraw_globally(self):
        instance = self.create_started()
        proposal_task = open_task(instance, "alice", "Task_PresentProposal")
        self.engine.submit(
            instance,
            "alice",
            proposal_task.id,
            {"tension": "T", "proposal": "P"},
        )
        self.engine.invoke_global_action(
            instance,
            "alice",
            "withdraw",
            artifact_id="proposal",
            reason="No longer needed",
        )
        self.assertEqual(instance.status, "completed")
        self.assertEqual(instance.outcome, "withdrawn")
        self.assertEqual(instance.artifacts["proposal"].lifecycle_state, "withdrawn")

    def test_valid_objection_is_integrated_and_retested(self):
        instance = self.create_started()
        self.advance_to_first_objection_round(instance)

        for user_id, response in (
            ("alice", {"decision": "noObjection"}),
            ("ben", {"decision": "objection", "statement": "Scope is ambiguous"}),
            ("cara", {"decision": "noObjection"}),
        ):
            task = open_task(instance, user_id, "Task_IDMPObjectionRound")
            self.engine.submit(instance, user_id, task.id, response)

        self.engine.post_message(instance, "ben", "The accountability needs a boundary.")
        test_close = open_task(instance, "farah", "Task_TestObjection")
        self.engine.submit(instance, "farah", test_close.id, {"action": "close"})
        item = instance.current_work_item()
        validity = open_task(instance, "farah", "Task_RecordIDMPValidity")
        self.engine.submit(
            instance,
            "farah",
            validity.id,
            {"objectionId": item.id, "decision": "valid"},
        )

        self.engine.post_message(
            instance,
            "alice",
            "Add an explicit boundary to the accountability.",
        )
        integration_close = open_task(instance, "farah", "Task_IntegrationDiscussion")
        self.engine.submit(
            instance,
            "farah",
            integration_close.id,
            {"action": "close"},
        )
        amendment = open_task(instance, "farah", "Task_RecordAmendment")
        self.engine.submit(
            instance,
            "farah",
            amendment.id,
            {"proposal": "Create an accountability with an explicit boundary"},
        )

        objector_confirmation = open_task(instance, "ben", "Task_ConfirmIntegration")
        self.engine.submit(
            instance,
            "ben",
            objector_confirmation.id,
            {"claim": "objectionResolved", "decision": "confirmed"},
        )
        proposer_confirmation = open_task(instance, "alice", "Task_ConfirmIntegration")
        self.engine.submit(
            instance,
            "alice",
            proposer_confirmation.id,
            {"claim": "tensionAddressed", "decision": "confirmed"},
        )

        self.assertEqual(
            instance.artifacts["proposal"].current_revision_id,
            "proposal-r2",
        )
        self.assertEqual(instance.current_node_id, "Task_IDMPObjectionRound")

        for user_id in ("alice", "ben", "cara"):
            task = open_task(instance, user_id, "Task_IDMPObjectionRound")
            self.engine.submit(
                instance,
                user_id,
                task.id,
                {"decision": "noObjection"},
            )

        self.assertEqual(instance.outcome, "adopted")
        self.assertEqual(instance.artifacts["proposal"].current_revision_id, "proposal-r2")


if __name__ == "__main__":
    unittest.main()
