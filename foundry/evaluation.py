"""Deterministic evaluation from visible facts and a freshly loaded policy.

No executable expressions, provider calls, financial probabilities or learned weights.
"""

from copy import deepcopy

from .evidence import claim_statuses
from .outcomes import relevant_outcomes
from .storage import encoded
from .validation import digest, number, validate_policy, validate_state


def unknown(reason):
    return {"value": None, "basis": "unknown", "confidence": "weak", "reason": reason,
            "sources": [], "claim_ids": []}


def effective_facts(idea, state):
    facts = deepcopy(idea["facts"])
    statuses = claim_statuses(state)
    for name, item in list(facts.items()):
        unusable = [cid for cid in item["claim_ids"] if not statuses[cid]["usable"]]
        if unusable:
            facts[name] = unknown(f"Personal attribution withheld: {', '.join(unusable)} is inferred, rejected, excluded or contradicted. Original estimate remains in the idea record.")
    # Outcomes do not rewrite estimates. They add explicitly named actual fields.
    for event in relevant_outcomes(state, idea["id"]):
        for metric, value in event["metrics"].items():
            if value is None:
                continue
            name = "actual_implementation_minutes" if metric == "implementation_minutes" else metric
            if metric == "money_earned":
                value = f"{value['amount']} {value['currency']} in {value['period']} (not lifetime revenue or profit)"
            elif metric == "implementation_minutes":
                value = {"low": value, "high": value, "unit": "minutes"}
            facts[name] = {
                "value": value, "basis": event["method"], "confidence": "moderate",
                "reason": f"Outcome {event['id']}; {event['occurred_at']}; scope: {event['scope']}. Latest nonempty report for this field; earlier and conflicting events remain visible.",
                "sources": event["sources"], "claim_ids": [],
            }
            if metric in ("actual_usefulness", "user_rating") and value != "none":
                facts[name]["assessment"] = value
            elif metric in ("continued_usage", "saved", "revisited"):
                facts[name]["assessment"] = "strong" if value else "weak"
            elif value == "none":
                facts[name]["assessment"] = "weak"
    return facts


def constraint_result(constraint, item):
    value = item["value"]
    if value is None:
        return "unknown"
    if constraint["op"] == "eq":
        if type(value) is not type(constraint["limit"]):
            return "unknown"
        return "pass" if value == constraint["limit"] else "fail"
    if not isinstance(value, dict) or value["unit"] != constraint["unit"]:
        return "unknown"
    low, high, limit = value["low"], value["high"], constraint["limit"]
    if constraint["op"] == "le":
        return "pass" if high <= limit else "fail" if low > limit else "unknown"
    return "pass" if low >= limit else "fail" if high < limit else "unknown"


def rating(criterion, item):
    if item["value"] is None:
        return "unknown"
    if criterion["rule"] == "assessment":
        return item.get("assessment", "unknown")
    value = item["value"]
    if not isinstance(value, dict) or value["unit"] != criterion["unit"]:
        return "unknown"
    # Classify both ends. A range straddling bands keeps the weaker fit band;
    # confidence and basis remain separately visible and are never upgraded.
    worst = value["high"] if criterion["rule"] == "lower" else value["low"]
    if criterion["rule"] == "lower":
        return "strong" if worst <= criterion["strong"] else "moderate" if worst <= criterion["moderate"] else "weak"
    return "strong" if worst >= criterion["strong"] else "moderate" if worst >= criterion["moderate"] else "weak"


def payback(facts):
    fields = {"setup_minutes": "minutes", "frequency_monthly": "uses/month",
              "minutes_saved_per_use": "minutes/use", "ongoing_minutes_monthly": "minutes/month"}
    for name, unit in fields.items():
        value = facts.get(name, {}).get("value")
        if not isinstance(value, dict) or value["unit"] != unit:
            return {"status": "unknown", "reason": f"Missing compatible range: {name}. No zero substituted."}
    setup, frequency, saving, ongoing = (facts[name]["value"] for name in fields)
    net_low = frequency["low"] * saving["low"] - ongoing["high"]
    net_high = frequency["high"] * saving["high"] - ongoing["low"]
    if not all(number(value) for value in (net_low, net_high)):
        return {"status": "unknown", "reason": "Ranges exceed finite arithmetic; narrow the estimates."}
    bases = sorted({facts[name]["basis"] for name in fields})
    result = {"basis": bases, "net_minutes_per_month": [net_low, net_high],
              "formula": "setup minutes / (uses per month × minutes saved per use − ongoing minutes per month)",
              "limits": "Time-only estimate against the stated baseline. Cash is separate; time is not also monetized. Assumed frequency and savings are not observed benefit. Outcomes do not silently replace these original estimates."}
    if net_high <= 0:
        return {**result, "status": "no time payback in this range"}
    months = [setup["low"] / net_high, setup["high"] / net_low if net_low > 0 else None]
    if any(value is not None and not number(value) for value in months):
        return {"status": "unknown", "reason": "Payback range exceeds finite arithmetic; narrow the estimates."}
    return {**result, "status": "conditional estimate", "months": months,
            "reason": "Upper end is unbounded when conservative net savings are zero or negative."}


def evaluate(state, policy):
    validate_state(state)
    validate_policy(policy)
    results = []
    for idea in state["ideas"]:
        section = policy["policies"][idea["category"]]
        facts = effective_facts(idea, state)
        constraints = []
        for constraint in section["hard_constraints"]:
            item = facts.get(constraint["fact"], unknown("No fact supplied for this constraint."))
            constraints.append({**constraint, "result": constraint_result(constraint, item), "evidence": item})
        criteria, balance = [], {key: 0 for key in ("strong", "moderate", "weak", "unknown")}
        by_id = {criterion["id"]: criterion for criterion in section["criteria"]}
        for cid in section["priorities"]:
            criterion = by_id[cid]
            item = facts.get(criterion["fact"], unknown("No assessment supplied for this preference."))
            band = rating(criterion, item)
            balance[band] += criterion["weight"]
            criteria.append({**criterion, "rating": band, "evidence": item})
        gaps = [name for name in section["required_facts"]
                if facts.get(name, {}).get("basis", "unknown") in ("unknown", "assumption")]
        experimental = [c for c in constraints if c["scope"] == "experiment"]
        implementation = [c for c in constraints if c["scope"] == "implementation"]
        if any(c["result"] == "fail" for c in experimental):
            readiness = "Outside the configured experiment budget"
        elif not experimental or any(c["result"] == "unknown" for c in experimental):
            readiness = "Resolve experiment constraints before proceeding"
        elif idea["category"] == "creative":
            readiness = "Creative provocation — within the proposed attention budget"
        else:
            readiness = "Ready for review of a bounded experiment — estimated costs only"
        implementation_state = "not evaluated for creative material" if idea["category"] == "creative" else (
            "outside configured constraints" if any(c["result"] == "fail" for c in implementation)
            else "evidence needed" if gaps or any(c["result"] == "unknown" for c in implementation)
            else "eligible for human implementation review; no approval inferred")
        results.append({
            "id": idea["id"], "category": idea["category"], "title": idea["title"],
            "description": idea["description"], "inspiration": idea["inspiration"],
            "readiness": readiness, "implementation": implementation_state,
            "constraints": constraints, "criteria": criteria, "preference_balance": balance,
            "facts": facts, "evidence_gaps": gaps, "alternatives": idea["alternatives"],
            "experiment": idea["experiment"], "outcomes": relevant_outcomes(state, idea["id"]),
            "payback": payback(facts) if idea["category"] == "personal" else None,
        })
    return {"schema_version": 1, "policy_name": policy["name"], "policy_sha256": digest(encoded(policy)),
            "state_sha256": digest(encoded(state)), "evaluations": results,
            "interpretation": "Preference weights are configurable emphasis units, not probabilities. A strong fit band can rest on weak evidence. Hard constraints cannot be offset by preference weights. Missing constraints remain unknown. No work is authorized by this report."}
