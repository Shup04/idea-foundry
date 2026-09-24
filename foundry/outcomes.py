"""Outcome records and deliberately narrow, inspectable proposal rules."""

from .validation import keys, require


def record_outcome(state, request):
    keys(request, ("sources", "outcome"))
    state["sources"].extend(request["sources"])
    state["outcomes"].append(request["outcome"])


def relevant_outcomes(state, idea_id):
    from datetime import datetime
    return sorted(
        (event for event in state["outcomes"] if event["idea_id"] == idea_id),
        key=lambda event: (datetime.fromisoformat(event["occurred_at"]), event["id"]),
    )


def proposals(state, policy):
    """Two distinct abandoned personal ideas can suggest a smaller setup cap.

    This is a heuristic for review, not a learned preference or causal finding.
    Repeated logs of one idea or one source origin do not satisfy the threshold.
    """
    from .evidence import support_origins
    ideas = {idea["id"]: idea for idea in state["ideas"]}
    evidence, used_ideas, used_origins = [], set(), set()
    for event in state["outcomes"]:
        idea = ideas[event["idea_id"]]
        if (idea["category"] != "personal" or event["event"] != "abandoned"
                or event["reason_code"] != "unexpected_time"):
            continue
        if not event["metrics"].get("reason_abandoned"):
            continue
        actual = event["metrics"].get("implementation_minutes")
        expected = idea["facts"].get("setup_minutes", {}).get("value")
        if actual is None or not isinstance(expected, dict) or actual <= expected["high"]:
            continue
        roots = set(support_origins({"sources": event["sources"]}, state))
        if idea["id"] in used_ideas or roots & used_origins:
            continue
        used_ideas.add(idea["id"])
        used_origins |= roots
        evidence.append({"event": event["id"], "idea": idea["id"], "actual_minutes": actual,
                         "estimated_minutes": expected, "reason": event["metrics"]["reason_abandoned"],
                         "sources": event["sources"]})
    constraints = policy["policies"]["personal"]["hard_constraints"]
    cap = next((c for c in constraints if c["fact"] == "setup_minutes" and c["op"] == "le"), None)
    proposed = policy["learning"]["propose_setup_cap_minutes"]
    if len(evidence) < policy["learning"]["min_distinct_ideas"] or cap is None or proposed >= cap["limit"]:
        return []
    require(cap["unit"] == "minutes", "setup-cap proposal expects minutes")
    return [{
        "id": "smaller_personal_setup_cap", "status": "proposal_only",
        "rule": "At least the configured number of distinct personal ideas were abandoned for unexpected time; reported implementation exceeded their original estimate.",
        "change": {"category": "personal", "constraint_id": cap["id"], "field": "limit",
                   "from": cap["limit"], "to": proposed},
        "evidence": evidence,
        "limitations": "Small selected history; abandonment may reflect experiment scope, bad estimates or changing circumstances. This does not prove a permanent preference or a causal threshold.",
        "action": "Review these records, then edit the named constraint in your policy only if you agree. No preference has been changed.",
    }]
