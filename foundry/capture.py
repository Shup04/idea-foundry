"""Selected personal input, lossless chunking, and explicit resumable analysis.

Originals are evidence. The queue records progress separately from reviewed
claims. Nothing runs on startup, follows links, or scans a directory.
"""

from copy import deepcopy
import os
from pathlib import Path
import stat

from . import openai_api as api, understanding as ai
from .storage import atomic_text, encoded
from .validation import digest, indexed, keys, read_json, require, words
from .workflow import now, uid

MAX_FILES = 8
MAX_INPUT = 100_000
MAX_TOTAL = 200_000
CHUNK_SIZE = 1800
MAX_CHUNKS = 3
MAX_CALLS = 3
EXTENSIONS = (".txt", ".text", ".md", ".markdown", ".json", ".csv")


def empty():
    return {"version": 1, "entries": [], "runs": []}


def _read_file(path):
    path = Path(path).expanduser().absolute()
    require(path.suffix.lower() in EXTENSIONS, "Choose a UTF-8 text, Markdown, JSON or CSV file.")
    # O_NOFOLLOW closes the final-component symlink race. There is no globbing,
    # directory traversal, URL fetching, or execution of imported content.
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as handle:
        require(stat.S_ISREG(os.fstat(handle.fileno()).st_mode), "Choose a regular file.")
        raw = handle.read(MAX_INPUT * 4 + 1)
    require(len(raw) <= MAX_INPUT * 4, "This file is too large; choose an excerpt of at most 100,000 characters.")
    try:
        text = raw.decode("utf-8")
    except UnicodeError as exc:
        raise ValueError("Choose a UTF-8 text file; binary documents need a text export.") from exc
    words(text, "file text (up to 100,000 characters)", MAX_INPUT)
    return path, text


def _split(text):
    """Partition all characters exactly once, preferring paragraph/sentence ends."""
    start = 0
    while start < len(text):
        end = min(len(text), start + CHUNK_SIZE)
        if end < len(text):
            floor = start + CHUNK_SIZE // 2
            boundary = max(text.rfind(mark, floor, end) + len(mark)
                           for mark in ("\n", ". ", "? ", "! ", "; ", " "))
            if boundary >= floor:
                end = boundary
        yield start, end
        start = end


def _experience(state, experience):
    if experience is None:
        return
    from . import skillmap
    require(any(n["id"] == experience and n["kind"] in skillmap.EXPERIENCES
                for n in skillmap.catalog(state)["nodes"]), "Choose an existing experience or general information.")


def preview(flow, *, text="", paths=(), title="", experience=None):
    state = flow.load()
    _experience(state, experience)
    require(isinstance(text, str) and isinstance(title, str), "Input must be text.")
    require(isinstance(paths, (list, tuple)) and len(paths) <= MAX_FILES, "Select at most eight files at a time.")
    entries = []
    if text.strip():
        words(text, "your text (up to 100,000 characters)", MAX_INPUT)
        entries.append({"title": title.strip() or "My note", "text": text,
                        "origin": "note-" + digest(text)[:24], "kind": "user_statement",
                        "experience": experience, "sha256": digest(text)})
    for selected in paths:
        path, content = _read_file(selected)
        entries.append({"title": path.name, "text": content, "origin": "file-" + digest(str(path))[:24],
                        "kind": "user_supplied_summary", "experience": experience, "sha256": digest(content)})
    require(entries, "Paste some information or select a file first.")
    require(sum(len(e["text"]) for e in entries) <= MAX_TOTAL, "Select at most 200,000 characters in one import.")
    for entry in entries:
        words(entry["title"], "input title", 1000)
    plan = {"version": 1, "dataset": flow.dataset, "mode": "new", "entries": entries}
    # Preview the reviewed context that retrieval can include, without exposing
    # complete resumes, repository files, or unrelated source passages.
    from . import memory
    chunks = []
    for i, entry in enumerate(entries):
        state["core"]["sources"].append({"id": f"preview-source-{i}", "kind": entry["kind"],
            "origin": f"preview-source-{i}", "version": 1, "text": entry["text"],
            "sha256": entry["sha256"], "locator": entry["title"], "parents": []})
        for start, end in _split(entry["text"]):
            chunks.append({"id": f"preview-{i}-{start}", "entry_id": f"preview-{i}",
                           "source_id": f"preview-source-{i}", "title": entry["title"],
                           "experience": experience, "start": start, "end": end,
                           "text": entry["text"][start:end]})
    contexts, entities = _contexts(state, chunks[:MAX_CHUNKS * MAX_CALLS])
    plan.update(context=contexts, entities=entities, chunks=len(chunks), sha256=digest(encoded(entries)))
    return plan


def _contexts(state, selected):
    from . import memory
    contexts, entities, seen = [], {}, set()
    for start in range(0, len(selected), MAX_CHUNKS):
        snapshot = memory.prepare(state, selected[start:start + MAX_CHUNKS])
        for record in snapshot["records"]:
            key = digest(encoded(record))
            if key not in seen:
                contexts.append(record)
                seen.add(key)
        entities.update({e["id"]: e for e in snapshot["entities"]})
    return contexts, list(entities.values())


def preview_text(plan):
    lines = ["Information selected for this import", ""]
    for entry in plan["entries"]:
        lines += [entry["title"], "Your words" if entry["kind"] == "user_statement" else "Supplied document; authorship is not independently verified",
                  entry["text"], ""]
    lines += [f"{plan['chunks']} sections. Each action handles at most {MAX_CHUNKS * MAX_CALLS}; remaining sections stay saved.",
              "", "Relevant existing knowledge for comparison"]
    for record in plan.get("context", []):
        lines.append(record.get("text", ""))
        for field in ("uncertainty", "follow_up"):
            if record.get(field):
                lines.append(str(record[field]))
        for question in record.get("questions", []):
            lines.append("Open question: " + question["text"])
    if not plan.get("context"):
        lines.append("No relevant reviewed statements yet.")
    lines += ["", "Names available for connections: " + (", ".join(e["label"] for e in plan.get("entities", [])) or "None yet")]
    lines += ["", "Save & understand sends selected sections and bounded relevant reviewed knowledge to OpenAI within your existing total cap. "
              "New statements and changes require review. Later actions retrieve current context again. Save locally sends nothing."]
    return "\n".join(lines)


def save(flow, *, plan=None, **options):
    plan = plan if plan is not None else preview(flow, **options)
    require(plan.get("mode", "new") == "new", "This is a saved-input preview; continue it instead of saving again.")
    require(plan["version"] == 1 and plan["dataset"] == flow.dataset, "Input preview belongs to another workspace type.")
    require(digest(encoded(plan["entries"])) == plan["sha256"], "Input preview changed; preview it again.")
    result = []
    def operation(state):
        saved = state.setdefault("capture", empty())
        for entry in plan["entries"]:
            words(entry["text"], "selected input", MAX_INPUT)
            require(digest(entry["text"]) == entry["sha256"], "Input hash mismatch.")
            require(entry["kind"] in ("user_statement", "user_supplied_summary"), "Only selected personal evidence can enter this queue.")
            _experience(state, entry["experience"])
            fingerprint = digest(encoded([entry["sha256"], entry["kind"], entry["experience"], entry["title"]]))
            existing = next((e for e in saved["entries"] if e["fingerprint"] == fingerprint), None)
            if existing:
                require(existing["status"] == "active", "This input was withdrawn. Restore it explicitly before processing it again.")
                result.append(existing["id"])
                continue
            related = [s for s in state["core"]["sources"] if s["origin"] == entry["origin"]]
            source = next((s for s in related if s["sha256"] == entry["sha256"] and s["kind"] == entry["kind"]), None)
            if source is None:
                source = {"id": uid("input-source-"), "kind": entry["kind"], "origin": entry["origin"],
                          "version": max((s["version"] for s in related), default=0) + 1,
                          "text": entry["text"], "sha256": entry["sha256"], "locator": entry["title"], "parents": []}
                state["core"]["sources"].append(source)
            eid = uid("input-")
            saved["entries"].append({"id": eid, "title": entry["title"], "source_ids": [source["id"]],
                "experience": entry["experience"], "at": now(), "status": "active", "fingerprint": fingerprint})
            result.append(eid)
    flow.update(operation, "saved explicitly selected input verbatim before any interpretation; unchanged inputs deduplicate")
    return list(dict.fromkeys(result))


def from_answers(flow, answer_ids=None):
    """Queue existing interviews without copying their original evidence."""
    result = []
    def operation(state):
        saved = state.setdefault("capture", empty())
        records = ai.answer_records(state, answer_ids)
        if answer_ids is None:
            wanted = {a["id"] for a in ai.pending(state)}
            records = [a for a in records if a["id"] in wanted]
        sources = {s["id"]: s for s in state["core"]["sources"]}
        for record in records:
            existing = next((e for e in saved["entries"] if e.get("answer_id") == record["id"]), None)
            if existing:
                result.append(existing["id"])
                continue
            ref = next(r for r in record["sources"] if record["text"] in sources[r["source"]]["text"])
            sid = ref["source"]
            if sources[sid]["text"] != record["text"]:
                sid = uid("input-source-")
                state["core"]["sources"].append({"id": sid, "kind": "user_statement", "origin": sid,
                    "version": 1, "text": record["text"], "sha256": digest(record["text"]),
                    "locator": "Selected interview answer", "parents": [ref["source"]]})
            eid = uid("input-")
            saved["entries"].append({"id": eid, "title": record["project"] + " — " + record["question"],
                "source_ids": [sid], "experience": record["experience"], "at": now(), "status": "active",
                "fingerprint": record["fingerprint"], "answer_id": record["id"], "claim_id": record["claim_id"]})
            result.append(eid)
    flow.update(operation, "selected saved interview evidence for context-aware understanding")
    return result


def active_source_ids(state):
    from .knowledge import statuses
    entries = state.get("capture", empty())["entries"]
    usable = statuses(state) if any(e.get("claim_id") for e in entries) else {}
    return {sid for e in entries
            if e["status"] == "active" and (not e.get("claim_id") or usable[e["claim_id"]]["usable"])
            for sid in e["source_ids"]}


def chunks(state, entry_ids=None):
    sources = {s["id"]: s for s in state["core"]["sources"]}
    active = active_source_ids(state)
    output = []
    for entry in state.get("capture", empty())["entries"]:
        if entry["status"] != "active" or (entry_ids is not None and entry["id"] not in entry_ids):
            continue
        for sid in entry["source_ids"]:
            if sid not in active:
                continue
            text = sources[sid]["text"]
            for start, end in _split(text):
                output.append({"id": "chunk-" + digest(encoded([entry["id"], sid, start, end]))[:24],
                    "entry_id": entry["id"], "source_id": sid, "title": entry["title"],
                    "experience": entry["experience"], "start": start, "end": end, "text": text[start:end]})
    return output


def pending(state, entry_ids=None):
    completed = {cid for r in state.get("capture", empty())["runs"] if r["status"] == "staged" for cid in r["chunk_ids"]}
    return [c for c in chunks(state, entry_ids) if c["id"] not in completed]


def progress(state):
    saved = state.get("capture", empty())
    current = chunks(state)
    remaining = pending(state)
    current_ids = {chunk["id"] for chunk in current}
    coverage = {}
    for batch in state.get("memory", {}).get("batches", []):
        for row in batch.get("coverage", []):
            if row["chunk_id"] in current_ids:
                coverage[row["chunk_id"]] = row
    notes = [{"chunk_id": row["chunk_id"], **note} for row in coverage.values() for note in row.get("unrepresented", [])]
    return {"entries": sum(e["status"] == "active" for e in saved["entries"]),
            "pending_chunks": len(remaining), "processed_chunks": len(current) - len(remaining),
            "withdrawn_entries": sum(e["status"] == "withdrawn" for e in saved["entries"]),
            "incomplete_chunks": len({note["chunk_id"] for note in notes}), "coverage_notes": notes}


def pending_preview(flow, entry_ids=None):
    plan = pending_plan(flow, entry_ids)
    return preview_text(plan) if plan["entries"] else "All saved sections have been processed. Review suggestions to confirm what belongs in your graph."


def pending_plan(flow, entry_ids=None):
    state = flow.load()
    selected = pending(state, entry_ids)[:MAX_CHUNKS * MAX_CALLS]
    sources = {s["id"]: s for s in state["core"]["sources"]}
    context, entities = _contexts(state, selected)
    return {"version": 1, "dataset": flow.dataset, "mode": "pending", "chunks": len(selected),
            "context": context, "entities": entities, "chunk_ids": [c["id"] for c in selected],
            "entries": [{"title": c["title"], "text": c["text"], "kind": sources[c["source_id"]]["kind"]} for c in selected]}


def withdraw(flow, entry_id, *, restore=False):
    def operation(state):
        entry = next(e for e in state["capture"]["entries"] if e["id"] == entry_id)
        entry["status"] = "active" if restore else "withdrawn"
    return flow.update(operation, "restored selected input" if restore else "withdrew selected input; originals and history retained")


def _finish(flow, run_id, proposals):
    def finish(state):
        run = next(r for r in state["capture"]["runs"] if r["id"] == run_id)
        run.update(status="staged", proposal_ids=proposals, error=None)
    flow.update(finish, "checkpointed processed sections; accepted graph unchanged until review")


def _recover(flow, entry_ids=None):
    from . import memory
    recovered = []
    state = flow.load()
    selected = {c["id"] for c in chunks(state, entry_ids)}
    for run in state.get("capture", empty())["runs"]:
        if run["status"] != "running" or not set(run["chunk_ids"]) <= selected:
            continue
        try:
            require(run["call_id"] is not None, "The interrupted request did not start.")
            call = next(c for c in state["understanding"]["calls"] if c["id"] == run["call_id"])
            response = read_json(flow.path / "ai" / "calls" / call["id"] / "response.json", max_bytes=api.MAX_RESPONSE_BYTES)
            require(call["response_sha256"] in (None, digest(encoded(response))), "Saved response changed.")
            snapshot = read_json(flow.path / "ai" / "capture" / run["id"] / "input.json", max_bytes=api.MAX_REQUEST_BYTES * 2)
            require(digest(encoded(snapshot)) == run["snapshot_sha256"], "Saved input changed.")
            proposals = memory.stage(flow, run["id"], snapshot, response)
            _finish(flow, run["id"], proposals)
            recovered.extend(proposals)
        except (OSError, ValueError, KeyError, StopIteration) as exc:
            def interrupted(current):
                row = next(r for r in current["capture"]["runs"] if r["id"] == run["id"])
                row.update(status="interrupted", error="Previous analysis was interrupted; an explicit retry is required.")
            flow.update(interrupted, "retained interrupted request and budget reservation; no automatic resend")
            raise ValueError("An earlier analysis was interrupted. Your input is saved. Continue again to retry within the remaining cap.") from exc
    return recovered


def process(flow, *, entry_ids=None, client=None, max_calls=MAX_CALLS, plan=None):
    """Explicit bounded action; each completed request has a durable checkpoint."""
    from . import memory
    require(type(max_calls) is int and 1 <= max_calls <= MAX_CALLS, "Choose one to three analysis calls per action.")
    client = client or api.OpenAI()
    result = {"proposals": [], "remaining_chunks": 0, "processed_chunks": 0, "recovered": False, "error": None}
    with ai.inference_lock(flow):
        require(ai.enabled(flow.load()), "Enable AI understanding with a total spending cap first. Your input is saved locally.")
        recovered = _recover(flow, entry_ids)
        result["proposals"].extend(recovered)
        result["recovered"] = bool(recovered)
        for _ in range(max_calls):
            state = flow.load()
            chosen = pending(state, entry_ids)[:MAX_CHUNKS]
            if plan and plan.get("mode") == "pending":
                chosen = [c for c in chosen if c["id"] in plan["chunk_ids"]]
            if not chosen:
                break
            snapshot = memory.prepare(state, chosen)
            if plan:
                require(plan["dataset"] == flow.dataset, "Input preview belongs to another workspace type.")
                approved = {digest(encoded(r)) for r in plan["context"]}
                known = {digest(encoded(e)) for e in plan["entities"]}
                # A concurrent review may add or alter relevant context. Never
                # send that new material under an earlier preview.
                require(all(digest(encoded(r)) in approved for r in snapshot["records"])
                        and all(digest(encoded(e)) in known for e in snapshot["entities"]),
                        "Your knowledge changed since this preview. Preview the saved input again before continuing.")
            body = memory.request(snapshot, state["understanding"]["config"]["model"])
            rid = uid("capture-")
            atomic_text(flow.path / "ai" / "capture" / rid / "input.json", encoded(snapshot))
            def start(current):
                current["understanding"]["config"].update(scope="knowledge_inputs", approved_at=now())
                current.setdefault("capture", empty())["runs"].append({"id": rid, "at": now(), "status": "running",
                    "chunk_ids": [c["id"] for c in chosen], "call_id": None, "proposal_ids": [], "error": None,
                    "snapshot_sha256": digest(encoded(snapshot))})
            flow.update(start, "explicitly processed selected input with relevant reviewed profile context under existing total API cap")
            try:
                response = ai._call(flow, client, "responses", body, rid)
                proposals = memory.stage(flow, rid, snapshot, response)
                _finish(flow, rid, proposals)
                result["proposals"].extend(proposals)
                result["processed_chunks"] += len(chosen)
            except Exception as exc:
                def failed(current):
                    row = next(r for r in current["capture"]["runs"] if r["id"] == rid)
                    row.update(status="failed", error="Analysis stopped. Original input and completed sections are saved.")
                flow.update(failed, "stopped bounded processing without retry; saved input and completed sections retained")
                # Provider errors are sanitized by the transport. Avoid recording
                # arbitrary exception contents (which may contain private text).
                result["error"] = str(exc) if isinstance(exc, ValueError) else "Analysis stopped. Your input is saved; continue to retry."
                break
        result["remaining_chunks"] = len(pending(flow.load(), entry_ids))
        result["proposals"] = list(dict.fromkeys(result["proposals"]))
    return result


def validate(state):
    saved = state["capture"]
    keys(saved, ("version", "entries", "runs"))
    require(saved["version"] == 1, "Unsupported input queue version.")
    sources = {s["id"]: s for s in state["core"]["sources"]}
    claims = {c["id"]: c for c in state["core"]["claims"]}
    for entry in indexed(saved["entries"], "saved input", 5000).values():
        keys(entry, ("id", "title", "source_ids", "experience", "at", "status", "fingerprint"), ("answer_id", "claim_id"))
        words(entry["title"], "input title", 1200)
        require(entry["status"] in ("active", "withdrawn"), "Invalid saved input status.")
        require(isinstance(entry["source_ids"], list) and entry["source_ids"] and set(entry["source_ids"]) <= sources.keys(), "Saved input source is missing.")
        require(all(sources[sid]["kind"] in ("user_statement", "user_supplied_summary") for sid in entry["source_ids"]), "Generated material cannot become personal input evidence.")
        require(entry.get("claim_id") is None or entry["claim_id"] in claims, "Saved answer is missing.")
    call_ids = {c["id"] for c in state.get("understanding", ai.empty())["calls"]}
    proposal_ids = {p["id"] for p in state["proposals"]}
    for run in indexed(saved["runs"], "input analysis", 5000).values():
        keys(run, ("id", "at", "status", "chunk_ids", "call_id", "proposal_ids", "error", "snapshot_sha256"))
        require(run["status"] in ("running", "staged", "failed", "interrupted"), "Invalid input analysis status.")
        require(isinstance(run["chunk_ids"], list) and 0 < len(run["chunk_ids"]) <= MAX_CHUNKS, "Invalid section count.")
        require(run["call_id"] is None or run["call_id"] in call_ids, "Input API call is missing.")
        require(isinstance(run["proposal_ids"], list) and set(run["proposal_ids"]) <= proposal_ids, "Input suggestions are missing.")
