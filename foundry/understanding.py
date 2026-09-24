"""Reviewable interview interpretations and local semantic retrieval.

The evidence store remains canonical. Embeddings are a disposable local cache;
similarity never accepts a fact or creates a relationship. Network calls hold
only a separate inference lock, not the evidence writer lock.
"""

from contextlib import contextmanager
from copy import deepcopy
import fcntl
import math

from . import openai_api as api
from . import skillmap
from . import understanding_contract as contract
from .knowledge import detail, empty_knowledge, statuses
from .storage import atomic_text, encoded
from .validation import digest, indexed, keys, number, read_json, require, words
from .workflow import normalize, now, possible_matches, uid

MAX_ANSWERS = 8


def empty():
    return {"version": 1, "config": {"enabled": False, "model": api.DEFAULT_MODEL,
            "budget_usd": 0, "approved_at": None, "scope": "interview_answers"},
            "calls": [], "batches": [], "insights": [], "neighbors": []}


def budget(state):
    saved = state.get("understanding", empty())
    return {"limit": saved["config"]["budget_usd"],
            "committed": round(sum(c["charged_usd"] for c in saved["calls"]), 8),
            "estimated": round(sum(c["cost_estimate_usd"] or 0 for c in saved["calls"]), 8),
            "unknown_calls": sum(c["cost_estimate_usd"] is None for c in saved["calls"])}


def enabled(state):
    return state.get("understanding", empty())["config"]["enabled"]


def configure(flow, *, budget_usd, model=api.DEFAULT_MODEL, enable=True):
    require(model in api.MODELS, "Choose a supported OpenAI model.")
    require(number(budget_usd) and 0 < budget_usd <= 100, "Choose a total API cap greater than $0 and at most $100.")
    require(type(enable) is bool, "Invalid AI setting.")
    def operation(state):
        require(budget_usd >= budget(state)["committed"], "The total cap cannot be below amounts already used or reserved.")
        saved = state.setdefault("understanding", empty())
        saved["config"].update(enabled=enable, model=model, budget_usd=budget_usd, approved_at=now())
    return flow.update(operation, "user configured OpenAI interview scope and cumulative API budget; no credential saved")


def pause(flow):
    def operation(state):
        state.setdefault("understanding", empty())["config"]["enabled"] = False
    return flow.update(operation, "user paused AI understanding; saved evidence retained")


def validate(state):
    saved = state["understanding"]
    keys(saved, ("version", "config", "calls", "batches", "insights", "neighbors"))
    require(saved["version"] == 1, "Unsupported understanding schema.")
    config = saved["config"]
    keys(config, ("enabled", "model", "budget_usd", "approved_at", "scope"))
    require(type(config["enabled"]) is bool and config["model"] in api.MODELS, "Invalid understanding configuration.")
    require(number(config["budget_usd"]) and 0 <= config["budget_usd"] <= 100, "Invalid API budget.")
    require(config["scope"] in ("interview_answers", "knowledge_inputs"), "Unsupported cloud scope.")
    require(not config["enabled"] or (config["approved_at"] and config["budget_usd"] > 0), "Cloud processing needs a budget and approval.")
    calls = indexed(saved["calls"], "API call", 1000)
    for call in calls.values():
        keys(call, ("id", "endpoint", "model", "status", "at", "reserved_usd", "charged_usd",
                    "cost_estimate_usd", "usage", "request_sha256", "response_sha256", "error"))
        require(call["endpoint"] in ("responses", "embeddings"), "Invalid API endpoint.")
        require(call["model"] in (*api.MODELS, api.EMBEDDING_MODEL), "Unknown API model.")
        require((call["endpoint"] == "embeddings") == (call["model"] == api.EMBEDDING_MODEL), "API endpoint/model mismatch.")
        require(call["status"] in ("running", "completed", "failed", "interrupted"), "Invalid API call state.")
        require(all(number(call[k]) and call[k] >= 0 for k in ("reserved_usd", "charged_usd")), "Invalid API reservation.")
        require(call["cost_estimate_usd"] is None or (number(call["cost_estimate_usd"]) and call["cost_estimate_usd"] >= 0),
                "Invalid cost estimate.")
        if call["usage"] is not None:
            keys(call["usage"], ("input_tokens", "output_tokens"))
            require(all(type(n) is int and n >= 0 for n in call["usage"].values()), "Invalid API usage.")
    answers = {a["id"]: a for a in state.get("skillmap", skillmap.empty_map())["answers"]}
    batches = indexed(saved["batches"], "understanding batch", 1000)
    for batch in batches.values():
        keys(batch, ("id", "at", "status", "answer_ids", "fingerprints", "call_id", "error", "proposal_ids"))
        require(batch["status"] in ("running", "staged", "failed", "interrupted"), "Invalid understanding batch.")
        require(isinstance(batch["answer_ids"], list) and 0 < len(batch["answer_ids"]) <= MAX_ANSWERS
                and set(batch["answer_ids"]) <= answers.keys(), "Invalid batch answer selection.")
        require(set(batch["fingerprints"]) == set(batch["answer_ids"]), "Missing answer fingerprint.")
        require(batch["call_id"] is None or batch["call_id"] in calls, "Missing API call.")
    proposals = {p["id"]: p for p in state["proposals"]}
    claims = {c["id"]: c for c in state["core"]["claims"]}
    graph = skillmap.catalog(state, history=True)
    skills = [{"id": n["id"], "label": n["label"]} for n in graph["nodes"] if n["kind"] == "skill"]
    for insight in indexed(saved["insights"], "answer insight", 1000).values():
        keys(insight, ("id", "proposal", "answer_id", "experience", "data"))
        require(insight["proposal"] in proposals and insight["answer_id"] in answers, "Insight evidence is missing.")
        require(insight["experience"] == answers[insight["answer_id"]]["experience"], "Insight experience mismatch.")
        original = claims[answers[insight["answer_id"]]["claim_id"]]
        contract.validate_insight(insight["data"], {"text": original["text"], "skills": skills})
        proposal = proposals[insight["proposal"]]
        require(proposal["claim"]["text"] == insight["data"]["text"] and proposal["claim"]["facet"] == insight["data"]["facet"],
                "Insight disagrees with its reviewable proposal.")
        require(all(any(r["source"] == source["source"] and r["quote"] in source["quote"] for source in original["sources"])
                    for r in proposal["claim"]["sources"]), "Insight needs its own answer's evidence.")
    for batch in batches.values():
        require(isinstance(batch["proposal_ids"], list) and set(batch["proposal_ids"]) <= proposals.keys(), "Missing batch proposal.")
    require(isinstance(saved["neighbors"], list) and len(saved["neighbors"]) <= 3000, "Related-answer budget exceeded.")
    for row in saved["neighbors"]:
        keys(row, ("from", "to", "similarity", "from_hash", "to_hash"))
        require(row["from"] in answers and row["to"] in answers and row["from"] != row["to"], "Invalid related answer.")
        require(number(row["similarity"]) and -1.00001 <= row["similarity"] <= 1.00001, "Invalid similarity.")


def answer_records(state, answer_ids=None):
    usable = statuses(state)
    graph = skillmap.catalog(state)
    nodes = {n["id"]: n for n in graph["nodes"]}
    claims = {c["id"]: c for c in state["core"]["claims"]}
    records = []
    for answer in state.get("skillmap", skillmap.empty_map())["answers"]:
        if answer_ids is not None and answer["id"] not in answer_ids:
            continue
        if not usable[answer["claim_id"]]["usable"] or answer["experience"] not in nodes:
            continue
        node = nodes[answer["experience"]]
        claim = claims[answer["claim_id"]]
        connected = {l["to"] for l in graph["links"] if l["from"] == node["id"]}
        # Existing skill labels only; raw repository files, resumes and unrelated
        # profile claims are deliberately absent from the network payload.
        skills = [{"id": n["id"], "label": n["label"]} for n in graph["nodes"] if n["id"] in connected]
        question = answer.get("question") or skillmap.TOPICS[answer["topic"]][1].format(name=node["label"])
        records.append({"id": answer["id"], "experience": node["id"], "project": node["label"],
                        "topic": answer["topic"], "question": question,
                        "question_basis": "saved" if answer.get("question") else "reconstructed topic; original full prompt unavailable",
                        "text": claim["text"], "skills": skills, "claim_id": claim["id"],
                        "sources": deepcopy(claim["sources"]), "fingerprint": digest(encoded([claim["text"], question]))})
    return records


def pending(state):
    completed = {(aid, fingerprint) for b in state.get("understanding", empty())["batches"]
                 if b["status"] == "staged" for aid, fingerprint in b["fingerprints"].items()}
    captured = set()
    if "capture" in state:
        from .capture import pending as pending_input
        remaining = {c["entry_id"] for c in pending_input(state)}
        captured = {e["answer_id"] for e in state["capture"]["entries"]
                    if e.get("answer_id") and e["id"] not in remaining}
    return [a for a in answer_records(state) if (a["id"], a["fingerprint"]) not in completed and a["id"] not in captured]


def public_input(answers):
    return [{k: v for k, v in a.items() if k not in ("sources", "claim_id", "fingerprint")} for a in answers]


def preview_text(answers):
    lines = []
    for answer in answers:
        lines += [answer["project"], "Question: " + answer["question"], "Your answer: " + answer["text"],
                  "Skill context: " + (", ".join(s["label"] for s in answer["skills"]) or "No named skills yet.")]
        if answer["question_basis"] != "saved":
            lines.append("The original full question was not saved; this is its topic prompt.")
        lines.append("")
    return "\n".join(lines) or "No new answers to interpret."


def request(answers, model):
    body = {"model": model, "store": False, "tools": [], "service_tier": "default",
            "reasoning": {"effort": "low"}, "max_output_tokens": api.MAX_OUTPUT_TOKENS,
            "instructions": contract.INSTRUCTIONS,
            "input": encoded({"answers": public_input(answers)}),
            "text": {"format": {"type": "json_schema", "name": "interview_insights", "strict": True, "schema": contract.SCHEMA}}}
    api.request_bytes(body)
    return body


@contextmanager
def inference_lock(flow):
    directory = flow.path / "ai"
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".lock").open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("AI understanding is already running in this workspace.") from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _call(flow, client, endpoint, body, batch_id=None):
    payload = encoded(body)
    if endpoint == "embeddings":
        # A crash after receiving embeddings but before writing the derived
        # cache can be repaired from the saved response with zero new calls.
        for old in reversed(flow.load().get("understanding", empty())["calls"]):
            if old["endpoint"] != endpoint or old["request_sha256"] != digest(payload):
                continue
            path = flow.path / "ai" / "calls" / old["id"] / "response.json"
            if not path.is_file():
                continue
            try:
                reply = read_json(path, max_bytes=api.MAX_RESPONSE_BYTES)
                require(not old["response_sha256"] or digest(encoded(reply)) == old["response_sha256"], "Saved response hash mismatch.")
                api.vectors(reply, len(body["input"]))
                return reply
            except (ValueError, OSError, KeyError, TypeError):
                continue
    cid = uid("api-")
    amount = api.reservation(endpoint, body)
    root = flow.path / "ai" / "calls" / cid
    atomic_text(root / "request.json", payload)
    def reserve(state):
        saved = state.setdefault("understanding", empty())
        require(enabled(state), "AI understanding is paused.")
        available = budget(state)
        require(available["committed"] + amount <= available["limit"],
                "API spending cap reached. Your answer is saved. Adjust the total cap in AI understanding to continue.")
        saved["calls"].append({"id": cid, "endpoint": endpoint, "model": body["model"], "status": "running", "at": now(),
            "reserved_usd": amount, "charged_usd": amount, "cost_estimate_usd": None, "usage": None,
            "request_sha256": digest(payload), "response_sha256": None, "error": None})
        if batch_id:
            batches = saved["batches"] + state.get("capture", {}).get("runs", [])
            next(b for b in batches if b["id"] == batch_id)["call_id"] = cid
    flow.update(reserve, "reserved bounded API cost before request; no evidence lock across network")
    try:
        response = client.post(endpoint, body)
        raw = encoded(response)
        require(len(raw.encode()) <= api.MAX_RESPONSE_BYTES, "OpenAI response exceeded the size limit.")
        atomic_text(root / "response.json", raw)
        usage, cost = api.usage_cost(endpoint, body["model"], response)
        def complete(state):
            call = next(c for c in state["understanding"]["calls"] if c["id"] == cid)
            call.update(status="completed", usage=usage, cost_estimate_usd=cost,
                        charged_usd=amount if cost is None else cost, response_sha256=digest(raw))
        flow.update(complete, "saved OpenAI response and reported token usage; cost remains an estimate")
        return response
    except BaseException as exc:
        def failed(state):
            call = next(c for c in state["understanding"]["calls"] if c["id"] == cid)
            # A response saved before a crash remains recoverable without a new
            # request. The reservation stays committed when usage is unknown.
            if call["status"] == "running":
                call.update(status="interrupted" if not isinstance(exc, Exception) else "failed",
                            error="Request did not complete locally; billing may be unknown.")
        flow.update(failed, "API request stopped; uncertain usage retains its reservation")
        raise


def _stage(flow, batch_id, answers, response):
    result = contract.validate_result(api.structured_result(response), answers)
    expected = {a["id"]: a for a in answers}
    result_ids = []
    def operation(state):
        saved = state["understanding"]
        batch = next(b for b in saved["batches"] if b["id"] == batch_id)
        if batch["status"] == "staged":
            result_ids.extend(batch["proposal_ids"])
            return
        require(batch["fingerprints"] == {a["id"]: a["fingerprint"] for a in answers}, "Saved answer snapshot mismatch.")
        current = {a["id"]: a for a in answer_records(state)}
        require(all(aid in current and current[aid]["fingerprint"] == a["fingerprint"] for aid, a in expected.items()),
                "An answer changed or was excluded during analysis. The response is saved, but was not applied.")
        for row in result["answers"]:
            answer = expected[row["answer_id"]]
            for insight in row["insights"]:
                references = [{"source": r["source"], "quote": insight["quote"]} for r in answer["sources"] if insight["quote"] in r["quote"]]
                require(references, "Insight is not supported by an original answer passage.")
                pid = uid("p-")
                claim = {"key": "insight-" + digest(encoded([answer["experience"], insight["relation"], normalize(insight["text"])]))[:24],
                    "facet": insight["facet"], "kind": "interpretation", "text": insight["text"], "stance": "asserts",
                    "confidence": "moderate" if insight["basis"] == "stated" else "weak", "sources": references}
                if any(p["claim"]["key"] == claim["key"] for p in state["proposals"]):
                    continue
                state["proposals"].append({"id": pid, "claim": claim, "status": "proposed", "matches": possible_matches(claim, state),
                    "run_id": batch_id, "core_id": None, "replacement": None, "note": "Interpretation of your answer; awaiting review."})
                saved["insights"].append({"id": uid("insight-"), "proposal": pid, "answer_id": answer["id"],
                    "experience": answer["experience"], "data": deepcopy(insight)})
                result_ids.append(pid)
        batch.update(status="staged", proposal_ids=result_ids, error=None)
    flow.update(operation, "validated quoted answer insights staged for human review; no personal facts auto-accepted")
    return result_ids


def _recover(flow):
    """Recover received replies; never automatically resend an uncertain call."""
    state = flow.load()
    calls = {c["id"]: c for c in state.get("understanding", empty())["calls"]}
    for batch in state.get("understanding", empty())["batches"]:
        if batch["status"] != "running":
            continue
        call = calls.get(batch["call_id"])
        path = flow.path / "ai" / "calls" / batch["call_id"] / "response.json" if call else None
        try:
            if path and path.is_file():
                response = read_json(path, max_bytes=api.MAX_RESPONSE_BYTES)
                if call["response_sha256"]:
                    require(digest(encoded(response)) == call["response_sha256"], "Saved response hash mismatch.")
                snapshot = read_json(flow.path / "ai" / "batches" / batch["id"] / "input.json")
                _stage(flow, batch["id"], snapshot["answers"], response)
                continue
        except (ValueError, OSError, KeyError, TypeError):
            pass
        def interrupted(current):
            target = next(b for b in current["understanding"]["batches"] if b["id"] == batch["id"])
            target.update(status="interrupted", error="Previous request interrupted. Retry explicitly; previous billing may be unknown.")
        flow.update(interrupted, "interrupted request needs an explicit retry; no network call was repeated")
        raise ValueError("An earlier analysis was interrupted. Your answers are safe. Run again to retry within the remaining cap.")


def reprocess(flow, batch_id):
    """Explicit local revalidation after a contract fix; never calls a provider."""
    with inference_lock(flow):
        state = flow.load()
        batch = next(b for b in state.get("understanding", empty())["batches"] if b["id"] == batch_id)
        call = next(c for c in state["understanding"]["calls"] if c["id"] == batch["call_id"])
        response = read_json(flow.path / "ai" / "calls" / call["id"] / "response.json", max_bytes=api.MAX_RESPONSE_BYTES)
        require(call["response_sha256"] == digest(encoded(response)), "Saved response hash mismatch.")
        snapshot = read_json(flow.path / "ai" / "batches" / batch_id / "input.json")
        require(snapshot["dataset"] == flow.dataset, "Saved response dataset mismatch.")
        return _stage(flow, batch_id, snapshot["answers"], response)


def _chunks(answer):
    text = f"{answer['project']} / {answer['topic']}\nQuestion: {answer['question']}\nAnswer: {answer['text']}"
    # Each chunk is at most 6000 UTF-8 bytes, under the model's 8192-token input
    # limit even without installing a tokenizer. All chunks are represented.
    return [text[start:start + 1500] for start in range(0, len(text), 1500)]


def _vector_key(text):
    return digest(encoded([api.EMBEDDING_MODEL, api.DIMENSIONS, text]))


def load_index(flow):
    path = flow.path / "ai" / "embeddings.json"
    if not path.exists():
        return {}
    data = read_json(path, max_bytes=20_000_000)
    keys(data, ("model", "dimensions", "vectors"))
    require(data["model"] == api.EMBEDDING_MODEL and data["dimensions"] == api.DIMENSIONS, "Embedding cache model mismatch.")
    require(isinstance(data["vectors"], dict) and len(data["vectors"]) <= 4000, "Embedding cache budget exceeded.")
    for vector in data["vectors"].values():
        require(isinstance(vector, list) and len(vector) == api.DIMENSIONS and
                all(number(v) for v in vector), "Invalid local embedding cache.")
        require(.99 <= sum(v * v for v in vector) <= 1.01, "Invalid local embedding normalization.")
    return data["vectors"]


def _index(flow, client, answers):
    cache = load_index(flow)
    missing = {_vector_key(chunk): chunk for a in answers for chunk in _chunks(a) if _vector_key(chunk) not in cache}
    # Bound a click to one embedding request. Existing reviewed/indexed answers
    # remain searchable; future batches add more without re-embedding old text.
    chosen, total = {}, 0
    for key, chunk in missing.items():
        if total + len(chunk.encode()) > 40_000:
            break
        chosen[key] = chunk
        total += len(chunk.encode())
    if chosen:
        body = {"model": api.EMBEDDING_MODEL, "input": list(chosen.values()),
                "encoding_format": "float", "dimensions": api.DIMENSIONS}
        response = _call(flow, client, "embeddings", body)
        cache.update(zip(chosen, api.vectors(response, len(chosen))))
        require(len(cache) <= 4000, "Embedding cache budget exceeded.")
        atomic_text(flow.path / "ai" / "embeddings.json", encoded({"model": api.EMBEDDING_MODEL,
                    "dimensions": api.DIMENSIONS, "vectors": cache}))
    vectors = {}
    # Average chunks per answer; cosine compares answers, never skill strength.
    for answer in answer_records(flow.load()):
        chunks = [_vector_key(text) for text in _chunks(answer)]
        if not all(key in cache for key in chunks):
            continue
        vector = [sum(cache[key][i] for key in chunks) / len(chunks) for i in range(api.DIMENSIONS)]
        norm = math.sqrt(sum(v * v for v in vector))
        if norm:
            vectors[answer["id"]] = (answer, [v / norm for v in vector])
    neighbors = []
    for aid, (answer, vector) in vectors.items():
        ranked = sorted(((sum(a * b for a, b in zip(vector, other)), bid, target) for bid, (target, other) in vectors.items()
                         if bid != aid and target["experience"] != answer["experience"]), reverse=True, key=lambda item: item[0])
        for score, bid, target in ranked[:3]:
            neighbors.append({"from": aid, "to": bid, "similarity": score,
                              "from_hash": answer["fingerprint"], "to_hash": target["fingerprint"]})
    def save(state):
        state["understanding"]["neighbors"] = neighbors
    flow.update(save, "cached answer embeddings and retrieval neighbors; similarities create no profile facts")
    return len(vectors)


def run(flow, *, answer_ids=None, client=None):
    """One explicit batch: at most one interpretation and one embedding call."""
    client = client or api.OpenAI()
    with inference_lock(flow):
        require(enabled(flow.load()), "Enable AI understanding with an API spending cap first.")
        _recover(flow)
        state = flow.load()
        chosen = [a for a in pending(state) if answer_ids is None or a["id"] in answer_ids][:MAX_ANSWERS]
        result = {"proposals": [], "indexed_answers": 0, "remaining_answers": 0, "embedding_error": None}
        if chosen:
            body = request(chosen, state["understanding"]["config"]["model"])
            bid = uid("understand-")
            atomic_text(flow.path / "ai" / "batches" / bid / "input.json", encoded({
                "version": contract.VERSION, "dataset": flow.dataset, "answers": chosen}))
            def start(current):
                current["understanding"]["batches"].append({"id": bid, "at": now(), "status": "running",
                    "answer_ids": [a["id"] for a in chosen], "fingerprints": {a["id"]: a["fingerprint"] for a in chosen},
                    "call_id": None, "error": None, "proposal_ids": []})
            flow.update(start, "selected interview answers for one bounded OpenAI interpretation")
            try:
                response = _call(flow, client, "responses", body, bid)
                result["proposals"] = _stage(flow, bid, chosen, response)
            except Exception:
                def failed(current):
                    batch = next(b for b in current["understanding"]["batches"] if b["id"] == bid)
                    batch.update(status="failed", error="Analysis failed; original answers and any prior reviews are unchanged.")
                flow.update(failed, "understanding failed; no automatic retry")
                raise
        try:
            # An explicit subset never sends other answers to embeddings. The
            # catch-up action processes the next bounded group of unindexed text.
            candidates = answer_records(flow.load(), answer_ids)
            cache = load_index(flow)
            missing = [a for a in candidates if any(_vector_key(t) not in cache for t in _chunks(a))][:MAX_ANSWERS]
            result["indexed_answers"] = _index(flow, client, missing)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            result["embedding_error"] = str(exc)
        result["remaining_answers"] = len(pending(flow.load()))
        return result


def accepted(state):
    usable = statuses(state)
    proposals = {p["id"]: p for p in state["proposals"]}
    answers = {a["id"]: a for a in state.get("skillmap", skillmap.empty_map())["answers"]}
    for insight in state.get("understanding", empty())["insights"]:
        p = proposals[insight["proposal"]]
        answer = answers[insight["answer_id"]]
        # Corrected/rejected claims and withdrawn input do not retain AI links.
        if (p["status"] == "accepted" and usable.get(p["core_id"], {}).get("usable")
                and usable[answer["claim_id"]]["usable"]):
            yield {**insight, "claim_id": p["core_id"]}


def semantic_graph(state):
    nodes, edges = {}, []
    available = {n["id"] for n in skillmap.catalog(state)["nodes"]}
    for insight in accepted(state):
        if insight["experience"] not in available:
            continue
        data, cid = insight["data"], insight["claim_id"]
        target = data["skill_id"]
        if target and target not in available:
            continue
        if not target:
            target = "concept-" + digest(normalize(data["concept"]))[:20]
            node = nodes.setdefault(target, {"id": target, "kind": "concept", "label": data["concept"],
                       "category": data["facet"], "claim_ids": [], "dates": [], "origin": "reviewed answer insight"})
            node["claim_ids"].append(cid)
        edges.append({"id": insight["id"], "from": insight["experience"], "to": target,
                      "relation": data["relation"], "role": "not_used" if data["relation"] == "did_not_use" else "unknown", "claim_ids": [cid],
                      "basis": "Your reviewed answer · " + contract.RELATIONS[data["relation"]]})
    return {"nodes": list(nodes.values()), "links": edges}


def related(state, experience):
    answers = {a["id"]: a for a in answer_records(state)}
    rows, seen = [], set()
    for row in state.get("understanding", empty())["neighbors"]:
        source, target = answers.get(row["from"]), answers.get(row["to"])
        if (source and target and source["experience"] == experience and target["id"] not in seen
                and source["fingerprint"] == row["from_hash"] and target["fingerprint"] == row["to_hash"]):
            seen.add(target["id"])
            rows.append({"project": target["project"], "text": target["text"], "answer_id": target["id"],
                         "experience": target["experience"], "similarity": row["similarity"]})
    return sorted(rows, key=lambda row: row["similarity"], reverse=True)[:3]


def proposal_detail(state, proposal_id):
    insight = next((i for i in state.get("understanding", empty())["insights"] if i["proposal"] == proposal_id), None)
    if not insight:
        return ""
    data = insight["data"]
    lines = ["WHAT I LEARNED · awaiting confirmation" if next(p for p in state["proposals"] if p["id"] == proposal_id)["status"] == "proposed"
             else "ANSWER INTERPRETATION", f"Connection: {contract.RELATIONS[data['relation']]} → {data['concept']}",
             "Basis: " + ("Close paraphrase of your answer" if data["basis"] == "stated" else "Broader interpretation; confirm the scope")]
    if data["uncertainty"]:
        lines.append("Still unknown: " + data["uncertainty"])
    if data["capability"]:
        cap = data["capability"]
        lines += ["Proposed skill context: " + skillmap.ROLES[cap["role"]], skillmap.ASSISTANCE[cap["assistance"]]]
        lines.extend(f"{label}: {skillmap.DEPTH[cap['depth'][key]]}" for key, label in skillmap.DIMENSIONS.items())
    if data["follow_up"]:
        lines.append("Useful follow-up: " + data["follow_up"])
    lines.append("Accept confirms the wording and proposed connection. A correction saves your wording without inheriting this connection.")
    return "\n".join(lines) + "\n\n"


def reviewed_context(state, proposal, cid):
    insight = next((i for i in state.get("understanding", empty())["insights"] if i["proposal"] == proposal["id"]), None)
    if insight:
        node = next(n for n in skillmap.catalog(state, history=True)["nodes"] if n["id"] == insight["experience"])
        state.setdefault("knowledge", empty_knowledge())["details"].setdefault(cid, detail())["context"] = node["label"]


def summary(state):
    b = budget(state)
    count = len(pending(state))
    return (f"{'Enabled' if enabled(state) else 'Paused'} · {count} answers ready to understand\n"
            f"API usage estimate ${b['estimated']:.4f}; used/reserved ${b['committed']:.4f} of ${b['limit']:.2f} total. "
            + (f"{b['unknown_calls']} calls have unknown billing; their reservations remain." if b["unknown_calls"] else ""))
