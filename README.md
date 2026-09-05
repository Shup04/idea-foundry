# Idea Foundry — three-pass starter kit

**Status:** Planning and Codex handoff files, not an implemented application.
**Prepared:** 2026-09-05.

## What we are testing

Can a system give you unusual, concrete, well-grounded inputs that cause YOU to develop worthwhile ideas, more reliably than an ordinary brainstorming conversation?

This is not a generic startup-idea generator, a frustration detector, an artificial-emotion experiment, or a replacement for your creativity.

## Three substantial passes

| Pass | Codex does | You do | Gate |
| --- | --- | --- | --- |
| 1. Discovery trial | Run a bounded creative experiment and produce a reviewable feed, using Astra in Codex. | Supply seeds and react to the output. | Is the material worth returning to? |
| 2. Working product | Build the whole useful vertical slice: library, exploration, provider interface, polished TUI, persistence, feedback and tests. | Use it with your own material and a selected model. | Does the application deliver the same useful experience? |
| 3. Calibration and unattended use | Improve selection from your feedback, compare providers, add bounded background operation, and harden the system. | Decide which output earns your attention and choose the default runtime. | Is it useful repeatedly, including on unseen inputs? |

Codex can perform many internal implementation steps in each pass. You do not need to approve each module or test. A pass may require resuming a Codex session; these are outcome boundaries, not promises about runtime or context limits.

## Get started

Extract these files into a NEW directory such as `~/work/idea-foundry`. Do not extract them over the existing personal-agent project. That project and the company repositories remain untouched.

From the new directory:

```bash
mkdir -p .foundry-data/inputs .foundry-data/reviews
cp templates/SEEDS.md .foundry-data/inputs/SEEDS.md
```

Fill in the private seed file, including its cloud-approval field. About 10–15 brief seeds and a few examples of what you find interesting are enough for the first trial. Do not include company material without permission to use it this way.

Start Codex with Astra selected, then send:

```text
Read AGENTS.md, docs/PRODUCT.md and docs/BUILD_PLAN.md.
Execute prompts/01_DISCOVERY_TRIAL.md only.
My inputs are in .foundry-data/inputs/SEEDS.md.
Stop at the human review gate. Do not build the application yet.
```

For the later passes, use `prompts/02_BUILD_V1.md` and `prompts/03_CALIBRATE_AND_HARDEN.md` after their gates are approved. These prompts are self-contained when read alongside the product and build-plan documents.

## Files

- `AGENTS.md`: permanent project instructions for Codex.
- `docs/PRODUCT.md`: the product contract and constraints.
- `docs/BUILD_PLAN.md`: the three passes, acceptance criteria, and decision gates.
- `docs/STATUS.md`: implementation status; initially not started.
- `docs/REFERENCES.md`: current primary-source documentation for the Codex workflow.
- `prompts/`: the three copy-ready execution prompts.
- `evals/`: direct-prompt and structured-loop comparison instructions.
- `templates/`: seed and review templates, not your actual private inputs.
- `schemas/`: a small application-level discovery-card contract.

Only product requirements already settled in the conversation are fixed. Technical choices that are cheap to reverse should be made and documented by Codex, not turned into another questionnaire. Privacy, paid calls, destructive changes, or a genuinely different product goal require approval.

## Important distinctions

Astra in Codex is the BUILDER and the first experimental model. It does not have to be the model used by the resulting application. Manual exchange of structured outputs keeps the prototype useful before a local model endpoint is configured.

Mock-provider tests prove software behaviour, not idea quality. Schema-valid JSON is not proof of factual accuracy. A positive first trial is not proof of a business, universal novelty, or long-term productivity.
