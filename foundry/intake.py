"""Read structured resume literals as data; never import or execute their contents."""

import ast
import json
import re

from .validation import Invalid, _pairs, digest, require, words


def resume_claims(source):
    """Recognize selected resume JSON or a single literal assignment.

    Unsupported/free-form notes use the reviewed manual extraction path. Listing a
    skill is a self-report, and project prose does not demonstrate mastery.
    """
    require(source["kind"] in ("user_statement", "user_supplied_summary"),
            "generated text cannot describe you")
    text = source["text"]
    require(len(text) <= 20000, "select a smaller source excerpt")
    try:
        data = json.loads(text, object_pairs_hook=_pairs)
    except Invalid:
        raise
    except (ValueError, RecursionError):
        # Only strip leading comments and a plain leading assignment name.
        # Calls, imports, attributes, expressions and f-strings are rejected by
        # literal_eval. It builds Python literals without executing Python code.
        literal = re.sub(r"\A(?:[ \t]*(?:#[^\n]*)?\n)*", "", text)
        literal = re.sub(r"^\s*[A-Za-z_][A-Za-z0-9_]*\s*=\s*", "", literal, count=1)
        try:
            tree = ast.parse(literal.strip(), mode="eval")
            for node in ast.walk(tree):
                if isinstance(node, ast.Dict):
                    names = [ast.literal_eval(key) for key in node.keys]
                    require(all(isinstance(name, str) for name in names), "resume keys must be strings")
                    require(len(names) == len(set(names)), "duplicate resume key")
            data = ast.literal_eval(tree)
        except (ValueError, SyntaxError, TypeError, RecursionError) as exc:
            raise Invalid("This source is not a structured resume. Use the manual Codex extraction for free-form notes.") from exc
    require(isinstance(data, dict) and bool(data) and data.keys() <= {"master_skills", "projects", "experience"},
            "expected a resume with master_skills, projects or experience")
    result = []

    def add(facet, statement, quote):
        words(statement, "listed detail", 4000)
        require(quote in text, "decoded detail is not an exact source passage; use manual extraction")
        result.append({"key": "listed-" + digest(source["origin"] + statement)[:24], "facet": facet,
                       "kind": "reported", "text": statement, "stance": "asserts", "confidence": "moderate",
                       "sources": [{"source": source["id"], "quote": quote}]})
        require(len(result) <= 200, "resume exceeds 200 details; select a smaller source")

    skills = data.get("master_skills", {})
    require(isinstance(skills, dict), "master_skills must group lists of skills")
    for group, items in skills.items():
        words(group, "skill group", 200)
        require(isinstance(items, list), "each skill group needs a list")
        for skill in items:
            words(skill, "skill", 200)
            add("claimed_skills", f"Listed skill: {skill} ({group}). Proficiency and recency are unspecified.", skill)
    for collection, label in (("projects", "Project"), ("experience", "Experience")):
        records = data.get(collection, [])
        require(isinstance(records, list) and len(records) <= 50, "invalid resume record list")
        for record in records:
            require(isinstance(record, dict), "invalid resume record")
            title = record.get("title") if collection == "projects" else record.get("role")
            words(title, "project or role", 300)
            dates = record.get("date", record.get("dates", "unspecified"))
            words(dates, "supplied dates", 200)
            context = f"{label}: {title} (uploaded dates: {dates}; current status unconfirmed)"
            if collection == "experience":
                company = record.get("company", "unspecified")
                words(company, "organization", 300)
                context += "; organization: " + company
            facts = record.get("master_facts", "")
            require(isinstance(facts, str), "master_facts must be plain text")
            lines = [line.strip() for line in facts.splitlines() if line.strip()]
            # The title itself is retained even when a record contains no prose.
            add("previous_projects", context + ".", title)
            if record.get("tech"):
                words(record["tech"], "listed technologies", 1000)
                add("claimed_skills", context + "; listed technologies: " + record["tech"], record["tech"])
            for line in lines:
                add("previous_projects", context + "; self-report: " + line.removeprefix("- "), line)
    require(result, "no listed skills or experience found")
    # Repetition within one source cannot inflate the review queue.
    return list({claim["key"]: claim for claim in result}.values())
