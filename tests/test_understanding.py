"""Synthetic contract, review, cost and recovery checks. No live API requests."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from foundry import knowledge, openai_api as api, skillmap, solar, understanding as ai
from foundry import understanding_contract as contract
from foundry.knowledge import Knowledge
from foundry.storage import encoded
from foundry.validation import Invalid, digest


def insight(answer):
    return {"text": f"In {answer['project']}, I enjoyed exploring geometry.", "facet": "interests",
            "relation": "enjoys", "concept": "Geometry", "skill_id": None, "basis": "stated",
            "quote": answer["text"], "capability": None, "uncertainty": "",
            "follow_up": "Which geometry concept can you explain without help?"}


class FakeOpenAI:
    def __init__(self, mutate=None):
        self.calls = []
        self.mutate = mutate

    def post(self, endpoint, body):
        self.calls.append((endpoint, deepcopy(body)))
        if endpoint == "embeddings":
            return {"model": api.EMBEDDING_MODEL, "usage": {"prompt_tokens": 100},
                    "data": [{"index": n, "embedding": [1.0] + [0.0] * (api.DIMENSIONS - 1)}
                             for n, _ in enumerate(body["input"])]}
        answers = json.loads(body["input"])["answers"]
        result = {"answers": [{"answer_id": a["id"], "insights": [insight(a)]} for a in answers]}
        if self.mutate:
            self.mutate(result)
        return {"id": "resp_synthetic", "model": body["model"], "status": "completed",
                "usage": {"input_tokens": 1000, "output_tokens": 200},
                "output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": encoded(result)}]}]}


class UnderstandingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.flow = Knowledge(Path(self.temp.name) / "workspace", "synthetic")
        self.flow.initialize()
        self.eid = skillmap.add_experience(self.flow, "Fictional geometry", "project", "I explored a small renderer.")
        self.sid = skillmap.add_skill(self.flow, self.eid, "Python", "language", "I used a plotting example.")
        state = skillmap.answer(self.flow, self.eid, "enjoyment", "I enjoyed working through the geometry.",
                                question="Which part was satisfying, and why?")
        self.aid = state["skillmap"]["answers"][-1]["id"]
        ai.configure(self.flow, budget_usd=1)

    def test_scope_structure_review_and_restart(self):
        self.flow.remember("PRIVATE UNRELATED CONTEXT", "context")
        client = FakeOpenAI()
        result = ai.run(self.flow, client=client)
        self.assertEqual(len(result["proposals"]), 1)
        self.assertEqual([c[0] for c in client.calls], ["responses", "embeddings"])
        request = client.calls[0][1]
        self.assertFalse(request["store"])
        self.assertEqual(request["tools"], [])
        self.assertNotIn("PRIVATE UNRELATED CONTEXT", encoded(client.calls))
        self.assertNotIn("sources", json.loads(request["input"])["answers"][0])
        self.assertTrue(request["text"]["format"]["strict"])
        self.assertEqual(ai.semantic_graph(self.flow.load())["links"], [])
        self.assertTrue(all(c["facet"] != "demonstrated_skills" for c in self.flow.load()["core"]["claims"]))
        pid = result["proposals"][0]
        self.flow.review(pid, "accept")
        state = Knowledge(self.flow.path, "synthetic").load()
        self.assertEqual(len(state["proposals"][0]["claim"]["sources"]), 1, "review must not mutate the original proposal evidence")
        links = ai.semantic_graph(state)["links"]
        self.assertEqual(links[0]["relation"], "enjoys")
        self.assertEqual(links[0]["from"], self.eid)
        self.assertIn("Fictional geometry", state["knowledge"]["details"][links[0]["claim_ids"][0]]["context"])
        graph = knowledge.build_graph(state)
        ids = {n["id"] for n in graph["nodes"]}
        self.assertTrue(all(e["from"] in ids and e["to"] in ids for e in graph["edges"]))
        self.assertIn("Geometry", knowledge.profile_text(state))
        self.assertIn("enjoys", encoded(solar.payload(state)))
        self.assertTrue(any(q.get("follow_up_of") for q in skillmap.questions(state, self.eid)))
        ai.run(self.flow, client=client)
        self.assertEqual(len(client.calls), 2, "unchanged inputs must reuse both interpretation and embeddings")

    def test_quote_ids_and_output_budgets_rejected_atomically(self):
        for mutate in (
            lambda r: r["answers"][0]["insights"][0].update(quote="I invented this quote."),
            lambda r: r["answers"][0].update(answer_id="wrong-answer"),
            lambda r: r["answers"][0]["insights"][0].update(skill_id="wrong-skill"),
            lambda r: r["answers"][0]["insights"].append(deepcopy(r["answers"][0]["insights"][0])),
            lambda r: r["answers"][0]["insights"][0].update(facet="demonstrated_skills"),
            lambda r: r["answers"][0]["insights"][0].update(basis="inferred", uncertainty=""),
        ):
            with self.subTest(mutate=mutate):
                before = deepcopy(self.flow.load()["core"])
                client = FakeOpenAI(mutate)
                with self.assertRaises((Invalid, ValueError)):
                    ai.run(self.flow, client=client)
                self.assertEqual(self.flow.load()["core"], before)
                self.assertEqual(self.flow.load()["proposals"], [])
                self.assertEqual(len(client.calls), 1)

    def test_refusal_incomplete_duplicate_json_and_invalid_embeddings(self):
        for response in ({"status": "incomplete"}, {"status": "completed", "output": [{"type": "message", "role": "assistant",
                          "content": [{"type": "refusal", "refusal": "No"}]}]}):
            with self.assertRaises(Invalid):
                api.structured_result(response)
        for raw in ('{"a":1,"a":2}', '{"a":NaN}', '[] trailing'):
            with self.assertRaises(Invalid):
                api.parse_json(raw)
        for vector in ([0.0] * api.DIMENSIONS, [float("nan")] * api.DIMENSIONS, [1.0, 0]):
            with self.assertRaises(Invalid):
                api.vectors({"data": [{"index": 0, "embedding": vector}]}, 1)

    def test_budget_precedes_network_and_uncertain_charge_survives_restart(self):
        ai.configure(self.flow, budget_usd=.001)
        client = FakeOpenAI()
        with self.assertRaisesRegex(ValueError, "cap reached"):
            ai.run(self.flow, client=client)
        self.assertEqual(client.calls, [])
        ai.configure(self.flow, budget_usd=1)
        client.post = lambda *args: (_ for _ in ()).throw(TimeoutError("synthetic timeout"))
        with self.assertRaises(TimeoutError):
            ai.run(self.flow, client=client)
        state = Knowledge(self.flow.path, "synthetic").load()
        self.assertGreater(ai.budget(state)["committed"], 0)
        self.assertEqual(ai.budget(state)["unknown_calls"], 1)
        self.assertEqual(len(state["skillmap"]["answers"]), 1)
        self.assertEqual(state["proposals"], [])
        with self.assertRaisesRegex(ValueError, "already used"):
            ai.configure(self.flow, budget_usd=.001)
        ai.pause(self.flow)
        with self.assertRaisesRegex(ValueError, "Enable"):
            ai.run(self.flow, client=FakeOpenAI())

    def test_embedding_failure_preserves_suggestions_and_does_not_repeat_extraction(self):
        client = FakeOpenAI()
        original = client.post
        def post(endpoint, body):
            if endpoint == "embeddings":
                raise ValueError("Synthetic embeddings failure")
            return original(endpoint, body)
        client.post = post
        result = ai.run(self.flow, client=client)
        self.assertEqual(len(result["proposals"]), 1)
        self.assertIn("failure", result["embedding_error"])
        retry = FakeOpenAI()
        ai.run(self.flow, client=retry)
        self.assertEqual([c[0] for c in retry.calls], ["embeddings"])
        self.assertEqual(len(self.flow.load()["proposals"]), 1)

    def test_received_reply_recovers_without_repeated_paid_call(self):
        client = FakeOpenAI()
        with patch("foundry.understanding._stage", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                ai.run(self.flow, client=client)
        self.assertEqual(self.flow.load()["understanding"]["batches"][0]["status"], "running")
        retry = FakeOpenAI()
        ai.run(Knowledge(self.flow.path, "synthetic"), client=retry)
        self.assertEqual([c[0] for c in retry.calls], ["embeddings"])
        self.assertEqual(len(self.flow.load()["proposals"]), 1)

    def test_project_uncertainty_and_local_revalidation_of_saved_reply(self):
        def uncertain(result):
            result["answers"][0]["insights"][0].update(
                relation="uncertain_about", facet="previous_projects", concept="Current contribution",
                text="The contribution to this fictional project needs clarification.", basis="inferred",
                uncertainty="The original detailed question was not available.")
        client = FakeOpenAI(uncertain)
        with patch("foundry.understanding_contract.validate_result", side_effect=Invalid("Synthetic restrictive rule")):
            with self.assertRaises(Invalid):
                ai.run(self.flow, client=client)
        batch = self.flow.load()["understanding"]["batches"][0]
        with patch("foundry.openai_api.OpenAI.post", side_effect=AssertionError("No new API request allowed")):
            self.assertEqual(len(ai.reprocess(self.flow, batch["id"])), 1)
            self.assertEqual(len(ai.reprocess(self.flow, batch["id"])), 1)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(len(self.flow.load()["proposals"]), 1)

    def test_interrupted_unknown_call_is_not_automatically_retried(self):
        client = FakeOpenAI()
        client.post = lambda *args: (_ for _ in ()).throw(KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt):
            ai.run(self.flow, client=client)
        retry = FakeOpenAI()
        with self.assertRaisesRegex(ValueError, "earlier analysis was interrupted"):
            ai.run(self.flow, client=retry)
        self.assertEqual(retry.calls, [])
        self.assertGreater(ai.budget(self.flow.load())["committed"], 0)

    def test_withdrawn_input_and_corrections_remove_links_and_stale_neighbors(self):
        eid2 = skillmap.add_experience(self.flow, "Fictional curves", "research", "I plotted curves.")
        skillmap.answer(self.flow, eid2, "enjoyment", "I enjoyed drawing geometry.")
        result = ai.run(self.flow, client=FakeOpenAI())
        self.assertTrue(ai.related(self.flow.load(), self.eid))
        first = result["proposals"][0]
        self.flow.review(first, "accept")
        self.assertEqual(len(ai.semantic_graph(self.flow.load())["links"]), 1)
        self.flow.review(first, "correct", "I only enjoyed one short exercise.")
        self.assertEqual(ai.semantic_graph(self.flow.load())["links"], [])
        self.flow.review(result["proposals"][1], "accept", acknowledge_matches=True)
        answer = self.flow.load()["skillmap"]["answers"][-1]
        self.flow.amend(answer["claim_id"], "exclude", "That answer needs replacing.")
        self.assertEqual(ai.semantic_graph(self.flow.load())["links"], [])
        self.assertEqual(ai.related(self.flow.load(), self.eid), [])
        proposal = self.flow.load()["proposals"][1]
        self.assertEqual(knowledge.statuses(self.flow.load())[proposal["core_id"]]["status"], "source_withdrawn")
        self.assertFalse(any(n["id"] == "claim:" + proposal["core_id"] for n in knowledge.build_graph(self.flow.load())["nodes"]))

    def test_concurrent_edit_is_preserved_and_withdrawn_answer_not_staged(self):
        client = FakeOpenAI()
        original = client.post
        def post(endpoint, body):
            self.flow.remember("A change while the network request was running.", "context")
            aid = self.flow.load()["skillmap"]["answers"][0]["claim_id"]
            self.flow.amend(aid, "exclude", "Please do not use this answer.")
            return original(endpoint, body)
        client.post = post
        with self.assertRaisesRegex(ValueError, "changed or was excluded"):
            ai.run(self.flow, client=client)
        self.assertEqual(self.flow.load()["proposals"], [])
        self.assertTrue(any(c["text"].startswith("A change") for c in self.flow.load()["core"]["claims"]))

    def test_accepted_capability_is_scoped_and_manual_assessment_takes_precedence(self):
        self.flow.amend(self.flow.load()["skillmap"]["answers"][0]["claim_id"], "exclude", "Replacing with a contribution example.")
        skillmap.answer(self.flow, self.eid, "contribution", "I adapted a Python plotting example with AI help.")
        def capability(result):
            result["answers"][0]["insights"][0].update(
                text="In Fictional geometry, I adapted a Python plotting example with AI help.",
                relation="used_skill", facet="claimed_skills", concept="Python", skill_id=self.sid,
                capability={"role": "supporting", "assistance": "ai_assisted",
                            "depth": {d: "with_help" if d == "adapt" else "unknown" for d in skillmap.DIMENSIONS}})
        pid = ai.run(self.flow, client=FakeOpenAI(capability))["proposals"][0]
        self.assertNotIn("assessment", skillmap.catalog(self.flow.load())["links"][0])
        self.flow.review(pid, "accept")
        assessed = skillmap.catalog(self.flow.load())["links"][0]["assessment"]
        self.assertEqual(assessed["depth"]["design"], "unknown")
        skillmap.assess(self.flow, self.eid, self.sid, role="incidental", assistance="documentation",
                        depth={d: "unknown" for d in skillmap.DIMENSIONS}, text="Only copied a plotting snippet.")
        self.assertEqual(skillmap.catalog(self.flow.load())["links"][0]["assessment"]["assistance"], "documentation")

    def test_selected_subset_does_not_embed_other_answers(self):
        state = skillmap.answer(self.flow, self.eid, "friction", "UNSELECTED ANSWER")
        client = FakeOpenAI()
        ai.run(self.flow, answer_ids={self.aid}, client=client)
        self.assertNotIn("UNSELECTED ANSWER", encoded(client.calls))
        self.assertEqual(len(ai.pending(self.flow.load())), 1)

    def test_embedding_cache_interruption_reuses_saved_response(self):
        from foundry.storage import atomic_text
        def interrupt(path, text):
            if Path(path).name == "embeddings.json":
                raise OSError("Synthetic interruption while writing cache")
            return atomic_text(path, text)
        first = FakeOpenAI()
        with patch("foundry.understanding.atomic_text", side_effect=interrupt):
            result = ai.run(self.flow, client=first)
        self.assertIsNotNone(result["embedding_error"])
        self.assertEqual(len(first.calls), 2)
        retry = FakeOpenAI()
        ai.run(self.flow, client=retry)
        self.assertEqual(retry.calls, [])
        self.assertEqual(len(ai.load_index(self.flow)), 1)

    def test_inference_lock_rejects_second_process_without_blocking_capture(self):
        with ai.inference_lock(self.flow):
            with self.assertRaisesRegex(ValueError, "already running"):
                ai.run(self.flow, client=FakeOpenAI())
            self.flow.remember("Capture remains available while inference is running.", "context")
        self.assertTrue(any(c["text"].startswith("Capture remains") for c in self.flow.load()["core"]["claims"]))

    def test_explicit_nonuse_weakens_only_reviewed_project_connection(self):
        self.flow.amend(self.flow.load()["skillmap"]["answers"][0]["claim_id"], "exclude", "Use the contribution answer instead.")
        skillmap.answer(self.flow, self.eid, "contribution", "I did not personally use Python in this exercise.")
        def nonuse(result):
            result["answers"][0]["insights"][0].update(
                text="In Fictional geometry, I did not personally use Python.",
                relation="did_not_use", facet="claimed_skills", concept="Python", skill_id=self.sid,
                capability={"role": "not_used", "assistance": "unknown", "depth": {d: "unknown" for d in skillmap.DIMENSIONS}})
        pid = ai.run(self.flow, client=FakeOpenAI(nonuse))["proposals"][0]
        self.assertEqual(skillmap.catalog(self.flow.load())["links"][0]["role"], "unknown")
        self.flow.review(pid, "accept")
        link = skillmap.catalog(self.flow.load())["links"][0]
        self.assertEqual(link["role"], "not_used")
        self.assertTrue(all(v == "unknown" for v in link["assessment"]["depth"].values()))
        self.assertTrue(any(n["id"] == self.sid for n in skillmap.catalog(self.flow.load())["nodes"]))

    def test_key_priority_and_provider_errors_never_expose_secret(self):
        with patch.dict("os.environ", {"OPENM_AI_API_KEY": "synthetic-secret-a", "OPENAI_API_KEY": "synthetic-secret-b"}):
            self.assertEqual(api.key_name(), "OPENM_AI_API_KEY")
            with patch("foundry.openai_api.build_opener") as opener:
                opener.return_value.open.side_effect = HTTPError(api.BASE_URL, 401, "synthetic-secret-a", {}, None)
                with self.assertRaisesRegex(Invalid, "did not accept") as error:
                    api.OpenAI().post("responses", {"model": api.DEFAULT_MODEL})
                self.assertNotIn("synthetic-secret", str(error.exception))
                called = opener.return_value.open.call_args.args[0]
                self.assertEqual(called.full_url, api.BASE_URL + "responses")
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(ValueError, "Set OPENM_AI_API_KEY"):
                api.OpenAI().post("responses", {})
        with patch.dict("os.environ", {"OPENAI_API_KEY": "synthetic-fallback"}, clear=True):
            self.assertEqual(api.key_name(), "OPENAI_API_KEY")


if __name__ == "__main__":
    unittest.main()
