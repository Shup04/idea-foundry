"""Selected-source workflow built on the prototype's evidence and versioned Store."""

from copy import deepcopy
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
import re
import stat
import uuid

from . import evidence, exchange, practicality
from .storage import Store, atomic_text, encoded
from .validation import (Invalid, digest, indexed, keys, read_json, require,
                         validate_state, words)


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def uid(prefix):
    return prefix + uuid.uuid4().hex[:16]


def blank_core():
    return {"schema_version": 1, "sources": [], "claims": [], "ideas": [], "outcomes": [], "corrections": []}


def validate_workspace(state):
    keys(state, ("schema_version", "dataset", "core", "source_labels", "proposals", "runs",
                 "settings", "snapshots", "batches", "migration", "review_gate"), ("knowledge", "skillmap", "understanding", "memory", "capture"))
    require(state["schema_version"] == 2 and state["dataset"] in ("personal", "synthetic"), "invalid workspace type")
    require(state["review_gate"] == "unreviewed", "software cannot approve personal usefulness")
    validate_state(state["core"], idea_limit=60, claim_limit=10000, source_limit=20000, correction_limit=20000)
    practicality.validate_settings(state["settings"])
    sources = {s["id"] for s in state["core"]["sources"]}
    require(isinstance(state["source_labels"], dict) and set(state["source_labels"]) == sources,
            "every source needs dataset attribution")
    require(all(v == state["dataset"] for v in state["source_labels"].values()), "synthetic/personal source boundary mismatch")
    proposals = indexed(state["proposals"], "proposal", 10000)
    claim_ids = {claim["id"] for claim in state["core"]["claims"]}
    temp = deepcopy(state["core"])
    temp["ideas"], temp["outcomes"] = [], []
    for p in proposals.values():
        keys(p, ("id", "claim", "status", "matches", "run_id", "core_id", "replacement", "note"))
        require(p["status"] in ("proposed", "accepted", "corrected", "rejected", "excluded"), "invalid review status")
        require(isinstance(p["matches"], list), "invalid correction matches")
        require(all(cid in claim_ids for cid in p["matches"]), "unresolved previous correction")
        require(p["core_id"] is None or p["core_id"] in claim_ids, "unresolved reviewed claim")
        require(p["replacement"] is None or p["replacement"] in claim_ids, "unresolved replacement claim")
        temp["claims"].append({**p["claim"], "id": p["id"], "status": "excluded", "contradicts": []})
    validate_state(temp, claim_limit=20000, source_limit=20000, correction_limit=20000)
    if "knowledge" in state:
        from .knowledge import validate_knowledge
        validate_knowledge(state)
    if "skillmap" in state:
        from .skillmap import validate_map
        validate_map(state)
    if "understanding" in state:
        from .understanding import validate
        validate(state)
    if "memory" in state:
        from .memory import validate
        validate(state)
    if "capture" in state:
        from .capture import validate
        validate(state)
    runs = indexed(state["runs"], "handoff", 200)
    for run in runs.values():
        require(run["payload"]["dataset"] == state["dataset"], "handoff dataset mismatch")
        require(run["sha256"] == digest(encoded(run["payload"])), "handoff hash mismatch")
        require(run["status"] in ("waiting", "failed", "imported", "cancelled"), "invalid handoff status")
        require(run["approved_at"] is not None, "handoff requires explicit approval")
    require(isinstance(state["snapshots"], list) and len(state["snapshots"]) <= 60, "snapshot budget reached")
    require(isinstance(state["batches"], list) and len(state["batches"]) <= 20, "batch history budget reached")
    known_ideas = {i["id"] for i in state["core"]["ideas"]}
    for batch in state["batches"]:
        require(1 <= len(batch["idea_ids"]) <= 3 and set(batch["idea_ids"]) <= known_ideas, "invalid batch")
        require(batch["dataset"] == state["dataset"], "batch dataset mismatch")
    return state


def normalize(text):
    return " ".join(re.findall(r"\w+", text.casefold()))


def possible_matches(claim, state):
    """Conservative lexical/source hints, not semantic equivalence or a decision."""
    matches = []
    origins = {s["id"]: s["origin"] for s in state["core"]["sources"]}
    for old in state["core"]["claims"]:
        if old["status"] not in ("rejected", "excluded"):
            continue
        a, b = set(normalize(claim["text"]).split()), set(normalize(old["text"]).split())
        same_source = any(origins.get(r["source"]) == origins.get(s["source"])
                          for r in claim["sources"] for s in old["sources"])
        similarity = len(a & b) / max(1, min(len(a), len(b)))
        if (claim["key"] == old["key"] or normalize(claim["text"]) == normalize(old["text"])
                or similarity >= 0.55 or SequenceMatcher(None, normalize(claim["text"]), normalize(old["text"])).ratio() >= 0.7
                or (same_source and claim["facet"] == old["facet"])):
            matches.append(old["id"])
    return matches


def selected_file(path, first=1, last=None):
    """Read exactly the chosen regular file; no link following, directory scan or URL fetch."""
    path = Path(path).expanduser()
    require(path.suffix.lower() in (".md", ".markdown", ".txt", ".text"), "select a Markdown or plain-text file")
    require(not path.is_symlink() and stat.S_ISREG(path.stat().st_mode), "select a regular file, not a link or device")
    # Bound read before decoding. Only selected text is persisted or exported.
    with path.open("rb") as handle:
        raw = handle.read(500001)
    require(len(raw) <= 500000, "file exceeds 500 KB; create a smaller selected excerpt")
    try:
        full = raw.decode("utf-8")
    except UnicodeError as exc:
        raise Invalid("source must be UTF-8 plain text") from exc
    lines = full.splitlines(keepends=True)
    last = len(lines) if last is None else last
    require(type(first) is int and type(last) is int and 1 <= first <= last <= len(lines), "invalid selected line range")
    text = "".join(lines[first - 1:last])
    words(text, "selected text", exchange.MAX_SELECTED)
    return {"path": str(path.absolute()), "first": first, "last": last, "text": text,
            "sha256": digest(text), "file_sha256": digest(full)}


class Workflow:
    def __init__(self, path, dataset="personal"):
        require(dataset in ("personal", "synthetic"), "choose personal or synthetic")
        self.path = Path(path)
        self.dataset = dataset
        self.store = Store(self.path / "state", validator=validate_workspace, max_bytes=100_000_000, compress=True)
        if (self.path / "state/current.json").exists():
            require(self.load()["dataset"] == dataset, "workspace belongs to a different dataset")

    def initialize(self, legacy=None):
        require(not (self.path / "state/current.json").exists(), "workspace already initialized; choose a new directory")
        state = {"schema_version": 2, "dataset": self.dataset, "core": blank_core(), "source_labels": {},
                 "proposals": [], "runs": [], "settings": practicality.defaults(), "snapshots": [],
                 "batches": [], "migration": None, "review_gate": "unreviewed"}
        if legacy is not None:
            # Copy only; never rewrite a v1 store or infer classification from a pathname.
            require(self.dataset == "personal", "legacy personal copy needs a personal destination")
            core = Store(legacy).load()
            require(not core["outcomes"], "legacy outcome classification is ambiguous; keep it separate")
            state["core"] = deepcopy(core)
            state["migration"] = {"from": str(legacy), "source_sha256": digest(encoded(core)), "at": now(),
                                  "archived_demo_ideas": len(core["ideas"]),
                                  "note": "Copy only. Legacy active claims need fresh review; demo limits disabled. Legacy demo ideas stay in the separate legacy-snapshot.json archive."}
            for c in state["core"]["claims"]:
                old_status = c["status"]
                if old_status == "active":
                    c["status"] = "excluded"
                claim = {k: v for k, v in c.items() if k not in ("id", "status", "contradicts")}
                state["proposals"].append({"id": uid("p-"), "claim": claim,
                    "status": "rejected" if old_status == "rejected" else "proposed", "matches": [],
                    "run_id": "legacy", "core_id": c["id"], "replacement": None,
                    "note": "Preserved legacy rejection." if old_status == "rejected" else "Legacy content; not yet accepted in this workflow."})
            state["core"]["ideas"] = []
            state["source_labels"] = {s["id"]: self.dataset for s in core["sources"]}
            archive = self.path / "legacy-snapshot.json"
            require(not archive.exists(), "migration archive already exists; select a fresh destination")
            atomic_text(archive, encoded(core))
        self.store.initialize(state)
        return state

    def load(self):
        state = self.store.load()
        require(state["dataset"] == self.dataset, "synthetic/personal workspace mismatch")
        return state

    def update(self, operation, reason):
        def guarded(state):
            require(state["dataset"] == self.dataset, "workspace dataset changed")
            operation(state)
            state["source_labels"] = {s["id"]: self.dataset for s in state["core"]["sources"]}
        return self.store.update(guarded, reason)

    def add_source(self, selection, *, authorship, dataset):
        require(dataset == self.dataset, "synthetic sources cannot enter personal history (or vice versa)")
        require(authorship in ("my_words", "supplied_summary", "generated"), "select source authorship")
        require(selection["sha256"] == digest(selection["text"]), "source preview changed")
        words(selection["text"], "selected text", exchange.MAX_SELECTED)
        result = []
        def add(state):
            core = state["core"]
            require(not any(i["description"] in selection["text"] and i["title"] in selection["text"]
                            for i in core["ideas"]), "known generated idea cannot be reimported as personal evidence")
            kind = {"my_words": "user_statement", "supplied_summary": "user_supplied_summary", "generated": "generated"}[authorship]
            origin = "file-" + digest(selection["path"])[:24]
            related = [s for s in core["sources"] if s["origin"] == origin]
            identical = next((s for s in related if s["sha256"] == selection["sha256"]), None)
            if identical:
                require(identical["kind"] == kind, "existing source authorship differs; cannot relabel on reimport")
                result.append(identical["id"])
                return
            sid = uid("s-")
            core["sources"].append({"id": sid, "kind": kind, "origin": origin,
                "version": max((s["version"] for s in related), default=0) + 1,
                "text": selection["text"], "sha256": selection["sha256"],
                "locator": f"{selection['path']} lines {selection['first']}–{selection['last']}", "parents": []})
            result.append(sid)
        self.update(add, "explicit selected file import")
        return result[0]

    def prepare(self, stage, **options):
        content = exchange.payload(self.load(), stage, **options)
        return {"id": uid("run-"), "stage": stage, "payload": content, "sha256": digest(encoded(content)),
                "prompt_version": exchange.PROMPT_VERSION, "status": "waiting", "approved_at": None,
                "model": "unknown", "usage": "unknown", "cost": "unknown", "attempts": []}

    def approve_export(self, request, *, approved):
        require(approved is True, "explicit approval of selected content is required")
        require(request["sha256"] == digest(encoded(request["payload"])), "handoff preview changed")
        request = deepcopy(request)
        request["approved_at"] = now()
        def add(state):
            require(request["payload"]["dataset"] == self.dataset, "handoff dataset mismatch")
            require(not any(r["status"] in ("waiting", "failed") for r in state["runs"]), "finish or cancel the pending handoff first")
            # Reconstruct from current approved records, preventing arbitrary payload injection.
            supplied = request["payload"]
            if request["stage"] == "claims":
                fresh = exchange.payload(state, "claims", source_id=supplied["sources"][0]["id"])
            else:
                fresh = exchange.payload(state, "ideas", category=supplied["category"], count=supplied["count"],
                                         claim_ids=[c["id"] for c in supplied["claims"]])
            require(fresh == supplied, "selected information changed; preview again")
            state["runs"].append(request)
        self.update(add, "human approved manual analysis payload; nothing transmitted automatically")
        return self.export_again(request["id"])

    def export_again(self, run_id):
        run = next(r for r in self.load()["runs"] if r["id"] == run_id)
        target = self.path / "exchange" / f"{run_id}.md"
        if not target.exists():
            atomic_text(target, exchange.prompt(run))
        return target

    def cancel(self, run_id, reason="Cancelled by user"):
        def operation(state):
            run = next(r for r in state["runs"] if r["id"] == run_id)
            require(run["status"] in ("waiting", "failed"), "handoff is already closed")
            run["status"] = "cancelled"
            run["attempts"].append({"at": now(), "error": reason})
        self.update(operation, "explicit handoff cancellation; no model job exists")

    def import_response(self, run_id, path):
        run = next(r for r in self.load()["runs"] if r["id"] == run_id)
        require(run["status"] in ("waiting", "failed"), "handoff is already closed")
        require(not Path(path).is_symlink() and stat.S_ISREG(Path(path).stat().st_mode), "select a regular response file")
        with Path(path).open("rb") as handle:
            raw = handle.read(exchange.MAX_RESPONSE + 1)
        require(len(raw) <= exchange.MAX_RESPONSE, "response exceeds 120 KB")
        require(raw, "response empty or exceeds 120 KB")
        saved = self.path / "exchange" / f"{run_id}-response-{uid('')}.txt"
        # Invalid model output is retained for diagnosis; never evaluated as code.
        atomic_text(saved, raw.decode("utf-8", errors="replace"))
        try:
            response = read_json(path)
            def accept(state):
                current = next(r for r in state["runs"] if r["id"] == run_id)
                require(current["status"] in ("waiting", "failed"), "handoff is already closed")
                exchange.validate_response(response, current, state["core"])
                if response["status"] == "failed":
                    raise Invalid(response["error"])
                core = state["core"]
                for claim in response["claims"]:
                    # Review history is never overwritten, even for identical reimports.
                    if any(p["claim"] == claim for p in state["proposals"]):
                        continue
                    state["proposals"].append({"id": uid("p-"), "claim": claim, "status": "proposed",
                        "matches": possible_matches(claim, state), "run_id": run_id,
                        "core_id": None, "replacement": None, "note": "Awaiting your review; quotation is not proof."})
                if response["ideas"]:
                    ids = []
                    for idea in response["ideas"]:
                        iid = uid("i-")
                        core["ideas"].append({**idea, "id": iid})
                        ids.append(iid)
                    state["batches"].append({"id": run_id, "idea_ids": ids, "dataset": self.dataset,
                                             "note": "Manual Codex output; unresearched assumptions."})
                    self._snapshot(state, "new idea batch", ids)
                current["status"], current["model"] = "imported", response["model"]
                current["attempts"].append({"at": now(), "response": str(saved), "error": None})
            return self.update(accept, "validated manual response; personal claims staged, never auto-accepted")
        except (Invalid, KeyError, TypeError, ValueError, RecursionError) as exc:
            error = str(exc)[:2000]
            def fail(state):
                current = next(r for r in state["runs"] if r["id"] == run_id)
                if current["status"] in ("waiting", "failed"):
                    current["status"] = "failed"
                    current["attempts"].append({"at": now(), "response": str(saved), "error": error})
            self.update(fail, "analysis failed validation; profile and ideas unchanged")
            raise Invalid(error) from exc

    def review(self, proposal_id, action, text="", *, acknowledge_matches=False):
        require(action in ("accept", "reject", "correct"), "unknown review action")
        if action != "accept":
            words(text.strip(), "your correction or rejection reason", 4000)
        def apply(state):
            p = next(p for p in state["proposals"] if p["id"] == proposal_id)
            from .memory import before_review, proposal_detail as memory_detail
            before_review(state, p, action)
            require(action != "accept" or (p["replacement"] is None and p["status"] != "excluded"),
                    "this statement was changed or excluded; write a correction instead of accepting its old wording")
            require(p["status"] != "rejected" or action == "correct", "rejected claims need an explicit correction")
            core = state["core"]
            matches = [cid for cid in possible_matches(p["claim"], state) if cid != p["core_id"]]
            require(action != "accept" or not matches or acknowledge_matches,
                    "potentially equivalent corrected/rejected information: review the matches and acknowledge")
            cid = p["core_id"]
            if cid is None:
                cid = uid("c-")
                core["claims"].append({**deepcopy(p["claim"]), "id": cid, "status": "excluded", "contradicts": []})
                p["core_id"] = cid
            target = next(c for c in core["claims"] if c["id"] == cid)
            statement = text.strip() or f"I accept this statement about me: {p['claim']['text']}"
            if action == "accept" and memory_detail(state, p["id"]):
                statement += "\nI also confirm this proposed change:\n" + memory_detail(state, p["id"])
            if action == "accept" and "understanding" in state:
                from .understanding import proposal_detail
                proposed_context = proposal_detail(state, p["id"])
                if proposed_context:
                    statement += "\nI also confirm this proposed context:\n" + proposed_context
            sid = uid("review-")
            source = {"id": sid, "kind": "user_statement", "origin": sid, "version": 1,
                      "text": statement, "sha256": digest(statement), "locator": "About Me: explicit user review", "parents": []}
            correction = {"id": uid("action-"), "claim_id": cid, "action": "reinstate" if action == "accept" else "reject",
                          "reason": statement, "sources": [{"source": sid, "quote": statement}], "recorded_at": now()}
            if action == "accept":
                require(not any(c["status"] == "rejected" and c["key"] == target["key"] and c["stance"] == target["stance"]
                                for c in core["claims"]), "this exact rejected proposition needs a written correction")
            evidence.correct(core, {"source": source, "correction": correction})
            if p["replacement"] and action in ("correct", "reject"):
                # A second edit retires the earlier corrected statement too.
                prior = next(c for c in core["claims"] if c["id"] == p["replacement"])
                prior["status"] = "rejected"
                core["corrections"].append({**correction, "id": uid("action-"), "claim_id": prior["id"], "action": "reject"})
            if action == "accept":
                # The click is an explicit confirmation, not a model promotion. Original interpretation stays in p.
                if target["kind"] == "interpretation":
                    target["kind"] = "explicit"
                    target["sources"].append({"source": sid, "quote": statement})
                p["status"] = "accepted"
            elif action == "correct":
                replacement = uid("c-")
                core["claims"].append({"id": replacement, "key": replacement, "facet": p["claim"]["facet"],
                    "kind": "explicit", "text": statement, "stance": "asserts", "confidence": "strong",
                    "status": "active", "sources": [{"source": sid, "quote": statement}], "contradicts": []})
                p["status"], p["replacement"] = "corrected", replacement
            else:
                p["status"] = "rejected"
            p["note"] = statement
            from .knowledge import detail, empty_knowledge
            graph = state.setdefault("knowledge", empty_knowledge())
            if action in ("accept", "correct"):
                reviewed_id = p["replacement"] or cid
                graph["details"].setdefault(reviewed_id, detail())
                graph["details"][reviewed_id]["reviewed_at"] = now()
                if "understanding" in state:
                    from .understanding import reviewed_context
                    reviewed_context(state, p, reviewed_id)
                if "memory" in state:
                    from .memory import reviewed_context
                    reviewed_context(state, p, reviewed_id)
            # Existing idea snapshots remain immutable; subsequent evaluation reads current claims.
        return self.update(apply, f"human {action}; preserve original proposal and supporting passage")

    def _snapshot(self, state, reason, idea_ids=None):
        ids = idea_ids or (state["batches"][-1]["idea_ids"] if state["batches"] else [])
        report = practicality.compare(state["core"], state["settings"], ids)
        snapshot = {"id": uid("eval-"), "at": now(), "reason": reason,
                    "settings": deepcopy(state["settings"]), "report": report}
        state["snapshots"].append(snapshot)
        return snapshot

    def evaluate(self, batch_id=None):
        result = []
        def operation(state):
            batch = next((b for b in state["batches"] if b["id"] == batch_id), None) if batch_id else None
            result.append(self._snapshot(state, "explicit comparison", batch["idea_ids"] if batch else None))
        self.update(operation, "preserved comparison snapshot")
        return result[0]

    def tune(self, category, collection, cid, value, *, enabled=True, strong=None, moderate=None, batch_id=None):
        result = []
        def operation(state):
            batch = next((b for b in state["batches"] if b["id"] == batch_id), None) if batch_id else None
            ids = batch["idea_ids"] if batch else None
            before = self._snapshot(state, "before explicit policy edit", ids)
            practicality.change_setting(state["settings"], category, collection, cid, value,
                                         enabled=enabled, strong=strong, moderate=moderate)
            after = self._snapshot(state, f"user changed {category}.{cid}", ids)
            result.append({"before": before, "after": after,
                           "difference": practicality.differences(before["report"], after["report"])})
        self.update(operation, "user policy change; before and after snapshots in same atomic revision")
        return result[0]

    def feedback(self, idea_id, event, statement, metrics=None):
        words(statement, "outcome statement", 4000)
        def operation(state):
            sid = uid("outcome-source-")
            state["core"]["sources"].append({"id": sid, "kind": "user_statement", "origin": sid, "version": 1,
                "text": statement, "sha256": digest(statement), "locator": "Ideas: explicit user feedback", "parents": []})
            state["core"]["outcomes"].append({"id": uid("outcome-"), "idea_id": idea_id, "event": event,
                "occurred_at": now(), "scope": "Selected idea; user report", "method": "user_report",
                "sources": [{"source": sid, "quote": statement}], "metrics": metrics or {}, "reason_code": "other"})
        return self.update(operation, "explicit outcome report; preferences and personal claims unchanged")
