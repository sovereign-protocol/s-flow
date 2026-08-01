# S-Flow — Sovereign Core integration

Status: application scaffold and first Core-backed topic implemented

Application identifiers:

- display name: `S-Flow`;
- application ID: `decision`;
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

Each process instance is one assignment-scoped shared topic. Provisional node
types, independent of the eventual product name:

- `workflow_process`: title, definition identifier/version and lifecycle;
- `workflow_assignment`: identity UUID, role and effective round;
- `workflow_round`: immutable participant set and artifact reference;
- `workflow_response`: participant-authored input for one round;
- `workflow_artifact_revision`: immutable proposal or candidate-list revision;
- `workflow_facilitator_decision`: recorded tie, objection-validity or
  transition decision;
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
   perspectives; the application derives round completion and facilitator
   work from those perspectives.

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
3. **Local projections done; peer reconciliation pending:** implement process
   and personal projections over local plus peer state.
4. **Initial slice done:** Core-backed agendas and participant assignment.
5. **Done:** expose facade API version 1 and add the Cockpit tile adapter.
6. Exercise two clients over the local relay and SFTP relay.
