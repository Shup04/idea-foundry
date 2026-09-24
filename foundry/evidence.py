"""Human-controlled personal claims. No extraction or automatic personalization."""

from .validation import refs, require, source_roots


def claim_statuses(state):
    claims = {claim["id"]: claim for claim in state["claims"]}
    active = {cid for cid, claim in claims.items() if claim["status"] == "active"}
    propositions, explicit = {}, {cid: set() for cid in claims}
    order = {cid: n for n, cid in enumerate(claims)}
    for cid, claim in claims.items():
        if cid in active:
            propositions.setdefault((claim["key"], claim["stance"]), set()).add(cid)
        for other in claim["contradicts"]:
            if other in claims:
                explicit[cid].add(other)
                explicit[other].add(cid)
    result = {}
    for cid, claim in claims.items():
        conflicts = []
        if cid in active:
            opposite = "denies" if claim["stance"] == "asserts" else "asserts"
            conflicts = sorted((explicit[cid] & active | propositions.get((claim["key"], opposite), set())) - {cid},
                               key=order.get)
        result[cid] = {
            "status": "contradicted" if conflicts else claim["status"],
            "conflicts": conflicts,
            "usable": claim["status"] == "active" and not conflicts and claim["kind"] != "interpretation",
        }
    return result


def support_origins(claim, state):
    sources = {source["id"]: source for source in state["sources"]}
    roots = set()
    for ref in claim["sources"]:
        roots |= source_roots(ref["source"], sources)
    return sorted(roots)


def correct(state, request):
    # A source is supplied explicitly with each user action; generated proposals
    # are never executable actions and cannot call this function themselves.
    from .validation import keys
    keys(request, ("source", "correction"))
    source, correction = request["source"], request["correction"]
    require(source["kind"] == "user_statement", "correction must be attributed to the user")
    require(not source["parents"], "correction must be an independent user statement")
    require(source["id"] not in {s["id"] for s in state["sources"]}, "correction source ID already exists")
    state["sources"].append(source)
    sources = {s["id"]: s for s in state["sources"]}
    refs(correction["sources"], sources, personal=True)
    require(all(r["source"] == source["id"] for r in correction["sources"]), "correction must cite its new source")
    claims = {c["id"]: c for c in state["claims"]}
    require(correction["claim_id"] in claims, "unknown claim to correct")
    action = correction["action"]
    require(action in ("reject", "exclude", "reinstate"), "unknown correction action")
    target = claims[correction["claim_id"]]
    # All copies of this proposition and stance receive the same action. An
    # independently sourced opposite statement is preserved, never invented or
    # rejected as a side effect of correcting this inference.
    status = {"reject": "rejected", "exclude": "excluded", "reinstate": "active"}[action]
    for claim in claims.values():
        if claim["key"] == target["key"] and claim["stance"] == target["stance"]:
            claim["status"] = status
            record = dict(correction)
            record["claim_id"] = claim["id"]
            record["id"] = correction["id"] if claim["id"] == target["id"] else f"{correction['id']}.{claim['id']}"
            state["corrections"].append(record)


def add_claim(state, request):
    """Manual correction/addition with immutable new source versions, never a model feed import."""
    from .validation import keys
    keys(request, ("sources", "claim"))
    state["sources"].extend(request["sources"])
    state["claims"].append(request["claim"])
