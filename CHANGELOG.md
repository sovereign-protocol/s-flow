# Changelog

## Unreleased

- **A flow is called a Flow.** The bar's label was "Process", which is the
  internal type name; the noun a person meets is the one the application is
  named for. The application mark is a chain of stages: the square and
  checkmark it replaces read as a checklist rather than as something that
  moves through them. See Core's `DESIGN_VOCABULARY.md` and
  `DESIGN_UI_CONSISTENCY.md` U8.

- **S-Flow says how a process is made.** Its registration carries the noun,
  the bundled workflows, the rule that one is required, and a `make_process`
  that looks a workflow's version up from its id — so a caller elsewhere no
  longer carries a version alongside a template, which was a copy of this
  application's catalogue kept in three other places.

- **The bar names this process and lists no others.** Reaching another one is
  the Cockpit's, which holds every topic this client has rather than one
  application's share of them. A deep link is `?topic=<uuid>` now, the one
  name every application answers to.

- **Leaving a shared flow no longer writes a deletion.** It took the creator's
  own path — end sharing, then delete — and was correct only by arithmetic: the
  tombstone did not travel because the peer set had just been emptied, and it
  was pruned locally for the same reason. Nothing about the intent said so, and
  releasing the channels is an effect the runtime delivers afterwards, so a
  poll landing in between had a tombstone to publish. Leaving is Core's
  `drop_topic` now, which writes no deletion at all: the others see this client
  stop publishing, and a peer who still runs the flow offers it back as an
  invitation. Deleting is unchanged and remains the creator's alone.

- Process topics now publish declared adoption metadata to Core: every held
  process, assignment and runtime-state node names the process owner's identity
  key as its author, so Core refuses a revision of those from anyone else.
  Responses stay unconstrained. The eligibility callback is gone: a node this
  client does not yet hold is classified at first sight instead — a response is
  anyone's, a process, assignment or runtime-state node is the owner's, and
  anything else has no business in the topic.

- Agenda items and counts now derive from verified perspectives without
  adopting peer records into the local Flow topic. The staleness window is
  Core's default rather than a Flow declaration; the unused
  `agenda_perspective_*` configuration keys are gone.

- Added a facade-level Integrative Election command that atomically configures
  the frozen required-participant snapshot, counterpart facilitator, eligible
  candidates, and starts the process. Consumers never manipulate Flow runtime
  or assignment nodes directly.
- Added the versioned `s-flow.decision-result` facade contract. It exposes a
  process's definition, lifecycle, terminal outcome, selected candidate,
  frozen participant assignments, facilitator, and canonical SHA-256 result
  hash without exposing S-Flow's runtime-node layout.

Nothing has been published from this repository yet. The entries below are
what a first release would carry.

- Exposed the bundled workflow template catalog through the public facade so
  S-Cockpit can offer template-aware Flow creation without duplicating IDs.
- Persisted a Flow selected through a Cockpit link so background polling no
  longer switches the page back to the previously selected Flow.
- Flow creators can return an active workflow to participant setup. Responses
  from the previous run stay immutable but are excluded from the new run.
- Flow creators can delete their local copy of a shared Flow; invitees can
  leave it locally. Other participants keep their copies.

- Added a two-client Minimal Consent slice: participant setup, start, proposal,
  consent/objection input, pending-response state, outcome and process history.
- Peer-authored `flow_response` nodes are identity-checked, adopted and applied
  once to the creator-owned runtime. Parallel round responses remain valid
  after another response advances the runtime hash.
- Added Core transition explanations and adopt/rollback reactions for process
  and participant-assignment differences, using the shared S-Initiative UI
  pattern.
- Fixed the example configuration's stale `decision` primary application ID.
- Polling no longer replaces a form while the user is typing or choosing a
  participant.
- Replaced raw JSON response entry with a small JSON-Schema form interpreter
  that renders named fields, choices, required markers and short guidance.
- Added workflow-level “Go back”: the creator retracts the latest immutable
  response, the runtime deterministically replays earlier responses, and the
  appropriate input is reopened. This is intentionally not Core node rollback.

- Updated Integrative Election: one participant row with role badges; parallel
  nomination, nomination-change and objection rounds; nomination and reason in
  one response; definition-driven deferred publication; readable status and
  history; and automatic objection context for the facilitator validity task.

- Renamed from S-decision to **S-Flow**, to be distributed as
  `sovereign-flow`. The application id is now `flow`, routes are served under
  `/api/flow/`, and the Python package is `s_flow`. Node types moved with it —
  `flow_process`, `flow_assignment`, `flow_runtime_state`, `flow_response` —
  because "decision" no longer names the application. The BPMN vocabulary is
  untouched: `integrative-decision-making`, `decisionWithdraw`,
  `Gateway_ProposerDecision` and the rest name decisions taken *inside* a
  process, which is domain language that survives the rename.
- The name follows the scope. The runtime is a general BPMN-subset
  interpreter; consent-based decision processes are its first definitions
  rather than its subject, and a decision belongs to whichever domain takes
  it rather than to one application.
- Added the Apache-2.0 `LICENSE`, `LICENSES/CC-BY-4.0.txt` for documentation,
  and `license-files` naming all three. The wheel previously carried only
  `NOTICE`, picked up by setuptools' default globs because no licence text
  existed to name.
- Added CI and Publish workflows, which this repository had never had. CI runs
  the suite on 3.10 and 3.14; a separate job validates the bundled BPMN
  definitions with `lxml` installed, because the validator soft-skips when it
  is absent and would otherwise report success without checking anything.

- **Fixed: the page never rendered a process.** Core's `shared.js` assigned
  `onclick` to `confirmModalCancelBtn` at the top level; this page has no
  confirm modal, so the script died before defining `SovereignShell`, which
  `refresh()` calls before its own empty-state guard. Fixed in Core 0.1.7,
  which this release now requires.
- **Mount the shared shell.** The page called `setTopicSelector` but never
  `SovereignShell.mount(...)`, and that call returns silently when the header
  does not exist — so the process picker, sharing state, profile and
  collaboration pane were all absent rather than broken. Mounting happens
  before the first refresh for the same reason. The shell's agenda pane is
  wired to this application's `/api/flow/agenda/*` routes, keyed on
  `process_uuid`.
- **Refresh the shell on every load.** Header state — divergences, sharing,
  agenda, sibling alarms — is derived from `state()` and recomputed only when
  asked, so without a `SovereignShell.refresh()` call the Collaboration
  control stayed disabled at "Select a topic first" no matter what was
  selected.
