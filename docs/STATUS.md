# Implementation status

Pass 1 and its requested discovery-format revision are complete. The revised feed awaits human review. No application has been built, and Gate 1 remains pending.

| Pass | State | Evidence |
| --- | --- | --- |
| 1. Discovery trial | Complete, 2026-09-05 | `.foundry-data/runs/trial-001/` |
| Pass 1 revision | Complete, 2026-09-05 | `.foundry-data/runs/trial-002/`; original trial preserved |
| Gate 1 | Awaiting revised-feed review and explicit decision | New private `feed.md` and blank `review.md`; original method mapping withheld |
| 2. Working application | Not started | None |
| Gate 2 | Awaiting real use | None |
| 3. Calibration and unattended use | Not started | None |

## Current next action

Read `.foundry-data/runs/trial-002/feed.md` and record understanding, interest, possible use and any user-authored idea in its `review.md`. The revision is an editorial change, not another controlled method comparison. Preserve the original run and continue withholding its method mapping. Do not begin Pass 2 without explicit Gate 1 approval.

## Decisions made during implementation

- 2026-09-05: Used the explicitly approved input pack only. Preserved its bytes, versioned source IDs, source hashes and prompt/contract snapshots inside the ignored private run directory.
- 2026-09-05: Ran a **contaminated informal pilot in one shared Codex context**, with six direct outputs and six selections from 24 structured candidates. Contexts were not isolated; generation effort was unequal. No external research, additional API jobs or nested model sessions were used.
- 2026-09-05: Produced the eight required artifacts plus separate method-labelled feeds/JSON, source inspection, a semantic audit and a one-run standard-library renderer/checker. Kept method labels out of the shuffled cards and left all human reactions blank.
- 2026-09-05: Kept exact backend identity, unavailable settings, token counts and cost as unknown. Session instructions identify the GPT-6 family; the requested Astra variant is not independently exposed in backend metadata.
- 2026-09-05: Used existing Python for the permitted artifact script. No application, dependency installation, container workflow, service or other infrastructure was added.
- 2026-09-05 revision: Followed the supplied revision brief found under its matching filename in the selected inputs directory. Kept the original trial and its feedback unchanged. Recorded overall feedback privately without inventing individual ratings or approval.
- 2026-09-05 revision: Produced eight concrete concepts, two speculative concepts and two open provocations. Kept `cards.json` compatible with the existing schema and placed new fields in versioned private `grounding.json`. This mix does not change the product contract.
- 2026-09-05 revision: Performed three bounded primary public documentation checks using generic queries. Evidence supports limited building blocks; unperformed checks, technical gaps and unknown demand are explicit. No extra model jobs, accounts, software installations or proposed experiments were used.

## Commands and checks actually run

- `python3 .foundry-data/runs/trial-001/assemble_trial.py`: rendered the real model-authored trial output and validated all constraint keywords used by the snapshotted card schema. Private `validation.json` records results.
- `python3 .foundry-data/runs/trial-001/assemble_trial.py --check`: passed in a fresh process after final run metadata was saved. `python3 -m py_compile` and `python3 -m tabnanny -v` passed for the artifact script; there is no configured application build or lint pipeline.
- Checks passed for twelve display IDs, six cards per method, source and claim references, original/source/prompt hashes, all retained candidates and exclusion reasons, shuffle mapping, method-free display cards, equal formatting, bounded output and twelve blank feedback rows. Rendered cards contain 157–171 words; the two six-card feeds contain 995 and 973 words under the same counting rule.
- Reread the original approved input and full feed for semantic fidelity. Preserved speculative claims and documented overlapping themes, source limitations and missing external evidence in the private audit. This is a model-authored check, not independent factual validation.
- `git ls-files .foundry-data` returned no tracked private files; `git check-ignore` confirmed all 28 private files checked are ignored. Final privacy and persisted-artifact verification is recorded in the private run.
- No application build, provider integration test or local-model demonstration applies to this pass. The actual demonstration is live model-authored material from the approved seeds, rendered and read back from disk. Human usefulness and Gate 1 remain untested.
- Revision: `python3 -B .foundry-data/runs/trial-002/render_revision.py` and its `--render`/`--check` modes validated the existing card schema, grounding/example/render consistency, the 8/2/2 mix, source and evidence references, predecessor mapping, blank separate review fields and preservation of all 27 original-trial files. Developed cards contain 235–259 rendered words; the two provocations contain 165 and 164. Syntax compilation and `tabnanny` checks passed for the private artifact helper.
- Revision: All new artifacts checked are ignored and none is tracked. The original seeds, revision brief and complete rendered feed were reread for fidelity. These checks establish artifact consistency, not user comprehension, feasibility or demand.

## Known limitations

The original shared generation context and unequal effort prevent an independent comparison. The revision does not rerun that comparison. Three public checks establish what their primary documentation describes; no proposed product or next test was executed. Structural validity and source-reference resolution do not prove truth or usefulness. Novelty, market demand and user comprehension remain unmeasured. Usage and cost are unknown. No gate has been approved, and no later pass has begun.
