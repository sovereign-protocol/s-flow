# S-Flow

S-Flow is a Sovereign application for fully asynchronous, human-in-the-loop
workflows. The bundled definitions are consent-based decision processes, but
the runtime is a general BPMN-subset interpreter rather than a decision tool.
Each process is a Core topic: Core owns identity, persistence, channels,
invitations, optimistic browser mutations and agenda items; S-Flow owns
process meaning.

The current scaffold:

- creates, shares, lists and deletes process topics;
- records role assignments and Core-backed agenda items;
- executes the three bundled workflow definitions;
- stores JSON-safe interpreter state and response records as Core nodes;
- exposes process position and personal “input, wait or information”
  projections;
- rejects stale task responses with the runtime node content hash; and
- provides a versioned facade consumed by S-Cockpit.

The workflow interpreter, BPMN/CWP definitions and response schemas are part
of this package under `src/s_flow/workflow`; they are not a separate
application or dependency. See [the runtime documentation](docs/WORKFLOW_RUNTIME.md)
and [serialization specification](docs/WORKFLOW_SERIALIZATION.md).

The Minimal Consent interface now runs end to end across two clients. A
participant publishes an immutable response in their own perspective; the
process creator verifies and applies it to the creator-owned runtime. Process
and assignment differences use Core's standard transition explanations and
adopt/rollback reactions. Workflow correction is separate from Core reactions:
the creator can retract the latest immutable response and S-Flow rebuilds the
runtime from the remaining response history.

## Run

```powershell
python -m pip install -e .
sovereign-host 9308 config/flow.example.json
```

## License

Application software is Apache-2.0. Sovereign Core is a separately replaceable
LGPL-3.0-or-later dependency.
