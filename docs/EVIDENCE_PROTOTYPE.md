# Personal evidence and practicality prototype

This focused experiment precedes any full application build. The current user request authorizes a local core and review artifacts, with exactly three example evaluations. It does not authorize automatic ingestion, more candidate generation, model endpoints, services or the old Pass 2 implementation.

## Implementation contract

- Preserve source bytes and versions. Each personal claim cites an exact excerpt, records whether it is stated, reported, observed or inferred, and keeps confidence separate from truth. Generated material is excluded from personal evidence, including through derived sources.
- Keep user corrections, exclusions and contradictions visible. Repetition is not independent corroboration. Self-reported experience is separate from inspected contributions. Unknown facts stay unknown.
- Load an editable JSON policy for every evaluation. Hard constraints and uncertainty are independent of weighted preference summaries. Show criterion-level reasons, evidence, costs, alternatives and the experiment that could resolve uncertainty.
- Use separate personal, commercial and creative policies. Weights express the user's chosen emphasis, not probabilities. Outcomes attach to the tested idea and scope; they do not generalize silently to a personality or preference.
- Save append-only revision snapshots and an atomic current-state pointer. Store real sources, examples, outcomes and local configurations only in ignored storage. Use synthetic fixtures for automated checks and any unperformed outcome demonstration.

## Acceptance checks

Validate source links and hashes, indirect generated-evidence contamination, contradictory/rejected claims, malformed imports, conservative missing-evidence handling, distinct category policies, live configuration changes, range/payback arithmetic, outcome attribution, proposal-only learning, budgets and interruption-safe persistence. Run the native CLI on the approved private inputs, preserve both old trials, and produce a profile, three evaluations, a tuning comparison, learning demonstration and blank review.

## Use it locally

Python 3.13 or newer is sufficient. There are no runtime dependencies, model downloads, services or network calls. The private review run has its own README under `.foundry-data/prototypes/personal-evidence-001/`. Its source selection and personal data are deliberately absent from tracked examples.

```bash
python3 -B -m foundry --help
python3 -B -m foundry --store .foundry-data/evidence init --bundle .foundry-data/selected-bundle.json
python3 -B -m foundry --store .foundry-data/evidence profile --output .foundry-data/profile.md
python3 -B -m foundry --store .foundry-data/evidence evaluate --policy .foundry-data/practicality.json --output .foundry-data/evaluations.md
python3 -B -m foundry --store .foundry-data/evidence validate
```

`init` requires a new directory and an explicitly prepared bundle; it does not scan files or infer a profile. Copy `config/practicality.default.json` to a private policy file before evaluating a new store. Run from the repository root. Omit `--output` to read on the terminal, or use `evaluate --json` for structured output. Existing Markdown/JSON reports are snapshots; rerender explicitly after edits. Every evaluation records the complete state's and policy's SHA-256 hashes.

## Correct personal evidence

Put your correction in a private plain-text file, then select the claim and action:

```bash
python3 -B -m foundry --store .foundry-data/evidence correct --claim C1 --action reject --statement-file .foundry-data/correction.txt
python3 -B -m foundry --store .foundry-data/evidence profile --output .foundry-data/profile.md
```

The CLI preserves your text, assigns a source ID/hash, records the correction, and writes a new state revision. `reject` marks an unsupported/corrected proposition; `exclude` removes it from evaluation without asserting falsehood; `reinstate` is an explicit user reversal. Original text and earlier versions remain distinguishable. Rejection is not the assertion of an opposite identity. To add a replacement or confirmation, `add-claim --input` accepts `{"sources": [...], "claim": {...}}` with new immutable source IDs. It never promotes an idea record into a claim.

Exclusion is removal from active use, not secure deletion of the source or revision history. This prototype does not implement a privacy-erasure workflow. Claims using a rejected, excluded, tentative or contradicted personal attribution become unknown in future evaluations. Previous idea estimates remain preserved. A generated source, including any descendant of one, cannot support any personal claim, even a tentative claim. A genuinely new user confirmation must be independently attributed to the user, not copied from a generator or linked as its derivative.

## Edit practicality without code

The three sections in the JSON file are `policies.personal`, `policies.commercial` and `policies.creative`. The CLI validates and reloads the file on every evaluation. There is no cached model profile or retraining. Invalid edits stop the evaluation rather than silently falling back to old settings.

| Configuration | Meaning | Later TUI control |
| --- | --- | --- |
| `hard_constraints` | Named fact, `le`/`ge`/`eq` operator, limit, optional unit, experiment/implementation scope, reason | Toggle or bound editor with source/rationale beside it |
| `criteria[].weight` | Integer 0–5 emphasis; zero retains visibility but contributes no weight | Slider or stepper |
| `priorities` | Explicit display order of all criterion IDs, independent of weight | Reorder list |
| `criteria[].rule` | Supplied qualitative assessment, or numeric `lower`/`higher` bands with units | Rule selector and editable band limits |
| `required_facts` | Evidence gaps that must remain visible; assumptions are still gaps | Evidence checklist |
| `learning` | Transparent proposal threshold and suggested smaller setup cap | Proposal settings and explicit accept/edit action |
| `basis` | Provenance of this policy: user statements versus suggested defaults | Explanation/editor |

For example, changing the personal `experiment_time` limit from 30 to 10 minutes immediately excludes a proposed 15–25 minute first test. No other category needs to change. A range straddling a hard limit remains unknown. A wrong unit or boolean type remains unknown. Unknown constraints do not pass; a failed constraint cannot be offset by weights. Changing a weight changes the displayed emphasis distribution, not a success probability. Priorities control review order and do not secretly alter weights.

The weights sum into four visible buckets: strong, moderate, weak and unknown. There is deliberately no overall viability score or inter-category ranking. Qualitative assessments are fallible, supplied judgments with reasons. Numerical bands use the less favorable end of a range. A strong fit band may have weak confidence and an assumed basis; the report shows both. Defaults are conservative demonstration choices, not inferred facts about the user or authorization to conduct an experiment.

Personal time payback uses `setup / (frequency × saving per use − ongoing effort)` with compatible units. Its favorable and unfavorable bounds use the corresponding ends of each input range. If conservative net benefit is nonpositive, payback may never occur. If inputs are missing or exceed finite arithmetic, it is unknown. Cash is reported separately, avoiding double counting time and its monetary equivalent. The commercial policy requires buyer, alternative, switch, acquisition, support, maintenance, communication, skills, enthusiasm and evidence inputs. Creative policies use attention and actual thoughts/saving/revisiting; no required financial return belongs there.

Readiness is deliberately limited: an experiment can be within configured estimated limits while implementation still fails a constraint or lacks evidence. The prototype does not certify an idea as researched, profitable or proven, and does not perform the proposed experiment.

## Record actual outcomes

Write your report in a private text file and the associated details in JSON. This synthetic example illustrates the contract; it must not be imported as real user history:

```json
{
  "idea_id": "P1",
  "event": "prototype_built",
  "occurred_at": "2026-09-05T12:00:00+00:00",
  "scope": "Synthetic weather-photo index example",
  "reason_code": null,
  "metrics": {
    "implementation_minutes": 45,
    "actual_usefulness": "moderate",
    "continued_usage": null,
    "money_earned": null,
    "reason_abandoned": null,
    "user_rating": "moderate",
    "unexpected_costs": "Additional manual labeling time",
    "useful_thoughts": null,
    "saved": null,
    "revisited": null
  }
}
```

```bash
python3 -B -m foundry --store .foundry-data/evidence record-outcome --details .foundry-data/outcome-details.json --statement-file .foundry-data/outcome.txt
python3 -B -m foundry --store .foundry-data/evidence proposals --policy .foundry-data/practicality.json --output .foundry-data/proposals.json
```

The text-file form always records `user_report`; it never upgrades self-report to measured fact. The complete `--input` contract is `{"sources": [...], "outcome": {...}}`. An outcome adds `id`, `method` (`user_report` or `measured`) and source excerpts to the fields above. Measured records require an observation/outcome source with the relevant excerpt. Attribution is checked structurally, not independently authenticated.

Events are `explored`, `rejected`, `prototype_built`, `used`, `abandoned`, `rated`, `saved` or `revisited`. Use null or omit an unobserved metric; never substitute zero. Useful/rating levels are `none`, `weak`, `moderate`, `strong`; usage, saving and revisiting are booleans. Commercial money records include `amount`, `currency` and `period`; they are not automatically revenue forecasts or profit. Unexpected costs and abandonment explanations remain free text. Do not add up repeated implementation-time reports: each states a total for its scope. Rejection of an idea is an outcome; rejection of a personal interpretation is a separate correction.

For the same idea, outcomes add explicitly named actual fields and affect configured criteria such as actual usefulness, saving or revisiting. Original estimates are retained. Latest nonempty fields are selected by occurrence time (ID breaks ties), with their method, date, scope and complete prior event history visible. No automatic causal generalization or change to personal claims occurs. Different scopes, stale reports and conflicting observations still require human interpretation.

The initial pattern rule considers personal ideas abandoned for `unexpected_time` when reported implementation exceeds the original setup estimate. It needs at least `learning.min_distinct_ideas` distinct ideas with distinct source origins; repeated logs or identical imported text are not independent evidence. It proposes the configured smaller cap only if it is lower than the current one. The proposal cites event IDs, actual/estimated time, reasons, excerpts and alternative explanations. It never writes the policy. Accepting a suggestion requires explicitly editing the configuration. No proposal is fabricated from an empty history. The private trial demonstrates this rule using a separate synthetic store.

## Data and trust boundaries

`foundry/validation.py` is the strict, versioned contract. Unknown fields, malformed JSON, duplicate IDs/JSON keys, nonfinite numbers, missing/incorrect excerpts and hash mismatches are rejected. Contracts deliberately remain small rather than introducing a schema framework.

| Object | Essential fields |
| --- | --- |
| State bundle | `schema_version: 1`, `sources`, `claims`, `ideas`, `outcomes`, `corrections` |
| Source version | `id`, `kind`, `origin`, `version`, verbatim `text`, `sha256`, `locator`, `parents` |
| Claim | `id`, canonical `key`, `facet`, `kind`, `text`, `stance`, `confidence`, `status`, `sources`, `contradicts` |
| Source reference | Exact `source` ID and `quote` substring from that source version |
| Idea | `id`, `category`, `title`, `description`, `inspiration`, `facts`, `alternatives`, `experiment` |
| Fact or estimate | `value`, `basis`, `confidence`, `reason`, `sources`, `claim_ids`, optional qualitative `assessment` |
| Range value | Nonnegative ordered `low`, `high`, `unit` |
| Alternative | `name`, `tradeoff`, optional-empty `sources` |
| Experiment | `question`, `scope`, `success`, `failure`; its costs appear as facts |

Source kinds are `user_statement`, `user_supplied_summary`, `observation`, `outcome`, `generated`. Claim kinds are `explicit`, `reported`, `observed`, `interpretation`. Facets cover interests, claimed/demonstrated skills, active/previous projects, previous ideas, goals, preferences/constraints, observed activity and context. Observed skills require an observation source, not a reported project. Fact bases are `unknown`, `assumption`, `supported`, `measured`, `user_report`; unknown values must be null. Support and measurement need nongenerated source excerpts.

All imports are explicit local attestations. A hash proves byte identity, not authorship, truth, or semantic entailment. A person can still misclassify a pasted model statement as user speech; the prototype does not claim to detect that deception automatically. The current private bundle was manually checked against the supplied sources. No account, source scraper, embedding index or automatic extractor exists.

Source ancestry prevents a generated idea being laundered through a derived summary. Shared origin groups and identical text do not add independent support or confidence. Contradictions use explicit edges or opposing stances on the same canonical key. Both sides are withheld until corrected; the software does not use a vote to decide truth. A rejected key and stance cannot return under a new claim ID. Correcting an inference preserves any independently sourced opposite statement; it does not invent one. Paraphrases assigned different keys require human review, not a claim of perfect semantic detection.

## Persistence, budgets and verification

`storage.py` writes immutable JSON revisions with a parent pointer, reason and timestamp, then atomically replaces a small current pointer. Linux advisory file locking serializes writers. A crash before pointer replacement leaves the previous revision current; an orphan revision can remain for inspection. Loading checks the revision hash and complete data contract. Invalid changes do not commit. Sources live inside revisions as well as the trial's separate original snapshots; replacing a report does not erase source history.

The prototype is limited to three supplied ideas, 200 sources, 200 claims, 1,000 outcomes, 500 corrections, 60 facts per idea, 24 criteria and 16 constraints per category, and 2 MB per JSON input, stored revision or rendered output. It has no candidate generator, model retries, paid requests or background process. Expansion is deferred to review, not hidden behind a larger budget knob.

`make check` builds the development-only Python container without network access and runs synthetic tests. Build checks compile source and run the standard-library indentation linter (`tabnanny`); no third-party style/type linter is installed. Unit and subprocess checks cover provenance, correction and contradiction handling, configuration reloads, ranges/payback, outcomes, proposals, malformed data, budgets, persistence and interrupted writes. Synthetic fixtures prove software behavior, not personal truth or live model/provider capability. The actual demonstration is the current session's three manually authored evaluations rendered by the real CLI on approved private sources. Token usage and monetary cost are unknown.

The review gate remains human: assess the personal profile, the three category evaluations, the tuning comparison and the separate outcome demonstration before authorizing ingestion, scaling or a full application.
