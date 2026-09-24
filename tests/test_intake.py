"""Safe local parsing of selected resume literals; all output remains proposed."""

from pathlib import Path
import tempfile
import unittest

from foundry.intake import resume_claims
from foundry.knowledge import Knowledge, build_graph
from foundry.validation import Invalid
from foundry.workflow import selected_file
from tests.fixtures import source


RESUME = '''# fictional resume, not executable input
RESUME_DATA = {
    "master_skills": {"Languages": ["ExampleLang", "QueryLang"]},
    "projects": [{"title": "Paper garden", "date": "2024 - Present",
                  "tech": "ExampleLang", "master_facts": """
                  - Made a fictional garden planner.
                  - Claimed a speed improvement; not independently measured.
                  """}],
    "experience": [{"role": "Fixture assistant", "company": "Fictional lab",
                    "dates": "2023", "master_facts": "- Drafted practice templates."}]
}
'''


class IntakeTests(unittest.TestCase):
    def test_listed_details_preserve_context_and_are_reports(self):
        claims = resume_claims(source("s", RESUME))
        self.assertEqual(len(claims), 8)
        self.assertEqual(len([c for c in claims if c["facet"] == "claimed_skills"]), 3)
        self.assertTrue(all(c["kind"] == "reported" for c in claims))
        self.assertTrue(all(c["sources"][0]["quote"] in RESUME for c in claims))
        self.assertTrue(any("current status unconfirmed" in c["text"] for c in claims))

    def test_json_and_duplicate_keys_and_invalid_shapes(self):
        self.assertEqual(len(resume_claims(source("s", '{"master_skills":{"Tools":["FictionTool"]}}'))), 1)
        for text in ('{"master_skills":{},"master_skills":{"Tools":["A"]}}',
                     "DATA = {'master_skills': {}, 'master_skills': {'Tools': ['A']}}",
                     '{"master_skills":{"Tools":"not a list"}}',
                     '{"projects":[null]}', '[]', 'ordinary free-form note'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                resume_claims(source("s", text))

    def test_arbitrary_python_in_literal_is_not_executed(self):
        with tempfile.TemporaryDirectory() as root:
            marker = Path(root) / "must-not-exist"
            for text in (f"DATA = __import__('pathlib').Path('{marker}').touch()",
                         f"DATA = {{'master_skills': __import__('os').system('touch {marker}')}}",
                         f"import os\nos.system('touch {marker}')",
                         f"DATA = {{'master_skills': f\"{{__import__('os').system('touch {marker}')}}\"}}"):
                with self.assertRaises(ValueError):
                    resume_claims(source("s", text))
            self.assertFalse(marker.exists())

    def test_staging_is_idempotent_and_preserves_reviews_on_reimport(self):
        with tempfile.TemporaryDirectory() as root:
            flow = Knowledge(Path(root) / "workspace", "synthetic")
            flow.initialize()
            path = Path(root) / "resume.txt"
            path.write_text(RESUME)
            sid = flow.add_source(selected_file(path), authorship="my_words", dataset="synthetic")
            proposals = flow.extract_listed(sid)
            self.assertEqual(len(proposals), 8)
            self.assertEqual(len(build_graph(flow.load())["nodes"]), 1)
            flow.review(proposals[0], "reject", "This was a fictional demonstration item.")
            self.assertEqual(flow.extract_listed(sid), [])
            self.assertEqual(flow.load()["proposals"][0]["status"], "rejected")
            self.assertEqual(flow.load()["runs"], [])
            fresh = Knowledge(flow.path, "synthetic")
            self.assertEqual(len(fresh.load()["proposals"]), 8)

    def test_generated_resume_cannot_describe_user(self):
        with self.assertRaises(Invalid):
            resume_claims(source("s", RESUME, kind="generated"))

    def test_hash_lines_inside_literal_are_preserved(self):
        text = '''# header
DATA = {"projects": [{"title": "Fictional notes", "master_facts": """
# This line is part of the supplied project description.
- Another detail.
"""}]}'''
        claims = resume_claims(source("s", text))
        self.assertTrue(any("# This line" in c["text"] for c in claims))


if __name__ == "__main__":
    unittest.main()
