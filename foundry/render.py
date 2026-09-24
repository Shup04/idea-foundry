"""Plain Markdown projections for review now and a later UI over the same core."""

import json

from .evidence import claim_statuses, support_origins
from .validation import FACETS


def safe(value):
    return str(value).replace("|", "\\|").replace("\n", " ").replace("<", "&lt;").replace(">", "&gt;")


def value_text(value):
    if value is None:
        return "unknown"
    if isinstance(value, dict) and {"low", "high", "unit"} <= value.keys():
        return f"{value['low']:g}–{value['high']:g} {value['unit']}"
    if type(value) is bool:
        return "yes" if value else "no"
    return safe(value)


def source_text(references):
    return "; ".join(f"{safe(ref['source'])}: “{safe(ref['quote'])}”" for ref in references) or "none"


def profile(state):
    statuses = claim_statuses(state)
    lines = ["# Personal Profile", "", "This view contains source-linked paraphrases and explicitly labelled interpretations. Confidence concerns the stated claim in context, not a global confidence in you. No generated idea is personal evidence.", "",
             "Direct statements show what you said; reported statements come from a supplied summary; observed claims require an inspected artifact. Interests and project association do not establish skill mastery or identity. Blank review fields are unknown.", ""]
    rejected = [c for c in state["claims"] if c["status"] == "rejected"]
    tentative = [c for c in state["claims"] if c["kind"] == "interpretation" and c["status"] == "active"]
    conflicted = [cid for cid, status in statuses.items() if status["status"] == "contradicted"]
    lines += [f"Review first: {len(rejected)} rejected interpretations; {len(tentative)} active tentative interpretations; {len(conflicted)} claims with unresolved contradictions.", "",
              "Rejection means the inference is unsupported or corrected. It does not establish its opposite. Rejected and excluded records remain in history and cannot influence personal-fit facts.", ""]
    for facet in FACETS:
        lines += [f"## {facet.replace('_', ' ').title()}", ""]
        entries = [c for c in state["claims"] if c["facet"] == facet]
        if not entries:
            lines += ["Unknown — no qualifying evidence in the selected sources.", ""]
        for claim in entries:
            status = statuses[claim["id"]]
            lines += [f"### {claim['id']} — {status['status'].upper()} / {claim['kind']} / {claim['confidence']} confidence", "",
                      safe(claim["text"]), "",
                      f"Canonical proposition: `{claim['key']}`; stance: {claim['stance']}. {'Available as attributed context' if status['usable'] else 'Withheld from personal-fit evidence'}.", "",
                      f"Source excerpts: {source_text(claim['sources'])}", "",
                      f"Independent origin groups: {len(support_origins(claim, state))}. Repeated text/imports do not raise confidence.", ""]
            if status["conflicts"]:
                lines += [f"Unresolved contradiction with: {', '.join(status['conflicts'])}. Neither side is silently selected.", ""]
            for change in state["corrections"]:
                if change["claim_id"] == claim["id"]:
                    lines += [f"Correction {change['id']} ({change['action']}): {safe(change['reason'])}", "",
                              f"Correction evidence: {source_text(change['sources'])}", ""]
    lines += ["## Correcting this profile", "", "Use the local `correct` command to reject, exclude or explicitly reinstate a claim. Use `add-claim` with a new source to supply a replacement or confirmation. Corrections preserve previous versions. Exclusion removes a claim from evaluations, not from the preserved audit history; it is not a secure data-erasure operation.", "",
              "The canonical proposition key prevents an explicitly rejected claim from returning under a new ID. Semantic paraphrases with a different key still require human review; there is no claim of automatic understanding of every equivalent sentence.", "",
              "## Source register", "", "Source kinds are import attestations. Hashes detect changes; they do not prove authorship or that a paraphrase is justified. Supplied summaries are not direct speech. Generated-source ancestry disqualifies a source from personal evidence.", "",
              "| ID | Kind | Origin / version | Locator | SHA-256 |", "| --- | --- | --- | --- | --- |"]
    for source in state["sources"]:
        lines.append(f"| {source['id']} | {source['kind']} | {safe(source['origin'])} / {source['version']} | {safe(source['locator'])} | `{source['sha256']}` |")
    lines += ["", f"Recorded outcomes: {len(state['outcomes'])}. An empty history is not a record of failure or zero benefit.", ""]
    return "\n".join(lines)


def evaluations(report):
    lines = ["# Three example evaluations", "", "These are model-authored examples for testing the evaluation system. They are not observed user preferences, completed experiments, customer evidence or recommendations to build.", "",
             f"Policy: {safe(report['policy_name'])}. Policy hash: `{report['policy_sha256']}`. State hash: `{report['state_sha256']}`.", "",
             report["interpretation"], ""]
    for item in report["evaluations"]:
        lines += [f"## {item['id']} — {item['title']}", "", f"Category: **{item['category']}**.", "", item["description"], "",
                  f"**{item['readiness']}**. Implementation: {item['implementation']}.", "",
                  f"Inspiration only: {source_text(item['inspiration'])}", "", "### Hard constraints", "",
                  "A pass applies to the supplied range or proposal; it does not verify the estimate. A straddling range is unknown. Preferences cannot compensate for a failed constraint.", "",
                  "| Constraint / scope | Rule | Result | Evidence |", "| --- | --- | --- | --- |"]
        for constraint in item["constraints"]:
            evidence = constraint["evidence"]
            operator = {"le": "≤", "ge": "≥", "eq": "must equal"}[constraint["op"]]
            lines.append(f"| {constraint['id']} / {constraint['scope']} | {constraint['fact']} {operator} {value_text(constraint['limit'])} {constraint.get('unit', '')} | **{constraint['result']}** | {value_text(evidence['value'])}; {evidence['basis']}, {evidence['confidence']} confidence. {safe(evidence['reason'])} Policy reason: {safe(constraint['reason'])} |")
        lines += ["", "### Weighted preferences", "", "Order follows editable priorities. Weights (0–5) are emphasis units. Fit bands and evidence confidence are separate; a favorable estimate is not a measured benefit.", "",
                  "| Priority | Preference | Weight | Fit band | Basis / confidence | Why |", "| --- | --- | --- | --- | --- | --- |"]
        for order, criterion in enumerate(item["criteria"], 1):
            evidence = criterion["evidence"]
            rule = "supplied qualitative assessment" if criterion["rule"] == "assessment" else f"{criterion['rule']}: strong boundary {criterion['strong']}, moderate boundary {criterion['moderate']} {criterion['unit']}; weaker end of range"
            lines.append(f"| {order} | {criterion['id']} | {criterion['weight']} | {criterion['rating']} | {evidence['basis']} / {evidence['confidence']} | {safe(criterion['reason'])} Rule: {rule}. {safe(evidence['reason'])} |")
        lines += ["", "Emphasis distribution (not a viability score): " + "; ".join(f"{key}: {value} weight units" for key, value in item["preference_balance"].items()) + ".", "",
                  "### Inputs, estimates and evidence", "", "Every entry is an attributed fact, an explicit assumption, or unknown. Narrative fit assessments are model-authored unless an outcome states otherwise.", "",
                  "| Input | Value | Basis / confidence | Reason and source |", "| --- | --- | --- | --- |"]
        for name, fact in item["facts"].items():
            links = (" Personal claims: " + ", ".join(fact["claim_ids"]) + ".") if fact["claim_ids"] else ""
            lines.append(f"| {name} | {value_text(fact['value'])} | {fact['basis']} / {fact['confidence']} | {safe(fact['reason'])}{links} Sources: {source_text(fact['sources'])} |")
        if item["payback"]:
            payback = item["payback"]
            lines += ["", "### Estimated time payback", "", f"Status: {payback['status']}."]
            if "months" in payback:
                low, high = payback["months"]
                # Coarse bounds deliberately round outward, never a success probability.
                import math
                lower = math.floor(low * 10) / 10
                if high is None:
                    lines += [f"The favorable end repays setup in about {lower:g} months; the unfavorable end may never repay the time. These rates are assumed, not measured."]
                else:
                    lines += [f"Conditional range: {lower:g}–{math.ceil(high * 10) / 10:g} months. The arithmetic uses assumed rates, not measured use."]
            for name in ("formula", "reason", "limits"):
                if name in payback:
                    lines += ["", payback[name]]
        lines += ["", "### Alternatives", ""]
        for alternative in item["alternatives"]:
            lines += [f"- **{safe(alternative['name'])}:** {safe(alternative['tradeoff'])} Evidence: {source_text(alternative['sources'])}."]
        lines += ["", "### Minimum viable experiment — proposed, not performed", ""]
        for name, text in item["experiment"].items():
            lines += [f"{name.title()}: {safe(text)}", ""]
        lines += ["Evidence still missing or assumed: " + (", ".join(item["evidence_gaps"]) or "none of the configured required fields") + ".", "",
                  "### Actual outcomes", ""]
        if not item["outcomes"]:
            missing = ("useful thoughts, saving, revisiting and user ratings" if item["category"] == "creative"
                       else "implementation time, usefulness, usage, abandonment and user ratings")
            if item["category"] == "commercial":
                missing += ", plus earnings"
            lines += [f"None recorded; {missing} remain unknown. No model opinion counts as an actual outcome.", ""]
        for event in item["outcomes"]:
            lines += [f"- {event['id']}: {event['event']} at {event['occurred_at']}; {event['method']}; scope: {safe(event['scope'])}. Metrics: {safe(json.dumps(event['metrics'], ensure_ascii=False))}. Evidence: {source_text(event['sources'])}", ""]
    return "\n".join(lines)
