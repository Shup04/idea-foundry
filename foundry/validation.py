"""Small explicit contracts for manually supplied data, including model-authored data.

Validation establishes structure and attribution, not the truth of a quotation's
interpretation or the identity of its author. Authorship is a local import attestation.
"""

import hashlib
import json
import math
import re
from pathlib import Path

MAX_BYTES = 2_000_000
LEVELS = ("weak", "moderate", "strong")
CATEGORIES = ("personal", "commercial", "creative")
FACETS = (
    "interests", "claimed_skills", "demonstrated_skills", "active_projects",
    "previous_projects", "previous_ideas", "goals", "constraints_preferences",
    "observed_activity", "context",
    "preferences", "constraints", "values", "personality", "working_style",
    "motivations", "avoidances", "resources", "learning_style", "risk_tolerance",
)
KINDS = ("user_statement", "user_supplied_summary", "observation", "outcome", "generated")
BASES = ("unknown", "assumption", "supported", "measured", "user_report")


class Invalid(ValueError):
    """Reviewable invalid-data error; never repaired by inventing a value."""


def require(condition, message):
    if not condition:
        raise Invalid(message)


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json(path, *, max_bytes=MAX_BYTES):
    path = Path(path)
    with path.open("rb") as handle:
        raw = handle.read(max_bytes + 1)
    require(len(raw) <= max_bytes, f"input exceeds {max_bytes} bytes")
    try:
        return json.loads(
            raw, object_pairs_hook=_pairs,
            parse_constant=lambda value: require(False, f"non-finite JSON: {value}"),
        )
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise Invalid(f"invalid JSON in {path.name}: {exc}") from exc


def keys(obj, required, optional=()):
    require(isinstance(obj, dict), "expected an object")
    require(set(required) <= obj.keys(), f"missing fields: {set(required) - obj.keys()}")
    require(obj.keys() <= set(required) | set(optional),
            f"unknown fields: {obj.keys() - set(required) - set(optional)}")


def words(value, label, limit=20000):
    require(isinstance(value, str) and 0 < len(value) <= limit, f"invalid {label}")
    require(not any(ord(c) < 32 and c not in "\n\t\r" for c in value),
            f"control character in {label}")


def identifier(value):
    require(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", value),
            f"invalid identifier: {value!r}")


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def interval(value, unit=None):
    keys(value, ("low", "high", "unit"))
    require(number(value["low"]) and number(value["high"]), "range must be finite")
    require(0 <= value["low"] <= value["high"], "range must be ordered and nonnegative")
    words(value["unit"], "unit", 60)
    if unit:
        require(value["unit"] == unit, f"expected unit {unit}")


def indexed(items, label, limit):
    require(isinstance(items, list) and len(items) <= limit, f"{label} budget exceeded")
    result = {}
    for item in items:
        require(isinstance(item, dict) and "id" in item, f"invalid {label} record")
        identifier(item["id"])
        require(item["id"] not in result, f"duplicate {label} ID: {item['id']}")
        result[item["id"]] = item
    return result


def source_roots(source_id, sources, visiting=None, memo=None):
    visiting = set() if visiting is None else visiting
    memo = {} if memo is None else memo
    require(source_id in sources, f"missing source: {source_id}")
    require(source_id not in visiting, "cyclic source ancestry")
    if source_id in memo:
        return memo[source_id]
    source = sources[source_id]
    if not source["parents"]:
        # Identical source text cannot become independent corroboration merely
        # because an import supplied a different origin label. Seed all roots
        # once for this memo: validation visits every source, so repeatedly
        # scanning the complete source table would otherwise be quadratic.
        origins = {}
        for candidate in sources.values():
            if not candidate["parents"]:
                sha = candidate["sha256"]
                origins[sha] = min(origins.get(sha, candidate["origin"]), candidate["origin"])
        for candidate_id, candidate in sources.items():
            if not candidate["parents"]:
                memo.setdefault(candidate_id, {origins[candidate["sha256"]]})
        return memo[source_id]
    roots = set()
    for parent in source["parents"]:
        roots |= source_roots(parent, sources, visiting | {source_id}, memo)
    memo[source_id] = roots
    return roots


def has_generated(source_id, sources):
    pending, seen = [source_id], set()
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        source = sources[current]
        if source["kind"] == "generated":
            return True
        pending.extend(source["parents"])
    return False


def refs(references, sources, *, personal=False, nonempty=True):
    require(isinstance(references, list) and len(references) <= 30, "invalid references")
    require(not nonempty or references, "source references required")
    for ref in references:
        keys(ref, ("source", "quote"))
        require(ref["source"] in sources, f"unresolved source {ref['source']}")
        words(ref["quote"], "source excerpt")
        require(ref["quote"] in sources[ref["source"]]["text"], "excerpt not in source version")
        if personal:
            require(not has_generated(ref["source"], sources),
                    "generated material cannot be personal evidence, including via a derived source")


def fact(item, sources, claims):
    keys(item, ("value", "basis", "confidence", "reason", "sources", "claim_ids"), ("assessment",))
    require(item["basis"] in BASES, "invalid evidence basis")
    require(item["confidence"] in LEVELS, "invalid confidence")
    words(item["reason"], "fact reasoning")
    require(isinstance(item["claim_ids"], list), "claim_ids must be a list")
    require(all(cid in claims for cid in item["claim_ids"]), "unresolved personal claim")
    refs(item["sources"], sources, nonempty=False)
    if "assessment" in item:
        require(item["assessment"] in LEVELS, "assessment must be qualitative")
    if item["basis"] == "unknown":
        require(item["value"] is None and "assessment" not in item, "unknown fact has a value")
    else:
        require(item["value"] is not None, "known fact needs a value")
    if isinstance(item["value"], dict):
        interval(item["value"])
    else:
        require(item["value"] is None or type(item["value"]) in (str, bool, int, float),
                "fact must be a scalar or a range")
        if type(item["value"]) in (int, float):
            require(number(item["value"]), "non-finite fact")
    if item["basis"] in ("supported", "measured", "user_report"):
        require(item["sources"], "evidenced fact needs a source excerpt")
        refs(item["sources"], sources, personal=True)
    if item["basis"] == "measured":
        require(any(sources[r["source"]]["kind"] in ("observation", "outcome")
                    for r in item["sources"]), "measurement needs an observation or outcome")
    if item["basis"] == "user_report":
        require(any(sources[r["source"]]["kind"] in ("user_statement", "outcome")
                    for r in item["sources"]), "user report needs direct attribution")


def validate_state(state, *, idea_limit=3, claim_limit=200, source_limit=200, correction_limit=500):
    keys(state, ("schema_version", "sources", "claims", "ideas", "outcomes", "corrections"))
    require(state["schema_version"] == 1, "unsupported state schema")
    sources = indexed(state["sources"], "source", source_limit)
    claims = indexed(state["claims"], "claim", claim_limit)
    ideas = indexed(state["ideas"], "idea", idea_limit)
    outcomes = indexed(state["outcomes"], "outcome", 1000)
    corrections = indexed(state["corrections"], "correction", correction_limit)
    for source in sources.values():
        keys(source, ("id", "kind", "origin", "version", "text", "sha256", "locator", "parents"))
        require(source["kind"] in KINDS, "invalid source kind")
        words(source["origin"], "source origin", 200)
        require(type(source["version"]) is int and source["version"] >= 1, "invalid source version")
        words(source["text"], "source text", 500000)
        words(source["locator"], "source locator", 1000)
        require(source["sha256"] == digest(source["text"]), "source hash mismatch")
        require(isinstance(source["parents"], list), "source parents must be a list")
    ancestry = {}
    for source in sources.values():
        source_roots(source["id"], sources, memo=ancestry)
    for claim in claims.values():
        keys(claim, ("id", "key", "facet", "kind", "text", "stance", "confidence", "status", "sources", "contradicts"))
        identifier(claim["key"])
        require(claim["facet"] in FACETS, "invalid personal facet")
        require(claim["kind"] in ("explicit", "reported", "observed", "interpretation"), "invalid claim kind")
        require(claim["stance"] in ("asserts", "denies"), "invalid claim stance")
        require(claim["confidence"] in LEVELS, "invalid claim confidence")
        require(claim["status"] in ("active", "rejected", "excluded"), "invalid claim status")
        words(claim["text"], "claim text")
        refs(claim["sources"], sources, personal=True)
        kinds = {sources[r["source"]]["kind"] for r in claim["sources"]}
        if claim["kind"] == "explicit":
            require("user_statement" in kinds, "explicit claim requires a direct user statement")
        if claim["kind"] == "observed":
            require("observation" in kinds, "observed activity needs an inspected artifact")
        if claim["facet"] == "demonstrated_skills":
            require(claim["kind"] == "observed", "reported projects do not demonstrate skills")
        require(isinstance(claim["contradicts"], list), "contradicts must be a list")
        require(all(cid in claims and cid != claim["id"] for cid in claim["contradicts"]),
                "invalid contradiction target")
    for change in corrections.values():
        keys(change, ("id", "claim_id", "action", "reason", "sources", "recorded_at"))
        require(change["claim_id"] in claims, "correction refers to absent claim")
        require(change["action"] in ("reject", "exclude", "reinstate"), "invalid correction action")
        words(change["reason"], "correction reason")
        words(change["recorded_at"], "correction timestamp")
        refs(change["sources"], sources, personal=True)
        require(all(sources[r["source"]]["kind"] == "user_statement" for r in change["sources"]),
                "a correction requires an explicit user statement")
    rejected_propositions = {(c["key"], c["stance"]) for c in claims.values() if c["status"] == "rejected"}
    for claim in claims.values():
        require(not (claim["status"] == "active" and (claim["key"], claim["stance"]) in rejected_propositions),
                "rejected proposition cannot return under another claim ID")
        if claim["status"] == "rejected":
            require(any(c["claim_id"] == claim["id"] and c["action"] == "reject" for c in corrections.values()),
                    "rejection requires a recorded user correction")
    for idea in ideas.values():
        keys(idea, ("id", "category", "title", "description", "inspiration", "facts", "alternatives", "experiment"))
        require(idea["category"] in CATEGORIES, "invalid evaluation category")
        words(idea["title"], "idea title", 300)
        words(idea["description"], "idea description")
        refs(idea["inspiration"], sources)
        require(isinstance(idea["facts"], dict) and len(idea["facts"]) <= 60, "fact budget exceeded")
        for name, item in idea["facts"].items():
            identifier(name)
            fact(item, sources, claims)
        require(isinstance(idea["alternatives"], list) and 1 <= len(idea["alternatives"]) <= 8,
                "one to eight alternatives required")
        for alternative in idea["alternatives"]:
            keys(alternative, ("name", "tradeoff", "sources"))
            words(alternative["name"], "alternative name")
            words(alternative["tradeoff"], "alternative comparison")
            refs(alternative["sources"], sources, nonempty=False)
        keys(idea["experiment"], ("question", "scope", "success", "failure"))
        for value in idea["experiment"].values():
            words(value, "experiment field")
    for event in outcomes.values():
        validate_outcome(event, ideas, sources)
    return state


OUTCOME_METRICS = {
    "implementation_minutes", "actual_usefulness", "continued_usage", "money_earned",
    "reason_abandoned", "user_rating", "unexpected_costs", "useful_thoughts", "saved", "revisited",
}


def validate_outcome(event, ideas, sources):
    keys(event, ("id", "idea_id", "event", "occurred_at", "scope", "method", "sources", "metrics", "reason_code"))
    require(event["idea_id"] in ideas, "outcome must link to a known idea")
    require(event["event"] in ("explored", "rejected", "prototype_built", "used", "abandoned", "rated", "saved", "revisited"),
            "invalid outcome event")
    require(event["method"] in ("user_report", "measured"), "outcomes require actual attribution")
    from datetime import datetime
    try:
        require(datetime.fromisoformat(event["occurred_at"]).tzinfo is not None, "outcome time needs timezone")
    except (ValueError, TypeError) as exc:
        raise Invalid("invalid outcome timestamp") from exc
    words(event["scope"], "outcome scope")
    require(event["reason_code"] in (None, "unexpected_time", "low_use", "other"), "invalid reason code")
    refs(event["sources"], sources, personal=True)
    expected = ("observation", "outcome") if event["method"] == "measured" else ("user_statement", "outcome")
    require(all(sources[r["source"]]["kind"] in expected for r in event["sources"]),
            "outcome source does not match its reporting method")
    require(isinstance(event["metrics"], dict) and event["metrics"].keys() <= OUTCOME_METRICS,
            "unknown outcome metric")
    for key, value in event["metrics"].items():
        if value is None:
            continue
        if key == "implementation_minutes":
            require(number(value) and value >= 0, "implementation time must be nonnegative minutes")
        elif key in ("continued_usage", "saved", "revisited"):
            require(type(value) is bool, "usage/saving/revisiting must be boolean or unknown")
        elif key == "money_earned":
            require(ideas[event["idea_id"]]["category"] == "commercial", "earnings only apply to commercial examples")
            keys(value, ("amount", "currency", "period"))
            require(number(value["amount"]) and value["amount"] >= 0, "invalid earnings")
            words(value["currency"], "currency", 10)
            words(value["period"], "earnings period", 200)
        elif key in ("actual_usefulness", "user_rating"):
            require(value in (*LEVELS, "none"), "usefulness/rating must be qualitative")
        else:
            words(value, "outcome detail")


def validate_policy(policy):
    keys(policy, ("schema_version", "name", "basis", "policies", "learning"))
    require(policy["schema_version"] == 1, "unsupported policy schema")
    words(policy["name"], "policy name")
    words(policy["basis"], "policy provenance")
    require(isinstance(policy["policies"], dict) and set(policy["policies"]) == set(CATEGORIES),
            "all three category policies required")
    for category, section in policy["policies"].items():
        keys(section, ("required_facts", "priorities", "criteria", "hard_constraints"))
        require(isinstance(section["required_facts"], list) and len(section["required_facts"]) <= 40,
                "invalid required fact list")
        for name in section["required_facts"]:
            identifier(name)
        criteria = indexed(section["criteria"], "criterion", 24)
        require(criteria and set(section["priorities"]) == set(criteria)
                and len(section["priorities"]) == len(criteria), "priorities must order every criterion once")
        for criterion in criteria.values():
            keys(criterion, ("id", "fact", "weight", "rule", "reason"), ("strong", "moderate", "unit"))
            identifier(criterion["fact"])
            require(type(criterion["weight"]) is int and 0 <= criterion["weight"] <= 5,
                    "preference weight must be an integer from 0 to 5")
            require(criterion["rule"] in ("assessment", "lower", "higher"), "unknown criterion rule")
            words(criterion["reason"], "policy rationale")
            if criterion["rule"] != "assessment":
                require(all(number(criterion.get(k)) and criterion[k] >= 0 for k in ("strong", "moderate")),
                        "numeric rule needs nonnegative band boundaries")
                ordered = (criterion["strong"] <= criterion["moderate"] if criterion["rule"] == "lower"
                           else criterion["strong"] >= criterion["moderate"])
                require(ordered, "reversed criterion bands")
                words(criterion.get("unit"), "criterion unit")
        constraints = indexed(section["hard_constraints"], "constraint", 16)
        for constraint in constraints.values():
            keys(constraint, ("id", "fact", "op", "limit", "scope", "reason"), ("unit",))
            identifier(constraint["fact"])
            require(constraint["op"] in ("le", "ge", "eq"), "unknown constraint operator")
            require(constraint["scope"] in ("experiment", "implementation"), "invalid constraint scope")
            words(constraint["reason"], "constraint reason")
            if constraint["op"] != "eq":
                require(number(constraint["limit"]) and constraint["limit"] >= 0, "invalid numeric constraint")
                words(constraint.get("unit"), "constraint unit")
            else:
                require(type(constraint["limit"]) in (str, bool), "equality limit must be string or boolean")
        if category == "creative":
            require(not any("money" in name or "payback" in name or "revenue" in name
                            for name in section["required_facts"]), "creative policy cannot require financial justification")
    keys(policy["learning"], ("min_distinct_ideas", "propose_setup_cap_minutes"))
    require(type(policy["learning"]["min_distinct_ideas"]) is int
            and 2 <= policy["learning"]["min_distinct_ideas"] <= 100, "learning needs at least two distinct ideas")
    require(number(policy["learning"]["propose_setup_cap_minutes"])
            and policy["learning"]["propose_setup_cap_minutes"] >= 0, "invalid proposed setup cap")
    return policy
