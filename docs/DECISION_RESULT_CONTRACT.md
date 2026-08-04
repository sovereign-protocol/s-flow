# S-Flow decision-result contract

Facade method: `decision_result(process_uuid)`.

Configured elections can be created through
`create_integrative_election(title, participant_uuids, facilitator_uuid,
eligible_candidate_uuids, definition_version)`. S-Flow freezes those
assignments and starts the process before returning its UUID.

Contract ID: `s-flow.decision-result`; contract version: `1`.

The detached result contains exactly:

- `contract_id`, `contract_version`;
- `process_uuid`;
- `definition_id`, `definition_version`;
- `lifecycle`, `current_stage`, `last_completed_stage`, `terminal_outcome`,
  `selected_candidate_uuid`;
- `participant_snapshot`, as sorted assignment records containing
  `identity_uuid`, `role`, and `required`;
- `facilitator_uuid`; and
- `result_hash`.

Before termination, `lifecycle` is not `completed` and the terminal fields are
null. For an elected Integrative Election result, `terminal_outcome` is
`elected` and `selected_candidate_uuid` is non-empty. A void election has no
selected candidate.

`result_hash` is `sha256:` plus the lowercase SHA-256 digest of the UTF-8 JSON
encoding of every other field. JSON object keys are sorted, separators are
`,` and `:`, non-ASCII text is preserved, and non-finite numbers are rejected.
Array order is significant; S-Flow sorts the participant snapshot by identity,
role, then required status before hashing.

Consumers must validate the contract ID/version, required fields, terminal
semantics, and recomputed hash. A consumer that has already recorded a result
hash must also compare it with the current facade result.
