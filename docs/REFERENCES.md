# Primary-source references

Checked 2026-09-05. These support current tool capabilities, not the originality or commercial viability of Idea Foundry. Recheck installed CLI help before relying on flags.

1. OpenAI model selection: Astra is listed for Codex; the documented launch is `codex -m gpt-6-astra`. Available controls vary by client and account.
   https://developers.openai.com/codex/models
2. OpenAI GPT-6 Astra model reference: documents supported reasoning effort and API capabilities. Do not infer the availability of a specific setting in the user's Codex client solely from API support.
   https://developers.openai.com/api/docs/models/gpt-6-astra
3. OpenAI execution-plan guidance: maintain self-contained plans and progress for multi-step work.
   https://developers.openai.com/cookbook/articles/codex_exec_plans
4. OpenAI AGENTS.md guidance: repository-scoped persistent instructions.
   https://developers.openai.com/codex/guides/agents-md
5. OpenAI non-interactive Codex: `codex exec`, JSON events, output schemas and permission controls exist. Their presence does not authorize hidden/unbounded nested calls or guarantee known cost.
   https://developers.openai.com/codex/non-interactive-mode
6. OpenAI Structured Outputs: schema-conforming outputs can still contain mistakes. Source fidelity and human usefulness need separate checks.
   https://developers.openai.com/api/docs/guides/structured-outputs

The cognitive loop, budgets, wildcard policy, three-pass grouping and acceptance thresholds in this kit are proposed design choices, not established research results.
