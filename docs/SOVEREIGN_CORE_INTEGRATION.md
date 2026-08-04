# S-Flow — Sovereign Core integration

Status: application scaffold and first Core-backed topic implemented

Application identifiers:

- display name: `S-Flow`;
- application ID: `flow`;
- Python package: `s_flow`.

## Ownership

| Concern                           | Owner                           |
| --------------------------------- | ------------------------------- |
| Workflow semantics and validation | New application                 |
| Durable shared state              | Core `ProtocolNode` topic       |
| Local persistence                 | Core Session persistence        |
| SFTP relay and other transports   | Core channels                   |
| Identity and known people         | Core Session                    |
| Topic membership and liveness     | Core collaboration view         |
| Agenda items                      | Core Session agenda API         |
| Browser optimism and retries      | Core Session View               |
| Cockpit presentation              | S-Cockpit via app facade |

## Topic model

Each process instance is one assignment-scoped shared topic. Implemented node
types:

- `flow_process`: title, definition identifier/version and lifecycle;
- `flow_assignment`: identity UUID, role and effective round;
- `flow_runtime_state`: creator-owned serialized interpreter state;
- `flow_response`: immutable participant-authored workflow command;
- Core `agenda_item`: asynchronous agenda entry attached to the topic.

The app registers the root through `ApplicationRegistration`, mounts accepted
invitations, and lets Core assign the topic to its home channel.

## Concurrency

There are three separate cases:

1. A browser command uses a `mutation_id`; Core deduplicates retries and returns
   the confirmed Session revision.
2. Editing an existing node supplies its captured `content_hash`; a mismatch
   rejects the stale form.
3. Different people submit their own response nodes. Core preserves their peer
   perspectives. The process creator verifies peer identity, adopts each
   immutable response node and applies it once to the creator-owned runtime.
   Applicability is the still-open task, not equality with the whole-runtime
   hash, so parallel responses from the same round remain valid.

Going back is an application-level correction, not a Core reaction. Response
nodes remain append-only. The creator records the latest applied response as
retracted and rebuilds the runtime by replaying the remaining response UUIDs in
their original application order. A replacement response creates a new node.

The third case is not a normal database conflict. Automatically adopting every
peer subtree would erase the sovereign authorship model.

## People

“Who is involved” has two distinct views:

- assigned people: persisted `workflow_assignment` nodes;
- currently known/reachable people: `Session.known_identities()`,
  `Session.peer_addresses(topic_uuid)` and
  `collaboration.network_info(topic_uuid)`.

The interface should show both. Reachability must not silently change who is
required in an already-open round.

## Agenda

Use `Session.create_agenda_item`, `delete_agenda_item`,
`set_agenda_item_priority` and `move_agenda_item`. The workflow app only checks
that the item belongs to its process topic and exposes app-scoped routes.

## S-Cockpit

The workflow application exposes facade API version 1 with detached queries
and commands. At minimum:

- list process topics;
- return a tile summary;
- create/delete a process;
- create/edit/move agenda items.

The first tile shows title, process template, current stage, “required from
me”, outstanding people, agenda count and divergence/status. Expanded mode can
show the latest completed step and current work.

S-Cockpit currently has explicit Kanban and Agreement adapters. Adding
a third hard-coded branch is acceptable for the MVP, but it will not scale.
After this integration proves the common fields, extract a generic versioned
tile-provider contract rather than changing Cockpit for every future app.

## Implementation order

1. **Done:** scaffold the sibling application package and Core topic
   registration.
2. **Local perspective done:** replace the in-memory instance store with a
   Core-node adapter.
3. **Done for Minimal Consent:** process and personal projections over local
   plus peer-authored response state.
4. **Initial slice done:** Core-backed agendas and participant assignment.
5. **Done:** expose facade API version 1 and add the Cockpit tile adapter.
6. **Local relay done for Minimal Consent; SFTP pending:** exercise two clients
   through the production publication/poll/reconciliation path.
