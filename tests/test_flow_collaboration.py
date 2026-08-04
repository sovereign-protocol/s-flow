"""Two-client Minimal Consent execution over Core's real relay path."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sovereign import app_server

from s_flow.desktop import APPLICATION_ALIASES
from s_flow.workflow_adapter import (
    HANDLED_RESPONSE_IDS,
    RESPONSE_TYPE,
)


def relay_runtime(test: unittest.TestCase, port: int, relay_root: str):
    directory = tempfile.TemporaryDirectory()
    test.addCleanup(directory.cleanup)
    config = app_server.load_config(None, "flow", APPLICATION_ALIASES)
    config["storage_file"] = str(Path(directory.name) / f"{port}.json")
    config["relay_state_directory"] = str(Path(directory.name) / "relay")
    runtime = app_server.create_runtime(port, config)
    created = runtime.relay_manager.create_target({
        "name": f"relay {port}",
        "backend": "local",
        "root": relay_root,
    })
    if created.status != "ok":
        raise RuntimeError(created.reason)
    runtime.relay_target = created.value
    runtime.relay = runtime.relay_manager.connection_for_target(created.value)
    runtime.peer_addr = f"relay:{runtime.relay.identity}"
    return runtime


def sync(*runtimes) -> None:
    for _ in range(2):
        for runtime in runtimes:
            runtime.relay.write_presence()
            runtime.relay.publish_due_topics()
        for runtime in runtimes:
            runtime.relay.poll_and_apply()
            outcome = runtime.host.notify_peer_update()
            if outcome.effects:
                runtime.deliver_effects(outcome.effects)


def connect(host, guest, topic_uuid: str | None = None) -> dict:
    topic_uuids = [topic_uuid] if topic_uuid else []
    for uuid in topic_uuids:
        host.session.start_discussion(uuid)
        attached = host.mailbox_channel.attach_topics(
            [uuid], {"target_id": host.relay_target},
        )
        if not attached.ok:
            return {"status": "error", "reason": attached.reason}
    identity_uuid = host.session.identity.uuid
    invited_topics = topic_uuids or [identity_uuid]
    token = host.channel_manager.compose_token(invited_topics, {
        uuid: {
            "kind": "mailbox",
            "target_id": host.relay_target,
        }
        for uuid in {*invited_topics, identity_uuid}
    })
    if not token.ok:
        return {"status": "error", "reason": token.reason}
    accepted = guest.channel_manager.accept_token(token.value)
    if not accepted.ok:
        return {"status": "error", "reason": accepted.reason}
    sync(host, guest)
    return accepted.value


def only_task(runtime, process_uuid: str) -> dict:
    tasks = runtime.logic.process_payload(process_uuid)["workflow"]["personal"][
        "tasks"
    ]
    if len(tasks) != 1:
        raise AssertionError(f"expected one task, got {tasks!r}")
    return tasks[0]


class MinimalConsentCollaborationTests(unittest.TestCase):
    def setUp(self):
        relay = tempfile.TemporaryDirectory()
        self.addCleanup(relay.cleanup)
        self.host = relay_runtime(self, 9361, relay.name)
        self.guest = relay_runtime(self, 9362, relay.name)

    def test_two_clients_converge_after_parallel_consent(self):
        created = self.host.logic.create_process(
            "Adopt policy", "minimal-consent", "0.2.0",
        )
        self.assertEqual(created.status, "ok")
        process_uuid = created.value

        self.assertEqual(connect(self.host, self.guest)["status"], "ok")
        self.assertEqual(
            connect(self.host, self.guest, process_uuid)["status"], "ok",
        )
        assigned = self.host.logic.set_assignment(
            process_uuid,
            self.guest.session.identity.uuid,
            "requiredParticipant",
            True,
        )
        self.assertEqual(assigned.status, "ok")
        self.assertEqual(self.host.logic.start_process(process_uuid).status, "ok")
        sync(self.host, self.guest)

        proposal_task = only_task(self.host, process_uuid)
        proposal_state = self.host.logic.process_payload(process_uuid)["workflow"]
        self.assertEqual(
            self.host.logic.submit_task(
                process_uuid,
                proposal_task["id"],
                {"proposal": "Adopt policy A"},
                proposal_state["runtime_content_hash"],
            ).status,
            "ok",
        )
        sync(self.host, self.guest)

        host_state = self.host.logic.process_payload(process_uuid)["workflow"]
        guest_state = self.guest.logic.process_payload(process_uuid)["workflow"]
        host_task = host_state["personal"]["tasks"][0]
        guest_task = guest_state["personal"]["tasks"][0]
        shared_round_hash = guest_state["runtime_content_hash"]

        self.assertEqual(
            self.host.logic.submit_task(
                process_uuid,
                host_task["id"],
                {"decision": "consent"},
                host_state["runtime_content_hash"],
            ).status,
            "ok",
        )
        submitted = self.guest.logic.submit_task(
            process_uuid,
            guest_task["id"],
            {"decision": "consent"},
            shared_round_hash,
        )
        self.assertEqual(submitted.status, "ok")

        pending = self.guest.logic.process_payload(process_uuid)["workflow"]
        self.assertEqual(pending["runtime_content_hash"], shared_round_hash)
        self.assertEqual(pending["personal"]["tasks"], [])
        self.assertEqual(
            pending["personal"]["waiting_reason"]["type"],
            "responsePending",
        )

        sync(self.host, self.guest)

        host_final = self.host.logic.process_payload(process_uuid)["workflow"]
        guest_final = self.guest.logic.process_payload(process_uuid)["workflow"]
        self.assertEqual(host_final["outcome"], "adopted")
        self.assertEqual(guest_final["outcome"], "adopted")
        self.assertEqual(
            host_final["artifacts"]["proposal"]["revisions"][0]["content"],
            {"proposal": "Adopt policy A"},
        )

        host_process = self.host.session.protocol.index[process_uuid]
        guest_responses = [
            child for child in host_process.live_children()
            if child.data.get("type") == RESPONSE_TYPE
            and child.data.get("identity_uuid") == self.guest.session.identity.uuid
        ]
        self.assertEqual(len(guest_responses), 1)
        instance = self.host.logic.workflow.load(host_process)
        self.assertIn(
            guest_responses[0].uuid,
            instance.data[HANDLED_RESPONSE_IDS],
        )

        returned = self.host.logic.go_back(process_uuid)
        self.assertEqual(returned.status, "ok")
        self.assertEqual(returned.value, guest_responses[0].uuid)
        sync(self.host, self.guest)
        reopened = self.guest.logic.process_payload(process_uuid)["workflow"]
        self.assertEqual(reopened["outcome"], None)
        self.assertEqual(
            reopened["personal"]["tasks"][0]["nodeId"],
            "Task_ConsentRound",
        )
        replacement = self.guest.logic.submit_task(
            process_uuid,
            reopened["personal"]["tasks"][0]["id"],
            {"decision": "consent"},
            reopened["runtime_content_hash"],
        )
        self.assertEqual(replacement.status, "ok")
        sync(self.host, self.guest)
        self.assertEqual(
            self.guest.logic.process_payload(process_uuid)["workflow"]["outcome"],
            "adopted",
        )

    def test_peer_process_modification_is_explained_and_reactable(self):
        created = self.host.logic.create_process(
            "Original title", "minimal-consent", "0.2.0",
        )
        process_uuid = created.value
        self.assertEqual(connect(self.host, self.guest)["status"], "ok")
        self.assertEqual(
            connect(self.host, self.guest, process_uuid)["status"], "ok",
        )

        changed = self.guest.logic.rename_process(
            process_uuid, "Suggested title",
        )
        self.assertEqual(changed.status, "ok")
        sync(self.host, self.guest)

        payload = self.host.logic.process_payload(process_uuid)
        transition = payload["transition_by_node"][process_uuid]
        self.assertEqual(transition["stage"], "awaiting_me")
        self.assertEqual(transition["reaction"], "adopt")
        self.assertEqual(
            transition["changes"][0]["authored_detail"],
            "title",
        )
        self.assertEqual(
            self.host.session.protocol.index[process_uuid].data["title"],
            "Original title",
        )

        adopted = self.host.logic.accept_peer_node(
            self.guest.peer_addr, process_uuid,
        )
        self.assertEqual(adopted.status, "ok")
        self.assertEqual(
            self.host.session.protocol.index[process_uuid].data["title"],
            "Suggested title",
        )

    def test_return_to_setup_converges_and_invitee_can_leave(self):
        process_uuid = self.host.logic.create_process(
            "Adjust participants", "minimal-consent", "0.2.0",
        ).value
        self.assertEqual(connect(self.host, self.guest)["status"], "ok")
        self.assertEqual(
            connect(self.host, self.guest, process_uuid)["status"], "ok",
        )
        self.assertEqual(
            self.host.logic.set_assignment(
                process_uuid,
                self.guest.session.identity.uuid,
                "requiredParticipant",
                True,
            ).status,
            "ok",
        )
        self.assertEqual(self.host.logic.start_process(process_uuid).status, "ok")
        sync(self.host, self.guest)

        returned = self.host.logic.return_to_setup(process_uuid)
        self.assertEqual(returned.status, "ok")
        sync(self.host, self.guest)

        host_payload = self.host.logic.process_payload(process_uuid)
        guest_payload = self.guest.logic.process_payload(process_uuid)
        self.assertEqual(host_payload["process"]["data"]["lifecycle"], "setup")
        self.assertEqual(guest_payload["process"]["data"]["lifecycle"], "setup")
        self.assertEqual(
            guest_payload["workflow"]["position"]["current_stages"][0]["id"],
            "setup",
        )
        self.assertTrue(host_payload["processes"][0]["can_delete"])
        self.assertTrue(guest_payload["processes"][0]["can_leave"])

        left = self.guest.logic.leave_process(process_uuid)
        self.assertEqual(left.status, "ok")
        self.guest.deliver_effects(left.effects)
        sync(self.host, self.guest)
        self.assertEqual(self.guest.logic.processes(), [])
        self.assertEqual(len(self.host.logic.processes()), 1)


if __name__ == "__main__":
    unittest.main()
