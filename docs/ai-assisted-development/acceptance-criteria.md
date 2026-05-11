# Acceptance Criteria — Writer-AI Output

Every criterion is **binary** (pass / fail) and **mechanically verifiable** (a command or a grep, not a judgment call). The writer-AI is "done" only when ALL of these pass.

A separate codex review pass enforces these AFTER the writer-AI claims completion. If codex flags a fail, writer-AI fixes it and we re-run.

---

> **Note on relaxation (per codex audit):** Exact file paths in Section A and bullet-count rules in Section F are *guidelines*. The writer-AI MAY use equivalent paths/structures if `README.md` cross-references them clearly. The behavioral tests in Section H are the load-bearing checks — they verify actual correctness, not file-tree shape.

## A. Structural — files exist at expected paths

- [ ] **A1.** All Tier 1 files exist (the demo path):
  - `spikes/one_stake_tx_probe.py`, `spikes/one_pa_tx_probe.py`
  - `ingestion/bq/{bq_client,log_extractor,trace_extractor,block_extractor,transaction_extractor}.py`
  - `decoder/{event_decoder,calldata_decoder,trace_decoder,trace_tree,proxy_resolver,abi_registry,contract_registry,types}.py`
  - `protocols/staking_v02/{semantics,ledger_builder}.py`
  - `protocols/payment_abstraction/{semantics,ledger_builder,reserves_resolver}.py`
  - `reconciliation/{movement_builder,economic_reconciler,balance_reconciler,checks}.py`
  - `lineage/run_metadata.py`
  - `storage/{bigquery_loader,dataset_writer,manifest}.py`

- [ ] **A2.** All Tier 2 files exist (JD checkbox files):
  - `dbt/models/{raw,staging,intermediate,marts,analytics}/*.sql` (≥1 in each subdir)
  - `dbt/tests/*.sql` (≥3)
  - `dbt/{dbt_project.yml,profiles.yml.example,packages.yml}` and per-dir `schema.yml`
  - `airflow/dags/staking_pipeline_dag.py`
  - At least one custom operator file under `airflow/plugins/operators/` (e.g. `evm_log_extract_operator.py`). *(criterion v3 — `bq_extract.py` removed; AGENTS.md §10 caps custom operators at 3 named ones: `EvmLogExtract`, `EvmTraceExtract`, `EvmBalanceSnapshot`.)*
  - `databricks/notebooks/parity_check.py`
  - `terraform/{main,bigquery,gcs,service_account,variables,outputs}.tf`
  - `analytics/{apy_realized,reward_distribution,pa_fee_attribution}.py`
  - `config/contracts/{staking_v02,payment_abstraction}.yaml`
  - `config/abis/{staking_pool,reserves,fee_aggregator,swap_automator,link_token}.json`
  - `scripts/{repro.sh,replay_partition.py,golden_tx_walkthrough.py}`
  - `tests/unit/test_*.py` (≥6 test files)

- [ ] **A3.** All Tier 3 docs exist and are non-empty (>500 chars each):
  - `README.md`, `docs/{architecture,reproduction,data-model,protocol-validation,runbook}.md`
  - `AGENTS.md`, `CLAUDE.md` (updated)

- [ ] **A4.** WHY files exist (Tier 4):
  - `ingestion/bq/WHY.md`, `ingestion/rpc/WHY.md`, `decoder/WHY.md`
  - `protocols/staking_v02/WHY.md`, `protocols/payment_abstraction/WHY.md`
  - `reconciliation/WHY.md`, `lineage/WHY.md`, `storage/WHY.md`
  - `analytics/WHY.md`, `dbt/WHY.md`, `airflow/WHY.md`
  - `terraform/WHY.md`, `databricks/WHY.md`
  - Each ≥ 300 chars; format: 5-8 bullets

- [ ] **A5.** `SUMMARY.md` at project root exists, lists every modified file + any TODOs.

- [ ] **A6.** No SUBSTANTIVE file is 0 bytes. `__init__.py` files MAY be 0 bytes (Python convention). No `.py` file ends in a `pass` as the only function body. *(criterion v3 — `__init__.py` exemption per codex audit.)*

---

## B. Functional — code actually runs

- [ ] **B1.** `uv run python -c "import ingestion, decoder, protocols, reconciliation, lineage, monitoring, analytics, storage"` exits 0 (all top-level packages importable).

- [ ] **B2.** `uv run python -c "from spikes.one_stake_tx_probe import main"` exits 0 (no syntax/import errors).

- [ ] **B3.** `uv run python -c "from spikes.one_pa_tx_probe import main"` exits 0.

- [ ] **B4.** `uv run python -m spikes.one_stake_tx_probe --help` produces argparse usage output (proves argparse wired).

- [ ] **B5.** `uv run python -m spikes.one_pa_tx_probe --help` same.

- [ ] **B6.** `uv run pytest tests/unit --collect-only` discovers ≥6 tests (no collection errors).

- [ ] **B7.** `uv run pytest tests/unit -v --tb=short` — any test that doesn't require live RPC/BQ passes. Tests requiring live access can `pytest.skip` cleanly.

- [ ] **B8.** `uv run --extra dbt dbt parse --project-dir dbt --profiles-dir dbt --target ci` exits 0 (dbt can parse all models).

- [ ] **B9.** `uv run python airflow/dags/staking_pipeline_dag.py` exits 0 (DAG file imports cleanly even without Airflow scheduler).

- [ ] **B10.** `uv run ruff check .` reports < 30 errors (some style nits OK; no `F` (logic) or `E9` (syntax) errors).

- [ ] **B11.** `uv run ruff format --check .` either passes or has < 5 file diffs.

---

## C. Correctness — uses real EVM facts, never fabricated

These are hard-coded constants; mechanical grep verifies presence.

- [ ] **C1.** `0x514910771AF9Ca656af840dff83E8264EcF986CA` (LINK token) appears in ≥1 file (any case).

- [ ] **C2.** `0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef` (ERC-20 Transfer sig) appears in ≥1 file.

- [ ] **C3.** `0xa9059cbb` (transfer() selector) is referenced by executable code in `decoder/trace_decoder.py` — either as a literal in code, or via an imported constant from `decoder/calldata_decoder.py` (or equivalent) that itself contains the literal. Behavioral verification: a unit test exercising the trace decoder with a real transfer() call asserts the path matched. Bare-comment occurrences do NOT pass. *(criterion v3 — codex relaxation.)*

- [ ] **C4.** `0x23b872dd` (transferFrom() selector) — same rule as C3, applied to transferFrom(). Behavioral test required.

- [ ] **C5.** `0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc` (EIP-1967 impl slot) appears in `decoder/proxy_resolver.py`.

- [ ] **C6.** `0x5680681ED3767B96914CE741a308155C7fB9171d` (PA Reserves) in `config/contracts/payment_abstraction.yaml`.

- [ ] **C7.** `0xd6e39d42AceE7Abcc460E6Ea78a0844A0980E78f` (PA FeeAggregator) in `config/contracts/payment_abstraction.yaml`.

- [ ] **C8.** `0x36E827bA2B270535ca1B099a6Ba2B280DDc0315e` (PA SwapAutomator) in `config/contracts/payment_abstraction.yaml`.

- [ ] **C9.** `bigquery-public-data.crypto_ethereum` referenced in ≥3 BQ extractor files (logs, traces, transactions/blocks).

- [ ] **C10.** No `import web3` statement in `decoder/` (raw decoding must use `eth_abi`, not web3.py contracts). `from web3 import` in `ingestion/rpc/` is OK as fallback.

- [ ] **C11.** No `: float` annotation on any field/parameter named `amount`, `value`, `principal`, `reward`, or `link_*` (all uint256 should be `int`).

- [ ] **C12.** Every `compute_*_id` function contains `hashlib.sha256` (deterministic IDs per AGENTS.md §2).

- [ ] **C13.** Zero f-strings interpolating addresses or hex into BQ SQL strings (`f"... 0x{` or `f"... {address}"` patterns). All BQ queries use parameterized `query_params`.

- [ ] **C14.** All EVM addresses in Python source are lowercase (mixed-case checksum is display-only). Grep: no `[A-F]` in 0x-prefixed 40-char hex strings inside `.py` files except in `*display*` modules / docstrings / configs.

---

## D. JD checkbox coverage — all 13 must be visible

- [ ] **D1.** Airflow — `airflow/dags/staking_pipeline_dag.py` defines a `DAG` with `dag_id`, `schedule`, ≥3 tasks.
- [ ] **D2.** dbt — `dbt/models/` has ≥6 model files; `dbt/tests/` has ≥3 test files; ≥1 mart has `contract: enforced: true` in `schema.yml`.
- [ ] **D3.** GCP/BigQuery — `from google.cloud import bigquery` (or equivalent) in ≥1 file.
- [ ] **D4.** GCS — `from google.cloud import storage` (or equivalent) in `storage/dataset_writer.py`.
- [ ] **D5.** Databricks — `databricks/notebooks/parity_check.py` starts with `# Databricks notebook source` header AND contains a real Spark/Delta parity computation: reads BQ mart `ledger_entries` (or exported parquet), recomputes a key aggregation in Spark, and `assert`s the row count + total LINK amount match dbt mart within tolerance. Mere header presence does not pass.
- [ ] **D6.** SQL — ≥10 `.sql` files under `dbt/`.
- [ ] **D7.** Python — already evident; no check needed.
- [ ] **D8.** Raw transactions — `crypto_ethereum.transactions` referenced in ≥1 BQ extractor.
- [ ] **D9.** Internal traces — `crypto_ethereum.traces` referenced in `ingestion/bq/trace_extractor.py`.
- [ ] **D10.** Event logs — `crypto_ethereum.logs` referenced in `ingestion/bq/log_extractor.py`.
- [ ] **D11.** Token transfers — DERIVED from logs (the Transfer event) AND traces (transfer/transferFrom internal calls), NOT pulled from `crypto_ethereum.token_transfers` as truth. **Grep enforcement:** `grep -rn "crypto_ethereum.token_transfers" ingestion/ decoder/ protocols/` returns ZERO hits; the string may only appear in `reconciliation/bq_validator.py` (or equivalent validator module). Behavioral verification: test H5 below.
- [ ] **D12.** ABI decoding happens in `decoder/event_decoder.py` and `decoder/calldata_decoder.py` using `eth_abi.decode`, either as `eth_abi.decode(...)` directly OR via `from eth_abi import decode as <alias>` followed by calls to that alias. No `web3.py` contract decoding (`Contract.events.<X>().processLog`) appears anywhere in `decoder/`. *(criterion v3 — codex wording, accepts idiomatic aliased import.)*
- [ ] **D13.** BQ-primary framing — README first paragraph contains "BigQuery" before any RPC/`eth_getLogs` mention. The phrase "beyond basic RPC" or equivalent appears in README.

---

## E. Architecture invariants — AGENTS.md §1-10 preserved

- [ ] **E1.** §1: dbt models do NOT contain decoding logic. `dbt/models/staging/stg_staking_events.sql` is a passthrough from `decoded_events` table; no `JSON_EXTRACT(topics)` or `SUBSTR(data, ...)` of raw bytes.

- [ ] **E2.** §2: 7 deterministic ID functions exist: `compute_raw_log_id`, `compute_decoded_event_id`, `compute_raw_trace_call_id`, `compute_movement_id`, `compute_action_id`, `compute_ledger_entry_id`, `compute_run_partition_id`. Each is pure (no `time.`, no `uuid.`, no `random.`).

- [ ] **E3.** §3: `run_partition_id` is NOT in any mart's `unique_key`. Grep: in `dbt/models/marts/*.sql`, `unique_key` does not contain `run_partition_id`.

- [ ] **E4.** §4: `match_action_to_movements` returns `list[ActionMovementMatch]` (a list type, never `Transfer | None`).

- [ ] **E5.** §5: `extract_erc20_transfer_calls` rejects a movement if **(a)** `receipt.status != 1` OR **(b)** ANY ancestor call on the `trace_address` path failed (not just `parent.success` — a grandparent revert must also disqualify the descendant). Verified by behavioral test H4 below.

- [ ] **E6.** §6: LINK amount columns use `NUMERIC` (BQ) or `int` (Python). No `FLOAT64` in mart `schema.yml` for amount columns.

- [ ] **E7.** §7: ≥1 mart has `contract: enforced: true` in `schema.yml`.

- [ ] **E8.** §8: `dbt/tests/assert_ledger_balanced_per_tx.sql` exists and is non-trivial.

- [ ] **E9.** §10: Exactly 3 custom Airflow operators max. No `DbtRunOperator` or `LoadToBigQueryOperator`.

---

## F. Defensibility — user can defend in interview

- [ ] **F1.** Every WHY-{module}.md has bullets in this format: *what, why, tradeoff, interview-detail, recite-cold*.

- [ ] **F2.** Every substantive Python file (>50 LoC) has a module-level docstring explaining purpose. Trivial init/passthrough files may have a 1-line docstring.

- [ ] **F3.** *(relaxed per codex audit — no longer enforced. Style is the writer-AI's call.)*

- [ ] **F4.** `SUMMARY.md` lists ≥1 "interview-defendable claim" per module (one sentence the user can quote when asked about that module).

---

## G. Reproducibility

- [ ] **G1.** `tests/fixtures/golden_stake_tx/README.md` exists describing what JSON files are expected.
- [ ] **G2.** `tests/fixtures/golden_pa_tx/README.md` same.
- [ ] **G3.** `scripts/repro.sh` exists, has `#!/usr/bin/env bash`, and is `chmod +x`.
- [ ] **G4.** `Makefile` targets exist: `install`, `test`, `lint`, `dbt-build`, `golden-walkthrough`, `idempotency-check`.

- [ ] **G5.** `scripts/repro.sh --fixture-only` runs the FULL repro path WITHOUT live RPC/BQ — uses cached fixtures from `tests/fixtures/golden_*_tx/`. Executes: `pytest tests/unit -v` + `dbt parse` + idempotency replay test. Exit 0 = green. This is the codex-required proof that "the project actually runs reproducibly," not just "tests can skip."

---

## H. Behavioral / Golden tests — the load-bearing correctness checks

These supersede grep-only checks where they overlap. The C section (constants present) and E section (invariants present) are weaker without these. Codex audit: *"Hard-coded constants can be pasted in comments and still pass; need tests that decode one golden tx and assert extracted values."*

- [ ] **H1.** Golden Stake-tx decoding test exists at `tests/unit/test_golden_stake_decoding.py`. It loads `tests/fixtures/golden_stake_tx/{tx,receipt,logs,trace}.json` and **asserts**: contract address matches expected staking pool, decoded `Staked` event has expected staker / amount, decoded LINK Transfer log has expected (from, to, amount), ledger entries balance per-tx, exactly N entries produced.

- [ ] **H2.** Golden PA-tx decoding test exists at `tests/unit/test_golden_pa_decoding.py`. Same shape but for one Reserves deposit tx. Asserts: proxy resolution returns expected impl address, swap call decoded with expected input/output token, reserves movement reconciled.

- [ ] **H3.** ID determinism test exists at `tests/unit/test_id_determinism.py`. Runs the decode pipeline on the same fixture **twice in separate Python subprocesses** (subprocess.run, fresh interpreter), captures all `*_id` fields, asserts they're byte-identical. Also asserts that changing `run_partition_id` between runs leaves entity IDs (`raw_log_id`, `decoded_event_id`, `action_id`, `movement_id`, `ledger_entry_id`) unchanged.

- [ ] **H4.** Ancestor-success test exists at `tests/unit/test_movement_builder_ancestor.py`. Constructs a synthetic trace tree where the grandparent call succeeded but the parent call reverted. Asserts: the descendant LINK transfer is REJECTED (not turned into a TokenMovement). Mirror test where parent succeeded but receipt.status==0 also rejects.

- [ ] **H5.** `token_transfers`-source-of-truth violation test at `tests/unit/test_no_token_transfers_in_pipeline.py`. Recursively greps `ingestion/`, `decoder/`, `protocols/` for the literal string `crypto_ethereum.token_transfers` (case-insensitive). Asserts ZERO matches. Validator module is allowed.

- [ ] **H6.** Event ABI shape test at `tests/unit/test_event_decoder.py`. Asserts:
  - ERC-20 Transfer log: 3 topics (signature + 2 indexed), 1 non-indexed (amount); decoder returns `(from, to, amount)`
  - Decoder rejects log where topic count doesn't match ABI's expected indexed-arg count
  - Anonymous events (no topic0) handled distinctly
  - `from`/`to` extracted from topic[1]/topic[2] as last 20 bytes (not full 32)

- [ ] **H7.** Trace tree reconstruction test at `tests/unit/test_trace_tree.py`. Given flat rows with `trace_address` values `["", "0", "1", "0,0", "0,1", "1,0"]` (string form per BQ's encoding), asserts:
  - Resulting tree has exactly one root (trace_address `""`)
  - Root has 2 children (`"0"` and `"1"`) in that sibling order
  - Node `"0"` has 2 children (`"0,0"`, `"0,1"`) in that order
  - `trace_address` parsed to `list[int]` for `RawTrace.trace_address` field
  - Reverse: tree → flat preserves all rows

---

## I. Reorg / finality / checkpoint — production reality

Codex audit: *"Reorg/finality/checkpointing are named in architecture but not accepted."*

- [ ] **I1.** Finality window config exists at `config/settings.yaml` (or equivalent), key `finality_window_blocks`, default 64 for mainnet. Loaded by `ingestion/finality.py`.

- [ ] **I2.** Checkpoint API in `ingestion/checkpoint.py` has signatures: `get_last_processed_block(chain_id: int, dag_id: str) -> int | None` and `set_last_processed_block(chain_id: int, dag_id: str, block: int, run_partition_id: str) -> None`. Backed by a stable storage (BQ table or local sqlite for the demo).

- [ ] **I3.** Replay-idempotency test at `tests/unit/test_replay_idempotency.py`. Runs decode pipeline twice on overlapping block range with different `run_partition_id` values; asserts mart row count is unchanged after second run (dedupe by entity ID). Codex's wording: *"replaying an overlapping block range dedupes/replaces rows."*

- [ ] **I4.** Reorg model documented: `dbt/models/staging/stg_canonical_blocks.sql` and `stg_shadow_tip_blocks.sql` exist. Marts source from canonical only. Documented in `docs/architecture.md` reorg section.

---

## J. Tokenomics output — the recruiter's "support incentive modeling" requirement

Codex audit: *"No criterion proves incentive modeling/tokenomics output."*

- [ ] **J1.** `dbt/models/analytics/` contains AT LEAST 3 marts that each answer ONE specific economic question, named clearly:
  - `weekly_reserve_accumulation.sql` — *how much LINK is the Reserve accumulating per week, broken down by source (PA fee inflow vs other)?*
  - `apy_realized_by_pool.sql` — *what APY are stakers actually realizing, computed from reward distributions / time-weighted principal?*
  - `fee_attribution_by_source.sql` — *where do PA fees come from (Chainlink service: VRF/Functions/Data Streams/CCIP)?*
  - (4th optional: `staker_reward_sustainability.sql` — *reward outflow vs reserve growth rate*)

- [ ] **J2.** Analytics marts may source ONLY from reconciled marts under `dbt/models/marts/*` PLUS an approved canonical-block dimension/staging table (`stg_canonical_blocks`) used solely for reorg-safety filtering and time-bucketing. They MUST NEVER source from raw/staging decoded events, logs, traces, token transfers, `bigquery-public-data.crypto_ethereum.*`, or `crypto_ethereum.token_transfers`. Verified by J4 below. *(criterion v3 — codex wording, narrow exception for `stg_canonical_blocks`.)*

- [ ] **J3.** Each analytics mart has a `description` block in `dbt/models/analytics/schema.yml` stating the economic question it answers. Reviewer can read schema.yml and immediately see "this mart answers X."

- [ ] **J4.** *(NEW v3 per codex audit.)* SQL-ref enforcement: a script `scripts/check_analytics_refs.py` parses every `dbt/models/analytics/*.sql` file (after stripping SQL comments), extracts every `{{ ref(...) }}` and `{{ source(...) }}`, and asserts:
  - All `ref()` targets are either in `dbt/models/marts/*` OR exactly `stg_canonical_blocks`
  - Zero `source()` calls
  - Zero references to `bigquery-public-data.crypto_ethereum.*`, `raw_*`, `decoded_*`, or `token_transfers`
  Run as `uv run python scripts/check_analytics_refs.py` — exit 0 = green. Add to `scripts/repro.sh --fixture-only`.

---

## K. Interview-defense — the grilling-readiness check

Codex audit: *"No defense against fake PA/CCIP reconstruction."*

- [ ] **K1.** PA spike fixture (`tests/fixtures/golden_pa_tx/`) contains a REAL Reserves deposit tx hash from mainnet, documented in `docs/protocol-validation.md` § "PA reference tx." If real PA tx unavailable at writer-AI runtime, writer-AI documents this loudly in `SUMMARY.md` as a TODO blocking K1 — does not silently use a fake hash.

- [ ] **K2.** Stake spike fixture (`tests/fixtures/golden_stake_tx/`) contains a REAL Staked tx from mainnet, same documentation requirement.

- [ ] **K3.** `SUMMARY.md` "interview-defendable claims" section lists, for each module, ONE sentence the user can quote when probed (e.g. *"We rebuild the call tree from BQ's flat trace_address rows because BQ doesn't preserve the callTracer nested shape — sorting by trace_address depth and joining children to parents reconstructs the tree."*).

---

## L. Function-level behavioral coverage — every function does what its docstring promises

User addition: *"all functions do what they are expected to do."* This goes beyond the golden-tx tests in Section H — those prove the demo path; Section L proves every function in the core layers.

- [ ] **L1.** Every public function (no leading `_`) in these directories has at least ONE unit test that exercises it:
  - `decoder/` (event_decoder, calldata_decoder, trace_decoder, trace_tree, proxy_resolver, abi_registry, contract_registry)
  - `protocols/staking_v02/`, `protocols/payment_abstraction/`
  - `reconciliation/` (movement_builder, economic_reconciler, balance_reconciler, checks)
  - `lineage/run_metadata.py`
  - `analytics/`
  - `storage/` (where logic exists; pure I/O wrappers exempt)

  Each test must:
  - Call the function with realistic input (a fixture or a constructed dataclass)
  - Assert the return type matches the type hint (e.g. `assert isinstance(result, DecodedEvent)`)
  - Assert AT LEAST ONE specific value in the return matches the docstring's stated contract (e.g. `result.event_name == "Staked"`, or `result.matched_method == "event_log"`)

- [ ] **L2.** Coverage threshold: `uv run pytest tests/unit --cov=decoder --cov=protocols --cov=reconciliation --cov=lineage --cov=analytics --cov-fail-under=70 -q` exits 0. (70% line coverage on the layers that contain real logic. `ingestion/bq` and `storage` excluded — they're thin wrappers around external services.)

- [ ] **L3.** Edge-case tests: each function whose docstring contains a `Gotcha:` / `Note:` / `Warning:` / `Edge case:` annotation has a dedicated test that exercises that exact edge case. Example: `decode_log`'s docstring says *"rejects log where topics count doesn't match ABI"* → there must be a test that passes a malformed log and asserts the rejection.

- [ ] **L4.** No `pytest.skip` / `@pytest.mark.skip` in tests covering Section L functions, EXCEPT tests explicitly marked `@pytest.mark.integration` or `@pytest.mark.requires_rpc` / `@pytest.mark.requires_bq`. When `scripts/repro.sh --fixture-only` runs, every Section L test executes (zero skips); only the integration markers are excluded.

- [ ] **L5.** Property-style sanity for `compute_*_id` functions: a parametrized test feeds 5+ different inputs to each ID function and asserts: (a) all outputs are 64-char hex strings (sha256), (b) different inputs produce different outputs (no collisions in the sample), (c) same inputs produce same outputs (determinism — also verified by H3 at process level).

---

## How a reviewer mechanically verifies each section

```bash
# A: structural
find ingestion decoder protocols reconciliation lineage storage analytics dbt airflow databricks terraform config tests scripts spikes -type f | sort

# B: functional
uv run python -c "import ingestion, decoder, protocols, reconciliation, lineage, monitoring, analytics, storage"
uv run python -m spikes.one_stake_tx_probe --help
uv run pytest tests/unit --collect-only
uv run --extra dbt dbt parse --project-dir dbt --profiles-dir dbt --target ci
uv run ruff check .

# C: correctness
grep -r "0x514910771AF9Ca656af840dff83E8264EcF986CA" -l
grep -r "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef" -l
grep -r "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc" decoder/
grep -rn "hashlib.sha256" decoder/ protocols/ reconciliation/ lineage/

# D: JD coverage
ls airflow/dags/*.py
ls dbt/models/**/*.sql
grep -r "from google.cloud import bigquery" -l
head -3 databricks/notebooks/parity_check.py
grep -r "crypto_ethereum.traces" ingestion/bq/

# E: invariants
grep -rn "run_partition_id" dbt/models/marts/
grep -A2 "def match_action_to_movements" reconciliation/economic_reconciler.py | grep "list\[ActionMovementMatch\]"

# F: defensibility
ls **/WHY.md | wc -l
test -f SUMMARY.md && wc -l SUMMARY.md
```
