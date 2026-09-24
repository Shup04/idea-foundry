# Idea Foundry — understand me first

The current product is a **personal knowledge graph**. Build a useful, inspectable picture of your skills, experience, preferences, personality, values, working habits, goals and circumstances. Business idea generation and validation come later, after you are happy with this foundation.

## Launch

```bash
.venv/bin/python -B -m foundry ui
```

Your existing uploads and reviewed statements are reused. On **Home**, choose **Add information** to paste anything you want the graph to remember. You can describe several topics together without choosing categories. **Files and context** lets you select exact UTF-8 text, Markdown, JSON or CSV files and optionally name an existing experience. **Preview** shows the selected content and relevant existing knowledge, then **Save & understand** saves the original before requesting suggestions. **Save locally** works without AI. Home starts with **About me as a whole** and a useful broader question; choose a specific experience in the same selector for a project question.

- **View map** opens the interactive solar graph in your browser. Select a skill to see the experiences it connects.
- **About me** presents your direction, preferences, ways of working, circumstances, experience and scoped skills. Search it to see matching reviewed statements and exact supporting passages. Missing context and unresolved questions are visible without a completeness score.
- **Review suggestions** shows imported interpretations for you to accept, correct or reject. Your own answers are saved directly.
- **More** holds occasional tools, with a short explanation beside each. **Experience details** contains supporting evidence, skill descriptions and GitHub imports for the selected experience. Other choices let you add an experience, tell the app something, update circumstances, import files, revisit sources, or browse/correct/export records. **Back to home** returns to the next question.

Under **Experience details**, **Describe skill** records a skill's role, what you can explain/adapt/design/debug, assistance used, and an example. **Connect another skill** also supports subject knowledge and people skills. **Update my circumstances** keeps broad priorities and constraints with an optional check-in after 90 days; **Ask me later** postpones for 30 days.

Under **Sources and extraction**, **Read listed details locally** reads structured resume data (`master_skills`, `projects`, `experience`) in JSON or a single Python literal assignment. It never executes that text. Free-form notes use **Extract with Codex**, an explicitly approved manual handoff. Both routes stage suggestions for review.

No model is needed to save information, extract supported resume literals, search reviewed evidence, review details, connect statements or export your graph. The unified input flow uses the optional OpenAI integration below; the older Sources screen retains its manual Codex extraction route. Foundry launches no provider process and scans no directories. The external Codex session's permissions are outside the app's control.

### Understand your answers with OpenAI

If AI is not configured, open **More → AI understanding**, choose a total API spending cap and save it. An existing configuration and cap are reused. New information and project answers use **Save & understand**. The original is saved first; a failed request never loses it. **Review suggestions** distinguishes new details, additional evidence, updates to existing records, answered questions and possible conflicts. It shows the proposed change, existing wording, exact evidence, scope and uncertainty. Accept confirms the displayed change. Correct keeps your wording without inheriting an unreviewed relationship or reconciliation action.

Long inputs are split into sections without dropping characters. Each section can yield up to 12 atomic facts plus quoted passages the model says it could not represent. That report is useful for review, not a guarantee that every meaning was captured. **Add information → Continue saved information** resumes remaining sections after a large import or interruption. About me shows pending sections and flagged passages. Import up to eight files, 100,000 characters per input and 200,000 total per selection. Binary documents need a text export. Reimporting unchanged input does not start duplicate work.

The model compares incoming evidence with a bounded set of relevant reviewed records and canonical entity names. It can propose resolving an old uncertainty, adding evidence to an existing fact, updating a changed circumstance, or flagging a genuine conflict. Different projects or historical periods are not automatically contradictions. Supporting evidence appears under one current fact; accepted updates preserve the old record in history. Rejecting the accepted update restores the earlier projection when its evidence remains usable. All originals and model replies remain available for audit. Semantic interpretation still needs your judgment.

The key stays in the launch environment: `OPENM_AI_API_KEY` takes priority, with `OPENAI_API_KEY` as fallback. No key is stored in configuration, exports or logs. Default interpretation model: `gpt-6-sol`; optional models: `gpt-6-luna` and `gpt-5.4-mini`. Embeddings use `text-embedding-3-small` at 384 dimensions and are cached locally. **API usage is billed separately from Codex subscription usage.**

Each unified input action makes at most three interpretation calls of up to three sections each, with durable checkpoints. Cloud context includes only those selected sections, titles/questions, bounded relevant reviewed profile statements and canonical names. It does not read raw repository code, follow links, scan directories or include whole unselected sources. A changed preview must be refreshed before sending newly retrieved context. The adapter uses fixed OpenAI endpoints, `store: false`, no tools and no automatic retries or provider fallbacks. It runs on explicit actions, never at startup or on a timer. Pause it from the same menu.

The total spending cap persists across restarts. Before a call, Foundry reserves a conservative estimate based on request bytes, output limits and published standard rates. Reported tokens replace that reservation with a cost estimate; unknown or interrupted calls retain the full reservation. Estimates are not invoices or account-wide billing controls. Current rates are recorded in `openai_api.py`; update them if provider pricing changes. Source: [OpenAI pricing](https://developers.openai.com/api/docs/pricing).

Accepted facts add shared skills, explicitly named experiences, interests and other scoped connections to the solar map and portable graph. Evidence of enjoying an activity does not establish skill depth. Explicit manual skill descriptions take precedence over accepted AI suggestions. Previously cached related answers remain retrieval hints; embedding similarity never creates a confirmed relationship. The unified route uses local retrieval of reviewed graph context without requiring another embedding call. Corrections and excluded answers remove their derived connections from the current view. Old answers that did not save the full question are identified as having reconstructed question context.

Terminal-free setup and use are also available:

```bash
.venv/bin/python -B -m foundry understand --preview
.venv/bin/python -B -m foundry understand --budget 1 --run
.venv/bin/python -B -m foundry understand
.venv/bin/python -B -m foundry understand --pause
```

These `understand` commands retain the earlier interview-only contract for compatibility (up to eight answers per run with cached embedding retrieval). Use **Add information** for the richer contextual workflow. The `--budget` value is the cumulative cap, not an additional allowance. `--answer ID` restricts the legacy run to selected interview answers. Saved completed replies are reused where possible. Idea generation remains deferred.

### Private GitHub evidence

Choose an experience on Home, then **More → Experience details → Import from GitHub**. Choose **Load my repos**, select a repository, choose files, then import. Foundry uses the existing `gh` login and lists repositories owned by that account, including accessible private repositories. If needed, sign in separately with `gh auth login --hostname github.com --web`; credentials remain with GitHub CLI.

Only the selected repository's metadata, file tree and up to 20 recent commit summaries are read before file selection. Import reads 1–8 selected UTF-8 source files, at most 20 KB each and 80 KB total, pinned to Git blob hashes and a commit. Symlinks, common dependency/build directories and obvious credential paths are excluded. Filenames are not a guarantee that a file contains no sensitive data: choose files you want stored locally. The app never clones, builds or executes repository code. It does not infer mastery from language percentages, commit authorship or unfinished status.

Imported files are available under **Sources** for a separately approved manual Codex handoff. Code-topic assessments are suggestions for **Review**. Accepted code topics can connect to a project while personal depth remains unknown. Corrections retire the proposed connection; connect the corrected topic explicitly if appropriate. AI assistance is described per project/skill, with no automatic penalty or global ability score. No automated repository analysis/provider backend or background sync is installed.

F1 opens the walkthrough; F2 shows workspace details. Tab/Shift+Tab moves focus, arrows navigate the graph, Enter selects, Escape closes dialogs, and Ctrl+Q quits. A 100-column, 35-row terminal is comfortable; smaller windows scroll.

## Your data

The default workspace is `.foundry-data/workspaces/personal/`. Personal data and exports remain ignored by Git. Original input versions, source hashes, model replies, review history, rejected statements and retired connections are retained. Historical idea data is preserved but absent from the active workflow.

A statement is a graph node with an area, attribution, source passages, review state, and optional context/dates. Directed relationships connect statements. Source nodes preserve the evidence trail. Conflicting, expired, future, tentative and unreviewed statements are withheld from the current profile. **All history** exposes retained statement history; **Review history** exposes earlier suggestions. New versions of a source produce a review notice without silently rewriting the earlier claims.

The experience map adds canonical named experiences and skills over that evidence. Repeated names and known aliases share a node; explicit tool/subject mentions create connections marked as needing context. Mention count, node size and distance never measure ability. A university named as an employer stays a research/work record; add an Education experience to describe actual study. Automatic grouping currently understands the supported resume format and explicitly added entries; it is not a general semantic identity resolver. Excluding a statement also removes connections supported only by that statement.

Coverage shows recorded areas and unanswered questions. It cannot measure how completely the system understands you. Unchanged input and exact pending propositions are deduplicated. Semantic duplicates and context-dependent contradictions receive reviewable suggestions, with no claim that every overlap will be detected. Listed numerical accomplishments remain attributed reports, not independently verified measurements. Dates such as “Present” in an old resume do not establish present activity.

**Export** writes concise `about-me.md`, detailed `profile.md`, `graph.json` and a completion manifest into a new local export directory. It includes current reviewed statements, their connections and cited passages, without including unrelated source text. These files are portable projections. To back up all original sources and history, copy the whole workspace while the app is closed.

Command-line access is also available:

```bash
.venv/bin/python -B -m foundry graph --check
.venv/bin/python -B -m foundry graph --search "Python"
.venv/bin/python -B -m foundry graph --export
.venv/bin/python -B -m foundry graph --visual --open
```

To inspect a separate fictional demonstration:

```bash
.venv/bin/python -B -m foundry ui --dataset synthetic --workspace .foundry-data/workspaces/skillmap-demo
```

An empty synthetic workspace can be opened with `--dataset synthetic`. Dataset identity is checked across state and manual replies; source authorship still depends on truthful attribution. No demonstration is evidence about the real user.

## Small local architecture

`knowledge.py` projects a typed graph from the canonical evidence store, adds guided capture, relationships, dates and exports, and blocks new idea handoffs in the active product. `intake.py` reads supported resume literals as data. `workflow.py` manages imports and review; `exchange.py` defines the manual model contract. `ui.py` presents this workflow in Textual. The standard-library core uses versioned JSON files with a locked writer and atomic revision pointer. There is no separate graph database, server or embeddings service.

`skillmap.py` projects shared entities and preserves scoped interviews/assessments. `github.py` is a bounded read-only transport and import adapter. `solar.py` embeds its data and assets in one offline HTML file with a restrictive content policy; `ui_skillmap.py` provides native editing controls. **View map** and `graph --visual` create immutable snapshots with portable `skillmap.json`; reopen the view after edits to see them. These exports contain personal evidence, including selected code excerpts, and are not public pages.

`openai_api.py` contains the bounded standard-library HTTP adapter. `understanding_contract.py` defines the extraction prompt/schema and semantic-field constraints; `understanding.py` stages suggestions, records calls and projects reviewed connections. Requests, responses and prompt versions are preserved under the private workspace's `ai/` directory. The embedding cache is outside versioned evidence revisions to avoid copying vectors on every edit. `ui_understanding.py` provides the single setup/catch-up screen. No added runtime dependencies or vector database are required.

`capture.py` handles the selected-input queue and resumable analysis, `memory.py` defines quoted extraction and reversible reviewed reconciliation, and `profile.py` renders readable output with local search. UI controls live in `ui_capture.py`; the standard-library core remains separate.

Workspace budgets are explicit: 10,000 claims, 10,000 proposals, 20,000 sources/corrections, 5,000 statement relationships, 200 manual handoffs and 100 MB per expanded revision. Limits include retained history. New revisions of at least 1 MB are stored as gzip-compressed JSON; older uncompressed revisions remain readable and unchanged. The atomic pointer records the format, and hashes cover the original JSON. Each revision still represents the complete state, so history continues to grow. These limits are guardrails, not a benchmark at maximum capacity. Older manual input selections retain their 20,000-character/120 KB reply bounds; local resume extraction retains its 200-detail limit. A limit fails visibly without replacing the previous state. Pending input and handoffs survive restart and never resume as background jobs.

The earlier evaluation modules and prototype CLI remain for historical data and regression coverage. See [the historical prototype guide](docs/EVIDENCE_PROTOTYPE.md). They are not part of the current graph workflow. The historical prompts in `prompts/` do not authorize resuming idea generation.

## Development

Python 3.13+ and Textual 8.2.8 are the current targets. The repository-local environment is already prepared. Run the native checks with:

```bash
.venv/bin/python -B -m unittest discover -v
```

For dependency setup on another checkout, `make deps ui-env` downloads generic pinned wheels in the existing development container and installs them into a local venv. No system packages are installed. The application needs no Docker runtime. `make check` remains an optional offline container check; its allowlist excludes personal state.

See [PRODUCT.md](docs/PRODUCT.md) for the current scope and [STATUS.md](docs/STATUS.md) for implementation evidence and remaining limits. Personal accuracy and usefulness require your review before the next phase.
