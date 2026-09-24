"""Canonical experiences and shared skills, with scoped, attributed interviews.

Named mentions are connections to investigate. They never imply proficiency,
authorship, enjoyment or project completion. Existing evidence stays canonical.
"""

from datetime import date, timedelta
import re

from .knowledge import Knowledge, statuses
from .validation import digest, indexed, keys, refs, require, words
from .workflow import now, uid

EXPERIENCES = {"project": "Project", "work": "Work", "research": "Research", "education": "Education"}
SKILL_TYPES = {"language": "Language", "tool": "Tool", "domain": "Subject knowledge", "practice": "Engineering practice", "soft": "People skills"}
DEPTH = {"unknown": "Not assessed", "with_help": "With help", "independent": "Independently", "not_yet": "Not yet"}
DIMENSIONS = {"explain": "Explain the concepts", "adapt": "Adapt an existing solution", "design": "Design a solution", "debug": "Diagnose problems"}
ROLES = {"unknown": "Connection needs context", "central": "Central to my contribution", "supporting": "Supporting role", "incidental": "Incidental exposure", "not_used": "I did not use this"}
ASSISTANCE = {"unknown": "Not recorded", "documentation": "Documentation / examples", "ai_assisted": "AI helped; I directed the work", "ai_led": "AI produced most of it", "team": "Help from other people", "mixed": "Mixed assistance", "none": "No assistance for this part"}
TOPICS = {
    "contribution": ("Your contribution", "In {name}, which parts did you personally design, implement or debug? What came from AI, tutorials or teammates?"),
    "enjoyment": ("What you enjoyed", "Which activity in {name} would you choose to do again, and what made it satisfying?"),
    "friction": ("What drained you", "Which part of {name} would you avoid or hand off next time? Was it the task or the circumstances?"),
    "motivation": ("Why it mattered", "What drew you to {name}, and what kept you going or made you stop? Unfinished work counts too."),
    "collaboration": ("Working with people", "In {name}, how did you explain decisions, ask for help, or work with others? Give one concrete example."),
}
ALIASES = {"ts": "TypeScript", "typescript": "TypeScript", "js": "JavaScript", "javascript": "JavaScript",
           "cpp": "C++", "c++": "C++", "python": "Python", "rust": "Rust", "nodejs": "Node.js", "node.js": "Node.js",
           "react native": "React Native", "react": "React", "matlab": "MATLAB", "vhdl": "VHDL", "sql": "SQL"}
LANGUAGES = {"Python", "Rust", "C++", "JavaScript", "TypeScript", "MATLAB", "VHDL", "SQL"}
# Explicit subject phrases make the initial map more useful than language counts.
# These are labelled mentions, not automatic assessments of the user's knowledge.
SUBJECTS = {
    "Ray tracing": ("ray tracer", "ray tracing", "ray-tracing"),
    "Spatial acceleration structures": ("bounding volume hierarchy", "bvh"),
    "Concurrency": ("multithreading", "multithreaded", "parallelized"),
    "3D mathematics": ("matrix transforms", "graphics math"),
    "Robot kinematics": ("kinematic", "human gait"),
    "Web scraping": ("web scraper", "web scraping"),
    "Embedded systems": ("firmware", "esp32", "microcontroller"),
    "Digital logic": ("vhdl", "fpga", "hardware debouncing"),
    "Circuit design": ("pcb design", "custom pcb"),
    "Signal processing": ("tdoa", "multilateration", "signal processing"),
}


def empty_map():
    return {"version": 1, "entities": [], "links": [], "answers": [], "assessments": [], "checkins": [], "snoozed": []}


def identity(kind, name):
    return kind + "-" + digest(" ".join(name.casefold().split()))[:20]


def skill_name(name):
    name = " ".join(name.strip().split())
    return ALIASES.get(name.casefold(), name)


def skill_type(name):
    return "language" if name in LANGUAGES else "domain" if name in SUBJECTS else "tool"


def catalog(state, *, history=False):
    """One entity per named experience/skill; all cited claims remain available."""
    usable = statuses(state)
    claims = [c for c in state["core"]["claims"] if history or usable[c["id"]]["usable"]]
    nodes, links, grouped = {}, {}, {}

    def node(kind, name, cid, category=None):
        nid = identity(kind, name)
        if nid not in nodes:
            nodes[nid] = {"id": nid, "kind": kind, "label": name, "category": category,
                          "claim_ids": [], "dates": [], "origin": "reviewed statements"}
        if cid and cid not in nodes[nid]["claim_ids"]:
            nodes[nid]["claim_ids"].append(cid)
        return nid

    def connect(eid, name, cid, category=None):
        name = skill_name(name)
        sid = node("skill", name, cid, category or skill_type(name))
        key = eid + ":" + sid
        link = links.setdefault(key, {"id": key, "from": eid, "to": sid, "claim_ids": [],
                                      "role": "unknown", "basis": "mentioned in reviewed record"})
        if cid not in link["claim_ids"]:
            link["claim_ids"].append(cid)

    for claim in claims:
        text = claim["text"]
        listed = re.match(r"^Listed skill: (.+?) \((.+?)\)\. Proficiency", text)
        if listed:
            name = skill_name(listed[1])
            node("skill", name, claim["id"], skill_type(name))
        experience = re.match(r"^(Project|Experience): (.+?) \(uploaded dates: (.*?); current status unconfirmed\)(.*)", text, re.S)
        if not experience:
            continue
        kind = "project" if experience[1] == "Project" else "research" if "research" in experience[2].casefold() else "work"
        name = experience[2]
        organization = re.search(r"; organization: (.*?)(?:; listed technologies:|; self-report:|\.$)", experience[4], re.S)
        if organization:
            name += " · " + organization[1]
        eid = node(kind, name, claim["id"])
        if experience[3] not in nodes[eid]["dates"]:
            nodes[eid]["dates"].append(experience[3])
        grouped.setdefault(eid, []).append(claim)
        tech = re.search(r"; listed technologies: (.+)", experience[4])
        if tech:
            for name in tech[1].split(","):
                if name.strip():
                    connect(eid, name, claim["id"])

    # Link explicit mentions of already named tools and a small transparent
    # subject vocabulary. No embeddings, skill scores or proficiency inference.
    vocabulary = {n["label"]: n["category"] for n in nodes.values() if n["kind"] == "skill"}
    for eid, records in grouped.items():
        for claim in records:
            text = claim["text"].casefold()
            for name, category in vocabulary.items():
                spellings = [name] + [alias for alias, canonical in ALIASES.items() if canonical == name and len(alias) > 2]
                candidate = text.replace("react native", "") if name == "React" else text
                if any(re.search(r"(?<![\w])" + re.escape(term.casefold()) + r"(?![\w])", candidate) for term in spellings):
                    connect(eid, name, claim["id"], category)
            for subject, phrases in SUBJECTS.items():
                if any(re.search(r"(?<![\w])" + re.escape(term) + r"(?![\w])", text) for term in phrases):
                    connect(eid, subject, claim["id"], "domain")

    saved = state.get("skillmap", empty_map())
    for entity in saved["entities"]:
        cids = [cid for cid in entity["claim_ids"] if history or usable[cid]["usable"]]
        if not cids:
            continue
        if entity["id"] in nodes:
            nodes[entity["id"]]["claim_ids"] = list(dict.fromkeys(nodes[entity["id"]]["claim_ids"] + cids))
            nodes[entity["id"]]["category"] = entity["category"]
        else:
            nodes[entity["id"]] = {**entity, "claim_ids": cids, "dates": [], "origin": "your description"}
    # A code topic joins the map only after its proposal is explicitly accepted.
    # Corrections do not silently inherit the original proposed relationship.
    proposals = {p["id"]: p for p in state["proposals"]}
    for finding in saved.get("findings", []):
        proposal = proposals[finding["proposal"]]
        cid = proposal["core_id"]
        if proposal["status"] == "accepted" and cid and (history or usable[cid]["usable"]) and finding["experience"] in nodes:
            connect(finding["experience"], finding["skill"], cid, finding["category"])
            key = finding["experience"] + ":" + identity("skill", skill_name(finding["skill"]))
            links[key]["basis"] = "reviewed code topic; personal contribution unconfirmed"
    for link in saved["links"]:
        if link["from"] in nodes and link["to"] in nodes and (history or usable[link["claim_id"]]["usable"]):
            key = link["from"] + ":" + link["to"]
            existing = links.setdefault(key, {"id": key, "from": link["from"], "to": link["to"],
                                               "claim_ids": [], "role": "unknown", "basis": "your description"})
            if link["claim_id"] not in existing["claim_ids"]:
                existing["claim_ids"].append(link["claim_id"])
    for assessment in saved["assessments"]:
        key = assessment["experience"] + ":" + assessment["skill"]
        if key in links and (history or usable[assessment["claim_id"]]["usable"]):
            links[key].update(role=assessment["role"], assessment=assessment, basis="your scoped assessment")
    if "understanding" in state:
        from .understanding import accepted
        for insight in accepted(state):
            data = insight["data"]
            key = insight["experience"] + ":" + (data["skill_id"] or "")
            if key not in links:
                continue
            links[key].setdefault("insight_ids", []).append(insight["id"])
            # An explicit assessment entered by the user takes precedence. An
            # accepted AI description is still scoped to the quoted activity.
            if data["capability"] and "assessment" not in links[key]:
                links[key].update(role=data["capability"]["role"], basis="reviewed answer interpretation",
                    assessment={**data["capability"], "experience": insight["experience"],
                                "skill": data["skill_id"], "claim_id": insight["claim_id"], "derived": True})
    if "memory" in state:
        from .memory import semantic_graph
        additions = semantic_graph(state, base_graph={"nodes": list(nodes.values()), "links": list(links.values())}, usable=usable, history=history)
        for item in additions["nodes"]:
            if item["id"] in nodes:
                nodes[item["id"]]["claim_ids"] = list(dict.fromkeys(nodes[item["id"]]["claim_ids"] + item["claim_ids"]))
            else:
                nodes[item["id"]] = item
        for item in additions["links"]:
            # Keep separate relationships and evidence, while a manual assessment
            # remains the authority for describing skill depth.
            key = item["from"] + ":" + item["to"]
            if key in links and "assessment" in links[key] and not links[key]["assessment"].get("derived"):
                item.pop("assessment", None)
                item["role"] = "unknown"
            links[item["id"]] = item
    return {"nodes": list(nodes.values()), "links": list(links.values())}


def validate_map(state):
    saved = state["skillmap"]
    keys(saved, ("version", "entities", "links", "answers", "assessments", "checkins", "snoozed"), ("findings",))
    require(saved["version"] == 1, "unsupported skill map schema")
    claims = {c["id"]: c for c in state["core"]["claims"]}
    for entity in indexed(saved["entities"], "map entity", 400).values():
        keys(entity, ("id", "kind", "label", "category", "claim_ids"))
        require(entity["kind"] in (*EXPERIENCES, "skill"), "invalid entity type")
        words(entity["label"], "entity label", 300)
        require(entity["id"] == identity(entity["kind"], entity["label"]), "entity identity mismatch")
        require(entity["category"] in SKILL_TYPES if entity["kind"] == "skill" else entity["category"] is None, "invalid skill category")
        require(isinstance(entity["claim_ids"], list) and entity["claim_ids"] and all(c in claims for c in entity["claim_ids"]), "entity evidence missing")
    # Catalog ignores assessments when constructing entity identities.
    proposals = {p["id"]: p for p in state["proposals"]}
    for finding in indexed(saved.get("findings", []), "repository finding", 400).values():
        keys(finding, ("id", "experience", "skill", "category", "proposal", "question", "model", "at"))
        require(finding["proposal"] in proposals, "unknown finding proposal")
        words(finding["skill"], "code topic", 200)
        words(finding["question"], "code review question", 1000)
        words(finding["model"], "assessment model", 200)
        words(finding["at"], "assessment time", 80)
        require(finding["category"] in SKILL_TYPES, "unknown code topic category")
    projection = {**state, "skillmap": {**saved, "links": [], "assessments": []}}
    nodes = {n["id"]: n for n in catalog(projection, history=True)["nodes"]}
    for finding in saved.get("findings", []):
        require(finding["experience"] in nodes and nodes[finding["experience"]]["kind"] in EXPERIENCES, "unknown finding experience")

    def evidence_record(record):
        require(record["claim_id"] in claims and claims[record["claim_id"]]["kind"] == "explicit", "map update needs your statement")
        words(record["at"], "recorded time", 80)

    def pair(record):
        require(record["experience"] in nodes and nodes[record["experience"]]["kind"] in EXPERIENCES, "unknown experience")
        require(record["skill"] in nodes and nodes[record["skill"]]["kind"] == "skill", "unknown skill")

    for link in indexed(saved["links"], "map connection", 1000).values():
        keys(link, ("id", "from", "to", "claim_id", "at"))
        pair({"experience": link["from"], "skill": link["to"]})
        evidence_record(link)
    for answer in indexed(saved["answers"], "interview answer", 1000).values():
        keys(answer, ("id", "experience", "topic", "claim_id", "at"), ("question", "follow_up_of"))
        require(answer["experience"] in nodes and nodes[answer["experience"]]["kind"] in EXPERIENCES, "unknown interview experience")
        require(answer["topic"] in TOPICS, "unknown interview topic")
        evidence_record(answer)
        if "question" in answer:
            words(answer["question"], "interview question", 5000)
        if answer.get("follow_up_of") is not None:
            require(any(i["id"] == answer["follow_up_of"] for i in state.get("understanding", {}).get("insights", []))
                    or answer["follow_up_of"] in state.get("memory", {}).get("proposals", {}),
                    "Unknown follow-up insight.")
    for item in indexed(saved["assessments"], "capability assessment", 1000).values():
        keys(item, ("id", "experience", "skill", "role", "depth", "assistance", "claim_id", "at"))
        pair(item)
        require(item["role"] in ROLES and item["assistance"] in ASSISTANCE, "invalid capability description")
        keys(item["depth"], DIMENSIONS)
        require(all(v in DEPTH for v in item["depth"].values()), "capability uses descriptions, not numeric scores")
        evidence_record(item)
    for checkin in indexed(saved["checkins"], "circumstances check-in", 100).values():
        keys(checkin, ("id", "claim_id", "at", "review_after"))
        evidence_record(checkin)
        date.fromisoformat(checkin["review_after"])
    for snooze in indexed(saved["snoozed"], "postponed question", 1000).values():
        keys(snooze, ("id", "key", "until"))
        words(snooze["key"], "question key", 200)
        date.fromisoformat(snooze["until"])


def _statement(state, text, facet, context):
    words(text.strip(), "your answer", 4000)
    cid = uid("c-")
    ref = Knowledge._source(state, text, context)
    state["core"]["claims"].append({"id": cid, "key": cid, "facet": facet, "kind": "explicit", "text": text,
        "stance": "asserts", "confidence": "strong", "status": "active", "sources": [ref], "contradicts": []})
    return cid


def add_experience(workflow, name, kind, description):
    require(kind in EXPERIENCES, "choose project, work, research or education")
    words(name.strip(), "experience name", 300)
    eid = identity(kind, name.strip())
    def operation(state):
        saved = state.setdefault("skillmap", empty_map())
        cid = _statement(state, description, "previous_projects", name.strip())
        existing = next((e for e in saved["entities"] if e["id"] == eid), None)
        if existing:
            existing["claim_ids"].append(cid)
        else:
            saved["entities"].append({"id": eid, "kind": kind, "label": name.strip(), "category": None, "claim_ids": [cid]})
    workflow.update(operation, "user described an experience for the skill map")
    return eid


def add_skill(workflow, experience, name, category, text):
    name = skill_name(name)
    words(name, "skill name", 200)
    require(category in SKILL_TYPES, "choose a skill category")
    sid = identity("skill", name)
    def operation(state):
        require(any(n["id"] == experience and n["kind"] in EXPERIENCES for n in catalog(state)["nodes"]), "choose an existing experience")
        saved = state.setdefault("skillmap", empty_map())
        cid = _statement(state, text, "claimed_skills", "Skill connection: " + name)
        entity = next((e for e in saved["entities"] if e["id"] == sid), None)
        if entity:
            entity["claim_ids"].append(cid)
        else:
            saved["entities"].append({"id": sid, "kind": "skill", "label": name, "category": category, "claim_ids": [cid]})
        saved["links"].append({"id": uid("map-link-"), "from": experience, "to": sid, "claim_id": cid, "at": now()})
    workflow.update(operation, "user connected a named skill to an experience")
    return sid


def answer(workflow, experience, topic, text, *, question=None, follow_up_of=None):
    require(topic in TOPICS, "choose an interview topic")
    def operation(state):
        node = next((n for n in catalog(state)["nodes"] if n["id"] == experience and n["kind"] in EXPERIENCES), None)
        require(node is not None, "choose an existing experience")
        facet = {"enjoyment": "preferences", "friction": "avoidances", "motivation": "motivations", "collaboration": "working_style"}.get(topic, "previous_projects")
        cid = _statement(state, text, facet, f"Project interview: {node['label']} / {topic}")
        state.setdefault("skillmap", empty_map())["answers"].append({"id": uid("answer-"), "experience": experience,
            "topic": topic, "claim_id": cid, "at": now(),
            "question": question or TOPICS[topic][1].format(name=node["label"]), "follow_up_of": follow_up_of})
    return workflow.update(operation, "user answered a project-grounded question; no global personality inference")


def assess(workflow, experience, skill, *, role, depth, assistance, text):
    def operation(state):
        require(any(l["from"] == experience and l["to"] == skill for l in catalog(state)["links"]), "choose an existing skill connection")
        cid = _statement(state, text, "claimed_skills", "Scoped skill assessment")
        state.setdefault("skillmap", empty_map())["assessments"].append({"id": uid("depth-"), "experience": experience,
            "skill": skill, "role": role, "depth": depth, "assistance": assistance, "claim_id": cid, "at": now()})
    return workflow.update(operation, "user described capability in context, with assistance and limitations")


def check_in(workflow, text, *, today=None):
    today = today or date.today()
    def operation(state):
        cid = _statement(state, text, "context", "Current circumstances; occasional check-in")
        saved = state.setdefault("skillmap", empty_map())
        # Prior circumstances remain in history but no longer describe today.
        for prior in saved["checkins"]:
            claim = next(c for c in state["core"]["claims"] if c["id"] == prior["claim_id"])
            claim["status"] = "excluded"
        saved["checkins"].append({"id": uid("checkin-"), "claim_id": cid, "at": now(),
                                 "review_after": (today + timedelta(days=90)).isoformat()})
    return workflow.update(operation, "user updated broad current circumstances; no schedule or task tracking")


def snooze(workflow, key, *, today=None):
    today = today or date.today()
    def operation(state):
        state.setdefault("skillmap", empty_map())["snoozed"].append({"id": uid("later-"), "key": key,
            "until": (today + timedelta(days=30)).isoformat()})
    return workflow.update(operation, "user postponed a question; no answer or preference inferred")


def questions(state, experience=None, *, today=None):
    today = today or date.today()
    graph = catalog(state)
    saved = state.get("skillmap", empty_map())
    usable = statuses(state)
    done = {(a["experience"], a["topic"]) for a in saved["answers"] if usable[a["claim_id"]]["usable"]}
    postponed = {s["key"] for s in saved["snoozed"] if date.fromisoformat(s["until"]) > today}
    result = []
    for node in graph["nodes"]:
        if node["kind"] not in EXPERIENCES or (experience and node["id"] != experience):
            continue
        for topic, (_, prompt) in TOPICS.items():
            key = node["id"] + ":" + topic
            if (node["id"], topic) not in done and key not in postponed:
                previous = next((a for a in reversed(saved["answers"]) if a["experience"] == node["id"]
                                 and usable[a["claim_id"]]["usable"]), None)
                grounding = ""
                if previous:
                    text = next(c["text"] for c in state["core"]["claims"] if c["id"] == previous["claim_id"])
                    grounding = "Earlier you said: “" + text[:400] + "”\n\n"
                if topic == "contribution":
                    proposals = {p["id"]: p for p in state["proposals"]}
                    findings = [f for f in saved.get("findings", []) if f["experience"] == node["id"]
                                and proposals[f["proposal"]]["status"] in ("proposed", "accepted")]
                    if findings:
                        grounding += "From the selected code (your contribution is still unconfirmed):\n" + findings[0]["question"] + "\n\n"
                result.append({"key": key, "experience": node["id"], "topic": topic,
                               "prompt": grounding + prompt.format(name=node["label"]), "claim_ids": node["claim_ids"][:3]})
    # Rotate through contribution gaps before deeper questions; no invented
    # relevance ranking or requirement to complete every question.
    result.sort(key=lambda q: list(TOPICS).index(q["topic"]))
    if "understanding" in state:
        from .understanding import accepted
        from .memory import open_questions
        open_ids = {q["id"] for q in open_questions(state)}
        followed = {a.get("follow_up_of") for a in saved["answers"] if usable[a["claim_id"]]["usable"]}
        original = {a["id"]: a for a in saved["answers"]}
        for insight in accepted(state):
            prompt = insight["data"]["follow_up"]
            key = "insight:" + insight["id"]
            if (prompt and insight["id"] + ":follow_up" in open_ids and insight["id"] not in followed and key not in postponed
                    and (not experience or experience == insight["experience"])):
                result.append({"key": key, "experience": insight["experience"],
                    "topic": original[insight["answer_id"]]["topic"], "prompt": prompt,
                    "follow_up_of": insight["id"], "claim_ids": [insight["claim_id"]]})
    if "memory" in state:
        from .memory import open_questions
        memory_ids = state["memory"]["proposals"]
        for question in open_questions(state):
            meta = memory_ids.get(question["origin_id"])
            if not meta or question["kind"] != "follow_up":
                continue
            fact = meta["fact"]
            eid = fact["experience_id"] or (identity(fact["experience_kind"], fact["experience_label"])
                                            if fact["experience_label"] else None)
            key = "insight:" + question["origin_id"]
            if eid and (not experience or experience == eid) and key not in postponed:
                result.append({"key": key, "experience": eid, "topic": "contribution", "prompt": question["text"],
                    "follow_up_of": question["origin_id"], "claim_ids": [question["claim_id"]]})
    return result


def describe(state, experience):
    graph = catalog(state)
    node = next((n for n in graph["nodes"] if n["id"] == experience), None)
    if not node:
        return "Choose a project, job, research role or education experience."
    by_id = {n["id"]: n for n in graph["nodes"]}
    claims = {c["id"]: c for c in state["core"]["claims"]}
    lines = [node["label"], EXPERIENCES.get(node["kind"], "Skill"), "", "REVIEWED CONTEXT"]
    lines.extend(claims[cid]["text"] for cid in node["claim_ids"])
    lines += ["", "SHARED SKILLS"]
    for link in graph["links"]:
        if link["from"] == experience:
            lines.append(by_id[link["to"]]["label"] + " · " + ROLES[link["role"]])
            if "assessment" in link:
                a = link["assessment"]
                lines.append("; ".join(f"{DIMENSIONS[k]}: {DEPTH[v]}" for k, v in a["depth"].items()))
                lines.append(ASSISTANCE[a["assistance"]] + ": " + claims[a["claim_id"]]["text"])
    lines += ["", "YOUR EXPERIENCE"]
    usable = statuses(state)
    for a in state.get("skillmap", empty_map())["answers"]:
        if a["experience"] == experience and usable[a["claim_id"]]["usable"]:
            lines += [TOPICS[a["topic"]][0] + ": " + claims[a["claim_id"]]["text"]]
    proposals = {p["id"]: p for p in state["proposals"]}
    findings = [f for f in state.get("skillmap", {}).get("findings", []) if f["experience"] == experience]
    if findings:
        lines += ["", "CODE REVIEW · TOPICS, NOT PERSONAL PROFICIENCY"]
        for finding in findings:
            p = proposals[finding["proposal"]]
            lines += [f"{finding['skill']} · {p['status']}", p["claim"]["text"], "Question: " + finding["question"]]
        lines += ["Accept or reject proposed code topics in Review. Describe your own contribution with One question or Skill context."]
    if "understanding" in state:
        from .understanding import accepted, related
        from .understanding_contract import RELATIONS
        from .memory import open_questions
        open_ids = {q["id"] for q in open_questions(state)}
        insights = [i for i in accepted(state) if i["experience"] == experience]
        if insights:
            lines += ["", "WHAT YOUR ANSWERS ADD · REVIEWED"]
            for insight in insights:
                data = insight["data"]
                lines += [f"{RELATIONS[data['relation']]}: {data['concept']}", claims[insight["claim_id"]]["text"],
                          "Your words: “" + data["quote"] + "”"]
                if data["uncertainty"] and insight["id"] + ":uncertainty" in open_ids:
                    lines.append("Still unknown: " + data["uncertainty"])
        neighbors = related(state, experience)
        if neighbors:
            lines += ["", "RELATED ANSWERS · SIMILARITY, NOT CONFIRMED CONNECTIONS"]
            lines.extend(row["project"] + ": “" + row["text"] + "”" for row in neighbors)
    return "\n\n".join(lines)
