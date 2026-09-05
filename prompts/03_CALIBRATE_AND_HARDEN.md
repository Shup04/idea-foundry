# Pass 3 — make it worthwhile to leave running

Read the repository instructions, product contract, build plan, implementation status, actual code and the user's Gate 2 feedback. Do not claim approval if it has not been given. Preserve the existing application and private state.

This pass combines feedback calibration, model evaluation, unattended operation and final hardening. Its purpose is NOT more generation volume. It is more useful material per unit of the user's attention.

## Decide from actual use

First identify concrete successes and failures in the user's feedback. Distinguish repetitive topics, weak raw material, forced analogies, unsupported factual premises, poor UI, and an inadequate local model. Do not solve every problem by adding agents or prompts.

Implement a short, evidence-based change list. Keep a simple generator if it performed as well as the multi-stage one. The user remains the source of preference labels.

## Personalization without an echo chamber

Use inspectable explicit preferences and a small set of relevant positive/negative examples in the context. No fine-tuning or claimed understanding of the user's emotions. Keep preferences versioned, editable, resettable and limited to this project.

Protect a configurable exploration fraction, initially around 20%, for unfamiliar territory. This is a product policy, not a scientific optimum. Don't score everything only by similarity to past favourites. Retain rejected candidates. A neglected card can be revisited, but unchanged repetition should not masquerade as a new discovery.

When revisiting an old seed, record what changed: another source, a different assumption, a new user idea or newly supported evidence. No automatic promotion of prior model guesses into facts.

## Test the model and the method separately

Build a small repeatable evaluation harness using held-out seed sets and the common card contract. Compare a direct strong-model prompt, the selected Foundry loop with a strong model, and the same loop with the user's local model when available.

Use fresh contexts that don't reveal the competing candidates. Keep source sets, display format/count and user reading budget equal. Record differences in calls, token budget, model settings, tools, latency and available usage. A direct baseline must not be intentionally restricted to a weaker model.

Strong-model runs can use manual Codex export/import. Use scripted Codex/API calls only after explicit user permission for the additional execution and usage. Never copy authentication files or bypass sandbox/approval controls. If independent contexts aren't available, label the result exploratory rather than a clean comparison.

Randomize the review order and withhold condition labels until reactions are captured. Measure useful-card reactions, user-authored follow-on ideas, duplicates, forced connections, unsupported factual claims, reading effort and actual resource usage. Unknown usage remains unknown. Do not fit and evaluate on the same feedback examples without disclosing overlap. Small samples provide directional personal evidence, not universal superiority claims.

If local output is weaker, offer a fixed hybrid profile: local models for extraction/deduplication or bounded expansion, strong models manually for selected exploration. Do not conceal the quality difference or insist on local-only operation.

## Bounded background worker

Add an optional worker process that continues independently of the TUI, with an optional Linux user-service example. Installation/enabling of a service requires the user's explicit action. The foreground application should still run without it.

Use durable jobs/checkpoints and one active generation by default. Enforce call, elapsed-time, candidate, output and unread-feed limits. Never run indefinitely because the computer is idle. Pause low-value delivery when the user has an unread backlog. Allow explicit deeper exploration of a chosen branch.

Provide Paused, Low and Normal modes with documented actual effects; do not pretend the application can cap all GPU activity without runtime support. On ordinary pause finish and checkpoint the current bounded call/stage. Explicit cancellation may discard the incomplete call but must retain completed work. Do not claim generation resumes mid-token.

When the worker is active, coordinate mutations through a single writer or a similarly simple tested ownership mechanism. Avoid repeating the earlier project's SQLite lifecycle-lock failure: no inference while holding write locks, explicit transaction lifetimes, short bounded contention handling, deterministic shutdown ordering and restart tests. Do not merely swallow database errors.

No cloud fallback, unapproved background paid calls, filesystem surveillance, company-repo access, or new connector permissions. Background generation requires an explicitly configured usable profile. Missing providers become a clear stopped/blocked job, not a successful empty result.

## Research handoff

Provide an export to investigate a selected idea with Codex: the seed, competing interpretations, exact claims needing verification, and questions about related work and cheap tests. The user reviews private material before launching the research.

Import actual evidence and source references, retaining retrieval dates and short supporting excerpts. Mark unsupported claims. A model-supplied URL alone is not verified evidence; establish what was fetched and what claim it supports. Do not claim that unsuccessful searches prove originality.

If the research runner lacks browsing, it must say so and provide an unanswered brief instead of fictional research. Do not build a new web search platform in this pass. Proposed code or real-world experiments remain proposals; automatic experiment execution belongs to another project.

## Hardening and acceptance

Test interruption during every important stage, duplicate enqueue/retry handling, budget exhaustion, provider outages, unsupported response formats, missing/corrupted artifacts, state migration, concurrent reading, graceful worker/TUI shutdown and restart, and restoring an exported backup into an isolated directory.

Do not auto-repeat an externally billed request whose completion is uncertain. Record uncertainty and request review. Keep logs and notification content private by default; generic completion counts are sufficient for desktop notices.

Recheck the TUI with actual discovered material, not only synthetic one-line fixtures. Make presentation concise and source inspection fast. Remove stages/features that fail to justify their complexity.

## Final report

Update STATUS with actual results. Report software acceptance separately from discovery usefulness and from model comparisons. Do not declare commercial viability, uniqueness, emotional intelligence, or superhuman productivity.

Recommend one of: continue with local profiles; use a fixed hybrid approach; simplify to the library plus strong-model workflow; or archive because it is not earning attention. The decision belongs to the user. Preserve a clean JSON/Markdown integration boundary for a future OS layer, but do not start that integration.
