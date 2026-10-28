# Thin CLI and pinned asset implementation

Task 4 is implemented under `src/agent_eval_suite`, with standard-library-only root imports. The console entry point is `eval-suite = agent_eval_suite.cli:main`; `python -m agent_eval_suite` is equivalent. Root packaging/setup belongs to the coordinator. No changes were made to the original repositories, frozen source JSON, or formal scoring/review policy.

## Environment and command contract

Run from the checkout after `make setup`, using `.venvs/builder/bin/eval-suite` (or put that directory on PATH). Root discovery searches the working directory and installed source location for this monorepo. Global overrides must precede the namespace:

```sh
eval-suite --root /absolute/suite --builder-python /absolute/builder/bin/python --evaluator-python /absolute/evaluator/bin/python bundle list
```

Defaults are `<root>/.venvs/builder/bin/python` and `<root>/.venvs/evaluator/bin/python`. The interpreter must exist and be executable; missing environments produce an actionable `make setup` message and exit 2. Subprocess stdout/stderr and exit codes are preserved. Forwarded paths retain their normal meaning relative to the caller's current directory. Help and registry listing do not require either environment or credentials. The root does not load `.env` files, import runtime packages, fetch code during evaluation, or make model/API calls.

`dataset` (alias `builder`) forwards to `python -m dataset_builder.cli`; `eval` forwards to `python -m eval_framework.cli`. Supported commands exactly match the existing CLIs. There is no invented `build` shorthand or automatic approval/freeze step. The authoring sequence remains explicit:

```sh
eval-suite dataset prepare --suite mini_agent_query_user_intent_v3 --workspace workspaces/query-user
# Supply a candidate response using the existing generation request contract.
eval-suite dataset ingest --request workspaces/query-user/generation_request.json --response response.json --workspace workspaces/query-user
eval-suite dataset validate --suite mini_agent_query_user_intent_v3 --draft DRAFT_JSON
eval-suite dataset review --suite mini_agent_query_user_intent_v3 --draft DRAFT_JSON --output REVIEW_JSON
# Human reviews the material; use the actual reviewer and approved review file.
eval-suite dataset freeze --suite mini_agent_query_user_intent_v3 --draft DRAFT_JSON --reviewer ACTUAL_REVIEWER --review-file APPROVED_REVIEW_JSON --output FROZEN_JSONL
```

`dataset generate` retains the existing explicit model-backed generation path; it is not called by preparation or these tests. `generate-full`, `validate-full`, `generate-nanobot`, and `validate-nanobot` are available as existing explicit passthrough commands. Use `eval-suite dataset COMMAND --help` for their upstream argument contracts. The root never fabricates reviewer identity or sends Oracle values into runtime inputs.

Evaluation and comparison use actual existing arguments, not a synthetic Agent/version shorthand:

```sh
eval-suite eval run --input CANDIDATE_DIR --binding configs/agents/external-static.json --output-dir artifacts/run
# Alternatively, use an existing suite or legacy frozen dataset with its Provider.
eval-suite eval run --dataset FROZEN_JSONL --provider mini_agent --capability-bundle REFERENCE_BUNDLE_DIR --output-dir artifacts/run
eval-suite eval compare --baseline-run artifacts/baseline --candidate artifacts/run --output-dir artifacts/comparison
eval-suite eval gate --candidate artifacts/run --comparison artifacts/comparison --policy POLICY_JSON --output-dir artifacts/gate
```

`--baseline-run` is a root compare-only alias translated to upstream `--baseline`. Passing both spellings is rejected. It is not a `run` option, an automatic run search, or a run-ID resolver: supply the saved run directories accepted by the evaluator. Other arguments are forwarded unchanged. In legacy mode, `--capability-bundle` supplies the reference bundle and must match the dataset's recorded Hash; it is **not** a runtime-bundle override. Current runtime capabilities are selected and checked by the Provider/explicit trusted runtime binding. Comparing different reference datasets/contracts remains invalid. Runtime Agent changes may be a supported experimental variable under the evaluator's compatibility controls.

`configs/agents/external-static.json` is a real evaluator `RuntimeBinding` for `mini_agent` and its static external adapter; it works only with matching candidate intake and supported static operations. It does not run mini_agent or a model. `configs/README.md` documents existing stdio binding fields and input-mode restrictions. No new network transport or endpoint identity guarantee is implied.

## Bundle registry

```sh
eval-suite bundle publish --input BUNDLE_DIR --agent mini_agent --version 0.1.0
eval-suite bundle list
eval-suite bundle resolve --agent mini_agent --version 0.1.0
eval-suite bundle validate --input data/bundles/mini_agent/0.1.0
eval-suite bundle diff --old OLD_BUNDLE_DIR --new NEW_BUNDLE_DIR
```

`cap` aliases `bundle`. Publications are copied to `data/bundles/<agent>/<version>`. `data/bundle-index.json` remains outside every v3 bundle and stores schema version 1, an Agent/version mapping, relative path, Agent identity/version, canonical `capability_bundle_sha256`, canonical `agent_snapshot_sha256`, and `files_sha256`. The last value hashes a sorted mapping of relative file paths to byte SHA-256 values; it supplements, and does not replace or alter, historical protocol hashing.

Publication stages the copy, rejects symlinks/path traversal, runs `python -m capability_snapshot_kit validate --input STAGING_DIR` in the installed Builder/contracts environment, verifies Agent identity, and writes the external index with an exclusive writer lock and atomic replacement. A previously published version is rejected even when content is identical. A publication version must begin with a digit; mutable names such as `latest` and `current` are unsupported. Publication version and the Agent's internal `agent_version` are separately recorded.

`resolve` requires an exact Agent/version, checks its prescribed path and file-byte digest, reruns canonical protocol validation, and verifies both protocol Hashes and Agent identity. The canonical validator compares supplied schema artifacts with trusted protocol schemas and rejects forged snapshots or additional unexpected JSON. `list` is discovery, not evidence of validation; formal callers must use `resolve`. A process interruption between bundle rename and index replacement can leave an unregistered directory; subsequent publication refuses to overwrite it. Recovery is explicit, never silent.

The included publication is `mini_agent@0.1.0`:

- Bundle Hash: `99baea74b9a4fbd6c493fb5a3159a8f019769804d94232f0d89aa072ea9af3d8`.
- Agent root Hash: `7f140848d755166188fdd22872a2ab782ab0b37ff51750938e609d6de0614b21`.
- All 44 JSON files are byte-identical to the historical evaluator fixture of the same bundle Hash.
- The only addition is `tools/.gitkeep`, retaining the protocol-required empty directory across Git clones. No manifest JSON was added inside the v3 bundle.

## Explicit external source acquisition

```sh
eval-suite agent sync --name external-agent --repository REPOSITORY_URL_OR_PATH --ref EXPLICIT_REF
eval-suite agent resolve --name external-agent --commit FULL_COMMIT_HASH
```

`source` aliases `agent`. Only `sync` performs Git fetch. It resolves the supplied ref to a full commit, checks out that commit detached under `.sources/<name>/<commit>`, and records repository, requested ref, resolved commit, tree Hash and checkout path in `data/source-index.json`. Different commits get separate directories. `resolve` requires a full immutable commit Hash, performs no network access, and rejects changed HEAD/tree, repository provenance, tracked changes or untracked files. Tracked files are read directly and their Git blob Hashes, file kinds, symlink target bytes and executable bits are compared against the pinned commit tree. This check is independent of index flags, stat caches and `core.filemode`; `git status` remains an additional staged/untracked change check. The same direct check runs before a new source publication is registered. Credentials embedded in HTTP repository URLs are rejected; use ordinary Git credential configuration.

An executable binding must explicitly use the resolved source path. Source sync does not install dependencies, configure a binding, recurse into submodules or launch evaluation. Empty/unmaterialized Gitlinks remain unfetched; a populated submodule is rejected because its code requires independent pinned source verification. Checkouts transformed by Git filters or newline conversion must still match the recorded raw blob bytes to claim the pinned source identity. Git provenance does not fingerprint ignored files, dependency environments or a remote endpoint's deployed state; it is not a complete runtime reproducibility claim. No external repository was fetched during implementation tests: they use temporary local Git repositories.

## Verification

- Initial dispatcher/publication tests failed before implementation; local-Git tests likewise failed before `sources.py` existed.
- `.venvs/builder/bin/python -m pytest -q tests/integration/test_cli.py tests/integration/test_cli_protocol.py tests/integration/test_cli_sources.py`: **32 passed** (including the P2 source-integrity follow-up).
- Tests cover missing environments, credential-free help, exact forwarding/exit codes, explicit baseline alias, human review arguments, immutable versions, traversal/symlinks, byte and index-Hash tampering, canonical supplied-schema rejection, forged Agent payloads, explicit ref-to-commit pinning, offline resolution and dirty source rejection.
- `.venvs/builder/bin/ruff check src/agent_eval_suite tests/integration/test_cli*.py`: **passed**; owned Python files formatted with Ruff.
- Installed console-command smoke checks passed for bundle publish/resolve and upstream prepare/freeze/compare/gate help. An actual offline `dataset prepare --suite mini_agent_query_user_intent_v3` generated its request, prompt, copied bundle, IR and source manifest in a temporary workspace.
- No formal freeze was performed and no human approval was fabricated. No paid model calls, hosted uploads, Git staging or commits were performed by this task.

Whole-package and clean-clone integration verification remain coordinator-owned.

## P2 review follow-up: Git index flags

Independent review reproduced a source-integrity gap: `git status` could report a clean tree after tracked source bytes were changed under `assume-unchanged` or `skip-worktree`. Regression tests were added first and failed with `resolve` incorrectly returning 0 for both flags. A third failing regression demonstrated an executable-bit change hidden by `core.filemode=false`.

The resolver now enumerates the pinned commit tree with NUL-delimited Git output and verifies actual file bytes/modes directly, without trusting Git's index state or cached stat metadata. Symlink contents are hashed without following the link, parent-directory symlinks are rejected, and Git replacement objects are disabled for source inspection. Unmodified files carrying either index flag remain valid. Tests also cover binary data and filenames containing tabs/newlines, altered symlink targets, and unmaterialized versus populated Gitlinks. Ignored files and dependencies remain outside this bounded Git source identity; no broader runtime/environment fingerprint claim was added.

Follow-up verification: the full three-file CLI test selection passed **32 tests in 15.82 seconds**; `ruff check src/agent_eval_suite tests/integration/test_cli*.py` passed. No commit or staging was performed.
