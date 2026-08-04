# Consent Workflow Profile 0.2 — Scenario Simulations

Status: design validation

## 1. Purpose

These simulations test whether the Consent Workflow Profile can execute its
three reference templates while always telling each user:

1. the last completed stage and current stage;
2. their concrete tasks, waiting dependency, or new information.

All interaction is asynchronous.

## 2. Projection notation

- `ACT(task)`: input is required from the user;
- `WAIT(dependency)`: no input is currently required;
- `INFO(item)`: new non-blocking information is available.

An information item may accompany either `ACT` or `WAIT`.

Process position is shown as:

```text
last completed stage → current stage
```

## 3. Integrative Election

Actors:

- Facilitator: Farah
- Participants: Alice, Ben, Cara
- Candidates: Dana, Eli

### E1. Valid objection and renewed nominations

| Step | Process position | Event and resulting personal projections |
| --- | --- | --- |
| 1 | Start → Present role | Farah `ACT(present role)`; participants `WAIT(Farah)` |
| 2 | Present role → Nomination | Alice, Ben and Cara each `ACT(nominate)` |
| 3 | Present role → Nomination | Alice nominates Dana and becomes `WAIT(Ben, Cara)`; nomination remains unpublished |
| 4 | Nomination → Nomination change | Ben nominates Eli, Cara nominates Eli; nominations and reasons publish together |
| 5 | Nomination change | All participants can explicitly record `keep` in parallel |
| 6 | Nomination change → Ranking | Application counts Dana 1, Eli 2 |
| 7 | Ranking → Objection round | Eli is proposed; all receive `INFO(proposed Eli)` |
| 8 | Objection round | Alice and Ben record no objection; Cara records an objection; responses publish when all submit |
| 9 | Objection round → Validity decision | Farah `ACT(record validity)` with Cara's objection shown as context; participants `WAIT(Farah)` |
| 10 | Validity decision → Nomination change | Farah records valid; Eli is excluded; all receive `INFO(Eli excluded)` |
| 11 | Nomination change | Alice may keep Dana; Ben and Cara must change because Eli is excluded |
| 12 | Nomination change → Ranking | All current nominations are Dana; application ranks Dana first |
| 13 | Ranking → Objection round | Dana is proposed; every participant records no objection |
| 14 | Objection round → Elected | Dana is elected; all receive `INFO(result)` |

Assertions:

- A submitted nomination remains unpublished until the initial round closes.
- After submitting, a participant waits only for named missing participants.
- A participant cannot keep a nomination for an excluded candidate.
- Exclusion creates a new nomination-change round rather than silently
  transferring votes.
- The final record retains both nomination rounds and the objection decision.

### E2. Tie

With eligible candidates Dana, Eli and Gita:

1. Alice nominates Dana, Ben nominates Eli and Cara nominates Gita.
2. The application reports a three-way top tie.
3. Farah receives two tasks: select one of the tied candidates, or repeat the
   nomination-change round.
4. All participants receive `WAIT(Farah)`.
5. Selection of anyone outside Dana, Eli and Gita is rejected.

### E3. Closed-list void election

1. Dana and Eli are the complete eligibility list.
2. Dana is proposed and excluded after a valid objection.
3. Participants complete a nomination-change round for Eli.
4. Eli is proposed and excluded after a valid objection.
5. The application detects that no eligible candidate remains and ends `void`.
6. It does not open another nomination-change round.

### E4. Open-list void election

1. All currently nominated candidates have been excluded.
2. The application cannot infer that no possible eligible person exists.
3. Farah receives `ACT(continue nominations or declare void)`.
4. Only Farah can produce the `void` outcome.

## 4. Integrative Decision-Making Process

Actors:

- Facilitator: Farah
- Proposer and participant: Alice
- Other participants: Ben, Cara

### D1. Two questions, two objections and two revisions

| Step | Process position | Event and resulting personal projections |
| --- | --- | --- |
| 1 | Start → Present proposal | Alice `ACT(record tension and proposal)`; others `WAIT(Alice)` |
| 2 | Present proposal → Clarifying questions | Proposal revision `P1` becomes current |
| 3 | Present proposal → Clarifying questions | Ben submits question `Q1`; Cara submits `Q2`; Alice now has two answer tasks |
| 4 | Present proposal → Clarifying questions | Ben and Cara mark question entry done; Alice answers `Q1` and declines `Q2` |
| 5 | Clarifying questions → Reaction round | Farah closes the completed question phase |
| 6 | Clarifying questions → Reaction round | Ben `ACT(react or pass)`; Cara `WAIT(prior turn)`; Alice waits |
| 7 | Reaction round → Option to clarify | Ben and Cara complete sequential reactions; replies were unavailable |
| 8 | Reaction round → Option to clarify | Alice `ACT(continue, clarify or amend)` |
| 9 | Option to clarify → Objection round | Alice amends `P1`, creating proposal revision `P2` |
| 10 | Option to clarify → Objection round | Alice records no objection; Ben submits `O1`; Cara submits `O2` |
| 11 | Objection round → Objection testing | Farah processes `O1` and `O2`; both are recorded valid |
| 12 | Objection testing → Integration O1 | `O1` becomes current; `O2` remains visible but inactive |
| 13 | Objection testing → Integration O1 | Asynchronous contributions produce amendment `P3` |
| 14 | Objection testing → Integration O1 | Ben confirms `O1` no longer triggers on `P3`; Alice confirms `P3` still addresses her tension |
| 15 | Integration O1 → Recheck O2 | Cara `ACT(confirm whether O2 still applies to P3)` |
| 16 | Recheck O2 → Integration O2 | Cara confirms it still applies; asynchronous integration produces `P4` |
| 17 | Recheck O2 → Integration O2 | Cara confirms resolution on `P4`; Alice confirms her tension remains addressed |
| 18 | Integration O2 → Objection round | A new objection round opens against `P4`; earlier responses do not carry forward |
| 19 | Objection round → Adopted | Alice, Ben and Cara record no objection; `P4` is adopted |

Revision trace:

| Item | Source revision | Applicable or confirmed revision |
| --- | --- | --- |
| Questions and reactions | `P1` | `P1` |
| `O1` and `O2` | `P2` | Initially `P2` |
| Resolution of `O1` | `P2` | Confirmed against `P3` |
| Recheck and resolution of `O2` | `P2` | Applies to `P3`, confirmed against `P4` |
| Final objection round | `P4` | `P4` |

Assertions:

- Alice can see and complete several question-answer tasks concurrently.
- Reactions cannot become discussion threads.
- Every objection retains its source revision while tracking applicability to
  newer revisions.
- Only one valid objection is active in integration.
- Integration requires both objector and proposer confirmations against the
  same current revision.
- A new objection round is required after all integrations.

### D2. Invalid objection

1. Ben submits a potential objection.
2. Only Ben and Farah can contribute during testing.
3. Farah records it invalid.
4. If no other valid objection exists, the current proposal revision is
   adopted.
5. The invalid objection and Farah's decision remain in history.

### D3. Withdrawal

1. During option-to-clarify or integration, Alice selects `withdraw`.
2. The current proposal revision moves to the `withdrawn` lifecycle state.
3. All pending questions, objections and integration tasks close as superseded
   by the terminal outcome.
4. All participants receive `INFO(withdrawn)`.

### D4. Unresolved integration

1. Ben confirms an amendment resolves his objection.
2. Alice does not confirm that it still addresses her tension.
3. The confirmation gate remains open.
4. Other participants see the exact actors and confirmations still required.
5. No objection or consent is inferred from elapsed time.

## 5. Minimal Consent Decision

Actors:

- Proposer and participant: Alice
- Other required participants: Ben, Cara

### C1. Objection, revision and consent

| Step | Process position | Event and resulting personal projections |
| --- | --- | --- |
| 1 | Start → Create proposal | Alice `ACT(create proposal)`; Ben and Cara `WAIT(Alice)` |
| 2 | Create proposal → Consent round | Proposal revision `P1` becomes current; all three participants `ACT(consent or object)` |
| 3 | Create proposal → Consent round | Alice consents and becomes `WAIT(Ben, Cara)` |
| 4 | Create proposal → Consent round | Ben objects; Cara consents; round closes |
| 5 | Consent round → Revision decision | Alice `ACT(amend or withdraw)` and receives Ben's objection as information |
| 6 | Consent round → Revision decision | Ben and Cara `WAIT(Alice)` |
| 7 | Revision decision → Consent round | Alice creates `P2`; prior consents remain historical but are not current |
| 8 | Revision decision → Consent round | Alice, Ben and Cara each consent to `P2` |
| 9 | Consent round → Adopted | `P2` is adopted automatically |

Assertions:

- An objection blocks only the exact revision it addresses.
- No facilitator judgment is required.
- Previous consent never carries to a new revision.
- The adopted result identifies `P2` and its complete consent set.

### C2. Withdrawal after objection

1. A consent round closes with at least one objection.
2. Alice selects `withdraw`.
3. The latest proposal revision ends `withdrawn`.
4. No further consent round opens.

### C3. Missing response and scheduled time

1. Alice and Ben respond; Cara does not.
2. Alice and Ben see `WAIT(Cara)`.
3. A scheduled reminder time arrives and creates an information event.
4. The round remains open.
5. Cara's response cannot be waived by schedule or inactivity.

## 6. Findings

The three templates are representable with the profile primitives. The
simulations expose three required refinements:

1. Waiting dependencies must identify concrete actors or tasks; a fixed list of
   role-specific waiting reasons is insufficient.
2. Objections need separate `sourceRevisionId` and `applicableRevisionId`.
3. Process position should report major stages. Completion of a nested question
   or objection task belongs in recent activity, not in `lastCompletedStage`.

These refinements have been applied to Profile 0.2. Its canonical
machine-readable serialization is part of S-Flow's workflow package.
