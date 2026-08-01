# Consent Workflow Profile 0.2 — Runtime Prototype

## Purpose

`s_decision.workflow` is a minimal definition interpreter and test oracle for
the three reference templates. It proves that the BPMN/CWP definitions can
drive execution and the two required user projections without
template-specific interface code. Production state belongs to Sovereign Core;
see `SOVEREIGN_CORE_INTEGRATION.md`.

## Supported

- BPMN start, end, user task, service task, exclusive gateway and subprocess;
- CWP single-user inputs and parallel or sequential human rounds;
- JSON Schema response validation for the subset used by the templates;
- guarded branches and named calculations;
- facilitator-managed objection queues;
- controlled question/answer interactions;
- asynchronous discussion messages;
- versioned proposal artifacts;
- confirmation gates and global withdrawal;
- process-position and per-user projections.

## Example

```python
from s_decision.workflow import WorkflowEngine, load_workflow

definition = load_workflow(
    "src/s_decision/workflow/templates/minimal-consent-decision.bpmn"
)
engine = WorkflowEngine(definition)
instance = engine.create_instance(
    "decision-1",
    {
        "proposer": ["alice"],
        "requiredParticipant": ["alice", "ben", "cara"],
    },
)
engine.start(instance)

alice = engine.personal_projection(instance, "alice")
task_id = alice.tasks[0]["id"]
engine.submit(instance, "alice", task_id, {"proposal": "Adopt policy A"})
```

The interface reads:

```python
engine.position(instance)
engine.personal_projection(instance, "alice")
```

It does not edit projection state directly.

## Verification

```powershell
python -m pytest
python scripts/validate_workflow_templates.py
```

The tests execute:

- unanimous consent;
- objection, proposal revision and renewed consent;
- election with and without a valid objection;
- forced change away from an excluded candidate;
- IDMP clarification, reactions and no-objection adoption;
- IDMP objection testing, integration, confirmation and renewed objection
  round;
- proposer withdrawal;
- response-validation failures.

## Deliberate limitations

- State is in memory; production must adapt it to Core protocol nodes rather
  than add an application-owned event store.
- There is one BPMN control token. Parallel participant rounds are supported,
  but general parallel gateways are not.
- Authentication, identity, persistence, transport and browser concurrency are
  delegated to Sovereign Core and are not implemented here.
- Scheduled waits and timers are not executed yet.
- JSON Schema validation covers the keywords used by the current response
  contracts, not the complete standard.
- Full OMG BPMN XSD certification remains separate.

S-decision's Core adapter stores runtime state and response records as protocol
nodes; the workflow package does not introduce a separate persistence layer.
