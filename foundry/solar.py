"""Self-contained, offline interactive skill map; no remote assets or server."""

import base64
import hashlib
import json
from pathlib import Path

from . import skillmap
from .knowledge import LABELS, statuses
from .storage import atomic_text, encoded
from .workflow import now, uid


def payload(state):
    graph = skillmap.catalog(state)
    if "understanding" in state:
        from .understanding import semantic_graph
        insights = semantic_graph(state)
        graph["nodes"].extend(insights["nodes"])
        graph["links"].extend(insights["links"])
    merged = {}
    for node in graph["nodes"]:
        if node["id"] in merged:
            merged[node["id"]]["claim_ids"] = list(dict.fromkeys(merged[node["id"]]["claim_ids"] + node["claim_ids"]))
        else:
            merged[node["id"]] = node
    graph["nodes"] = list(merged.values())
    claims = {c["id"]: c for c in state["core"]["claims"]}
    sources = {s["id"]: s for s in state["core"]["sources"]}
    usable = statuses(state)
    saved = state.get("skillmap", skillmap.empty_map())
    used = {cid for node in graph["nodes"] for cid in node["claim_ids"]}
    used |= {cid for link in graph["links"] for cid in link["claim_ids"]}
    used |= {a["claim_id"] for a in saved["answers"] + saved["assessments"] if usable[a["claim_id"]]["usable"]}
    from .memory import effective_source_index
    source_index = effective_source_index(state)
    graph.update(dataset=state["dataset"], exported_at=now(), questions=skillmap.questions(state),
                 answers=[a for a in saved["answers"] if usable[a["claim_id"]]["usable"]],
                 labels={"kinds": skillmap.EXPERIENCES, "categories": skillmap.SKILL_TYPES, "facets": LABELS, "roles": skillmap.ROLES,
                         "depth": skillmap.DEPTH, "dimensions": skillmap.DIMENSIONS, "assistance": skillmap.ASSISTANCE,
                         "topics": {k: v[0] for k, v in skillmap.TOPICS.items()}},
                 evidence={cid: {"text": claims[cid]["text"], "kind": claims[cid]["kind"],
                                  "passages": [{"locator": sources[r["source"]]["locator"],
                                                "version": sources[r["source"]]["version"], "quote": r["quote"]}
                                               for r in source_index[cid]]} for cid in used})
    return graph


def html(state):
    assets = Path(__file__).parent / "assets"
    script = (assets / "solar.js").read_text()
    style = (assets / "solar.css").read_text()
    data = json.dumps(payload(state), ensure_ascii=True).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    sha = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
    template = (assets / "solar.html").read_text()
    return template.replace("__CSP_HASH__", sha).replace("__STYLE__", style).replace("__DATA__", data).replace("__SCRIPT__", script)


def export(workflow):
    state = workflow.load()
    directory = workflow.path / "exports" / uid("solar-")
    document = html(state)
    atomic_text(directory / "index.html", document)
    atomic_text(directory / "skillmap.json", encoded(payload(state)))
    atomic_text(directory / "manifest.json", encoded({"created_at": now(), "dataset": state["dataset"],
        "mode": "offline interactive snapshot", "html_sha256": hashlib.sha256(document.encode()).hexdigest()}))
    return directory / "index.html"
