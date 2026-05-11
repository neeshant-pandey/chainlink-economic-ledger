# Learning Companion Site — Design Spec

**Date:** 2026-05-10
**Status:** Approved by user, pending implementation plan
**Owner:** Brainstormed with user (Neeshant) via Claude

## 1. Summary

A self-contained, Brilliant.org-quality HTML teaching site that lives inside this repo at `learning/`. It teaches blockchain fundamentals (Bitcoin, Ethereum, EVM) to a user with zero prior crypto knowledge, grounded in two source PDFs (Mastering Bitcoin Programming, Mastering Ethereum 2e) and an existing 50,000-word markdown curriculum in `../teaching-plans/`. A second content tier (Chainlink Project lessons) unlocks incrementally as each phase of the `chainlink-economic-ledger` project ships.

The deliverable is **static HTML/CSS/JS** — no build step, no framework. Open `learning/index.html` and it works.

## 2. Goal & Non-Goals

### Goal
Get the user reading a first lesson, in a polished editorial format, within ~20 minutes of approval. Have all 17 first-wave lessons readable within ~45 minutes. Eliminate "I don't know any crypto" as a blocker on the parent Chainlink interview project.

### Non-Goals (v1)
- Not a public deliverable. This is personal study material; it is not part of the JD submission.
- No build pipeline, no framework, no SSR, no SPA. Pure static files.
- No live simulators (EVM emulator, ABI decoder, signature recovery widget). Reserved for v2 if useful.
- No backend, no authentication, no server-side progress sync. Progress is `localStorage` only.
- No search. The sidebar search box is decorative in v1.
- No dark mode.
- No Chainlink-specific lessons in the first wave. Those are written as the matching project phase ships.

## 3. Visual Direction (locked)

**Direction A — Editorial / Brilliant.org / Quanta Magazine.** Approved via visual companion brainstorm session `50994-1778435169`, mockup `full-layout-v2.html`.

Concrete style anchors:
- **Background:** `#faf7f2` (warm cream) main, `#f4ede0` (deeper cream) sidebar
- **Body type:** Charter / Georgia, serif, 19px, line-height 1.7, max reading-column ~720px
- **Display type:** Charter, 46px, line-height 1.12, weight 700
- **UI type:** -apple-system / Inter, sans-serif
- **Accent:** `#92400e` (warm brown) for in-text emphasis, `#f59e0b → #d97706` gradient for progress bars and illustrations
- **Illustrations:** soft yellow gradient backgrounds, hand-drawn-feeling SVG with brown stroke, captions in sans-serif
- **Pull quotes:** left orange rule, italic body, brown text
- **Check-yourself widgets:** white card, left orange rule, multi-choice radio options (no scoring in v1)

Reference mockup: `.superpowers/brainstorm/50994-1778435169/content/full-layout-v2.html`

## 4. Site Architecture

```
learning/
├── index.html                       # landing, redirects to first lesson
├── _assets/
│   ├── site.css                     # shared editorial styles (all classes from mockup)
│   ├── sidebar.js                   # renders sidebar from manifest; reads/writes localStorage
│   ├── manifest.json                # source of truth for lesson list + ordering
│   └── template.html                # skeleton agents copy from
└── lessons/
    ├── btc/                         # Bitcoin foundations (6 lessons)
    ├── eth/                         # Ethereum foundations (6 lessons)
    ├── evm/                         # EVM deep dive (5 lessons)
    └── chainlink/                   # empty in v1; unlocks per project phase
```

**Page composition.** Each lesson is a standalone HTML file. On load:
1. The page injects `<link rel="stylesheet" href="/_assets/site.css">` (relative path: `../../_assets/site.css`)
2. The page injects `<script defer src="../../_assets/sidebar.js">` which renders the sidebar into a `<div id="sidebar-root">` and wires progress.
3. The main content is inline HTML in the lesson file (so each lesson is self-contained and AI-grep-able).

**Why this composition:** sidebar logic is shared, but lesson content is self-contained. An agent writing a lesson only has to produce the `<main>` block. The sidebar is identical across pages and lives once in `sidebar.js`.

**Manifest schema** (`_assets/manifest.json`):
```json
{
  "tracks": [
    {
      "id": "btc",
      "title": "Bitcoin Foundations",
      "lessons": [
        { "id": "why-bitcoin", "title": "Why Bitcoin exists", "file": "lessons/btc/why-bitcoin.html" },
        ...
      ]
    },
    ...
  ]
}
```

## 5. Content Scope — First Wave (17 lessons)

| # | Track | Slug | Title (working) | Source pages |
|---|---|---|---|---|
| 1 | btc | why-bitcoin | Why Bitcoin exists | MB Ch 1 (PDF 27–40) |
| 2 | btc | keys-addresses | Keys, addresses & wallets | MB Ch 2 (PDF 41–54) |
| 3 | btc | utxo | The UTXO model | MB Ch 2 (PDF 41–54) |
| 4 | btc | transactions | Bitcoin transactions | MB Ch 2 (PDF 41–54) |
| 5 | btc | mining | Mining & proof of work | MB Ch 3 (PDF 55–78) |
| 6 | btc | blockchain | The blockchain itself | MB Ch 3 (PDF 55–78) |
| 7 | eth | what-is-ethereum | What Ethereum is | ME Ch 1 (PDF 19–42) |
| 8 | eth | accounts | Accounts vs UTXO | ME Ch 2 (PDF 43–106) |
| 9 | eth | transactions-gas | Transactions & gas | ME Ch 6 (PDF 280–357) |
| 10 | eth | solidity | Smart contracts & Solidity | ME Ch 7 (PDF 358–421) |
| 11 | eth | defi | DeFi primitives | ME Ch 13 (PDF 619–647) |
| 12 | eth | evm-intro | The EVM (overview) | ME Ch 14 (PDF 648–758) |
| 13 | evm | opcodes | Opcodes & gas costs | ME Ch 14 (specific modules) |
| 14 | evm | storage-slots | Storage slots | ME Ch 14 (specific modules) |
| 15 | evm | logs-events | Logs & events | ME Ch 14 + ME Ch 6 |
| 16 | evm | internal-traces | Internal traces | ME Ch 14 (DELEGATECALL section) |
| 17 | evm | proxy-patterns | Proxy patterns | ME Ch 7 + ME Ch 14 |

**MB** = Mastering Bitcoin Programming.pdf, **ME** = Mastering Ethereum.pdf. Both at `../../Mastering Bitcoin Programming.pdf` and `../../Mastering Ethereum.pdf` relative to repo root.

**Cross-references** = `../../teaching-plans/<NN>-*.md` for each chapter.

## 6. Agent Contract

Every dispatched agent receives the same envelope:

**Inputs to the agent:**
- Output path: `learning/lessons/<track>/<slug>.html`
- Template path: `learning/_assets/template.html`
- Primary source: `../Mastering <Bitcoin|Ethereum>.pdf` with **specific page range**
- Companion source: `../teaching-plans/<NN>-<chapter>.md` (existing curriculum)
- Style guide (embedded in prompt, see §7)
- Lesson scope (title, working summary, what *not* to cover)

**Hard rules (in agent prompt, non-negotiable):**
1. **No hallucination.** Every non-trivial factual claim must trace to a specific page of the PDF. The agent must include an HTML comment `<!-- source: MB p.43 -->` (or similar) above any paragraph that asserts a fact.
2. **Stay in scope.** Don't drift into adjacent topics. If proxy patterns come up while writing the UTXO lesson, link to the proxy-patterns lesson; don't explain proxies inline.
3. **Use the template literally.** Copy `template.html`, fill the placeholders. Do not reinvent the page structure.
4. **One SVG illustration per lesson, minimum.** Hand-rolled, follows the design tokens in §3.
5. **One check-yourself widget per lesson, minimum.** 3 options, only one correct.
6. **One pull quote per lesson.** Compresses the key insight.
7. **No emojis** in HTML body text (decorative emojis in UI chrome like the search box are allowed).
8. **Length target:** 800–1500 words of body text per lesson.

**Outputs:**
- One HTML file at the assigned path.
- An optional `<!-- agent-notes: ... -->` block at the bottom describing tradeoffs, uncertainties, or pages skipped.

## 7. Style Guide (excerpt, full version embedded in agent prompts)

**Voice:** Quanta Magazine + Stripe docs. Curious, precise, never condescending. Assumes a sharp engineer who has zero crypto knowledge.

**Opening pattern:** every lesson opens with a concrete analogy or scenario, then names the technical term. Pattern: "Imagine X. Bitcoin works the same way, but Y. The name for this is Z."

**Sentence rhythm:** vary sentence length. Short. Then occasionally a longer sentence that lays out a chain of reasoning across two or three clauses. Then short again.

**Vocabulary:** introduce every term in italic the first time it's used; never use a term before it's defined. Maintain a glossary footer at the bottom of each page.

**SVG diagram constraints:** viewBox-based, max-width 480px, brown strokes (`#92400e`), white or `#fef3c7` fills, Charter font for labels. No PNG, no external images.

**Page structure (every lesson must have):**
```
<main>
  <div class="eyebrow">Track · Lesson N of K</div>
  <h1>Title (as a question or vivid statement)</h1>
  <p>Opening analogy paragraph.</p>
  <p>Introduce the term in italics.</p>
  <div class="pull-quote">The single sentence the user should remember.</div>
  <p>...more body...</p>
  <div class="illus"><svg>...</svg><div class="illus-caption">Caption.</div></div>
  <p>...continued exposition...</p>
  <div class="check-card">
    <div class="check-label">Check yourself</div>
    <h4>The question</h4>
    <div class="opt">⚪  Option 1</div>
    <div class="opt">⚪  Option 2</div>
    <div class="opt">⚪  Option 3</div>
  </div>
  <div class="next-prev">...</div>
</main>
```

## 8. Progress Tracking

`localStorage` keys:
- `ccl.progress.<track>.<slug>` = one of `"unread" | "active" | "done"`
- `ccl.last-visited` = full lesson slug, used by `index.html` to resume

Sidebar reads these on every page load to render the pip states. Marking a lesson as `done` is automatic when the user scrolls past 90% of the page; can also be toggled by clicking the pip. No analytics, no server, no sync.

## 9. Implementation Sequence

1. **Chassis (single-threaded, me):** write `index.html`, `_assets/site.css`, `_assets/sidebar.js`, `_assets/manifest.json`, `_assets/template.html`.
2. **Dispatch (parallel, 17 agents):** each agent reads its assigned PDF page range + teaching-plan markdown, produces one lesson HTML file.
3. **Review (me):** scan the 17 outputs for style drift, citation completeness, and broken SVGs. Patch any that drifted.
4. **User reads:** `open learning/index.html`.

Estimated wall-clock to first lesson readable: ~15 min (chassis only blocks the index page; lessons load as agents finish).
Estimated wall-clock to all 17 lessons readable: ~45 min.

## 10. Success Criteria

The site is "shipped" when:
- ✅ `open learning/index.html` loads without errors.
- ✅ All 17 lesson pages render with the editorial design.
- ✅ Sidebar shows progress and is consistent across pages.
- ✅ Clicking through next/prev moves through the curriculum in order.
- ✅ Progress persists across page reloads via `localStorage`.
- ✅ Every lesson has: eyebrow, headline, opening analogy, pull quote, ≥1 SVG illustration, ≥1 check-yourself widget, next/prev nav.
- ✅ Spot-checked: 5 random factual claims trace to specific PDF pages via the HTML comment citations.

## 11. Deferred / Open

- **Chainlink Project lessons** — written incrementally as each phase ships. Schema:
  - Phase 1 (raw extraction + ABI decoding) → 3–4 lessons
  - Phase 2 (dbt staging) → 2–3 lessons
  - Phase 3 (PA reverse-engineering) → 4–5 lessons
  - …etc.
- **Search functionality** — sidebar search is a decorative input in v1.
- **Interactive widgets** — live ABI decoder, transaction visualizer, EVM stack walker. Reserved for v2.
- **Dark mode** — possible later; the editorial cream palette doesn't have a clean dark counterpart, would need a separate design pass.
- **Print stylesheet** — not in v1.

## 12. Risks

- **Agent drift on style.** Mitigation: hard-rule the template usage, review pass after dispatch.
- **PDF page-number references rotting.** Mitigation: citations include both page number AND a short verbatim quote anchor.
- **SVG quality variance.** Mitigation: provide 2–3 SVG examples in the agent prompt as templates to follow.
- **Time overrun on agent dispatch.** Mitigation: agents are independent — partial completion still ships a useful site.
