"""Personal graph over the existing evidence store; no inferred biography or network.

Claims are the canonical statement nodes. Relationships and temporal context are
small, versioned additions; graph exports are projections, never a second database.
"""

from copy import deepcopy
from datetime import date, datetime, timezone

from . import evidence
from .storage import atomic_text, encoded
from .validation import FACETS, digest, indexed, keys, refs, require, words
from .workflow import Workflow, normalize, now, uid


# First question establishes the area; the second adds concrete examples/context.
TOPICS = {
    "claimed_skills": ("Skills", "What can you do, and how have you used it? Add one skill at a time.",
                       "For an existing skill, what have you delivered, how recently, and how independently?"),
    "interests": ("Interests", "What subjects or activities do you keep returning to voluntarily?",
                  "Which part interests you most, and what has lost its appeal?"),
    "preferences": ("Preferences", "What do you prefer when choosing how to spend your time?",
                    "Describe a choice you liked, an alternative you disliked, and why."),
    "working_style": ("Working style", "What conditions help you do your best work?",
                      "How do you prefer to collaborate, communicate and handle ambiguity?"),
    "values": ("Values", "What matters enough that you would turn down an opportunity over it?",
               "Describe a tradeoff that reveals what matters to you."),
    "personality": ("Personality", "How would you describe yourself, in your own words?",
                    "When does that description fit, and when are you different?"),
    "goals": ("Goals", "What do you want to achieve, and over what timeframe?",
              "Why does this goal matter, and what would progress look like?"),
    "constraints": ("Constraints", "What limits your available time, money, energy or commitments?",
                    "Which limits are firm, which are flexible, and when might they change?"),
    "resources": ("Resources", "What tools, assets, access or support could you draw on?",
                  "What can you actually use now, and what would require permission or investment?"),
    "motivations": ("Motivations", "What makes you start something and keep going?",
                    "Describe something you sustained and something you abandoned. What differed?"),
    "avoidances": ("Dislikes & avoidances", "What work or situations do you want to avoid, and why?",
                   "Is this a firm boundary, a current preference, or dependent on context?"),
    "learning_style": ("Learning style", "How do you prefer to learn something unfamiliar?",
                       "What helped with your last difficult learning experience?"),
    "risk_tolerance": ("Risk preferences", "What uncertainty or potential loss are you comfortable with?",
                       "How does that change with time, money, reputation or other commitments?"),
    "active_projects": ("Current projects", "What are you actively working on, and what is your part?",
                        "What is the current stage, next decision and biggest obstacle?"),
    "previous_projects": ("Past experience", "What have you worked on, and what did you personally contribute?",
                          "What went well or badly, and would you choose similar work again?"),
    "previous_ideas": ("Past ideas", "What possibilities have you already considered?",
                       "What drew you to a past idea, and why did you pursue or leave it?"),
    "context": ("Other context", "What else would help someone understand your situation?",
                "What might someone misunderstand without additional context?"),
}
LABELS = {facet: facet.replace("_", " ").capitalize() for facet in FACETS}
LABELS.update({facet: topic[0] for facet, topic in TOPICS.items()})
LABELS.update(demonstrated_skills="Demonstrated contributions",
              constraints_preferences="Earlier preferences & constraints")
RELATIONS = {"supports": "supports", "uses_skill": "uses skill", "motivates": "motivates",
             "constrains": "constrains", "depends_on": "depends on",
             "related_to": "relates to", "conflicts_with": "conflicts with"}


def empty_knowledge():
    return {"version": 1, "details": {}, "links": []}


def date_value(value):
    if value is None:
        return None
    require(isinstance(value, str), "date must be YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("date must be YYYY-MM-DD") from exc
    require(parsed.isoformat() == value, "date must be YYYY-MM-DD")
    return parsed


def validate_knowledge(state):
    graph = state["knowledge"]
    keys(graph, ("version", "details", "links"))
    require(graph["version"] == 1, "unsupported knowledge schema")
    claims = {c["id"] for c in state["core"]["claims"]}
    sources = {s["id"]: s for s in state["core"]["sources"]}
    require(isinstance(graph["details"], dict) and graph["details"].keys() <= claims,
            "knowledge details require existing claims")
    for detail in graph["details"].values():
        keys(detail, ("context", "recorded_at", "reviewed_at", "valid_from", "valid_until"))
        words(detail["context"], "context", 1000)
        for field in ("recorded_at", "reviewed_at"):
            require(isinstance(detail[field], str) and datetime.fromisoformat(detail[field]).tzinfo is not None,
                    "knowledge timestamp needs a timezone")
        start, end = date_value(detail["valid_from"]), date_value(detail["valid_until"])
        require(start is None or end is None or start <= end, "end date precedes start date")
    signatures = set()
    for link in indexed(graph["links"], "relationship", 5000).values():
        keys(link, ("id", "from", "to", "relation", "reason", "sources", "recorded_at", "status"))
        require(link["from"] in claims and link["to"] in claims and link["from"] != link["to"],
                "relationship needs two different existing statements")
        require(link["relation"] in RELATIONS, "unknown relationship")
        require(link["status"] in ("active", "retired"), "invalid relationship status")
        words(link["reason"], "relationship explanation", 4000)
        require(datetime.fromisoformat(link["recorded_at"]).tzinfo is not None, "relationship timestamp needs timezone")
        refs(link["sources"], sources, personal=True)
        require(all(sources[r["source"]]["kind"] == "user_statement" for r in link["sources"]),
                "relationships require explicit user attribution")
        signature = (link["from"], link["relation"], link["to"])
        if link["status"] == "active":
            require(signature not in signatures, "duplicate active relationship")
            signatures.add(signature)


def detail(context="General", valid_from=None, valid_until=None):
    return {"context": context.strip() or "General", "recorded_at": now(), "reviewed_at": now(),
            "valid_from": valid_from or None, "valid_until": valid_until or None}


def statuses(state, today=None):
    """Compute current usability once, with dated entries excluded before conflicts."""
    today = today or datetime.now(timezone.utc).date()
    graph = state.get("knowledge", empty_knowledge())
    core = {"claims": [{**claim, "contradicts": list(claim["contradicts"])} for claim in state["core"]["claims"]]}
    temporal = {}
    for claim in core["claims"]:
        meta = graph["details"].get(claim["id"], {})
        start, end = date_value(meta.get("valid_from")), date_value(meta.get("valid_until"))
        if claim["status"] == "active" and ((start and start > today) or (end and end < today)):
            temporal[claim["id"]] = "upcoming" if start and start > today else "expired"
            claim["status"] = "excluded"
    by_id = {c["id"]: c for c in core["claims"]}
    for link in graph["links"]:
        if link["status"] == "active" and link["relation"] == "conflicts_with":
            by_id[link["from"]]["contradicts"].append(link["to"])
    if "understanding" in state:
        # Withdrawing an interview answer also withholds its derived, accepted
        # interpretations until reviewed again. A user's written correction is
        # independent evidence and is not silently transferred or discarded.
        source_status = evidence.claim_statuses(core)
        proposals = {p["id"]: p for p in state["proposals"]}
        answers = {a["id"]: a for a in state.get("skillmap", {}).get("answers", [])}
        for insight in state["understanding"]["insights"]:
            proposal = proposals[insight["proposal"]]
            cid = proposal["core_id"]
            answer = answers[insight["answer_id"]]
            if (proposal["status"] == "accepted" and cid in by_id and by_id[cid]["status"] == "active"
                    and not source_status[answer["claim_id"]]["usable"]):
                by_id[cid]["status"] = "excluded"
                temporal[cid] = "source_withdrawn"
    if "memory" in state or "capture" in state:
        from .memory import project_statuses
        project_statuses(state, core, temporal)
    result = evidence.claim_statuses(core)
    for cid, value in result.items():
        if cid in temporal:
            value.update(status=temporal[cid], usable=False)
        elif value["status"] == "active":
            value["status"] = "current" if value["usable"] else "tentative"
    return result


def inventory(state, today=None):
    status = statuses(state, today)
    claims = state["core"]["claims"]
    pending = [p for p in state["proposals"] if p["status"] == "proposed"]
    return [{"facet": facet, "label": LABELS[facet],
             "current": sum(c["facet"] == facet and status[c["id"]]["usable"] for c in claims),
             "pending": sum(p["claim"]["facet"] == facet for p in pending)} for facet in FACETS]


def next_question(state):
    coverage = {row["facet"]: row for row in inventory(state)}
    earlier = coverage["constraints_preferences"]
    if earlier["current"] or earlier["pending"]:
        for facet in ("preferences", "constraints"):
            coverage[facet]["current"] += earlier["current"]
            coverage[facet]["pending"] += earlier["pending"]
    # Existing answers and imports take precedence; no duplicate skills onboarding.
    missing = [f for f in TOPICS if not coverage[f]["current"] and not coverage[f]["pending"]]
    if missing:
        facet = missing[0]
        return facet, TOPICS[facet][1]
    facet = min(TOPICS, key=lambda f: coverage[f]["current"] + coverage[f]["pending"])
    return facet, TOPICS[facet][2]


def build_graph(state, *, include_history=False, today=None):
    status = statuses(state, today)
    claims = [c for c in state["core"]["claims"] if include_history or status[c["id"]]["usable"]]
    ids = {c["id"] for c in claims}
    knowledge = state.get("knowledge", empty_knowledge())
    nodes = [{"id": "person:self", "type": "person", "label": "Me"}]
    edges = []
    from .memory import effective_source_index
    source_index = effective_source_index(state)
    for claim in claims:
        claim = {**claim, "sources": claim["sources"] if include_history else source_index[claim["id"]]}
        cid = "claim:" + claim["id"]
        nodes.append({"id": cid, "type": "statement", "label": claim["text"],
                      "claim": deepcopy(claim), "state": status[claim["id"]]["status"],
                      "details": deepcopy(knowledge["details"].get(claim["id"], {}))})
        edges.append({"from": "person:self", "to": cid, "relation": claim["facet"]})
        for ref in claim["sources"]:
            edges.append({"from": cid, "to": "source:" + ref["source"], "relation": "evidenced_by", "quote": ref["quote"]})
    for link in knowledge["links"]:
        if link["from"] in ids and link["to"] in ids and (include_history or link["status"] == "active"):
            edges.append({**deepcopy(link), "from": "claim:" + link["from"], "to": "claim:" + link["to"]})
            for ref in link["sources"]:
                edges.append({"from": "claim:" + link["from"], "to": "source:" + ref["source"],
                              "relation": "relationship_evidence", "link_id": link["id"], "quote": ref["quote"]})
    if "memory" in state:
        proposals = {p["id"]: p for p in state["proposals"]}
        relations = {"support": "supports", "update": "supersedes", "resolve": "resolves_question", "conflict": "conflicts_with"}
        for pid, meta in state["memory"]["proposals"].items():
            proposal, fact = proposals[pid], meta["fact"]
            if (proposal["core_id"] in ids and fact["target_id"] in ids
                    and (include_history or proposal["status"] == "accepted")):
                edges.append({"id": pid, "from": "claim:" + proposal["core_id"],
                    "to": "claim:" + fact["target_id"], "relation": relations[fact["action"]],
                    "reason": fact["scope"], "review_state": proposal["status"],
                    "question": deepcopy(meta["question"])})
    source_quotes = {}
    for edge in edges:
        if edge["to"].startswith("source:"):
            source_quotes.setdefault(edge["to"].removeprefix("source:"), {}).setdefault(edge["quote"], None)
    for source in state["core"]["sources"]:
        if source["id"] in source_quotes:
            # Export only referenced passages, not unrelated parts of an imported file.
            quotes = list(source_quotes[source["id"]])
            nodes.append({"id": "source:" + source["id"], "type": "source", "label": source["locator"],
                          "kind": source["kind"], "version": source["version"], "sha256": source["sha256"],
                          "passages": quotes})
    if "understanding" in state or "memory" in state:
        from . import skillmap, understanding
        maps = [skillmap.catalog(state), understanding.semantic_graph(state)]
        entity_nodes = {}
        for projection in maps:
            for node in projection["nodes"]:
                entity = "entity:" + node["id"]
                existing = entity_nodes.get(entity)
                if existing is None:
                    existing = {**deepcopy(node), "id": entity, "type": node["kind"]}
                    nodes.append(existing)
                    entity_nodes[entity] = existing
                for claim_id in node["claim_ids"]:
                    if claim_id in ids:
                        edges.append({"from": "claim:" + claim_id, "to": entity, "relation": "describes"})
            for link in projection["links"]:
                edges.append({**deepcopy(link), "from": "entity:" + link["from"], "to": "entity:" + link["to"],
                              "relation": link.get("relation", "uses_skill"),
                              "reason": link.get("basis", "reviewed answer")})
    return {"schema_version": 1, "dataset": state["dataset"], "scope": "history" if include_history else "current",
            "nodes": nodes, "edges": edges}


def issues(state):
    status = statuses(state)
    result = [f"{sum(p['status'] == 'proposed' for p in state['proposals'])} imported statements awaiting review."]
    for flag in ("contradicted", "expired", "upcoming", "tentative", "source_withdrawn"):
        count = sum(v["status"] == flag for v in status.values())
        if count:
            result.append(f"{count} {flag} statements; withheld from the current profile.")
    current = [c for c in state["core"]["claims"] if status[c["id"]]["usable"]]
    seen = {}
    for claim in current:
        signature = (claim["facet"], normalize(claim["text"]))
        if signature in seen:
            result.append(f"Possible duplicate: {claim['id']} and {seen[signature]}. Review before excluding either.")
        seen[signature] = claim["id"]
    latest = {}
    for source in state["core"]["sources"]:
        latest[source["origin"]] = max(source["version"], latest.get(source["origin"], 0))
    sources = {s["id"]: s for s in state["core"]["sources"]}
    for claim in current:
        if any(sources[r["source"]]["version"] < latest[sources[r["source"]]["origin"]] for r in claim["sources"]):
            result.append(f"Source updated: review {claim['id']} against the newer version; its original evidence is preserved.")
    return result


def profile_text(state):
    status = statuses(state)
    from .memory import effective_source_index
    source_index = effective_source_index(state)
    lines = ["# My knowledge graph", "", f"Dataset: {state['dataset']}. User descriptions and attributed evidence; not a psychological assessment.",
             "", "## Review attention", "", *issues(state), "", "## Current profile"]
    for row in inventory(state):
        lines.extend(["", "### " + row["label"], ""])
        claims = [c for c in state["core"]["claims"] if c["facet"] == row["facet"] and status[c["id"]]["usable"]]
        if not claims:
            lines.append("No current reviewed statement." + (f" {row['pending']} awaiting review." if row["pending"] else ""))
        for claim in claims:
            lines.append(f"- {claim['text']} ({claim['id']}; {claim['kind']})")
            meta = state.get("knowledge", empty_knowledge())["details"].get(claim["id"], {})
            if meta:
                lines.append(f"  Context: {meta['context']}; dates: {meta['valid_from'] or 'unspecified'} to {meta['valid_until'] or 'open'}.")
            for ref in source_index[claim["id"]]:
                lines.append(f"  Evidence [{ref['source']}]: {ref['quote']}")
    graph = build_graph(state)
    lines += ["", "## Connections", ""]
    by_id = {n["id"]: n["label"] for n in graph["nodes"]}
    for edge in graph["edges"]:
        if edge["relation"] in RELATIONS:
            lines += [f"- {by_id[edge['from']]} → {RELATIONS[edge['relation']]} → {by_id[edge['to']]}",
                      "  Context: " + edge["reason"]]
    if "understanding" in state:
        from .understanding_contract import RELATIONS as INSIGHT_RELATIONS
        lines += ["", "## What your answers add", ""]
        for edge in graph["edges"]:
            if edge["relation"] in INSIGHT_RELATIONS:
                lines.append(f"- {by_id[edge['from']]} → {INSIGHT_RELATIONS[edge['relation']]} → {by_id[edge['to']]}")
    lines += ["", "Coverage names areas to explore; it does not measure how completely a person is understood."]
    return "\n".join(lines) + "\n"


def claim_text(state, cid):
    claim = next(c for c in state["core"]["claims"] if c["id"] == cid)
    status = statuses(state)[cid]
    lines = [claim["text"], "", f"{LABELS[claim['facet']]} · {status['status']} · {claim['kind']}",
             f"ID: {cid}"]
    meta = state.get("knowledge", empty_knowledge())["details"].get(cid, {})
    if meta:
        lines += [f"Context: {meta['context']}", f"Valid: {meta['valid_from'] or 'unspecified'} to {meta['valid_until'] or 'open'}",
                  f"Last reviewed: {meta['reviewed_at']}"]
    else:
        lines.append("Context and dates not recorded in the earlier profile.")
    lines += ["", "EVIDENCE"]
    sources = {s["id"]: s for s in state["core"]["sources"]}
    for ref in claim["sources"]:
        source = sources[ref["source"]]
        lines += [f"{source['locator']} · v{source['version']} · {source['kind']}", ref["quote"], ""]
    lines += ["CONNECTIONS"]
    by_id = {c["id"]: c for c in state["core"]["claims"]}
    for link in state.get("knowledge", empty_knowledge())["links"]:
        if cid in (link["from"], link["to"]):
            lines += [f"{by_id[link['from']]['text']} → {RELATIONS[link['relation']]} → {by_id[link['to']]['text']}",
                      f"{link['status']} · {link['reason']}"]
    if status["conflicts"]:
        lines += ["", "CONFLICTS", *status["conflicts"]]
    if "memory" in state:
        from .memory import proposal_detail
        for proposal in state["proposals"]:
            if proposal["core_id"] == cid or proposal["replacement"] == cid:
                context = proposal_detail(state, proposal["id"])
                if context:
                    lines += ["", "PROPOSED CHANGE AND REVIEW", proposal["status"], context]
    lines += ["", "REVIEW HISTORY"]
    lines.extend(f"{c['recorded_at']} · {c['action']} · {c['reason']}" for c in state["core"]["corrections"] if c["claim_id"] == cid)
    return "\n".join(lines)


class Knowledge(Workflow):
    """The active product exposes extraction only; historical ideas remain stored."""

    def prepare(self, stage, **options):
        require(stage == "claims", "Idea generation is deferred. Build and review your knowledge graph first.")
        return super().prepare(stage, **options)

    def approve_export(self, request, *, approved):
        require(request["stage"] == "claims", "Idea generation is deferred.")
        return super().approve_export(request, approved=approved)

    def import_response(self, run_id, path):
        run = next(r for r in self.load()["runs"] if r["id"] == run_id)
        require(run["stage"] == "claims", "This historical idea handoff is deferred; cancel it to continue building your graph.")
        return super().import_response(run_id, path)

    def extract_listed(self, source_id):
        """Stage literal resume details locally, with the same review boundary."""
        from .intake import resume_claims
        from .workflow import possible_matches
        result = []
        def operation(state):
            source = next(s for s in state["core"]["sources"] if s["id"] == source_id)
            # All parsing/validation finishes before mutation; Store also validates
            # the complete candidate state before changing its revision pointer.
            claims = resume_claims(source)
            for claim in claims:
                if any(p["claim"] == claim for p in state["proposals"]):
                    continue
                pid = uid("p-")
                state["proposals"].append({"id": pid, "claim": claim, "status": "proposed",
                    "matches": possible_matches(claim, state), "run_id": "local-listed-v1",
                    "core_id": None, "replacement": None,
                    "note": "Read from a structured resume locally; not independently verified. Awaiting your review."})
                result.append(pid)
        self.update(operation, "local structured resume extraction; every detail awaits human review")
        return result

    @staticmethod
    def _source(state, text, locator):
        sid = uid("s-")
        state["core"]["sources"].append({"id": sid, "kind": "user_statement", "origin": sid,
            "version": 1, "text": text, "sha256": digest(text), "locator": locator, "parents": []})
        return {"source": sid, "quote": text}

    def remember(self, text, facet, *, context="General", valid_from=None, valid_until=None):
        words(text.strip(), "your statement", 4000)
        require(facet in TOPICS, "choose a self-described topic; demonstrated skill needs inspected evidence")
        result = []
        def operation(state):
            graph = state.setdefault("knowledge", empty_knowledge())
            signature = (facet, normalize(text), context.strip() or "General", valid_from or None, valid_until or None)
            for claim in state["core"]["claims"]:
                meta = graph["details"].get(claim["id"], {})
                if (claim["facet"], normalize(claim["text"]), meta.get("context", "General"),
                        meta.get("valid_from"), meta.get("valid_until")) == signature and claim["status"] == "active":
                    result.append(claim["id"])
                    return
            cid = uid("c-")
            reference = self._source(state, text, "Guided profile: " + LABELS[facet])
            state["core"]["claims"].append({"id": cid, "key": cid, "facet": facet, "kind": "explicit",
                "text": text, "stance": "asserts", "confidence": "strong", "status": "active",
                "sources": [reference], "contradicts": []})
            graph["details"][cid] = detail(context, valid_from, valid_until)
            result.append(cid)
        self.update(operation, "user added their own words to the knowledge graph")
        return result[0]

    def amend(self, cid, action, text, *, facet=None, context="General", valid_from=None, valid_until=None):
        require(action in ("correct", "exclude"), "choose correct or exclude")
        words(text.strip(), "your correction or explanation", 4000)
        def operation(state):
            claim = next(c for c in state["core"]["claims"] if c["id"] == cid)
            graph = state.setdefault("knowledge", empty_knowledge())
            reference = self._source(state, text, "Knowledge graph: explicit " + action)
            claim["status"] = "excluded"
            state["core"]["corrections"].append({"id": uid("action-"), "claim_id": cid,
                "action": "exclude", "reason": text, "sources": [reference], "recorded_at": now()})
            if action == "correct":
                chosen = facet or claim["facet"]
                require(chosen in TOPICS or chosen == "constraints_preferences", "choose a self-described topic")
                replacement = uid("c-")
                state["core"]["claims"].append({"id": replacement, "key": replacement, "facet": chosen,
                    "kind": "explicit", "text": text, "stance": "asserts", "confidence": "strong",
                    "status": "active", "sources": [reference], "contradicts": []})
                graph["details"][replacement] = detail(context, valid_from, valid_until)
            for proposal in state["proposals"]:
                if cid == (proposal["replacement"] or proposal["core_id"]):
                    proposal["status"] = "corrected" if action == "correct" else "excluded"
                    if action == "correct":
                        proposal["replacement"] = replacement
                    proposal["note"] = text
            # Existing connections keep their historical endpoints. Do not silently
            # transfer them to a correction that may mean something different.
        return self.update(operation, "user revised knowledge; original statement and connections retained")

    def connect(self, from_id, relation, to_id, reason):
        words(reason.strip(), "why these statements are connected", 4000)
        require(relation in RELATIONS, "choose a known relationship")
        result = []
        def operation(state):
            current = statuses(state)
            require(from_id != to_id and all(current.get(cid, {}).get("usable") for cid in (from_id, to_id)),
                    "choose two different current reviewed statements")
            graph = state.setdefault("knowledge", empty_knowledge())
            for link in graph["links"]:
                if (link["from"], link["relation"], link["to"], link["status"]) == (from_id, relation, to_id, "active"):
                    result.append(link["id"])
                    return
            reference = self._source(state, reason, "Knowledge graph: explicit relationship")
            lid = uid("link-")
            graph["links"].append({"id": lid, "from": from_id, "to": to_id, "relation": relation,
                "reason": reason, "sources": [reference], "recorded_at": now(), "status": "active"})
            result.append(lid)
        self.update(operation, "user connected two reviewed statements")
        return result[0]

    def retire_link(self, lid):
        def operation(state):
            link = next(l for l in state["knowledge"]["links"] if l["id"] == lid)
            link["status"] = "retired"
        return self.update(operation, "user retired a relationship; original explanation retained")

    def export_profile(self):
        state = self.load()
        target = self.path / "exports" / uid("profile-")
        # Manifest is written last, making interrupted export detectable; previous
        # complete exports are never overwritten.
        markdown = profile_text(state)
        from .profile import render
        overview = render(state)
        graph = encoded(build_graph(state))
        atomic_text(target / "profile.md", markdown)
        atomic_text(target / "about-me.md", overview)
        atomic_text(target / "graph.json", graph)
        atomic_text(target / "manifest.json", encoded({"created_at": now(), "dataset": self.dataset,
            "scope": "current reviewed statements and their cited passages",
            "files": {"profile.md": digest(markdown), "about-me.md": digest(overview), "graph.json": digest(graph)}}))
        return target
