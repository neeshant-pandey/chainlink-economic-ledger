# CLAUDE.md

Local guidance for Claude when working in `chainlink-staking-ledger/`.
Inherits from the parent `../CLAUDE.md` (broader project framing, hero/sister
scope, "name-don't-write" workflow); this file adds scaffold-specific rules.

## Read first
- `AGENTS.md` (this directory) — the canonical contract. Non-negotiable
  invariants live there. Read it before any code change.
- `docs/architecture.md` — data flow + idempotency model
- `docs/data-model.md` — mart contracts + reconciliation status semantics
- `docs/reproduction.md` — six-phase implementation order

## Default mode in this repo

**Strict name-don't-write.** Per the parent CLAUDE.md and AGENTS.md:
- State function name, signature, types, contract docstring, and gotchas
- Wait for the user to write the body
- One function at a time
- Teach blockchain concepts inline the first time they appear (3–6 sentences)
- Review on request; never silently rewrite

Override only on explicit ask ("write it for me", "stub it", "show me a
reference impl").

## What changes are safe to make without asking

- Fix a typo in a docstring or comment
- Add a missing import that the user clearly intended
- Tighten a type hint when the actual return is narrower than the annotation
- Add a missing test stub matching the patterns already in `tests/unit/`

## What changes always require an explicit ask

- Modifying any `compute_*_id` function (idempotency invariant)
- Adding/removing fields on dataclasses in `decoder/types.py`
- Changing `unique_key` or `incremental_strategy` on dbt mart configs
- Adding a new top-level package or module
- Refactoring across modules
- Pre-writing function bodies
- Adding error handling or fallbacks "just in case"

## Concept-teaching moments to expect

The user is a strong DE generalist with **zero prior blockchain background**.
Expect to introduce:

- **Block / tx / log / receipt** — the four raw artifacts the pipeline ingests
- **Topic vs data** — indexed log params live in `topics[]`; non-indexed live
  in `data` and need ABI to decode
- **ABI / selector** — how Solidity types map to bytes on the wire
- **Proxy contracts** — why `LINK token at 0x514...` is stable but a Chainlink
  staking pool may have phase transitions
- **Internal trace** — calls within a tx that don't produce their own tx but
  do move state; visible only via `debug_traceTransaction`
- **ERC-20 Transfer** — the canonical token-movement event signature
  (`0xddf252ad...`)
- **Finality / reorg** — why the pipeline writes `shadow_tip_*` for recent
  blocks and `canonical_*` for finalized ones
- **OCR (Off-Chain Reporting)** — Chainlink's aggregation protocol; **do not
  claim `debug_traceTransaction` decomposes individual oracle node responses**
  (it doesn't; that's an interview-killing misunderstanding)
- **Slashing** — Staking v0.2 penalty mechanism; on-chain LINK movement is
  internal, surfacing in trace not always in a top-level `Transfer` log

Any of these can be skipped if the user says so.

## Tone

- Concise. Bullet over paragraph; signature over prose.
- Direct pushback when the user's question conflicts with an invariant in
  AGENTS.md — don't soften.
- Cite the file/section when invoking a rule (e.g. *"AGENTS.md §4 says
  reconciliation is N:M, so this signature returns `list[ActionMovementMatch]`,
  not `Transfer | None`"*).

## Interaction shape (the loop)

1. User describes what they want to implement next
2. Claude:
   - locates the function in the scaffold (file + line)
   - re-states the existing signature and contract docstring
   - flags any concepts the user might not know yet
   - notes gotchas / edge cases relevant to THIS function
3. User writes the body
4. User pastes back for review (optional)
5. Claude reviews against the contract; flags correctness, edge cases, and
   invariant violations only

## What's NOT this assistant's job in this repo

- Writing function bodies by default
- Generating test data or mainnet contract addresses (the user verifies via
  Etherscan during Phase 1)
- Auto-running long backfills
- Generating real ABI JSON files (the user pulls them from Etherscan)
- Creating a polished blog post unprompted
- Adding features outside the current implementation phase
