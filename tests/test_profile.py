"""Synthetic profile projections: evidence, context, omissions and local search."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from foundry import capture, profile, skillmap, understanding
from foundry.knowledge import Knowledge
from foundry.storage import encoded
from foundry.validation import digest, read_json
from tests.test_understanding import FakeOpenAI
from tests.workflow_fixtures import import_proposal


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.flow = Knowledge(self.root / "workspace", "synthetic")
        self.flow.initialize()

    def test_overview_retains_exact_words_and_sources_without_mutating_state(self):
        text = "I prefer a quiet room when sketching imaginary machines."
        cid = self.flow.remember(text, "working_style", context="Evening sketches")
        state = self.flow.load()
        before = deepcopy(state)
        view = profile.overview(state)
        section = next(s for s in view["sections"] if s["id"] == "working")
        item = section["items"][0]
        self.assertEqual(item["id"], cid)
        self.assertEqual(item["text"], text)
        self.assertEqual(item["attribution"], "Your words")
        self.assertEqual(item["context"], "Evening sketches")
        self.assertEqual(item["sources"][0]["quote"], text)
        self.assertIn(cid, profile.render(state, "quiet"))
        self.assertNotIn(cid, profile.render(state))
        self.assertEqual(state, before)

    def test_withheld_claims_do_not_leak_into_profile_or_search(self):
        self.flow.remember("VISIBLE graphite sketches", "interests")
        hidden = self.flow.remember("HIDDEN excluded work", "preferences")
        self.flow.amend(hidden, "exclude", "This statement was a fictional example.")
        self.flow.remember("HIDDEN expired room access", "resources", valid_until="2000-01-01")
        self.flow.remember("HIDDEN future project", "active_projects", valid_from="2999-01-01")
        a = self.flow.remember("HIDDEN conflicting choice A", "working_style")
        b = self.flow.remember("HIDDEN conflicting choice B", "working_style")
        self.flow.connect(a, "conflicts_with", b, "The contexts have not been distinguished.")
        state = self.flow.load()
        view = profile.overview(state, "HIDDEN")
        self.assertEqual(view["result_count"], 0)
        self.assertEqual(view["counts"]["reviewed"], 1)
        self.assertEqual(view["counts"]["withheld"], {"excluded": 1, "expired": 1, "upcoming": 1, "contradicted": 2})
        rendered = profile.render(state)
        self.assertNotIn("HIDDEN", rendered)
        self.assertIn("VISIBLE", rendered)

    def test_default_is_bounded_and_search_can_retrieve_omitted_evidence(self):
        for index in range(profile.SECTION_LIMIT + 3):
            self.flow.remember(f"I enjoy imaginary subject {index}.", "interests")
        state = self.flow.load()
        section = next(s for s in profile.overview(state)["sections"] if s["id"] == "interests")
        self.assertEqual(section["total"], profile.SECTION_LIMIT + 3)
        self.assertEqual(section["omitted"], 3)
        self.assertNotIn("imaginary subject 0", profile.render(state))
        self.assertIn("3 more available through search", profile.render(state))
        matches = profile.overview(state, "subject 0")
        self.assertEqual(matches["result_count"], 1)
        self.assertEqual(matches["results"][0]["text"], "I enjoy imaginary subject 0.")
        self.assertIn("Evidence", profile.render(state, "subject 0"))

    def test_search_bounds_output_and_matches_source_quote_and_identifier(self):
        _, pid = import_proposal(self.flow, self.root)
        self.flow.review(pid, "accept")
        claim = self.flow.load()["core"]["claims"][0]
        quote = claim["sources"][0]["quote"]
        self.assertEqual(profile.overview(self.flow.load(), quote)["result_count"], 1)
        self.assertEqual(profile.overview(self.flow.load(), claim["id"])["result_count"], 1)
        for index in range(profile.SEARCH_LIMIT + 2):
            self.flow.remember(f"Searchable activity {index}", "interests")
        view = profile.overview(self.flow.load(), "Searchable")
        self.assertEqual(view["result_count"], profile.SEARCH_LIMIT + 2)
        self.assertEqual(len(view["results"]), profile.SEARCH_LIMIT)
        self.assertEqual(view["results_omitted"], 2)
        self.assertEqual(profile.overview(self.flow.load(), "!!!")["results"], [])

    def test_search_distinguishes_cpp_from_statement_identifier_prefix(self):
        self.flow.remember("I used C++ while following a graphics tutorial.", "claimed_skills")
        self.flow.remember("I enjoy sketching geometric patterns.", "interests")
        view = profile.overview(self.flow.load(), "C++")
        self.assertEqual(view["result_count"], 1)
        self.assertIn("C++", view["results"][0]["text"])

    def test_skills_remain_scoped_and_unknown_depth_is_visible(self):
        project = skillmap.add_experience(self.flow, "Fictional terrarium", "project", "I started a terrarium log.")
        python = skillmap.add_skill(self.flow, project, "python", "language", "I adapted a Python data example.")
        rust = skillmap.add_skill(self.flow, project, "rust", "language", "I tried a Rust tutorial.")
        skillmap.assess(self.flow, project, python, role="supporting", assistance="ai_assisted",
            depth={"explain": "with_help", "adapt": "independent", "design": "unknown", "debug": "unknown"},
            text="I can adapt the data conversion but needed AI to explain the parser.")
        view = profile.overview(self.flow.load())
        section = next(s for s in view["sections"] if s["id"] == "skills")
        self.assertEqual({i["id"] for i in section["items"]}, {python, rust})
        output = profile.render(self.flow.load())
        self.assertIn("Fictional terrarium", output)
        self.assertIn("Design a solution: not assessed", output)
        self.assertIn("AI helped; I directed the work", output)
        self.assertIn("Depth and independence not assessed", output)
        self.assertIn("current activity unconfirmed", output)

    def test_ai_provenance_keeps_interpretation_and_project_scope_after_acceptance(self):
        project = skillmap.add_experience(self.flow, "Fictional geometry", "project", "I tried a renderer.")
        skillmap.answer(self.flow, project, "enjoyment", "I enjoyed exploring geometry in this renderer.")
        understanding.configure(self.flow, budget_usd=1)
        def inferred(result):
            row = result["answers"][0]["insights"][0]
            row.update(basis="inferred", uncertainty="This only describes one project.")
        result = understanding.run(self.flow, client=FakeOpenAI(inferred))
        self.flow.review(result["proposals"][0], "accept")
        state = self.flow.load()
        cid = state["proposals"][0]["core_id"]
        row = profile.overview(state, cid)["results"][0]
        self.assertEqual(row["attribution"], "Reviewed AI interpretation")
        self.assertEqual(row["experiences"], ["Fictional geometry"])
        self.assertIn("This only describes one project.", profile.render(state))
        answer = state["skillmap"]["answers"][0]
        self.flow.amend(answer["claim_id"], "exclude", "Withdraw this example.")
        self.assertEqual(profile.overview(self.flow.load(), cid)["result_count"], 0)

    def test_breadth_questions_respect_existing_and_pending_evidence(self):
        self.assertEqual(profile.overview(self.flow.load())["next_question"]["facet"], "context")
        self.flow.remember("I have two free evenings most weeks.", "context")
        _, pid = import_proposal(self.flow, self.root)
        self.assertEqual(self.flow.load()["proposals"][0]["id"], pid)
        self.assertEqual(profile.overview(self.flow.load())["next_question"]["facet"], "values")
        self.flow.remember("I value keeping promises to close friends.", "values")
        self.assertEqual(profile.overview(self.flow.load())["next_question"]["facet"], "goals")
        self.assertNotIn("completeness", profile.render(self.flow.load()).casefold())

    def test_project_interests_do_not_become_global_traits_and_gaps_are_grounded(self):
        project = skillmap.add_experience(self.flow, "Fictional geometry", "project", "I tried a renderer.")
        skillmap.answer(self.flow, project, "enjoyment", "I enjoyed geometry in this particular project.")
        self.flow.remember("I have time on Sundays.", "context")
        understanding.configure(self.flow, budget_usd=1)
        result = understanding.run(self.flow, client=FakeOpenAI())
        self.flow.review(result["proposals"][0], "accept")
        view = profile.overview(self.flow.load())
        self.assertEqual(view["next_question"]["facet"], "interests")
        self.assertIn("Outside your projects", view["next_question"]["question"])
        interest = next(s for s in view["sections"] if s["id"] == "interests")["items"][0]
        self.assertEqual(interest["experiences"], ["Fictional geometry"])

    def test_markdown_from_inputs_remains_readable_text(self):
        text = "# My label\n[Open](https://example.invalid) <script>ignored</script>"
        cid = self.flow.remember(text, "interests")
        result = profile.render(self.flow.load(), cid)
        self.assertNotIn("[Open](", result)
        self.assertNotIn("<script>", result)
        self.assertIn("\\[Open\\]", result)
        self.assertEqual(profile.overview(self.flow.load(), cid)["results"][0]["text"], text)

    def test_portable_export_includes_brief_and_full_evidence_with_manifest(self):
        original = self.flow.remember("I enjoy drawing fictional landscapes.", "interests")
        self.flow.remember("I prefer learning through worked examples.", "learning_style")
        state = self.flow.load()
        target = self.flow.export_profile()
        manifest = read_json(target / "manifest.json")
        self.assertEqual(set(manifest["files"]), {"profile.md", "about-me.md", "graph.json"})
        self.assertEqual((target / "about-me.md").read_text(), profile.render(state))
        for name, expected in manifest["files"].items():
            self.assertEqual(digest((target / name).read_text()), expected)
        self.assertIn("claim:" + original, {n["id"] for n in read_json(target / "graph.json")["nodes"]})
        self.assertEqual(self.flow.load(), state)

    def test_selected_input_coverage_and_support_evidence_survive_review_and_withdrawal(self):
        class SelectedTextClient:
            def __init__(client, *, action="add", target=None):
                client.action, client.target = action, target

            def post(client, endpoint, body):
                chunks = json.loads(body["input"])["chunks"]
                rows = []
                for chunk in chunks:
                    fact = {"action": client.action, "target_id": client.target, "resolves": None,
                        "text": "I enjoy hiking.", "facet": "interests", "scope": "General",
                        "experience_id": None, "experience_label": None, "experience_kind": None,
                        "entity_id": None, "entity_kind": "concept", "concept": "Hiking",
                        "relation": "enjoys", "basis": "stated", "uncertainty": "", "follow_up": None,
                        "valid_from": None, "valid_until": None, "capability": None,
                        "evidence": [{"chunk_id": chunk["id"], "quote": "I enjoy hiking." if client.action == "add" else chunk["text"]}]}
                    notes = [{"quote": "I can sometimes borrow a canoe.", "reason": "Availability needs clarification."}] if client.action == "add" else []
                    rows.append({"chunk_id": chunk["id"], "facts": [fact], "unrepresented": notes})
                return {"id": "synthetic-selected-profile", "model": body["model"], "status": "completed",
                    "usage": {"input_tokens": 100, "output_tokens": 100},
                    "output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": encoded({"chunks": rows})}]}]}

        understanding.configure(self.flow, budget_usd=1)
        entry = capture.save(self.flow, text="I enjoy hiking. I can sometimes borrow a canoe.")[0]
        result = capture.process(self.flow, client=SelectedTextClient(), max_calls=1)
        self.assertIsNone(result["error"])
        self.flow.review(result["proposals"][0], "accept")
        state = self.flow.load()
        cid = state["proposals"][0]["core_id"]
        output = profile.render(state)
        self.assertIn("borrow a canoe", output)
        self.assertIn("1 section(s)", output)
        self.assertIn("may miss other details", output)
        self.assertEqual(profile.overview(state, cid)["results"][0]["attribution"], "Reviewed AI extraction")
        second = capture.save(self.flow, text="Hiking with friends is something I enjoy.")[0]
        support = capture.process(self.flow, client=SelectedTextClient(action="support", target=cid), max_calls=1)
        self.assertIsNone(support["error"])
        self.flow.review(support["proposals"][0], "accept")
        state = self.flow.load()
        self.assertEqual(profile.overview(state)["counts"]["reviewed"], 1)
        evidence = profile.overview(state, cid)["results"][0]["sources"]
        self.assertIn("Hiking with friends is something I enjoy.", [source["quote"] for source in evidence])
        capture.withdraw(self.flow, second)
        evidence = profile.overview(self.flow.load(), cid)["results"][0]["sources"]
        self.assertNotIn("Hiking with friends is something I enjoy.", [source["quote"] for source in evidence])
        capture.withdraw(self.flow, entry)
        self.assertNotIn("canoe", profile.render(self.flow.load()))
        self.assertEqual(profile.overview(self.flow.load())["counts"]["reviewed"], 0)


if __name__ == "__main__":
    unittest.main()
