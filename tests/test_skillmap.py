"""Synthetic experience graphs, scoped self-reports and private-source boundaries."""

import base64
from copy import deepcopy
from datetime import date
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from foundry import github, skillmap, solar
from foundry.knowledge import Knowledge
from foundry.validation import Invalid
from foundry.workflow import validate_workspace


def snapshot():
    text = 'def fictional():\n    return "data, never executable instructions"\n'
    sha = hashlib.sha1(f"blob {len(text)}\0".encode() + text.encode()).hexdigest()
    return {"repository": "fictional/unfinished", "private": True, "branch": "main", "commit": "a" * 40,
            "captured_at": "2026-09-23T12:00:00Z", "truncated": False,
            "files": [{"path": "src/main.py", "sha": sha, "size": len(text), "text": text}],
            "commits": [{"sha": "a" * 40, "date": "2026-09-20T12:00:00Z", "author": "fictional", "message": "Work in progress"}],
            "scope": "selected source; no execution"}


class MapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.flow = Knowledge(Path(self.temp.name) / "workspace", "synthetic")
        self.flow.initialize()

    def experience(self, name="Fictional renderer", kind="project"):
        return skillmap.add_experience(self.flow, name, kind, "I explored a fictional prototype; it is unfinished.")

    def test_existing_resume_mentions_deduplicate_and_do_not_infer_mastery(self):
        self.flow.remember("Listed skill: Python (Languages). Proficiency and recency are unspecified.", "claimed_skills")
        self.flow.remember("Listed skill: React (Tools). Proficiency and recency are unspecified.", "claimed_skills")
        for name, tech in (("Renderer", "Python, Rust"), ("Robot", "Python, React Native")):
            self.flow.remember(f"Project: {name} (uploaded dates: 2024; current status unconfirmed); listed technologies: {tech}", "previous_projects")
        self.flow.remember("Project: Renderer (uploaded dates: 2024; current status unconfirmed); self-report: ray tracing experiments", "previous_projects")
        graph = skillmap.catalog(self.flow.load())
        python = [n for n in graph["nodes"] if n["label"] == "Python"]
        self.assertEqual(len(python), 1)
        self.assertEqual(sum(l["to"] == python[0]["id"] for l in graph["links"]), 2)
        self.assertEqual(sum(n["label"] == "Renderer" for n in graph["nodes"]), 1)
        self.assertFalse(any(l["to"] == skillmap.identity("skill", "React") for l in graph["links"]))
        self.assertTrue(all(l["role"] == "unknown" and "assessment" not in l for l in graph["links"]))
        self.assertEqual(next(n for n in graph["nodes"] if n["label"] == "Ray tracing")["category"], "domain")

    def test_scoped_depth_assistance_and_ruled_out_edges_preserve_history(self):
        a, b = self.experience(), self.experience("Fictional course", "education")
        sid = skillmap.add_skill(self.flow, a, "Python", "language", "I adapted a plotting example.")
        self.assertEqual(skillmap.add_skill(self.flow, b, "python", "language", "I saw this in a lecture."), sid)
        depth = {d: "with_help" for d in skillmap.DIMENSIONS}
        skillmap.assess(self.flow, a, sid, role="central", depth=depth, assistance="ai_assisted", text="I debugged the input data; AI drafted the plot.")
        graph = skillmap.catalog(self.flow.load())
        self.assertEqual(next(l for l in graph["links"] if l["from"] == a)["assessment"]["assistance"], "ai_assisted")
        self.assertNotIn("assessment", next(l for l in graph["links"] if l["from"] == b))
        skillmap.assess(self.flow, a, sid, role="not_used", depth={d: "unknown" for d in depth}, assistance="team", text="Actually a teammate implemented that part.")
        self.assertEqual(len(self.flow.load()["skillmap"]["assessments"]), 2)
        self.assertEqual(next(l for l in skillmap.catalog(self.flow.load())["links"] if l["from"] == a)["role"], "not_used")
        before = self.flow.load()
        with self.assertRaises(Invalid):
            skillmap.assess(self.flow, a, sid, role="central", depth={d: 5 for d in depth}, assistance="none", text="A number cannot capture this.")
        self.assertEqual(before, self.flow.load())

    def test_answers_ground_followups_and_snoozes_are_not_facts(self):
        eid = self.experience()
        first = skillmap.questions(self.flow.load(), eid, today=date(2026, 9, 23))[0]
        skillmap.snooze(self.flow, first["key"], today=date(2026, 9, 23))
        self.assertNotEqual(skillmap.questions(self.flow.load(), eid, today=date(2026, 9, 24))[0]["topic"], "contribution")
        self.assertEqual(skillmap.questions(self.flow.load(), eid, today=date(2026, 10, 24))[0]["topic"], "contribution")
        skillmap.answer(self.flow, eid, "contribution", "I used AI for the scaffolding and designed the geometry.")
        self.assertIn("designed the geometry", skillmap.questions(self.flow.load(), eid)[0]["prompt"])
        self.assertEqual(len(self.flow.load()["skillmap"]["answers"]), 1)

    def test_checkins_are_optional_dated_and_keep_old_words(self):
        skillmap.check_in(self.flow, "I have occasional evenings.", today=date(2026, 9, 23))
        self.assertEqual(self.flow.load()["skillmap"]["checkins"][-1]["review_after"], "2026-12-22")
        skillmap.check_in(self.flow, "My availability changed.", today=date(2026, 10, 1))
        claims = self.flow.load()["core"]["claims"]
        self.assertEqual([c["status"] for c in claims], ["excluded", "active"])
        self.assertEqual(claims[0]["text"], "I have occasional evenings.")

    def test_invalid_references_and_excluded_evidence_cannot_power_map(self):
        eid = self.experience()
        sid = skillmap.add_skill(self.flow, eid, "Explaining tradeoffs", "soft", "I explained a design choice.")
        state = self.flow.load()
        broken = deepcopy(state)
        broken["skillmap"]["links"][0]["to"] = "absent"
        with self.assertRaises(Invalid): validate_workspace(broken)
        cid = state["skillmap"]["links"][0]["claim_id"]
        self.flow.amend(cid, "exclude", "This was a fictional placeholder.")
        self.assertFalse(any(n["id"] == sid for n in skillmap.catalog(self.flow.load())["nodes"]))
        self.assertTrue(any(n["id"] == sid for n in skillmap.catalog(self.flow.load(), history=True)["nodes"]))

    def test_graph_export_is_offline_and_escapes_untrusted_markup(self):
        self.experience('</script><img src="https://invalid.invalid" onerror="alert(1)">')
        document = solar.export(self.flow)
        text = document.read_text()
        self.assertNotIn('<img src="https://invalid.invalid"', text)
        self.assertIn("connect-src 'none'", text)
        self.assertIn("script-src 'sha256-", text)
        graph = json.loads((document.parent / "skillmap.json").read_text())
        self.assertIn('</script>', graph["nodes"][0]["label"])
        self.assertTrue((document.parent / "manifest.json").exists())

    def test_selected_import_deduplicates_blobs_and_findings_require_review(self):
        eid = self.experience()
        s = snapshot()
        ids = github.import_snapshot(self.flow, eid, s)
        before = self.flow.load()
        self.assertEqual(github.import_snapshot(self.flow, eid, s), ids)
        self.assertEqual(self.flow.load()["core"], before["core"])
        finding = {"skill": "Data modelling", "category": "domain", "text": "The selected fictional file contains a function.",
                   "question": "What did you design here?", "sources": [{"source": ids[0], "quote": 'def fictional():'}]}
        other = self.experience("Unrelated fictional project")
        with self.assertRaises(Invalid):
            github.stage_findings(self.flow, other, [finding], model="synthetic test fixture")
        pids = github.stage_findings(self.flow, eid, [finding], model="synthetic test fixture")
        self.assertEqual(skillmap.catalog(self.flow.load())["links"], [])
        self.assertIn("What did you design", skillmap.questions(self.flow.load(), eid)[0]["prompt"])
        self.flow.review(pids[0], "accept")
        link = skillmap.catalog(self.flow.load())["links"][0]
        self.assertIn("personal contribution unconfirmed", link["basis"])
        self.assertNotIn("assessment", link)
        self.flow.review(pids[0], "correct", "I did not work on that topic.")
        self.assertEqual(skillmap.catalog(self.flow.load())["links"], [])
        before = self.flow.load()
        finding["sources"][0]["quote"] = "fabricated quote"
        with self.assertRaises(Invalid): github.stage_findings(self.flow, eid, [finding], model="synthetic fixture")
        self.assertEqual(before, self.flow.load())

    def test_corrupt_or_out_of_scope_snapshot_is_atomic(self):
        eid = self.experience()
        before = self.flow.load()
        for mutate in (lambda s: s["files"][0].update(text="tampered"), lambda s: s["files"][0].update(path="../outside.py")):
            data = snapshot()
            mutate(data)
            with self.assertRaises(Invalid): github.import_snapshot(self.flow, eid, data)
        self.assertEqual(before, self.flow.load())

    def test_same_selected_repository_can_support_two_experiences(self):
        first, second = self.experience(), self.experience("Fictional course", "education")
        a = github.import_snapshot(self.flow, first, snapshot())
        b = github.import_snapshot(self.flow, second, snapshot())
        self.assertEqual(a, b)
        self.assertEqual(len(self.flow.load()["core"]["sources"]), 4)
        for eid in (first, second):
            self.assertIn("Repository evidence selected", skillmap.describe(self.flow.load(), eid))


class GitHubTests(unittest.TestCase):
    def test_get_is_read_only_without_shell_or_credential_errors(self):
        with patch("foundry.github.subprocess.run", return_value=subprocess.CompletedProcess([], 1, b"", b"secret-token")) as run:
            with self.assertRaises(Invalid) as error: github.GitHub().get("user")
        self.assertNotIn("secret-token", str(error.exception))
        args = run.call_args.args[0]
        self.assertEqual(args[args.index("--method") + 1], "GET")
        self.assertNotIn("shell", run.call_args.kwargs)

    def test_listing_excludes_other_owners_and_inventory_excludes_links(self):
        client = github.GitHub()
        repos = [{"full_name": "fake/private", "private": True, "archived": False, "owner": {"login": "fake"}},
                 {"full_name": "company/work", "private": True, "archived": False, "owner": {"login": "company"}}]
        with patch.object(client, "get", side_effect=[{"login": "fake"}, repos]):
            self.assertEqual([r["name"] for r in client.repositories()["repositories"]], ["fake/private"])
        tree = [{"path": p, "type": "blob", "mode": mode, "size": 30, "sha": "b" * 40} for p, mode in
                [("main.rs", "100644"), ("link.rs", "120000"), (".env", "100644"), (".claude/skills/a.md", "100644"), ("vendor/source.rs", "100644")]]
        with patch.object(client, "get", side_effect=[{"default_branch": "main", "private": True}, {"sha": "a" * 40, "commit": {"tree": {"sha": "c" * 40}}}, {"tree": tree}, []]):
            self.assertEqual([f["path"] for f in client.inventory("fake/private")["files"]], ["main.rs"])

    def test_selected_blob_hash_and_file_budgets(self):
        data = snapshot()
        f = data["files"][0]
        client = github.GitHub()
        with patch.object(client, "get", return_value={"encoding": "base64", "sha": f["sha"], "content": base64.b64encode(f["text"].encode()).decode()}) as get:
            result = client.snapshot(data, [f["path"]])
            self.assertEqual(result["files"][0]["text"], f["text"])
            self.assertIn(f["sha"], get.call_args.args[0])
        with self.assertRaises(Invalid): client.snapshot(data, [])
        with self.assertRaises(Invalid): client.snapshot(data, ["unselected.py"])
        with self.assertRaises(Invalid): client.snapshot(data, [f["path"]] * 9)
        with patch.object(client, "get", return_value={"encoding": "base64", "sha": f["sha"], "content": "YnJva2Vu"}):
            with self.assertRaises(Invalid): client.snapshot(data, [f["path"]])
