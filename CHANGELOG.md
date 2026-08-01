# Changelog

## Unreleased

Nothing has been published from this repository yet. The entries below are
what a first release would carry.

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
