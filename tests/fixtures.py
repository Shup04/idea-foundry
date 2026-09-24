"""Entirely synthetic. These people, activities and outcomes are not user history."""

from foundry.validation import digest


def source(sid="S1", text="I enjoy sorting weather photographs.", kind="user_statement", origin=None, parents=None):
    return {"id": sid, "kind": kind, "origin": origin or sid, "version": 1, "text": text,
            "sha256": digest(text), "locator": "synthetic fixture", "parents": parents or []}


def ref(sid="S1", quote="I enjoy sorting weather photographs."):
    return {"source": sid, "quote": quote}


def claim(cid="C1", key="weather_photograph_interest", kind="explicit", **changes):
    value = {"id": cid, "key": key, "facet": "interests", "kind": kind,
             "text": "Synthetic person reports an interest in sorting weather photos.", "stance": "asserts",
             "confidence": "strong", "status": "active", "sources": [ref()], "contradicts": []}
    return value | changes


def fact(value=None, basis="assumption", assessment=None, sources=None, claim_ids=None, **changes):
    value = {"value": value, "basis": "unknown" if value is None else basis, "confidence": "weak",
             "reason": "Synthetic illustrative input, not an observation of the user.",
             "sources": sources or [], "claim_ids": claim_ids or []} | changes
    if assessment:
        value["assessment"] = assessment
    return value


def band(low, high, unit="minutes"):
    return {"low": low, "high": high, "unit": unit}


def idea(iid="P1", category="personal"):
    return {"id": iid, "category": category, "title": "Synthetic weather-photo index",
            "description": "A synthetic example only.", "inspiration": [ref()],
            "facts": {"setup_minutes": fact(band(30, 60)), "experiment_minutes": fact(band(15, 20)),
                      "frequency_monthly": fact(band(4, 8, "uses/month")),
                      "minutes_saved_per_use": fact(band(3, 5, "minutes/use")),
                      "ongoing_minutes_monthly": fact(band(2, 4, "minutes/month")),
                      "adoption_fit": fact("May be relevant", assessment="moderate", claim_ids=["C1"])},
            "alternatives": [{"name": "Do nothing", "tradeoff": "No setup; no new index.", "sources": []}],
            "experiment": {"question": "Does an index help?", "scope": "Compare two retrievals on synthetic data.",
                           "success": "Both are easier to find.", "failure": "Neither improves."}}


def bundle():
    return {"schema_version": 1, "sources": [source()], "claims": [claim()],
            "ideas": [idea()], "outcomes": [], "corrections": []}


def outcome(eid="E1", idea_id="P1", **changes):
    event = {"id": eid, "idea_id": idea_id, "event": "used", "occurred_at": "2026-09-05T12:00:00+00:00",
             "scope": "Synthetic manual trial", "method": "user_report", "sources": [ref("O1", "Synthetic outcome report.")],
             "metrics": {"actual_usefulness": "strong", "continued_usage": True}, "reason_code": None}
    return event | changes


def correction(action="reject"):
    text = "I reject this inferred interest; it was only an example."
    return {"source": source("COR1", text), "correction": {
        "id": "FIX1", "claim_id": "C1", "action": action, "reason": text,
        "sources": [ref("COR1", text)], "recorded_at": "2026-09-05T12:00:00+00:00"}}
