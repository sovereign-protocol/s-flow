# Consent Workflow Profile 0.2

Status: second design draft

## 1. Purpose

This profile defines the smallest reusable workflow model needed for
consent-based and view-gathering processes. Its first reference process is an
Integrative Election.

The profile reuses BPMN 2.0 control-flow concepts and adds a small vocabulary
for collaborative human rounds. It is not a new general-purpose programming
language.

## 2. Scope

Version 0.2 supports:

- fully asynchronous collaboration;
- Sovereign Core topics, identity, persistence and configured channels;
- facilitator-controlled and automatically advancing stages;
- required and optional participant roles;
- individual responses collected in rounds;
- sequential or parallel rounds;
- deferred or immediate publication of responses;
- scheduled waits;
- asynchronous discussion attached to process items;
- versioned process artifacts;
- controlled question-and-answer interactions;
- dynamically created work items;
- facilitator-managed work queues;
- multi-party confirmation gates;
- proposal lifecycles;
- structured response validation;
- deterministic aggregation;
- conditional branches and loops;
- recorded facilitator decisions;
- successful and unsuccessful terminal outcomes.

Version 0.2 does not support:

- arbitrary scripts in workflow definitions;
- cryptographic secrecy or anonymous voting;
- automatic evaluation of the substance of objections;
- automatic removal of non-responsive participants;
- changing a workflow definition while an instance is running.

This is a trusted-space model. Deferred publication controls when responses
appear in the normal process. It is not a privacy or confidentiality guarantee.

## 3. BPMN subset

| Profile concept | BPMN 2.0 concept |
| --- | --- |
| Process beginning | Start event |
| Human action | User task |
| Participant round | Multi-instance user task |
| Automated calculation | Business-rule or service task |
| Facilitated group phase | Subprocess |
| Conditional branch | Exclusive gateway |
| Repeated phase | Loop or sequence flow |
| Wait until a scheduled time | Intermediate timer catch event |
| Inform users without blocking progress | Message event |
| Successful or void result | Named end event |
| Process information | Data object |
| Facilitator and participants | Lanes and resource assignments |

The initial implementation needs only this subset. Other BPMN elements are not
part of the profile until a concrete process requires them.

## 4. Core definition model

A workflow definition contains:

- `id`: stable identifier;
- `version`: immutable definition version;
- `roles`: available process roles;
- `data`: process-level data definitions;
- `artifacts`: versioned objects governed by the process;
- `activities`: tasks, rounds, calculations and facilitator decisions;
- `transitions`: allowed movement between activities;
- `outcomes`: terminal results.

A workflow instance contains:

- the exact workflow definition identifier and version;
- assigned facilitator and participants;
- the current activity or activities;
- immutable round instances;
- immutable artifact revisions;
- responses and facilitator decisions;
- asynchronous discussion records;
- calculated results;
- an append-only process event record;
- the final outcome, when reached.

### 4.1 Production application boundary

The production implementation is a new Sovereign application alongside
S-Kanban and S-Agreement. It does not own a database, SFTP integration, a
participant directory, browser retry queues or a second concurrency system.

- Each workflow instance is an assignment-scoped Core topic.
- Core `ProtocolNode` trees hold its durable, shareable state.
- `ApplicationServices.mutation_response` supplies confirmed revisions,
  retry-safe mutation IDs and persistence.
- Expected node `content_hash` values protect editable forms from lost updates.
- Peer-authored responses remain peer perspectives until the workflow rules
  reconcile them; concurrent views are not silently overwritten.
- Core channels publish and poll the topic, including an SFTP relay.
- `Session.known_identities()` and topic-scoped peer membership supply the
  available people; explicit role assignments remain workflow data.
- Core agenda items are children of the workflow topic.
- A versioned application facade supplies workflow summaries and commands to
  Personal Cockpit, which renders one tile per workflow instance.

The in-memory runtime remains a definition interpreter and test oracle. It
must be adapted to read and emit Core nodes rather than becoming a parallel
storage or synchronization layer.

## 5. Roles

The profile defines these reusable role types:

- `facilitator`: controls designated transitions and records judgments made
  outside the application;
- `requiredParticipant`: must respond before an all-required round completes;
- `optionalParticipant`: may respond but cannot block completion;
- `observer`: may view published process information but cannot act.

Candidate is process data, not a role. A candidate may also hold any process
role, including required participant.

Participant membership is frozen when a round opens. Adding or removing
participants affects only later rounds and must be recorded explicitly. The
Integrative Election template does not permit membership changes during an
election.

## 6. Asynchronous interaction and user projection

No workflow activity requires participants to be online simultaneously. Inputs,
discussion messages and facilitator decisions are durable records that may be
provided at different times.

The interface presents two independent projections to every user.

### 6.1 Process position

The process-position projection contains at least:

- `lastCompletedStage`: the most recently completed major workflow stage, its
  result and completion time;
- `currentStages`: the active major stage or stages and their opening time;
- `recentActivity`: optional recent nested work such as a question answer or
  objection decision.

Completing a nested work item updates `recentActivity`; it does not replace
`lastCompletedStage`. Stage boundaries are defined by the workflow template.

For a scheduled wait, `currentStages` includes the absolute continuation time.
For a participant round, it includes progress without exposing unpublished
response content.

### 6.2 Personal requirement

The personal projection contains:

- `primaryState`: one of the three states below;
- `tasks`: zero or more concrete actions currently available to the user;
- `waitingReason`: present when the primary state is `waiting`;
- `informationItems`: newly published information relevant to the user.

| State | Meaning |
| --- | --- |
| `inputRequired` | The user must provide a response or decision |
| `waiting` | The user has no current action and progress depends on something else |
| `information` | New process information is available; no response is required |

`waitingReason` contains:

- `type`: `responses`, `actorTask`, `scheduledTime`, `priorTurn`, or
  `processTransition`;
- `dependencies`: concrete participant, role, task or event references;
- `until`: an absolute time when the dependency is time-based.

Examples include waiting for named participants' responses, a facilitator
decision, a proposer amendment, the prior participant's turn, a scheduled
time, or an automated calculation.

When a user submits their response in a parallel all-participant round, their
state changes from `inputRequired` to `waiting`, with the missing responses as
dependencies, until the round completes.

If several tasks are available, `primaryState` remains `inputRequired` and all
tasks are shown. Completing one task does not hide the others.

Primary-state priority is `inputRequired`, then `information`, then `waiting`.
An information item may coexist with tasks or a waiting dependency.

Information delivery does not block the workflow. If explicit acknowledgment
is required, it is modelled as an input task rather than an information item.

These projections are derived from the authoritative workflow state and event
record. They are not independently editable status fields.

### 6.3 Asynchronous discussion

A process item may own a durable discussion thread. Messages record author,
time and the item or decision they address. Participation may be required or
optional.

Closing a discussion is a separate facilitator action. The application hosts
and records the discussion but does not determine the quality, truth or
validity of its contents.

## 7. Collaborative human round

A collaborative round extends a BPMN multi-instance user task with:

| Property | Meaning |
| --- | --- |
| `audience` | Role whose members receive the task |
| `participation` | `all`, `optional`, or a defined threshold |
| `ordering` | `parallel` or `sequential` |
| `publication` | `immediate` or `onRoundComplete` |
| `responseSchema` | JSON Schema for one response |
| `completionRule` | Condition that closes the round |
| `participantSnapshot` | Members required for this round |
| `revision` | Whether a submitted response can be replaced before closure |

For `participation: all`, each member in `participantSnapshot` must submit
exactly one current response. No timeout silently changes this rule.

In a sequential round, the participant order is frozen when the round opens.
Only the current participant receives `inputRequired`; later participants see
`waiting` with the prior turn as dependency. Sequential describes activation
order, not synchronous presence.

`publication: onRoundComplete` means responses are not shown through the normal
workflow interface until the completion rule is satisfied. It does not imply
confidential storage.

## 8. Reusable deliberation primitives

### 8.1 Versioned artifact

A decision process may govern an artifact such as a proposal.

The artifact record contains:

- `artifactId`: stable identity across revisions;
- `currentRevisionId`;
- `lifecycleState`.

Each immutable revision contains:

- `revisionId`;
- `artifactId`;
- `supersedes`: previous revision, when present;
- `content`: typed artifact content;
- `createdBy` and `createdAt`.

Amending an artifact creates a new revision. It never replaces the previous
revision. Every question, reaction, objection, consent and confirmation
references the exact `revisionId` it addresses.

The standard proposal lifecycle is:

```text
draft → proposed → underReview → adopted
                          └────→ withdrawn
```

Lifecycle changes are append-only events and do not mutate revisions.
`withdrawn` is reachable from any non-terminal state. Workflow templates may
omit states, but may not change the meaning of `adopted` or `withdrawn`.

### 8.2 Controlled interaction

A controlled interaction defines:

- who may create an item;
- who may respond;
- whether responses may themselves receive replies;
- whether an explicit `pass` or `done` response is required;
- who may close the interaction;
- the closure condition.

Version 0.2 provides:

- `questionAnswer`: permitted users create questions; designated responders
  answer or explicitly decline;
- `statementRound`: each audience member submits a statement or pass; replies
  are disabled;
- `discussion`: permitted users may contribute messages until the designated
  closer ends it.

These policies are enforced by the application, not merely presented as
facilitation guidance.

### 8.3 Dynamic work collection

Questions, objections and similar items are not known when the workflow starts.
A dynamic work collection creates a durable work item for each submitted item.
Each work item has:

- identity, type and author;
- `sourceRevisionId`: the revision that caused the item;
- `applicableRevisionId`: the newest revision against which it was confirmed
  still applicable;
- lifecycle state;
- zero or more assigned tasks;
- optional discussion;
- resolution record.

The collection closes only when item creation has ended and every required work
item has reached a permitted terminal state.

### 8.4 Managed work queue

A managed work queue processes dynamic work items one at a time. Its order may
be submission order or facilitator-controlled. Non-current items remain visible
but inactive.

The current item's assignees receive `inputRequired`. Other participants receive
`waiting` on the current queue task or an information item, depending on the
template.

### 8.5 Confirmation gate

A confirmation gate names the parties whose confirmation is required and the
claim each confirms. It completes only when all required confirmations are
positive for the same applicable artifact revision.

A negative or withdrawn confirmation keeps the related work item open. Any new
artifact revision invalidates confirmations made against an earlier revision
unless the workflow explicitly preserves them.

## 9. Automated calculation

Calculations use named, versioned operations implemented by the application.
Workflow authors select an operation and its inputs; they cannot insert
arbitrary code.

Version 0.2 requires:

- `pluralityRanking`: count current nominations and order candidates by count;
- `topTie`: return all candidates sharing the highest count;
- `anyValidObjection`: test whether at least one recorded objection is valid;
- `availableCandidates`: return candidates that are eligible and not excluded.

Every calculation records its operation version, inputs and output so its
result can be reproduced.

## 10. Candidate eligibility

An election selects one of two eligibility modes.

### 10.1 Closed eligibility

- The election begins with a finite list of eligible candidate identifiers.
- Nominations must reference that list.
- If all listed candidates are excluded, the election automatically ends as
  void.

### 10.2 Open eligibility

- A participant may introduce a person not yet present in the election.
- The facilitator records that the person satisfies the configured eligibility
  rule before the nomination becomes valid.
- The application cannot infer that no possible candidate remains.
- Only the facilitator can declare the election void.

Candidates use stable person identifiers rather than names. Display names are
labels and are not used when counting nominations.

An excluded candidate remains excluded for the complete election instance.

## 11. Reference template: Integrative Election

### 11.1 Process data

- role title and optional description;
- eligibility mode and eligibility rule;
- facilitator;
- fixed participant list;
- candidates introduced or listed;
- current nomination for every participant;
- nomination round number;
- excluded candidates;
- current ranking;
- proposed candidate;
- objections, asynchronous discussion and facilitator validity decisions;
- final outcome.

### 11.2 Activities

| ID | Activity | Actor and rule |
| --- | --- | --- |
| `presentRole` | Present the role when a description is needed | Facilitator |
| `nominate` | Select one eligible candidate; abstention is invalid | All participants, parallel, publish on completion |
| `shareReasons` | State why the nominee is a good fit | All participants, sequential |
| `changeNominations` | Explicitly keep or change the current nomination | All participants, sequential |
| `calculateRanking` | Apply `pluralityRanking` | Application |
| `resolveTie` | Select a tied candidate or repeat nomination change | Facilitator |
| `proposeCandidate` | Record the selected candidate as the proposal | Application |
| `objectionRound` | Submit no objection or a reasoned objection | All participants, sequential |
| `discussObjection` | Discuss each submitted objection asynchronously | Participants and facilitator |
| `recordValidity` | Record valid or invalid for every objection | Facilitator |
| `excludeCandidate` | Permanently exclude the proposed candidate | Application |
| `declareVoid` | End an open-eligibility election without a result | Facilitator |

### 11.3 Flow

1. Start the election and freeze the participant list.
2. Present the role if required.
3. Open the nomination round.
4. Wait until every participant has nominated exactly one eligible candidate.
5. Publish all nominations.
6. Complete the sequential sharing round.
7. Complete a nomination-change round. Every participant explicitly records
   `keep` or `change`; a change requires a candidate and explanation.
8. Calculate the plurality ranking.
9. If there is one top-ranked candidate, propose that candidate.
10. If there is a top tie, the facilitator either:
    - proposes one of the tied candidates; or
    - starts another nomination-change round.
11. Ask every participant for `noObjection` or `objection`.
12. Each submitted objection receives an asynchronous discussion thread.
13. The facilitator closes each discussion and records the validity of its
    objection. The application does not determine validity.
14. If no objection is valid, end with `elected`.
15. If at least one objection is valid:
    - exclude the proposed candidate once;
    - retain all objection and validity records;
    - in closed mode, end with `void` if no candidate remains;
    - otherwise start a new nomination-change round.
16. In open mode, the facilitator may declare the election void at the
    candidate-availability checkpoint.

### 11.4 Response shapes

Initial nomination:

```json
{
  "candidateId": "person-identifier"
}
```

Sharing:

```json
{
  "statement": "Why this person is a good fit"
}
```

Nomination change:

```json
{
  "decision": "keep"
}
```

or:

```json
{
  "decision": "change",
  "candidateId": "person-identifier",
  "reason": "Reason for changing the nomination"
}
```

Objection:

```json
{
  "decision": "objection",
  "statement": "Reasoned objection"
}
```

or:

```json
{
  "decision": "noObjection"
}
```

Facilitator validity record:

```json
{
  "objectionId": "objection-identifier",
  "decision": "valid",
  "note": "Optional record of the facilitated decision"
}
```

### 11.5 Outcomes

`elected` contains:

- elected candidate;
- final ranking;
- complete nomination-round history;
- objections and facilitator decisions;
- facilitator and participant identities;
- completion time.

`void` contains:

- eligibility mode;
- reason recorded by the process or facilitator;
- excluded candidates;
- complete process history;
- completion time.

### 11.6 User projection checkpoints

| Current activity | Acting user | Other users |
| --- | --- | --- |
| Nomination | `inputRequired`, then `WAIT(missing responses)` | Same |
| Sequential sharing, change or objection | Current participant: `inputRequired` | `WAIT(prior turn)` |
| Tie resolution | Facilitator: `inputRequired` | `WAIT(facilitator decision)` |
| Objection validity | Facilitator: `inputRequired` | `WAIT(facilitator decision)` |
| Ranking calculation | None | `WAIT(process transition)` |
| Candidate proposed, excluded, elected or void | Relevant information item | Relevant information item |

## 12. Reference template: Integrative Decision-Making

This template implements the Integrative Decision-Making Process used in
Holacracy. Its collaboration is asynchronous while preserving the process's
stage order and contribution restrictions.

This document uses `IDMP`; current Holacracy material commonly abbreviates the
process as `IDM`.

### 12.1 Roles and process data

Roles:

- `facilitator`;
- `proposer`;
- `requiredParticipant`, including the proposer;
- optional `observer`.

Process data:

- the proposer's tension;
- a versioned proposal artifact;
- fixed participant list;
- clarifying-question collection;
- reactions;
- potential objections and validity decisions;
- valid-objection integration queue;
- confirmations and final outcome.

### 12.2 Activities

| ID | Activity | Actor and rule |
| --- | --- | --- |
| `presentProposal` | Describe the tension and submit proposal revision 1 | Proposer |
| `clarifyingQuestions` | Ask questions; proposer answers or declines | Participants except proposer; controlled Q&A |
| `reactionRound` | React to the proposal or pass; no replies | Participants except proposer; sequential |
| `optionToClarify` | Continue, clarify or amend the proposal | Proposer |
| `objectionRound` | Record no objection or a potential objection | All participants; sequential |
| `testObjections` | Test and record validity without general discussion | Facilitator and each objector |
| `integrationQueue` | Process valid objections one at a time | Facilitator-managed queue |
| `integrateObjection` | Develop an amendment asynchronously | All may contribute |
| `confirmIntegration` | Confirm the amendment resolves the objection and still addresses the tension | Objector and proposer |
| `adoptProposal` | Adopt the current proposal revision | Application |
| `withdrawProposal` | End without adoption | Proposer |

### 12.3 Flow

1. Freeze the participant list.
2. The proposer records the tension and submits proposal revision 1.
3. Open clarifying questions against the current revision.
4. Each non-proposer either submits questions or marks themselves done.
5. The proposer answers or explicitly declines every question.
6. When all participants are done and all questions are resolved, the
   facilitator closes clarifying questions.
7. Run a sequential reaction round for every participant except the proposer.
   Each submits a reaction or explicit pass. Replies are prohibited.
8. The proposer selects:
   - `continue`;
   - `clarify`, adding a statement without changing the proposal; or
   - `amend`, creating a new proposal revision.
9. Run a sequential objection round against the current revision. Every
   participant submits `noObjection` or a potential objection.
10. The facilitator processes each potential objection with a restricted
    facilitator-objector interaction and records `valid`, `invalid` or
    `withdrawn`.
11. If no valid objections remain, adopt the current proposal revision.
12. Otherwise, place valid objections in a facilitator-managed integration
    queue.
13. For the current objection:
    - open an asynchronous integration discussion;
    - allow a candidate amendment;
    - create a new proposal revision for an accepted candidate amendment;
    - require the objector to confirm that the objection no longer triggers;
    - require the proposer to confirm that the revision still addresses the
      original tension.
14. When both confirmations address the same current revision, resolve the
    objection and move to the next queued objection.
15. After an amendment, each remaining objector confirms whether their queued
    objection still applies to the current revision. A no-longer-applicable
    objection is recorded as withdrawn.
16. Once the queue is empty, repeat the objection round against the newest
    proposal revision.
17. The proposer may withdraw the proposal before adoption.

### 12.4 Interaction restrictions

- Clarifying questions may seek information only. Only the proposer answers,
  and the answer may be an explicit decline.
- Reactions address the proposal, not other reactions. Replies are disabled.
- Potential-objection testing permits only facilitator and objector input.
- Integration permits contributions from all participants, but the objector
  and proposer own the required confirmations.
- Reactions and objections always retain the revision they originally
  addressed.

### 12.5 Response contracts

| Activity | Required response |
| --- | --- |
| Present proposal | Tension text and proposal content |
| Clarifying questions | `question` with text, or participant `done` |
| Question response | `answer` with text, or `decline` |
| Reaction | `reaction` with text, or `pass` |
| Option to clarify | `continue`, `clarify` with text, or `amend` with proposal content |
| Objection round | `noObjection`, or `objection` with statement |
| Objection test | `valid`, `invalid`, or `withdrawn`, with optional note |
| Integration confirmation | `confirmed` or `notConfirmed`, with optional note |
| Withdrawal | `withdraw`, with optional reason |

Conditional fields are enforced through each activity's JSON Schema.

### 12.6 User projection checkpoints

| Current activity | Acting user | Other users |
| --- | --- | --- |
| Present proposal | Proposer: `inputRequired` | `WAIT(proposer task)` |
| Clarifying questions | Participants: ask or mark done; proposer: answer tasks | Facilitator observes open work |
| Reaction round | Current non-proposer: `inputRequired` | `WAIT(prior turn)`; proposer waits |
| Option to clarify | Proposer: `inputRequired` | `WAIT(proposer task)` |
| Objection round | Current participant: `inputRequired` | `WAIT(prior turn)` |
| Test objections | Facilitator and current objector: task list | Others: `WAIT(facilitator task)` |
| Integration | Current objector and proposer: tasks; facilitator manages | Others: information or optional discussion |
| Adopted or withdrawn | Information item | Information item |

### 12.7 Outcomes

`adopted` references the exact adopted proposal revision and complete process
history.

`withdrawn` references the latest proposal revision, proposer, reason when
provided, and complete process history.

## 13. Reference template: Minimal Consent Decision

This template provides the smallest decision process in which every required
participant must consent to the same proposal revision.

### 13.1 Roles and process data

Roles:

- `proposer`;
- `requiredParticipant`, normally including the proposer;
- optional `observer`.

A facilitator may administer the process but makes no substantive decision.

Process data:

- versioned proposal artifact;
- fixed participant list;
- consent rounds;
- objections;
- final outcome.

### 13.2 Activities and flow

1. Freeze the participant list.
2. The proposer submits proposal revision 1.
3. Open a parallel all-participant consent round against that revision.
4. Every participant submits exactly one of:
   - `consent`;
   - `objection` with a required statement.
5. After submitting, each participant waits for the others.
6. If all responses are `consent`, adopt that exact revision automatically.
7. If any objection exists, publish the objections and assign the proposer one
   task:
   - amend the proposal, creating a new revision; or
   - withdraw the proposal.
8. Optional asynchronous discussion remains available while the proposer
   decides, but does not itself complete the stage.
9. After amendment, repeat the complete consent round against the new revision.
   Prior consent never carries forward automatically.

There is no objection-validity judgment and no separate confirmation gate. An
objector confirms that a concern is resolved by consenting in a later round.

### 13.3 Response contracts

Consent response:

- `consent`; or
- `objection` with a required statement.

Proposer response after objections:

- `amend` with new proposal content; or
- `withdraw` with an optional reason.

Each contract is represented by JSON Schema and references the active proposal
revision.

### 13.4 User projection checkpoints

| Current activity | Acting user | Other users |
| --- | --- | --- |
| Create or amend proposal | Proposer: `inputRequired` | `WAIT(proposer task)` |
| Consent round before response | Participant: `inputRequired` | Same |
| Consent round after response | Participant: `WAIT(missing responses)` | Pending participants still act |
| Objections published | Proposer: amend or withdraw task | Others: `WAIT(proposer task)` plus information |
| Adopted or withdrawn | Information item | Information item |

### 13.5 Outcomes

- `adopted`: exact unanimously consented proposal revision and all responses;
- `withdrawn`: latest revision and complete consent-round history.

## 14. Required invariants

### 14.1 All workflows

An implementation must enforce:

- no round completion while a required participant lacks a response;
- no workflow task requires simultaneous presence;
- immutable workflow definitions within a running instance;
- immutable artifact revisions linked through `supersedes`;
- every artifact-related input references an exact revision;
- a dynamic item's `sourceRevisionId` never changes;
- a confirmation gate uses confirmations against the same applicable revision;
- every facilitator decision records its actor and time;
- every personal requirement is derivable from authoritative workflow state;
- nested work completion cannot replace the last completed major stage;
- scheduled waits use an absolute time and recorded time zone;
- every terminal instance has exactly one outcome.

### 14.2 Integrative Election

- There is one current nomination per participant.
- Abstention is invalid.
- An excluded or ineligible candidate cannot be nominated.
- `keep` is invalid when the participant's current nominee has been excluded.
- Initial nominations are not published before their round closes.
- A changed nomination requires an explanation.
- Only a top-ranked candidate may be proposed automatically.
- A facilitator tie choice must be one of the tied candidates.
- Exclusion requires at least one recorded valid objection.
- A candidate is excluded at most once.

### 14.3 Integrative Decision-Making

- The proposer does not participate in the reaction round.
- The proposer does participate in the objection round.
- Every clarifying question is answered or explicitly declined before the phase
  closes.
- Reactions cannot receive replies.
- Only the facilitator records objection validity.
- An integration resolves only when objector and proposer confirm the same
  applicable proposal revision.
- Adoption requires an objection round against the current revision with no
  valid objections.

### 14.4 Minimal Consent Decision

- Every required participant responds to the same proposal revision.
- Any objection prevents adoption of that revision.
- Adoption requires consent from every required participant.
- Consent given to an earlier revision never carries forward automatically.

## 15. Deliberate MVP constraints

- A template that requires facilitation has exactly one active facilitator.
  Minimal Consent may run without one.
- Participants cannot enter or leave during a running process.
- Candidate withdrawal and refusal of election are not modelled.
- A proposer may withdraw a proposal before adoption.
- Submitted records are append-only; corrections create superseding records.
- The application hosts asynchronous discussion threads but does not judge
  their contents.
- A schedule may activate a task or send information, but cannot silently waive
  a required response.
- Visual workflow authoring is deferred until executable scenario simulations
  for all three reference templates pass.

## 16. References

- [BPMN 2.0](https://www.omg.org/spec/BPMN/2.0/)
- [SCXML 1.0](https://www.w3.org/TR/scxml/)
- [JSON Schema 2020-12](https://json-schema.org/specification)
- [Holacracy Constitution v5.0](https://www.holacracy.org/wp-content/uploads/2023/04/Holacracy-Constitution-5.0.pdf)

## 17. Machine-readable serialization

The canonical Profile 0.2 serialization is defined in
`WORKFLOW_SERIALIZATION.md`. It uses BPMN 2.0 XML plus the extension
namespace:

```text
urn:s-protocol:consent-workflow:0.2
```

Machine-readable reference templates and their JSON Schema response contracts
are stored under `src/s_decision/workflow/templates` and
`src/s_decision/workflow/schemas`.

## 18. Runtime prototype

The in-memory Profile 0.2 execution kernel is documented in
`WORKFLOW_RUNTIME.md`. It loads the canonical BPMN files, validates
responses, executes all three reference-process paths, and derives process and
personal projections from authoritative instance state.
