"""Visible, category-local comparisons; preference votes are not viability scores."""

from copy import deepcopy
from itertools import combinations
from pathlib import Path

from .evaluation import evaluate
from .storage import encoded
from .validation import CATEGORIES, digest, keys, read_json, require, validate_policy


def defaults():
    policy = read_json(Path(__file__).resolve().parent.parent / "config/practicality.default.json")
    return {"policy": policy, "approved_constraints": [], "approved_preferences": []}


def validate_settings(settings):
    keys(settings, ("policy", "approved_constraints", "approved_preferences"))
    validate_policy(settings["policy"])
    for field, collection in (("approved_constraints", "hard_constraints"),
                              ("approved_preferences", "criteria")):
        allowed = {f"{cat}.{c['id']}" for cat, p in settings["policy"]["policies"].items()
                   for c in p[collection]}
        values = settings[field]
        require(isinstance(values, list) and len(values) == len(set(values))
                and set(values) <= allowed, "invalid policy approval selection")


def compare(core, settings, idea_ids):
    """Compare at most three ideas; unknown assessments never cast a losing vote."""
    validate_settings(settings)
    selected = deepcopy(core)
    selected["ideas"] = [i for i in core["ideas"] if i["id"] in idea_ids]
    selected["outcomes"] = [o for o in core["outcomes"] if o["idea_id"] in idea_ids]
    policy = deepcopy(settings["policy"])
    for cat, section in policy["policies"].items():
        section["hard_constraints"] = [c for c in section["hard_constraints"]
                                       if f"{cat}.{c['id']}" in settings["approved_constraints"]]
    report = evaluate(selected, policy)
    report["settings_sha256"] = digest(encoded(settings))
    report["provisional"] = any(
        f"{cat}.{c['id']}" not in settings["approved_preferences"]
        for cat, section in policy["policies"].items() for c in section["criteria"]
        if c["weight"] and c["fact"] != "evidence_quality")
    for row in report["evaluations"]:
        if not any(c["scope"] == "experiment" for c in row["constraints"]):
            row["readiness"] = "Investigation budget not set by you; review the proposed experiment cost."
        row["evidence_summary"] = {
            basis: sum(f["basis"] == basis for f in row["facts"].values())
            for basis in ("unknown", "assumption", "supported", "user_report", "measured")}
    pairs = []
    bands = {"weak": 0, "moderate": 1, "strong": 2}
    for category in CATEGORIES:
        rows = [r for r in report["evaluations"] if r["category"] == category]
        for left, right in combinations(rows, 2):
            votes = {left["id"]: 0, right["id"]: 0}
            reasons, unknowns = [], []
            for a, b in zip(left["criteria"], right["criteria"]):
                if a["fact"] == "evidence_quality" or not a["weight"]:
                    continue
                if "unknown" in (a["rating"], b["rating"]):
                    unknowns.append(a["id"])
                    continue
                winner = (left["id"] if bands[a["rating"]] > bands[b["rating"]]
                          else right["id"] if bands[b["rating"]] > bands[a["rating"]] else None)
                if winner:
                    votes[winner] += a["weight"]
                reasons.append({"criterion": a["id"], "weight": a["weight"],
                                "left": a["rating"], "right": b["rating"], "favors": winner,
                                "reason": a["reason"]})
            verdict = ("insufficient comparable information" if not reasons else
                       "balanced tradeoff" if len(set(votes.values())) == 1 else
                       max(votes, key=votes.get))
            pairs.append({"category": category, "left": left["id"], "right": right["id"],
                          "preference": verdict, "votes": votes, "reasons": reasons,
                          "unknown": unknowns,
                          "excluded": [r["id"] for r in (left, right)
                                       if any(c["result"] == "fail" for c in r["constraints"])]})
    report["comparisons"] = pairs
    report["interpretation"] = (
        "Within each category, each comparable preference casts its configured weight toward the "
        "better qualitative band. Equal bands tie; unknowns abstain. Evidence quality and approved "
        "hard exclusions are separate. This is an explainable preference comparison, not a viability "
        "probability. Provisional defaults are unapproved. Assumptions are not measured benefit.")
    return report


def change_setting(settings, category, collection, cid, value, *, enabled=True,
                   strong=None, moderate=None):
    require(category in CATEGORIES and collection in ("criteria", "hard_constraints"), "unknown setting")
    rows = settings["policy"]["policies"][category][collection]
    item = next((r for r in rows if r["id"] == cid), None)
    require(item is not None, "unknown setting")
    approval = f"{category}.{cid}"
    if collection == "criteria":
        item["weight"] = value
        for name, boundary in (("strong", strong), ("moderate", moderate)):
            if boundary is not None:
                require(item["rule"] != "assessment", "qualitative preference has no numeric bands")
                item[name] = boundary
        approvals = settings["approved_preferences"]
        if approval not in approvals:
            approvals.append(approval)
    else:
        item["limit"] = value
        approvals = settings["approved_constraints"]
        if approval in approvals:
            approvals.remove(approval)
        if enabled:
            approvals.append(approval)
    validate_settings(settings)


def differences(before, after):
    changes = []
    previous = {(p["left"], p["right"]): p for p in before["comparisons"]}
    for pair in after["comparisons"]:
        old = previous.get((pair["left"], pair["right"]))
        if old and old != pair:
            changes.append({"left": pair["left"], "right": pair["right"],
                            "before": old, "after": pair})
    constraints = []
    prior = {r["id"]: r for r in before["evaluations"]}
    for row in after["evaluations"]:
        if row["id"] in prior and row["constraints"] != prior[row["id"]]["constraints"]:
            constraints.append({"idea": row["id"], "before": prior[row["id"]]["constraints"],
                                "after": row["constraints"]})
    return {"comparisons": changes, "constraints": constraints,
            "message": ("Comparison or constraint details changed; earlier snapshot preserved."
                        if changes or constraints else
                        "No candidate comparison changed. This setting has no differentiating evidence in this batch.")}
