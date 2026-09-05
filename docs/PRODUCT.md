# Idea Foundry — product contract

**Status:** Proposed V1 contract. Human approval is required at the build-plan gates.

## 1. Purpose

Give the user a small stream of unusual, concrete, traceable material that triggers their own creative thinking, and help them explore directions they choose.

The user is not short of creativity. They want a wider field of possibilities and better prompts for their judgement. Input must not depend on them feeling annoyed, bored, or frustrated. Sources may be things they admire, elegant mechanisms, strange observations, abandoned ideas, questions, aesthetic interests, or capabilities that might change an old assumption.

The product's first test is not whether it can generate thousands of ideas. It is whether the user thinks, “That gives me a genuinely interesting direction to explore.”

## 2. V1 boundaries

Standalone application, separate from Personal Agent. Initially one user on Linux. The reported workstation has 8 GB VRAM and 16 GB system RAM. Do not assume a particular model will fit or run acceptably without measuring it.

Manual text/Markdown input first. Imported public excerpts and links are allowed, but a supplied URL is not evidence that its page was read. Actual company information is outside the initial corpus. A later integration must separately establish authority and privacy requirements.

Astra in Codex builds and trials the system. Application inference uses an interchangeable configured provider. The application remains useful for library, review, feedback, export and import when no model is available.

No simulated emotions, consciousness claims, unattended coding experiments, fine-tuning, universal life ingestion, multi-agent platform, giant graph, Slack/email connectors, or agentic OS integration in V1.

## 3. Human workflow

The user adds a seed in ordinary language. The system preserves it verbatim, extracts optional concise observations, then selects a small working set. It applies varied exploration strategies and returns a curated feed. The user marks what caused a spark, captures their own idea, or chooses a branch to explore.

An exploration may yield alternative interpretations, transferable mechanisms, disputed premises, useful questions, or a cheap proposed experiment. It does not need to be a finished business concept.

The user can inspect the source trail and rejected candidates, change preferences, reset personalization, or explicitly request unfamiliar territory.

## 4. Exploration strategies

Implement a few explicit strategies rather than a collection of role-playing agents:

- **Assumption inversion:** identify a constraint and explore what changes if it is removed or reversed.
- **Mechanism transfer:** move a useful mechanism from one domain into another and explain what transfers.
- **Distant connection:** connect two inputs through a concrete relationship, not shared vocabulary alone.
- **Capability change:** ask whether an old idea changes under a new capability; claims about that capability require evidence or a hypothetical label.
- **Revisit:** bring a neglected seed back with genuinely new context; explain what changed.
- **Wildcard:** deliberately protect a small amount of exploration outside inferred preferences.

These are controllable search policies, not emotional states. Don't present repetition counts or embedding distances as measurements of boredom, taste, or originality.

## 5. Bounded discovery loop

Use an explicit run budget. A reasonable starting experiment is 24–32 candidates and 6–8 displayed cards, not 10,000 generated candidates.

The loop is: selected sources → candidates through different strategies → validity/duplication checks → reasoned critique → diverse selection → human feedback → user-directed expansion.

Source fidelity, JSON validation and duplicate checks can reject broken records. A model's opinion that something is uninteresting is not sufficient to erase it. Retain discarded candidates and the reason for exclusion. Protect a wildcard slot. Do not exhaustively enumerate the space or claim every possibility was explored.

Each run has maximum calls, output size, candidates and elapsed time; unbounded retry and recursive self-critique are forbidden. Within a run, a failed call may be retried once with the failure reported. Stop when the budget is reached or another pass produces no distinct useful candidates.

## 6. Discovery cards

The application-level JSON schema is in `schemas/discovery-card.schema.json`. It is a starting interoperability contract, not a promise that every provider supports that exact schema as a generation constraint.

A card contains identity, kind, a concrete premise or question, the mechanism or connection, the assumption being challenged, a human-experience lens, source IDs, uncertainties, factual claims and their evidence status, and a next probe.

Human-experience lenses may include play, relief, beauty, agency, belonging, comprehension or curiosity. These name possible outcomes to investigate, not feelings the model has or experiences it has measured in the user.

Show the short version first. An expanded view contains source excerpts and versions, the reasoning summary, alternatives, claims needing research, generation provenance, and feedback history.

A hypothetical capability must remain hypothetical. A searched-but-unconfirmed claim must not be promoted to “fact.” Source IDs must resolve to the exact input version, and a claim labelled supported must point to relevant evidence. Neither JSON validity nor source existence proves that a source actually supports a claim.

## 7. Feedback and personalization

Accept explicit reactions: `spark`, `interesting_material`, `already_knew`, `forced_connection`, `nonsense`, `not_for_me`, `unsure`. Allow a free-text explanation and a linked user-authored idea. Missing feedback is unknown, not rejection.

Separate “I already knew this” from “this is bad.” Separate “not useful to me today” from “impossible.” Permit personal relevance and commercial potential as user goals, not automatic claims of value.

Initially use explicit preferences and a small set of retrieved examples, not model-weight updates. Keep preferences inspectable, scoped, editable and resettable. Reserve exploration outside previous preferences. Do not optimize only for approval or familiar themes.

## 8. Provenance and truth

Store original inputs separately from extracted observations and generated hypotheses. Keep source versions, prompt versions, run IDs, provider/model names, selected sources, and available usage with each run.

Distinguish user statements, externally supported claims, inferences, speculation and claims needing research. “New to me” is user feedback. “Absent from a few searches” is not proof that no one has done it.

There is no authoritative creativity score or business-success probability. Tests prove the software's behaviour; human review measures whether the product is useful.

## 9. Inference and external research

Use fixed feature-to-profile mapping. No autonomous intelligence router. Let the user choose the actual local model and endpoint. Limit generation concurrency to one by default. Use configurable context/output budgets, and do not silently download or swap large models.

V1 supports manual Codex handoff/import plus one configurable local HTTP generation adapter. Add a directly billed cloud adapter only with explicit user authorization and budget. Unknown cost is not zero cost. Usage under a Codex subscription must not be fabricated as API dollars.

For evidence research, start with a concise export for a user-launched Codex research session and import its findings. Require real sources and quotes/excerpts as appropriate. The research agent must disclose unavailable browsing rather than invent citations. Automatic web-search-provider integration is deferred until the discovery loop proves useful.

Private exports show the included material before transmission. Local-only runs do not silently fall back to cloud providers.

## 10. Application design

Default direction after the discovery trial: Python, a polished Textual TUI, SQLite metadata and agent-owned files. Choose exact compatible dependencies during implementation. Do not require a graph database or an embeddings service for a small seed corpus.

Core logical objects: SourceVersion, Observation, Discovery, Feedback, UserIdea, ExplorationRun, ProviderProfile and an optional later Job. Keep storage details modest. Export/import contracts are enough to preserve future OS-layer integration; don't build a plugin system now.

Keep the TUI responsive, with a real feed rather than placeholder dashboards. Show honest empty, failed, partial and provider-unavailable states. Make source inspection and quick feedback easy. Include a context/usage inspector without dumping raw diagnostics into every card.

## 11. Success and stop conditions

For the initial trial, seek several pieces of material worth saving and at least one direction the user genuinely wants to explore. A suggested gate is two useful cards out of twelve and one user-authored follow-on idea, but this is a personal decision threshold, not a scientific claim.

Compare against a direct strong-model prompt using the same seeds and reading budget. If a simple prompt is equally useful, simplify the generator and retain only useful persistence/review features. If strong-model output helps but local output does not, keep a hybrid model rather than pretending the local version works.

A few good outputs do not establish commercial demand. Repeated voluntary use, worthwhile user-created ideas, and reduced attention spent on low-quality material are the relevant early signals.
