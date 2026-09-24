"""Synthetic graph behavior, auditability and failure boundaries."""

from copy import deepcopy
from datetime import date
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from foundry import knowledge
from foundry.knowledge import Knowledge
from foundry.storage import Store, encoded
from foundry.validation import Invalid, digest, read_json
from foundry.workflow import Workflow, selected_file, validate_workspace
from tests.workflow_fixtures import import_proposal, proposed, response, supply


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.flow = Knowledge(self.root / "workspace", "synthetic")
        self.flow.initialize()

    def test_existing_workspace_is_read_without_migration_or_idea_loss(self):
        _, pid = import_proposal(self.flow, self.root)
        self.flow.review(pid, "accept")
        original = self.flow.load()
        pointer = (self.flow.path / "state/current.json").read_bytes()
        reopened = Knowledge(self.flow.path, "synthetic")
        self.assertEqual(reopened.load(), original)
        self.assertEqual(pointer, (self.flow.path / "state/current.json").read_bytes())
        self.assertEqual(len([n for n in knowledge.build_graph(original)["nodes"] if n["type"] == "statement"]), 1)

    def test_direct_answers_preserve_words_context_dates_and_deduplicate(self):
        text = "  I use a fictional sketching tool.\nExamples matter.\n"
        cid = self.flow.remember(text, "claimed_skills", context="Home projects", valid_from="2026-01-01")
        again = self.flow.remember(text, "claimed_skills", context="Home projects", valid_from="2026-01-01")
        self.assertEqual(cid, again)
        state = Knowledge(self.flow.path, "synthetic").load()
        self.assertEqual(len(state["core"]["claims"]), 1)
        self.assertEqual(state["core"]["claims"][0]["text"], text)
        self.assertEqual(state["core"]["sources"][0]["text"], text)
        self.assertEqual(state["knowledge"]["details"][cid]["context"], "Home projects")
        self.assertNotEqual(knowledge.next_question(state)[0], "claimed_skills")

    def test_invalid_dates_or_demonstrated_skill_do_not_commit(self):
        before = self.flow.load()
        for options in ({"valid_from": "2026-99-01"}, {"valid_from": "2027-01-01", "valid_until": "2026-01-01"}):
            with self.assertRaises(ValueError):
                self.flow.remember("Synthetic skill", "claimed_skills", **options)
        with self.assertRaises(Invalid):
            self.flow.remember("Synthetic mastery", "demonstrated_skills")
        self.assertEqual(self.flow.load(), before)

    def test_dates_conflicts_resolution_and_exports(self):
        a = self.flow.remember("I prefer solo work.", "working_style")
        b = self.flow.remember("I prefer paired work.", "working_style")
        link = self.flow.connect(a, "conflicts_with", b, "These need more context before using either.")
        state = self.flow.load()
        self.assertEqual(knowledge.statuses(state)[a]["status"], "contradicted")
        self.assertEqual(len(knowledge.build_graph(state)["nodes"]), 1)
        self.flow.retire_link(link)
        self.assertTrue(knowledge.statuses(self.flow.load())[a]["usable"])
        expired = self.flow.remember("I have a temporary workshop.", "resources", valid_until="2026-01-01")
        future = self.flow.remember("I will start a course.", "goals", valid_from="2027-01-01")
        statuses = knowledge.statuses(self.flow.load(), date(2026, 9, 23))
        self.assertEqual(statuses[expired]["status"], "expired")
        self.assertEqual(statuses[future]["status"], "upcoming")

    def test_expired_conflicting_entry_does_not_block_current(self):
        a = self.flow.remember("First preference", "preferences")
        b = self.flow.remember("Second preference", "preferences", valid_until="2099-01-01")
        self.flow.connect(a, "conflicts_with", b, "Conflicting preferences until expiry")
        status = knowledge.statuses(self.flow.load(), date(2100, 1, 1))
        self.assertTrue(status[a]["usable"])
        self.assertEqual(status[b]["status"], "expired")

    def test_connections_are_typed_attributed_and_reference_existing_nodes(self):
        skill = self.flow.remember("I can draft simple fixtures.", "claimed_skills")
        goal = self.flow.remember("I want to build a small shelf.", "goals")
        lid = self.flow.connect(goal, "uses_skill", skill, "Drafting helps me plan the shelf joints.")
        self.assertEqual(lid, self.flow.connect(goal, "uses_skill", skill, "Drafting helps me plan the shelf joints."))
        state = self.flow.load()
        graph = knowledge.build_graph(state)
        node_ids = {n["id"] for n in graph["nodes"]}
        self.assertTrue(all(e["from"] in node_ids and e["to"] in node_ids for e in graph["edges"]))
        link = state["knowledge"]["links"][0]
        self.assertEqual(link["sources"][0]["quote"], link["reason"])
        for target in (goal, "missing"):
            with self.assertRaises(Invalid):
                self.flow.connect(goal, "uses_skill", target, "Invalid reference")
        with self.assertRaises(Invalid):
            self.flow.connect(goal, "magic", skill, "Unknown relation")

    def test_edit_keeps_history_does_not_transfer_connections_and_survives_restart(self):
        a = self.flow.remember("I enjoy small group work.", "preferences")
        b = self.flow.remember("I want a team project.", "goals")
        self.flow.connect(a, "supports", b, "Small group work supports this goal.")
        self.flow.amend(a, "correct", "I prefer solo work currently.", facet="working_style", context="Evenings")
        state = Knowledge(self.flow.path, "synthetic").load()
        self.assertEqual(state["core"]["claims"][0]["status"], "excluded")
        self.assertIn("I enjoy small group work.", knowledge.claim_text(state, a))
        self.assertFalse(any(e["relation"] == "supports" for e in knowledge.build_graph(state)["edges"]))
        self.assertTrue(any(e["relation"] == "supports" for e in knowledge.build_graph(state, include_history=True)["edges"]))
        self.assertIn("I prefer solo work currently.", knowledge.profile_text(state))

    def test_graph_correction_cannot_be_undone_by_accepting_old_proposal(self):
        _, pid = import_proposal(self.flow, self.root)
        self.flow.review(pid, "accept")
        cid = self.flow.load()["proposals"][0]["core_id"]
        self.flow.amend(cid, "correct", "This was an example, not a real interest.")
        with self.assertRaises(Invalid):
            self.flow.review(pid, "accept")
        self.assertEqual(self.flow.load()["proposals"][0]["status"], "corrected")

    def test_pending_and_rejected_claims_do_not_enter_current_graph(self):
        _, pid = import_proposal(self.flow, self.root)
        state = self.flow.load()
        self.assertEqual(len(knowledge.build_graph(state)["nodes"]), 1)
        self.assertNotEqual(knowledge.next_question(state)[0], "interests")
        self.flow.review(pid, "reject", "The quoted passage does not say this.")
        self.assertEqual(len(knowledge.build_graph(self.flow.load())["nodes"]), 1)

    def test_export_is_a_consistent_portable_snapshot_with_cited_passages_only(self):
        sid, pid = import_proposal(self.flow, self.root)
        self.flow.review(pid, "correct", "I collect fictional sound references.")
        output = self.flow.export_profile()
        manifest = read_json(output / "manifest.json")
        for name, expected in manifest["files"].items():
            self.assertEqual(digest((output / name).read_text()), expected)
        graph = read_json(output / "graph.json")
        self.assertEqual(graph["dataset"], "synthetic")
        self.assertNotIn(sid, {n["id"].removeprefix("source:") for n in graph["nodes"]})
        self.assertIn("fictional sound references", (output / "profile.md").read_text())
        result = subprocess.run([sys.executable, "-B", "-m", "foundry", "graph", "--workspace", str(self.flow.path),
                                 "--dataset", "synthetic"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("fictional sound references", result.stdout)

    def test_interrupted_mutation_and_export_leave_previous_state_intact(self):
        self.flow.remember("Synthetic starting point", "context")
        before = self.flow.load()
        from foundry.storage import atomic_text
        def interrupt(path, content):
            if Path(path).name == "current.json":
                raise OSError("interrupted")
            return atomic_text(path, content)
        with patch("foundry.storage.atomic_text", side_effect=interrupt):
            with self.assertRaises(OSError):
                self.flow.remember("New detail", "context")
        self.assertEqual(before, self.flow.load())
        complete = self.flow.export_profile()
        def interrupt_export(path, content):
            if Path(path).name == "graph.json":
                raise OSError("interrupted")
            return atomic_text(path, content)
        with patch("foundry.knowledge.atomic_text", side_effect=interrupt_export):
            with self.assertRaises(OSError):
                self.flow.export_profile()
        self.assertTrue((complete / "manifest.json").exists())
        partial = [p for p in complete.parent.iterdir() if p != complete][0]
        self.assertFalse((partial / "manifest.json").exists())

    def test_source_version_changes_are_visible_and_old_evidence_is_preserved(self):
        path = self.root / "source.txt"
        path.write_text("I draw synthetic diagrams.")
        sid = self.flow.add_source(selected_file(path), authorship="my_words", dataset="synthetic")
        run = self.flow.prepare("claims", source_id=sid)
        self.flow.approve_export(run, approved=True)
        claim = proposed(sid, "I draw synthetic diagrams.")
        claim["sources"][0]["quote"] = path.read_text()
        supply(self.flow, run, response(run, claims=[claim]))
        self.flow.review(self.flow.load()["proposals"][0]["id"], "accept")
        path.write_text("I no longer draw those diagrams.")
        self.flow.add_source(selected_file(path), authorship="my_words", dataset="synthetic")
        self.assertTrue(any("Source updated" in i for i in knowledge.issues(self.flow.load())))

    def test_invalid_metadata_and_relationship_evidence_fail_atomically(self):
        a = self.flow.remember("Synthetic skill", "claimed_skills")
        b = self.flow.remember("Synthetic goal", "goals")
        self.flow.connect(b, "uses_skill", a, "Synthetic reason")
        state = self.flow.load()
        broken = deepcopy(state)
        broken["knowledge"]["links"][0]["to"] = "missing"
        with self.assertRaises(Invalid):
            validate_workspace(broken)
        broken = deepcopy(state)
        broken["knowledge"]["links"][0]["sources"][0]["quote"] = "not in source"
        with self.assertRaises(Invalid):
            validate_workspace(broken)
        self.assertEqual(self.flow.load(), state)

    def test_model_budget_is_40_atomic_claims_and_ideas_are_deferred(self):
        sid, _ = import_proposal(self.flow, self.root)
        with self.assertRaisesRegex(Invalid, "deferred"):
            self.flow.prepare("ideas", claim_ids=[])
        run = self.flow.prepare("claims", source_id=sid)
        self.flow.approve_export(run, approved=True)
        claims = [proposed(sid, f"Fictional interpretation {i}", key=f"skill-{i}") for i in range(41)]
        before = len(self.flow.load()["proposals"])
        with self.assertRaisesRegex(Invalid, "budget"):
            supply(self.flow, run, response(run, claims=claims))
        self.assertEqual(len(self.flow.load()["proposals"]), before)
        supply(self.flow, run, response(run, claims=claims[:40]))
        self.assertEqual(len(self.flow.load()["proposals"]), before + 40)
        from foundry.exchange import validate_response
        legacy = {**run, "prompt_version": "selected-source-v1"}
        with self.assertRaisesRegex(Invalid, "budget"):
            validate_response(response(legacy, claims=claims[:9]), legacy, self.flow.load()["core"])

    def test_runtime_text_is_never_executed(self):
        marker = self.root / "must-not-exist"
        text = f"$(touch {marker}) [link=https://example.invalid]ordinary data[/link]"
        self.flow.remember(text, "context")
        self.flow.export_profile()
        self.assertFalse(marker.exists())

    def test_workspace_budget_failure_is_atomic(self):
        self.flow.remember("Synthetic starting point", "context")
        before = self.flow.load()
        self.flow.store.max_bytes = 20
        with self.assertRaises(Invalid):
            self.flow.remember("Another point", "context")
        self.flow.store.max_bytes = 20_000_000
        self.assertEqual(self.flow.load(), before)


if __name__ == "__main__":
    unittest.main()
