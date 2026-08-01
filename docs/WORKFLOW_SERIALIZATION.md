# Consent Workflow Profile 0.2 — Serialization

## Canonical form

The canonical workflow definition is BPMN 2.0 XML with extension elements in:

```text
urn:s-protocol:consent-workflow:0.2
```

The namespace prefix `cwp` is conventional; the namespace URI is normative.
BPMN controls graph structure. CWP extensions define collaborative human
semantics that BPMN does not standardize.

Definitions omit BPMN diagram-interchange coordinates in version 0.2. A visual
editor may add them without changing execution semantics.

## Files

```text
schema/
  consent-workflow-profile.xsd
src/s_flow/workflow/schemas/
  integrative-election.responses.schema.json
  integrative-decision-making.responses.schema.json
  minimal-consent.responses.schema.json
src/s_flow/workflow/templates/
  integrative-election.bpmn
  integrative-decision-making.bpmn
  minimal-consent-decision.bpmn
src/s_flow/workflow/
  engine.py
  loader.py
  model.py
  schema_validation.py
tests/
  test_workflow_runtime.py
scripts/
  validate_workflow_templates.py
```

## Extension placement

| CWP element | BPMN owner |
| --- | --- |
| `profile` | `process` |
| `candidateEligibility` | election `process` |
| `assignment` | human `userTask` |
| `input` | single-actor `userTask` |
| `humanRound` | multi-instance `userTask` |
| `controlledInteraction` | `userTask` or `subProcess` |
| `dynamicWorkCollection` | `userTask` or `subProcess` |
| `managedQueue` | `subProcess` |
| `confirmationGate` | confirmation `userTask` or integration `subProcess` |
| `calculation` | automated `serviceTask` |
| `artifactAction` | task changing an artifact lifecycle or revision |
| `guard` | conditional `sequenceFlow` |

## Normative rules

1. A process has exactly one `cwp:profile`.
2. IDs and references use stable XML identifiers.
3. A running instance fixes `profile@templateVersion`.
4. CWP roles referenced by tasks must exist in the profile.
5. A `humanRound` is also represented by BPMN multi-instance loop
   characteristics.
6. A response schema is a relative URI with a JSON Pointer fragment into
   `$defs`.
7. Sequence-flow conditions use named `cwp:guard` predicates. Workflow files
   cannot contain arbitrary executable expressions.
8. Service tasks use named and versioned `cwp:calculation` operations.
9. Artifact changes use `cwp:artifactAction`; revisions remain immutable.
10. CWP extensions determine execution when generic BPMN engine behaviour
    would otherwise be ambiguous.
11. Unknown mandatory CWP elements or predicates make a definition
    unsupported rather than silently changing its meaning.

## Trusted-space rule

`publication="onRoundComplete"` delays normal application publication. It does
not promise encryption, anonymity or confidentiality from trusted operators.

## Validation

Run:

```powershell
python scripts/validate_workflow_templates.py
```

The validator checks:

- XML well-formedness;
- CWP extension elements against the CWP XSD;
- unique BPMN IDs and sequence-flow references;
- reachability within each process and subprocess;
- role references;
- JSON Schema files and referenced `$defs`.

Full OMG BPMN XSD conformance remains a separate interoperability check. The
validator intentionally checks the executable subset used by this profile.
