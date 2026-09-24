"""Fresh fictional source and model responses. Never load these into personal history."""

from pathlib import Path

from foundry.storage import encoded
from foundry.workflow import selected_file

SOURCE = ("# Radio textures\nI catalogue old radio recordings to find mechanical sound textures.\n"
          "I do not repair radios.\nI prefer manual tagging over recording calls.\n")
QUOTE = "I catalogue old radio recordings to find mechanical sound textures."
CORRECTED = "I catalogue recordings for sound textures; I do not repair radios."


def response(request, *, claims=None, ideas=None):
    return {"schema_version": 1, "request_id": request["id"], "request_sha256": request["sha256"],
            "dataset": request["payload"]["dataset"], "method": "manual_codex", "model": "synthetic-test-fixture",
            "status": "ok", "error": None, "claims": claims or [], "ideas": ideas or []}


def proposed(sid, text="The person repairs radios.", key="radio_repair_interest"):
    return {"key": key, "facet": "interests", "kind": "interpretation", "text": text,
            "stance": "asserts", "confidence": "weak", "sources": [{"source": sid, "quote": QUOTE}]}


def supply(workflow, request, data):
    path = workflow.path / "test-response.json"
    path.write_text(encoded(data))
    workflow.import_response(request["id"], path)


def import_proposal(workflow, parent):
    path = Path(parent) / "fresh-selected.md"
    path.write_text(SOURCE)
    sid = workflow.add_source(selected_file(path), authorship="my_words", dataset=workflow.dataset)
    req = workflow.prepare("claims", source_id=sid)
    workflow.approve_export(req, approved=True)
    supply(workflow, req, response(req, claims=[proposed(sid)]))
    return sid, workflow.load()["proposals"][0]["id"]


def fact(value, *, assessment=None, claim_ids=None):
    result = {"value": value, "basis": "unknown" if value is None else "assumption", "confidence": "weak",
              "reason": "Fictional estimate for a software test; no benefit measured.", "sources": [], "claim_ids": claim_ids or []}
    if assessment:
        result["assessment"] = assessment
    return result


def idea_pair(request):
    cid = request["payload"]["claims"][0]["id"]
    refs = request["payload"]["claims"][0]["sources"]
    ideas = []
    for title, cost, benefit in (("One-page listening index", 20, "weak"), ("Searchable sound notebook", 300, "strong")):
        ideas.append({"category": request["payload"]["category"], "title": title,
            "description": "Fictional comparison candidate using a small collection of sound references.",
            "inspiration": refs, "facts": {
                "setup_minutes": fact({"low": cost, "high": cost, "unit": "minutes"}),
                "experiment_minutes": fact({"low": 10, "high": 15, "unit": "minutes"}),
                "expected_benefit": fact("Potential retrieval benefit; unmeasured", assessment=benefit),
                "adoption_fit": fact("May fit the corrected interest", assessment="moderate", claim_ids=[cid]),
                "evidence_quality": fact(None)},
            "alternatives": [{"name": "Keep the current folders", "tradeoff": "No new setup; retrieval remains as it is.", "sources": []}],
            "experiment": {"question": "Can one reference be found faster?", "scope": "Try two lookups manually.",
                           "success": "Find both without extra searching.", "failure": "No useful difference."}})
    return ideas


def populated(workflow, parent):
    sid, pid = import_proposal(workflow, parent)
    workflow.review(pid, "correct", CORRECTED)
    cid = workflow.load()["proposals"][0]["replacement"]
    request = workflow.prepare("ideas", claim_ids=[cid], count=2)
    workflow.approve_export(request, approved=True)
    supply(workflow, request, response(request, ideas=idea_pair(request)))
    return sid, pid, cid
