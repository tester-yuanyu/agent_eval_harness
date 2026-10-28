# Migration provenance

Imported the current working trees on 2026-10-28. Uncommitted source files are included; the source HEADs alone do not represent the imported implementation. Original repositories remain separate and unchanged.

| Source repository | Recorded HEAD | Working tree |
| --- | --- | --- |
| mini_agent | `124a26ac92d2dd5a2be88ad5f69cf7fc8522f954` | Changes present |
| agent_dataset_builder | `fa30dcbd9f996a442f450f7649a01e998468c8f9` | Changes present |
| agent_evaluator | `76f9209ec9c91bde69e98a1b47bed609668e1e1e` | Changes present |

Inspect is pinned to 0.3.280, upstream commit `dfcb169e1cb170a8fbe2c37a0e3befc45c2c2b85`. No tracked upstream source modifications were present during import. Business extensions were materialized into packages/evaluator; upstream source and nested Git repositories were not copied.

Private source Git status, diffs, initial file hashes and baseline copies are kept in ignored `.migration/`. Historical project documentation is retained inside each package; the root README and this repository’s guides describe the supported monorepo entrypoints.

`frozen-assets.json` records 416 imported reference files for migration integrity verification.
