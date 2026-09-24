"""Readable projections of reviewed personal evidence, without model inference.

The overview is deliberately short. Search retains every usable statement and
its quotations, while the full graph remains the portable, complete record.
Counts describe stored evidence, never how completely a person is understood.
"""

from collections import Counter
from datetime import date
import re

from . import knowledge, skillmap


SECTION_LIMIT = 4
ENTITY_LIMIT = 8
SEARCH_LIMIT = 25
SECTIONS = (
    ("direction", "What matters and motivates you", ("values", "motivations", "goals")),
    ("interests", "What you enjoy and prefer", ("interests", "preferences")),
    ("working", "How you work and learn", ("working_style", "learning_style", "personality")),
    ("boundaries", "What drains you or sets limits", ("avoidances", "constraints", "risk_tolerance", "constraints_preferences")),
    ("circumstances", "Your circumstances and resources", ("context", "resources")),
    ("earlier_ideas", "Possibilities you have explored", ("previous_ideas",)),
)
BREADTH = (
    ("values", "What matters enough that you would turn down an otherwise attractive opportunity? Describe a real tradeoff."),
    ("goals", "What would you like your life to look like a year from now, and why does that matter to you?"),
    ("motivations", "What makes you keep working on something after the initial excitement wears off? Give one example."),
    ("working_style", "Think of a day when work felt natural. What were you doing, with whom, and under what conditions?"),
    ("learning_style", "When you last learned something difficult, what helped you understand it? What did not help?"),
    ("resources", "What people, tools, communities or spaces can you actually draw on when pursuing something?"),
    ("risk_tolerance", "What kinds of uncertainty are you comfortable with? Where would you put a firm limit on time, money or commitment?"),
    ("avoidances", "What kinds of work leave you drained, even when you are good at them? Is that always true or situation-dependent?"),
)


def _short(text, limit):
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def _plain(text):
    """Keep imported Markdown from becoming links, headings or HTML in exports."""
    value = " ".join(str(text).split())
    for character in ("\\", "`", "*", "_", "[", "]", "<", ">", "#", "|"):
        value = value.replace(character, "\\" + character)
    return value


def _terms(text):
    # Keep C++ and C# distinct from the common statement-ID prefix "c".
    return set(re.findall(r"\w+(?:\+\+|#)?", text.casefold().replace("_", " ")))


def _sources(references, sources):
    result, seen = [], set()
    for ref in references:
        signature = ref["source"], ref["quote"]
        if signature in seen:
            continue
        seen.add(signature)
        source = sources[ref["source"]]
        result.append({"id": source["id"], "quote": ref["quote"], "locator": source["locator"],
                       "kind": source["kind"], "version": source["version"], "sha256": source["sha256"]})
    return result


def _records(state, usable, graph):
    proposals = {p["core_id"]: p for p in state["proposals"] if p["status"] == "accepted"}
    corrected = {p["replacement"] for p in state["proposals"] if p.get("replacement")}
    insights = {}
    if "understanding" in state:
        from .understanding import accepted
        insights = {insight["claim_id"]: insight for insight in accepted(state)}
    references = {claim["id"]: claim["sources"] for claim in state["core"]["claims"]}
    if "memory" in state:
        from .memory import accepted, effective_source_index
        insights.update({insight["claim_id"]: insight for insight in accepted(state)})
        references = effective_source_index(state)
    sources = {source["id"]: source for source in state["core"]["sources"]}
    nodes = {node["id"]: node for node in graph["nodes"]}
    contexts = {}
    for node in graph["nodes"]:
        if node["kind"] in skillmap.EXPERIENCES:
            for cid in node["claim_ids"]:
                contexts.setdefault(cid, []).append(node["label"])
    for answer in state.get("skillmap", {}).get("answers", []):
        if answer["experience"] in nodes:
            contexts.setdefault(answer["claim_id"], []).append(nodes[answer["experience"]]["label"])
    for cid, insight in insights.items():
        if insight["experience"] in nodes:
            contexts.setdefault(cid, []).append(nodes[insight["experience"]]["label"])
    result = []
    for order, claim in enumerate(state["core"]["claims"]):
        cid = claim["id"]
        if not usable[cid]["usable"]:
            continue
        meta = state.get("knowledge", {}).get("details", {}).get(cid, {})
        project_context = list(dict.fromkeys(contexts.get(cid, [])))
        context = meta.get("context", "")
        if context == "General":
            context = ""
        attribution = {"explicit": "Your words", "reported": "Reported information",
                       "observed": "Artifact observation"}.get(claim["kind"], "Interpretation")
        if cid in corrected:
            attribution = "Your correction"
        elif cid in proposals:
            proposed_kind = proposals[cid]["claim"]["kind"]
            attribution = {"explicit": "Reviewed statement", "reported": "Reviewed imported report",
                           "observed": "Reviewed artifact evidence", "interpretation": "Reviewed AI interpretation"}[proposed_kind]
        if cid in insights:
            attribution = "Reviewed AI interpretation" if insights[cid]["data"]["basis"] == "inferred" else "Reviewed AI extraction"
        temporal = ""
        if meta.get("valid_from") or meta.get("valid_until"):
            temporal = f"Valid {meta.get('valid_from') or 'start unspecified'} to {meta.get('valid_until') or 'open-ended'}"
        elif claim["facet"] in ("previous_projects", "previous_ideas"):
            temporal = "Past experience; current activity unconfirmed"
        elif claim["facet"] == "active_projects":
            temporal = "Reported active; last confirmed date not recorded" if not meta.get("reviewed_at") else "Reported active; reviewed " + meta["reviewed_at"][:10]
        elif claim["facet"] == "observed_activity":
            temporal = "Recorded activity; timing unspecified"
        result.append({"id": cid, "claim_ids": [cid], "text": claim["text"], "facet": claim["facet"],
                       "kind": claim["kind"], "attribution": attribution, "context": context,
                       "experiences": project_context, "temporal": temporal,
                       "valid_from": meta.get("valid_from"), "valid_until": meta.get("valid_until"),
                       "reviewed_at": meta.get("reviewed_at"), "sources": _sources(references[cid], sources), "order": order})
    return result


def _balanced(records, facets, limit):
    """Recent evidence from each area before repeated details of one area."""
    groups = [[r for r in reversed(records) if r["facet"] == facet] for facet in facets]
    result = []
    for index in range(max((len(group) for group in groups), default=0)):
        for group in groups:
            if index < len(group):
                result.append(group[index])
                if len(result) == limit:
                    return result
    return result


def _open_questions(state, usable):
    if "memory" in state:
        from .memory import open_questions
        return open_questions(state)
    proposals = {p["id"]: p for p in state["proposals"]}
    answers = state.get("skillmap", {}).get("answers", [])
    followed = {a.get("follow_up_of") for a in answers if usable[a["claim_id"]]["usable"]}
    result = []
    for insight in state.get("understanding", {}).get("insights", []):
        proposal = proposals[insight["proposal"]]
        cid = proposal["core_id"]
        if proposal["status"] != "accepted" or not usable.get(cid, {}).get("usable"):
            continue
        for field in ("uncertainty", "follow_up"):
            text = insight["data"].get(field)
            if text and not (field == "follow_up" and insight["id"] in followed):
                result.append({"id": insight["id"] + ":" + field, "claim_id": cid, "kind": field,
                               "text": text, "experience": insight["experience"], "origin_id": insight["id"]})
    return result


def _breadth(state, records, usable):
    """Questions name missing evidence, without inferring missing human traits."""
    facets = Counter(record["facet"] for record in records)
    pending = Counter(p["claim"]["facet"] for p in state["proposals"] if p["status"] == "proposed")
    gaps = []
    checkins = [c for c in state.get("skillmap", {}).get("checkins", []) if usable[c["claim_id"]]["usable"]]
    general_circumstances = [r for r in records if r["facet"] in ("constraints", "resources", "context") and not r["experiences"]]
    if not checkins and not general_circumstances and not any(pending[f] for f in ("constraints", "resources", "context")):
        gaps.append({"id": "breadth:context", "facet": "context", "question":
                     "What does your life look like right now? Roughly what time, energy and commitments shape what you can take on? Broad ranges are enough.",
                     "reason": "Current circumstances have no general reviewed description yet."})
    elif checkins and checkins[-1]["review_after"] < date.today().isoformat():
        gaps.append({"id": "breadth:context", "facet": "context", "question":
                     "Since your last circumstances update, has anything changed about your time, energy, commitments or available support?",
                     "reason": "Your last circumstances check-in was recorded " + checkins[-1]["at"][:10] + "."})
    interests = [r for r in records if r["facet"] == "interests"]
    if not pending["interests"] and (not interests or all(r["experiences"] for r in interests)):
        gaps.append({"id": "breadth:interests", "facet": "interests", "question":
                     "Outside your projects and work, what do you choose to read, explore or do for fun? What keeps drawing you back?",
                     "reason": "Interests outside the recorded experiences need more context."})
    for facet, question in BREADTH:
        if facets[facet] or pending[facet]:
            continue
        gaps.append({"id": "breadth:" + facet, "facet": facet, "question": question,
                     "reason": "No reviewed statement about " + knowledge.LABELS[facet].lower() + " yet."})
    return gaps


def _entities(graph, records):
    by_claim = {r["id"]: r for r in records}
    nodes = {n["id"]: n for n in graph["nodes"]}
    experiences, skills = [], []
    for node in graph["nodes"]:
        cids = [cid for cid in node["claim_ids"] if cid in by_claim]
        if not cids:
            continue
        item = {"id": node["id"], "label": node["label"], "kind": node["kind"], "claim_ids": cids,
                "dates": node.get("dates", []), "record_count": len(cids), "connections": []}
        for link in graph["links"]:
            if node["id"] not in (link["from"], link["to"]):
                continue
            other = link["to"] if node["id"] == link["from"] else link["from"]
            if other not in nodes:
                continue
            item["connections"].append({"id": other, "label": nodes[other]["label"], "role": link["role"],
                                        "basis": link["basis"], "assessment": link.get("assessment"),
                                        "claim_ids": link["claim_ids"]})
        if node["kind"] == "skill":
            skills.append(item)
        elif node["kind"] in skillmap.EXPERIENCES:
            experiences.append(item)
    # Prefer experiences with reviewed personal nuance, then a stable name order.
    for items in (skills, experiences):
        items.sort(key=lambda item: (-sum(bool(link["assessment"]) for link in item["connections"]), item["label"].casefold()))
    return skills, experiences


def overview(state, query=""):
    """Return an inspectable local profile, or full matching reviewed records.

    ``sections`` and ``results`` are bounded for display with explicit totals.
    Search covers all usable records, including ones omitted from the overview.
    No source file is opened and no network request or state mutation occurs.
    """
    usable = knowledge.statuses(state)
    graph = skillmap.catalog(state)
    records = _records(state, usable, graph)
    skills, experiences = _entities(graph, records)
    sections = []
    for key, label, facets in SECTIONS:
        relevant = [r for r in records if r["facet"] in facets]
        items = _balanced(relevant, facets, SECTION_LIMIT)
        sections.append({"id": key, "label": label, "kind": "statements", "items": items,
                         "total": len(relevant), "omitted": len(relevant) - len(items)})
    represented = {cid for node in graph["nodes"] for cid in node["claim_ids"]}
    for key, label, items, facets in (
        ("skills", "Skills in context", skills, ("claimed_skills", "demonstrated_skills")),
        ("experiences", "Projects, work and education", experiences, ("active_projects", "previous_projects", "observed_activity")),
    ):
        other = [r for r in records if r["facet"] in facets and r["id"] not in represented]
        sections.append({"id": key, "label": label, "kind": "entities", "items": items[:ENTITY_LIMIT],
                         "total": len(items), "omitted": max(0, len(items) - ENTITY_LIMIT),
                         "other": list(reversed(other))[:SECTION_LIMIT], "other_total": len(other),
                         "other_omitted": max(0, len(other) - SECTION_LIMIT)})
    gaps = _breadth(state, records, usable)
    questions = _open_questions(state, usable)
    query = query.strip()
    results = []
    if query:
        tokens = _terms(query)
        entity_names = {}
        for node in graph["nodes"]:
            for cid in node["claim_ids"]:
                entity_names.setdefault(cid, []).append(node["label"])
        for record in reversed(records):
            searchable = _terms(" ".join([record["id"], record["text"], record["facet"], record["context"],
                *record["experiences"], *entity_names.get(record["id"], []),
                *(source["quote"] + " " + source["id"] + " " + source["locator"] for source in record["sources"])]))
            if tokens and tokens <= searchable:
                results.append(record)
    withheld = dict(Counter(row["status"] for row in usable.values() if not row["usable"]))
    intake = None
    if "capture" in state:
        from .capture import progress
        intake = progress(state)
    return {"title": "About me", "dataset": state["dataset"], "query": query, "sections": sections,
            "counts": {"reviewed": len(records), "skills": len(skills), "experiences": len(experiences),
                       "pending": sum(p["status"] == "proposed" for p in state["proposals"]), "withheld": withheld},
            "gaps": gaps, "next_question": gaps[0] if gaps else None, "intake": intake,
            "open_questions": questions, "results": results[:SEARCH_LIMIT], "result_count": len(results),
            "results_omitted": max(0, len(results) - SEARCH_LIMIT)}


def _record_lines(record, *, detailed=False):
    text = record["text"] if detailed else _short(record["text"], 300)
    lines = ["- " + _plain(text)]
    context = " · ".join(dict.fromkeys([*record["experiences"], record["context"]] if record["context"] else record["experiences"]))
    parts = [record["attribution"], context, record["temporal"]]
    if detailed:
        parts.append(record["id"])
    lines.append("  " + " · ".join(_plain(part) for part in parts if part))
    # Original supporting quotations precede the explicit review attestation.
    sources = record["sources"] if detailed else record["sources"][:1]
    for source in sources:
        quote = source["quote"] if detailed else _short(source["quote"], 160)
        label = f"Evidence ({_plain(source['id'])}, v{source['version']})" if detailed else "Evidence"
        lines.append(f"  {label}: “{_plain(quote)}”")
        if detailed:
            lines.append("  Source: " + _plain(source["locator"]))
    return [line + "  " for line in lines]


def _entity_lines(item):
    lines = [f"- **{_plain(item['label'])}** · {item['record_count']} supporting statement(s)"]
    if item["kind"] != "skill":
        lines.append("  " + skillmap.EXPERIENCES[item["kind"]] + "; current activity unconfirmed unless dated in a statement.")
    connections = item["connections"]
    if connections:
        names = [_plain(link["label"]) for link in connections[:6] if link["role"] != "not_used"]
        if names:
            lines.append("  " + ("Appears in: " if item["kind"] == "skill" else "Skill connections: ") + ", ".join(names))
        if len(connections) > 6:
            lines.append(f"  {len(connections) - 6} more connection(s); search the name for evidence.")
    for link in connections[:6]:
        assessment = link["assessment"]
        if not assessment:
            continue
        ability = "; ".join(skillmap.DIMENSIONS[dimension] + ": " + skillmap.DEPTH[level].lower()
                            for dimension, level in assessment["depth"].items())
        lines.append("  " + _plain(link["label"]) + " — " + ability + ".")
        lines.append("  Contribution: " + skillmap.ROLES[assessment["role"]] + ". Assistance: " + skillmap.ASSISTANCE[assessment["assistance"]] + ".")
    if item["kind"] == "skill" and not any(link["assessment"] for link in connections):
        lines.append("  Depth and independence not assessed.")
    return [line + "  " for line in lines]


def render(state, query=""):
    """Render a concise overview or evidence-bearing local search as Markdown."""
    view = overview(state, query)
    counts = view["counts"]
    lines = ["# About me"]
    if view["query"]:
        lines += ["", "## Search: " + _plain(view["query"]), "", f"{view['result_count']} matching reviewed statement(s).", ""]
        for record in view["results"]:
            lines.extend(_record_lines(record, detailed=True) + [""])
        if view["results_omitted"]:
            lines.append(f"{view['results_omitted']} more matches. Add a project name, topic or statement ID to narrow the search.")
        elif not view["results"]:
            lines.append("Try a shorter phrase, a skill, an experience, or a statement ID. Pending and withheld records stay in Review and Records.")
        return "\n".join(lines) + "\n"
    if not counts["reviewed"]:
        lines += ["", "Add a note or choose a file, then review the proposed details to start your profile."]
    for section in view["sections"]:
        if not section["total"] and not section.get("other_total"):
            continue
        lines += ["", "## " + section["label"], ""]
        for item in section["items"]:
            lines.extend(_record_lines(item) if section["kind"] == "statements" else _entity_lines(item))
        for item in section.get("other", []):
            lines.extend(_record_lines(item))
        if section["omitted"]:
            unit = "statements" if section["kind"] == "statements" else "named entries"
            lines.append(f"\nShowing {len(section['items'])} of {section['total']} {unit}; {section['omitted']} more available through search.")
        if section.get("other_omitted"):
            lines.append(f"\n{section['other_omitted']} more supporting statements available through search.")
    if view["open_questions"]:
        lines += ["", "## Questions still open", ""]
        shown = view["open_questions"][:3]
        for question in shown:
            lines.append("- " + _plain(_short(question["text"], 220)))
        if len(view["open_questions"]) > len(shown):
            lines.append(f"- {len(view['open_questions']) - len(shown)} more open questions remain with their evidence.")
    if view["next_question"]:
        question = view["next_question"]
        lines += ["", "## One useful next detail", "", question["question"], "", question["reason"]]
        if len(view["gaps"]) > 1:
            labels = list(dict.fromkeys(knowledge.LABELS[gap["facet"]].lower() for gap in view["gaps"][1:]))
            lines.append("Other areas to explore: " + ", ".join(labels) + ".")
    if counts["pending"] or counts["withheld"]:
        lines += ["", "## Review attention", ""]
        if counts["pending"]:
            lines.append(f"- {counts['pending']} proposal(s) awaiting your review.")
        for status, count in counts["withheld"].items():
            if status == "supporting_evidence":
                lines.append(f"- {count} supporting record(s) attached to existing statements.")
            elif status == "superseded":
                lines.append(f"- {count} earlier statement(s) replaced by reviewed updates; preserved in history.")
            else:
                lines.append(f"- {count} {status.replace('_', ' ')} statement(s), kept outside this profile.")
    if view["intake"]:
        intake = view["intake"]
        lines += ["", "## Information you added", "",
                  f"{intake['entries']} saved entry(s) · {intake['processed_chunks']} text section(s) analyzed · {intake['pending_chunks']} waiting."]
        if intake["pending_chunks"]:
            lines.append("Use Add information → Continue to process the saved sections still waiting.")
        if intake["coverage_notes"]:
            lines += ["", f"The AI flagged passages in {intake['incomplete_chunks']} section(s) that need more detail or review.",
                      "Coverage notes are model-reported and may miss other details.", ""]
            for note in intake["coverage_notes"][:3]:
                lines.append("- “" + _plain(_short(note["quote"], 160)) + "” — " + _plain(_short(note["reason"], 160)))
            if len(intake["coverage_notes"]) > 3:
                lines.append(f"- {len(intake['coverage_notes']) - 3} more flagged passage(s) retained with the import.")
    lines += ["", f"{counts['reviewed']} reviewed statements · {counts['skills']} named skills · {counts['experiences']} experiences."]
    lines += ["", "Search a name, topic or statement ID to see exact wording and source passages. The full graph export retains all current reviewed statements and connections."]
    return "\n".join(lines) + "\n"
