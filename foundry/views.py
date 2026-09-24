"""Short plain-text reading views. No imported markup, hyperlinks or commands run."""

from .evidence import claim_statuses
from .validation import FACETS

CATEGORY_NAMES = {"personal": "Personal quality of life", "commercial": "Commercial opportunity", "creative": "Creative provocation"}


def label(value):
    return value.replace("_", " ").capitalize()


def profile_summary(state):
    statuses = claim_statuses(state["core"])
    counts = {s: sum(p["status"] == s for p in state["proposals"])
              for s in ("proposed", "accepted", "corrected", "rejected")}
    usable = [c for c in state["core"]["claims"] if statuses[c["id"]]["usable"]]
    facets = {c["facet"] for c in usable}
    missing = ", ".join(label(f).lower() for f in FACETS if f not in facets)
    return (f"{state['dataset'].upper()} • " + " · ".join(f"{n} {s}" for s, n in counts.items())
            + f"\n{len(usable)} statements available for ideas. Proposed information is withheld. "
            "Acceptance records your confirmation; it does not prove a model's interpretation."
            + f"\nNo accepted evidence yet for: {missing or 'all facets have entries; completeness remains unknown'}."
            + "\nChoose a statement to see its original wording and supporting passage.")


def passages(core, refs):
    sources = {s["id"]: s for s in core["sources"]}
    return "\n\n".join(f"{sources[r['source']]['locator']} · version {sources[r['source']]['version']}"
                         f" · {sources[r['source']]['kind']}\n{r['quote']}" for r in refs)


def claim_detail(p, state):
    claim = p["claim"]
    result = (f"{p['status'].upper()} · {label(claim['facet'])}\n\n{claim['text']}\n\n"
              f"Originally: {claim['kind']} · {claim['confidence']} confidence. "
              "Confidence is the author's assessment, not verification.\n")
    if "understanding" in state:
        from .understanding import proposal_detail
        insight = proposal_detail(state, p["id"])
        if insight:
            result = f"{p['status'].upper()} · {label(claim['facet'])}\n\n{claim['text']}\n\n" + insight
    from .memory import proposal_detail as memory_detail
    reconciliation = memory_detail(state, p["id"])
    if reconciliation:
        result = f"{p['status'].upper()} · {label(claim['facet'])}\n\n{claim['text']}\n\n" + reconciliation + "\n"
    statuses = claim_statuses(state["core"])
    if p["core_id"] in statuses and not reconciliation:
        status = statuses[p["core_id"]]
        result += f"Current original claim: {status['status']}"
        if status["conflicts"]:
            result += " — conflicts with " + ", ".join(status["conflicts"])
        result += "\n"
    if p["replacement"]:
        replacement = next(c for c in state["core"]["claims"] if c["id"] == p["replacement"])
        result += f"\nYOUR CORRECTION\n{replacement['text']}\n"
    if p["status"] != "proposed":
        result += f"\nReview note: {p['note']}\n"
    from .workflow import possible_matches
    matched_ids = set(p["matches"]) | set(possible_matches(claim, state))
    matches = [c for c in state["core"]["claims"] if c["id"] in matched_ids and c["id"] != p["core_id"]]
    if matches:
        result += "\nCHECK PREVIOUS CORRECTIONS\n" + "\n".join(f"• {c['status']}: {c['text']}" for c in matches)
        result += "\nThese are lexical/source similarities, not proof of equivalence.\n"
    return result + "\nSUPPORTING PASSAGE\n" + passages(state["core"], claim["sources"])


def value_text(fact):
    if not fact or fact["value"] is None:
        return "unknown"
    value = fact["value"]
    if isinstance(value, dict):
        value = f"{value['low']:g}–{value['high']:g} {value['unit']}"
    return f"{value} ({fact['basis']}; {fact['confidence']} confidence)"


def feed_text(report):
    if not report["evaluations"]:
        return "No ideas yet. Accept or correct information in About Me, then prepare a small manual idea handoff."
    rows = []
    for n, row in enumerate(report["evaluations"], 1):
        facts = row["facts"]
        lines = [f"{n}. {row['title']}", CATEGORY_NAMES[row["category"]], "", row["description"], "",
                 "Investigation: " + value_text(facts.get("experiment_minutes")), row["readiness"]]
        if row["category"] == "creative":
            lines += ["Attention: " + value_text(facts.get("attention_minutes")),
                      "Useful thoughts: " + value_text(facts.get("useful_thoughts")),
                      "Saved / revisited: " + value_text(facts.get("saved")) + " / " + value_text(facts.get("revisited"))]
        else:
            lines += ["Eventual build/setup: " + value_text(facts.get("setup_minutes")),
                      "Expected benefit: " + value_text(facts.get("expected_benefit"))]
        if row["category"] == "commercial":
            lines += ["Possible customer: " + value_text(facts.get("plausible_customer")),
                      "Reason to switch: " + value_text(facts.get("reason_to_switch"))]
        lines += ["", "Try: " + row["experiment"]["scope"],
                  "Simpler alternative: " + row["alternatives"][0]["name"],
                  "Evidence: unresearched idea; assumptions and unknowns remain visible in Details."]
        if any(c["result"] == "fail" for c in row["constraints"]):
            lines.append("An approved hard exclusion applies; preference fit cannot override it.")
        rows.append("\n".join(lines))
    return "\n\n────────────────────────────────────────\n\n".join(rows) + "\n\n" + comparison_text(report)


def comparison_text(report):
    titles = {r["id"]: r["title"] for r in report["evaluations"]}
    lines = ["COMPARISON WITHIN EACH CATEGORY", "Provisional defaults remain unapproved." if report["provisional"] else "Using your selected preference definitions."]
    if not report["comparisons"]:
        lines.append("No pair in the same category in this batch. Generate two ideas in one category to compare.")
    for pair in report["comparisons"]:
        lines.append(f"\n{titles[pair['left']]} ↔ {titles[pair['right']]}")
        lines.append("Preference: " + (titles[pair["preference"]] if pair["preference"] in titles else pair["preference"]))
        for reason in pair["reasons"]:
            favors = titles[reason["favors"]] if reason["favors"] else "neither (equal fit)"
            lines.append(f"• {label(reason['criterion'])}: {reason['left']} / {reason['right']}, emphasis {reason['weight']} → {favors}")
        if pair["unknown"]:
            lines.append("Unknown; no vote: " + ", ".join(label(n) for n in pair["unknown"]))
        if pair["excluded"]:
            lines.append("Hard exclusions apply separately to: " + ", ".join(titles[i] for i in pair["excluded"]))
    lines.append("\nWeights are preference votes, not success probabilities. Evidence quality is separate. Unknown benefit stays unknown.")
    return "\n".join(lines)


def idea_detail(row, state):
    lines = [row["title"], row["description"], "\nSUPPORTING PASSAGES", passages(state["core"], row["inspiration"]),
             "\nESTIMATES AND UNKNOWNS"]
    for name in sorted(set(row["facts"]) | set(row["evidence_gaps"])):
        fact = row["facts"].get(name)
        lines.append(f"\n{label(name)}: {value_text(fact)}")
        if fact:
            lines.append(fact["reason"])
            for cid in fact["claim_ids"]:
                claim = next(c for c in state["core"]["claims"] if c["id"] == cid)
                lines.append(f"Personal link: {claim['text']} ({claim['status']})")
            if fact["sources"]:
                lines.append(passages(state["core"], fact["sources"]))
    if row["payback"]:
        p = row["payback"]
        lines += ["\nTIME PAYBACK: " + p["status"], p.get("reason", "")]
        if "months" in p:
            low, high = p["months"]
            lines.append(f"{low:.1f} months to " + (f"{high:.1f} months" if high is not None else "possibly never"))
        lines.append(p.get("formula", ""))
    lines += ["\nALTERNATIVES"] + [a["name"] + ": " + a["tradeoff"] for a in row["alternatives"]]
    lines += ["\nEXPERIMENT"] + [label(k) + ": " + v for k, v in row["experiment"].items()]
    lines += ["\nOUTCOME HISTORY (user reports, not model evidence)"]
    for outcome in row["outcomes"]:
        lines.append(f"{outcome['occurred_at']} · {outcome['event']}\n" + passages(state["core"], outcome["sources"]))
    if not row["outcomes"]:
        lines.append("No outcomes recorded. This does not mean zero usefulness.")
    return "\n".join(lines)
