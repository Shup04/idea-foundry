# Idea Foundry — three substantial passes

**Status:** Pass 1 review artifacts completed on 2026-09-05; Gate 1 awaits the user. Passes 2–3 have not started. See `docs/STATUS.md` for execution evidence. This is an implementation and learning plan, not an application.

## Operating rule

Group work by a complete user-visible result. Codex should carry each pass through its internal design, implementation where appropriate, tests and demonstration. The human intervenes at the two main product gates and for permissions or genuinely missing inputs. Internal tests and checkpoints are not eight additional milestones.

Do not promise that a pass fits in one context window or lasts one hour. Save concise state so a session can continue without reopening settled decisions.

## Before Pass 1: small human seed pack

Create `.foundry-data/inputs/SEEDS.md` from `templates/SEEDS.md`. Provide roughly 10–15 short inputs, including things you admire or find puzzling, interesting mechanisms, abandoned ideas and speculative questions. Include a few liked and disliked examples with reasons. These are not required to be annoyances.

The file's `approved_for_codex` field must reflect your actual permission. Keep company-confidential information out of this trial. The builder is a cloud-backed Codex session, even though the eventual application may run locally.

A local model does not need to be installed for Pass 1.

## Pass 1 — discovery trial, not software scaffolding

**Prompt:** `prompts/01_DISCOVERY_TRIAL.md`.

### Objective

Produce enough real output for the user to judge the premise BEFORE building another platform.

### Deliverables

Inside a private trial directory, preserve the source snapshot, source IDs, two small feeds, candidates and selection reasons, a shuffled review feed, a method map kept out of the initial review, and a blank review file.

Generate six cards using a direct strong-model approach and six using the structured Foundry loop. Both use the same seeds and display format. The structured loop may generate up to 24 intermediate candidates before selecting six. Use fresh generation contexts when available; otherwise explicitly call this a contaminated pilot, not an independent comparison. Do not conceal unequal generation or search budgets in the result.

No web access is necessary in this first comparison. Unverified external claims remain hypotheses or needs-research. The purpose is to isolate whether the exploration format supplies better creative material.

The user reviews the twelve cards without method labels, marks useful material, and writes what thought it triggered. Only then reveal which method produced which output. This is an informal personal pilot, not a blind scientific study.

### Gate 1: user decision

Proceed only when the user approves one of these:

- Continue with the structured loop because it offers useful differences.
- Continue with a simpler direct-prompt generator because the library/review workflow is still worthwhile.
- Revise the discovery approach once before deciding.
- Stop development because neither output justifies it.

A suggested positive signal is two worthwhile cards and one direction to explore. Do not let a model grade its own output and declare the gate passed.

## Pass 2 — build the complete useful application

**Prompt:** `prompts/02_BUILD_V1.md`.

### Objective

Turn the approved discovery experience into a usable local application in one coherent build.

### Build together

Input/library management; source and observation persistence; the selected exploration loop; safe schema validation and source-reference checks; model-provider interface; manual exchange with Codex; one local HTTP adapter; polished TUI feed and detail views; feedback; capture of user-authored ideas; branch exploration; run/context inspection; export/import; and automated tests.

Default to a native Linux application with a small Python core, SQLite and Textual. Exact package versions must be checked, pinned and documented by the builder. No separate daemon, Docker requirement, graph renderer or complex GPU installation belongs in this pass.

Suggested interface: Feed, Library, Explore and Runs. Provider settings and context inspection can be panels rather than additional large screens. Design spacing, typography, focus states, keyboard help and empty/error states now, not after eight more milestones.

### Runtime paths

1. File exchange lets the user export an exploration brief, run it manually in Codex, and import the response. It must work without a local model.
2. A local HTTP profile runs the bounded loop directly when the user supplies a real endpoint/model. Verify health and capabilities; don't assume every compatible server implements identical schema/token features.
3. Do not add unattended Codex calls or API billing as a workaround for a missing local model.

For local generation use one active model request at a time. Preserve stages already completed on errors. Show actual token usage where available and clearly labelled estimates/unknowns otherwise. Do not hold a database write transaction during inference.

### Required acceptance checks

- A new user can launch a populated synthetic demo and operate the actual feed, not a UI mock.
- Text and Markdown sources import with stable IDs and versioned originals; repeated imports do not duplicate unchanged content.
- User feedback and user-authored ideas survive restart and export/import.
- Each displayed card resolves its source references, and speculative claims remain visibly labelled.
- The selected loop is bounded by call, candidate, output and elapsed-time limits.
- Bad JSON, refusal, timeout, invalid IDs or a missing provider yield visible partial/failure states, not fake success.
- TUI interaction continues during model work; keyboard focus, resize and details are tested.
- Excluded candidates remain inspectable and novelty/market scores are not fabricated.
- No unapproved cloud/network call or access outside selected data occurs.
- Private runtime files are untracked and ignored; source/tests use synthetic fixtures.
- Automated tests are accompanied by a real model demonstration OR a clearly labelled not-yet-run live check. Mock success cannot be reported as live validation.

### Gate 2: user decision

Use the result with personal seeds over a few sessions. Is it producing worthwhile material in a form you prefer to a plain chat? Does source inspection work? Is feedback quick? Is the local model useful at any of the assigned tasks?

Only after this review choose whether to invest in unattended operation. Keep the user's reactions in private data; keep the generic implementation status in `docs/STATUS.md`.

## Pass 3 — calibration, unattended use and hardening

**Prompt:** `prompts/03_CALIBRATE_AND_HARDEN.md`.

### Objective

Make a useful system improve and run unattended within clear limits. Do not use automation to conceal a weak discovery loop.

### Build together

Inspectable preference retrieval from real feedback; controlled diversity and a wildcard quota; avoidance of unchanged repeat cards; revisit scheduling that records what is new; a durable worker with checkpoints; optional Linux user-service setup; pause/low/normal controls; a small delivery quota; recovery and export/restore checks; and a model/loop comparison on held-out seeds.

The worker and TUI must not compete with unsynchronised SQLite writes. Keep a single coordinated writer while the worker is active, or an equally simple tested design. Do not hold database locks across inference. Restart/resume must not duplicate completed stages or automatically repeat paid calls.

Start with one unfinished generation at a time. Complete the current bounded call/stage on ordinary pause and persist it; an explicit cancel may terminate the request. Do not claim a partially generated response resumes mid-token unless the provider actually supports it.

The worker is opt-in and scoped to the imported corpus. It does not browse files, send email, change company repositories, or autonomously expand cloud spending. If no runtime profile is configured, disable unattended inference clearly and retain the manual workflow.

### Evaluation

Use user-feedback examples for calibration, but hold out different seeds for evaluation. Compare:

- Direct Astra prompting on the same source bundle.
- The selected Foundry loop with a strong model.
- The same loop with the chosen local model, when available.

Use equal displayed-card counts and a similar reading budget. Record model, prompt, sampling, search permissions, call/token budgets and available costs. Hide method labels during the user's review. A fresh generation context is necessary for a clean comparison. Small samples are directional evidence only.

Record worthwhile cards, sparks leading to user-authored ideas, forced connections, factual errors, duplicates, reading time and compute usage. Never train/evaluate on identical examples without labelling the overlap. Model scoring is not the user's verdict.

### Release decision

- Strong and local results useful: choose fixed local profiles for appropriate features.
- Strong useful, local weak: retain manual/hybrid use or move local models to bounded utility jobs.
- Simple prompting equally useful: remove stages that add cost without better output.
- Neither useful repeatedly: archive the experiment rather than extending the platform.

## Outside all three passes

Whole-life ingestion, company surveillance, Slack/email connectors, automatic purchases, broad shell actions, actual emotion simulation, fine-tuning, giant knowledge graphs, commercial claims, automatic code experiments and merging into an OS layer. Preserve a small export/import interface so integration can be considered later.

## Where Codex may decide without asking

Module names, exact compatible package versions, reversible UI layout, local schema details, test fixtures and small refactors inside the approved scope. Document the decision and proceed.

## Where the user decides

Actual taste, input privacy, provider credentials, cloud budgets, permission changes, whether the discovery loop earns another build pass, and whether to continue at all.
