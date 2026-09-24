"""Selected input, durable progress, preview isolation and real adapter boundaries.

The provider in this module is a synthetic fixture; no test spends API money.
"""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from foundry import capture, knowledge, memory, openai_api as api, skillmap, understanding
from foundry.storage import encoded


def fact(chunk, **changes):
    data = {"action": "add", "target_id": None, "resolves": None,
        "text": "I enjoy gardening.", "facet": "interests", "scope": "General",
        "experience_id": chunk["experience"], "entity_id": None, "concept": "Gardening",
        "relation": "enjoys", "basis": "stated", "uncertainty": "", "follow_up": None,
        "valid_from": None, "valid_until": None, "capability": None,
        "evidence": [{"chunk_id": chunk["id"], "quote": chunk["text"][:100]}]}
    # These are schema fields of the canonical entity refinement, kept explicit
    # so fixture callers can override them to exercise other entity shapes.
    data.update(entity_kind="concept", experience_label=None, experience_kind=None)
    data.update(changes)
    return data


class FakeOpenAI:
    def __init__(self, mutate=None):
        self.calls = []
        self.mutate = mutate

    def post(self, endpoint, body):
        self.calls.append((endpoint, deepcopy(body)))
        if endpoint == "embeddings":
            return {"usage": {"prompt_tokens": 10}, "data": [
                {"index": n, "embedding": [1.0] + [0.0] * (api.DIMENSIONS - 1)} for n, _ in enumerate(body["input"])]}
        snapshot = json.loads(body["input"])
        result = {"chunks": [{"chunk_id": c["id"], "facts": [fact(c)], "unrepresented": []} for c in snapshot["chunks"]]}
        if self.mutate:
            self.mutate(result)
        return {"id": "resp_synthetic", "model": body["model"], "status": "completed",
            "usage": {"input_tokens": 1000, "output_tokens": 200},
            "output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": encoded(result)}]}]}


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.flow = knowledge.Knowledge(self.path / "workspace", "synthetic")
        self.flow.initialize()
        understanding.configure(self.flow, budget_usd=5)

    def test_preview_is_read_only_and_save_preserves_selected_version(self):
        source = self.path / "selected.md"
        source.write_text("I enjoy gardening.")
        pointer = (self.flow.path / "state/current.json").read_bytes()
        plan = capture.preview(self.flow, text="I value patient learning.", paths=[source])
        self.assertEqual((self.flow.path / "state/current.json").read_bytes(), pointer)
        source.write_text("Changed after preview.")
        ids = capture.save(self.flow, plan=plan)
        self.assertEqual(len(ids), 2)
        content = [s["text"] for s in self.flow.load()["core"]["sources"]]
        self.assertIn("I enjoy gardening.", content)
        self.assertNotIn("Changed after preview.", content)
        self.assertEqual(capture.save(self.flow, plan=plan), ids)
        self.assertEqual(len(self.flow.load()["capture"]["entries"]), 2)

    def test_invalid_selection_never_saves_partial_import(self):
        text = self.path / "safe.txt"
        text.write_text("My chosen file.")
        link = self.path / "link.txt"
        link.symlink_to(text)
        for paths in ([text, link], [self.path], [text] * 9):
            with self.assertRaises((OSError, ValueError)):
                capture.preview(self.flow, paths=paths)
        self.assertNotIn("capture", self.flow.load())

    def test_partition_and_resumable_request_budget(self):
        text = ("I enjoy gardening. I like experiments with plants.\n" * 500) + "Final meaningful detail."
        ids = capture.save(self.flow, text=text)
        chunks = capture.chunks(self.flow.load())
        self.assertEqual("".join(c["text"] for c in chunks), text)
        self.assertTrue(all(len(c["text"]) <= capture.CHUNK_SIZE for c in chunks))
        client = FakeOpenAI()
        result = capture.process(self.flow, entry_ids=ids, client=client, max_calls=1)
        self.assertIsNone(result["error"])
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(result["processed_chunks"], 3)
        self.assertEqual(result["remaining_chunks"], len(chunks) - 3)
        first_chunks = json.loads(client.calls[0][1]["input"])["chunks"]
        restarted = knowledge.Knowledge(self.flow.path, "synthetic")
        capture.process(restarted, client=client, max_calls=1)
        next_chunks = json.loads(client.calls[1][1]["input"])["chunks"]
        self.assertFalse({c["id"] for c in first_chunks} & {c["id"] for c in next_chunks})
        self.assertEqual(self.flow.load()["core"]["claims"], [])

    def test_budget_and_failure_preserve_input(self):
        ids = capture.save(self.flow, text="I enjoy gardening.")
        understanding.configure(self.flow, budget_usd=.001)
        client = FakeOpenAI()
        result = capture.process(self.flow, entry_ids=ids, client=client)
        self.assertIn("cap reached", result["error"])
        self.assertEqual(client.calls, [])
        self.assertEqual(result["remaining_chunks"], 1)
        understanding.configure(self.flow, budget_usd=5)
        client.post = lambda *_: (_ for _ in ()).throw(TimeoutError("private arbitrary failure text"))
        result = capture.process(self.flow, entry_ids=ids, client=client)
        self.assertNotIn("private arbitrary", result["error"])
        self.assertGreater(understanding.budget(self.flow.load())["committed"], 0)
        self.assertEqual(capture.progress(self.flow.load())["pending_chunks"], 1)
        self.assertEqual(self.flow.load()["proposals"], [])

    def test_preview_context_changes_require_new_preview_before_request(self):
        self.flow.remember("I enjoy gardening with friends.", "interests")
        plan = capture.preview(self.flow, text="I enjoy gardening.")
        ids = capture.save(self.flow, plan=plan)
        self.flow.remember("My gardening resources include a shared greenhouse.", "resources")
        client = FakeOpenAI()
        with self.assertRaisesRegex(ValueError, "changed since"):
            capture.process(self.flow, entry_ids=ids, plan=plan, client=client)
        self.assertEqual(client.calls, [])
        result = capture.process(self.flow, entry_ids=ids, plan=capture.pending_plan(self.flow), client=client)
        self.assertIsNone(result["error"])

    def test_successful_preview_review_and_no_repeat_calls(self):
        plan = capture.preview(self.flow, text="I enjoy gardening.")
        ids = capture.save(self.flow, plan=plan)
        client = FakeOpenAI()
        result = capture.process(self.flow, entry_ids=ids, plan=plan, client=client)
        self.assertIsNone(result["error"])
        self.assertEqual(result["remaining_chunks"], 0)
        pid = result["proposals"][0]
        self.flow.review(pid, "accept")
        fresh = knowledge.Knowledge(self.flow.path, "synthetic")
        self.assertEqual(fresh.load()["proposals"][0]["status"], "accepted")
        capture.process(fresh, client=client)
        self.assertEqual(len(client.calls), 1)
        capture.withdraw(fresh, ids[0])
        cid = fresh.load()["proposals"][0]["core_id"]
        self.assertFalse(knowledge.statuses(fresh.load())[cid]["usable"])
        capture.withdraw(fresh, ids[0], restore=True)
        self.assertTrue(knowledge.statuses(fresh.load())[cid]["usable"])

    def test_interrupted_staging_recovers_saved_reply_without_charge(self):
        capture.save(self.flow, text="I enjoy gardening.")
        client = FakeOpenAI()
        with patch("foundry.memory.stage", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                capture.process(self.flow, client=client)
        cost = understanding.budget(self.flow.load())["committed"]
        result = capture.process(self.flow, client=client)
        self.assertTrue(result["recovered"])
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(understanding.budget(self.flow.load())["committed"], cost)
        self.assertEqual(len(result["proposals"]), 1)

    def test_unknown_interruption_never_resends_automatically(self):
        capture.save(self.flow, text="I enjoy gardening.")
        client = FakeOpenAI()
        client.post = lambda *_: (_ for _ in ()).throw(KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt):
            capture.process(self.flow, client=client)
        second = FakeOpenAI()
        with self.assertRaisesRegex(ValueError, "interrupted"):
            capture.process(self.flow, client=second)
        self.assertEqual(second.calls, [])
        self.assertGreater(understanding.budget(self.flow.load())["committed"], 0)

    def test_coverage_notes_and_malformed_quotes(self):
        capture.save(self.flow, text="I enjoy gardening. The rest needs more context.")
        def omission(result):
            result["chunks"][0]["unrepresented"] = [{"quote": "The rest needs more context.", "reason": "Unclear reference."}]
        capture.process(self.flow, client=FakeOpenAI(omission))
        progress = capture.progress(self.flow.load())
        self.assertEqual(progress["incomplete_chunks"], 1)
        self.assertEqual(progress["coverage_notes"][0]["reason"], "Unclear reference.")
        capture.save(self.flow, text="I garden on weekends.")
        def malformed(result):
            result["chunks"][0]["facts"][0]["evidence"][0]["quote"] = "Invented missing quote"
        before = len(self.flow.load()["proposals"])
        result = capture.process(self.flow, client=FakeOpenAI(malformed))
        self.assertIsNotNone(result["error"])
        self.assertEqual(len(self.flow.load()["proposals"]), before)

    def test_saved_answer_scope_reuses_evidence(self):
        eid = skillmap.add_experience(self.flow, "Fictional garden", "project", "I grew plants.")
        skillmap.answer(self.flow, eid, "enjoyment", "I enjoy gardening.", question="What did you enjoy?")
        answer = self.flow.load()["skillmap"]["answers"][-1]
        before = len(self.flow.load()["core"]["sources"])
        ids = capture.from_answers(self.flow, [answer["id"]])
        self.assertEqual(len(self.flow.load()["core"]["sources"]), before)
        self.assertEqual(capture.from_answers(self.flow, [answer["id"]]), ids)
        self.assertIn("What did you enjoy?", capture.pending_preview(self.flow))


if __name__ == "__main__":
    unittest.main()
