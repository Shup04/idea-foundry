"""Headless tests operate the real Textual screens; model replies are fictional fixtures."""

import asyncio
import importlib.util
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from foundry.storage import encoded
from foundry.workflow import Workflow
from tests.workflow_fixtures import (CORRECTED, SOURCE, idea_pair, import_proposal,
                                     populated, proposed, response)

HAS_TEXTUAL = importlib.util.find_spec("textual") is not None
if HAS_TEXTUAL:
    from textual.widgets import Button, Checkbox, Input, OptionList, Select, TabbedContent, TextArea
    from foundry.ui import FoundryApp, HandoffDialog, Reading, ResponseDialog, SourceDialog
    from foundry.knowledge import Knowledge


@unittest.skipUnless(HAS_TEXTUAL, "install pinned UI dependencies with make deps ui-env")
class UITests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.flow = Workflow(self.root / "workspace", "synthetic")
        self.flow.initialize()

    async def settle(self, app, pilot):
        await pilot.pause(0.1)
        await app.workers.wait_for_complete()
        await pilot.pause(0.1)

    async def tab(self, app, pilot, tab):
        if tab == "profile-tab":
            await pilot.click("#review-nav")
        elif tab == "map-tab":
            await pilot.click("#home-nav")
        else:
            await pilot.click("#more-nav")
            await self.settle(app, pilot)
            choices = app.screen.query_one("#more-options", OptionList)
            choices.highlighted = choices.get_option_index(tab)
            await pilot.press("enter")
        await self.settle(app, pilot)

    async def test_file_preview_handoff_proposal_correction_restart_via_ui(self):
        selected = self.root / "unfamiliar.md"
        selected.write_text(SOURCE)
        app = FoundryApp(self.flow)
        async with app.run_test(size=(120, 44)) as pilot:
            await self.settle(app, pilot)
            await self.tab(app, pilot, "sources-tab")
            await pilot.click("#add-file")
            self.assertIsInstance(app.screen, SourceDialog)
            app.screen.query_one("#source-path", Input).value = str(selected)
            await pilot.click("#preview-source")
            await self.settle(app, pilot)
            self.assertEqual(app.screen.query_one("#source-preview", TextArea).text, SOURCE)
            app.screen.query_one("#authorship", Select).value = "my_words"
            app.screen.query_one("#source-attestation", Checkbox).value = True
            await pilot.click("#add-selection")
            await self.settle(app, pilot)
            await pilot.click("#analyse-source")
            self.assertIsInstance(app.screen, HandoffDialog)
            self.assertTrue(app.screen.query_one("#export-handoff", Button).disabled)
            self.assertEqual(self.flow.load()["runs"], [])
            app.screen.query_one("#approve-content", Checkbox).value = True
            await pilot.click("#export-handoff")
            await self.settle(app, pilot)
            await pilot.press("escape")
            await self.settle(app, pilot)
            run = self.flow.load()["runs"][0]
            sid = run["payload"]["sources"][0]["id"]
            await pilot.click("#open-response")
            self.assertIsInstance(app.screen, ResponseDialog)
            app.screen.query_one("#response-paste", TextArea).load_text(encoded(response(run, claims=[proposed(sid)])))
            await pilot.click("#import-response")
            await self.settle(app, pilot)
            await self.tab(app, pilot, "profile-tab")
            self.assertIn("SUPPORTING PASSAGE", app.query_one("#profile-content", TextArea).text)
            await pilot.click("#correct-claim")
            app.screen.query_one("#review-text", TextArea).load_text(CORRECTED)
            await pilot.click("#save-review")
            await self.settle(app, pilot)
            app.query_one("#review-filter", Select).value = "all"
            await pilot.pause()
            self.assertIn(CORRECTED, app.query_one("#profile-content", TextArea).text)
        fresh = FoundryApp(Workflow(self.flow.path, "synthetic"))
        async with fresh.run_test(size=(100, 36)) as pilot:
            await self.settle(fresh, pilot)
            fresh.query_one("#review-filter", Select).value = "all"
            await pilot.pause()
            self.assertIn("CORRECTED", fresh.query_one("#profile-content", TextArea).text)
            self.assertIn(CORRECTED, fresh.query_one("#profile-content", TextArea).text)

    async def test_guided_capture_search_connection_and_export(self):
        app = FoundryApp(self.flow)
        async with app.run_test(size=(120, 44)) as pilot:
            await self.settle(app, pilot)
            self.assertEqual(app.query_one("#tabs", TabbedContent).active, "map-tab")
            await self.tab(app, pilot, "capture-tab")
            self.assertFalse(list(app.query("#ideas-tab")))
            app.query_one("#answer", TextArea).load_text("I can sketch fictional fixtures.")
            await pilot.click("#save-answer")
            await self.settle(app, pilot)
            skill = self.flow.load()["core"]["claims"][0]["id"]
            self.assertIn("sketch fictional fixtures", app.query_one("#known-context", TextArea).text)
            await pilot.click("#next-topic")
            self.assertNotEqual(app.query_one("#topic", Select).value, "claimed_skills")
            app.query_one("#topic", Select).value = "goals"
            app.query_one("#answer", TextArea).load_text("I want to make a miniature shelf.")
            await pilot.click("#save-answer")
            await self.settle(app, pilot)
            goal = self.flow.load()["core"]["claims"][-1]["id"]
            await self.tab(app, pilot, "graph-tab")
            app.selected_claim = goal
            app.show_graph()
            await pilot.pause()
            await pilot.click("#connect-claim")
            app.screen.query_one("#relation", Select).value = "uses_skill"
            app.screen.query_one("#link-target", Select).value = skill
            app.screen.query_one("#link-reason", TextArea).load_text("Sketches help me plan the joints.")
            await pilot.click("#save-link")
            await self.settle(app, pilot)
            self.assertIn("Sketches help", app.query_one("#graph-detail", TextArea).text)
            self.assertEqual(len(self.flow.load()["knowledge"]["links"]), 1)
            await pilot.click("#export-profile")
            await self.settle(app, pilot)
            self.assertIsInstance(app.screen, Reading)
            self.assertEqual(len(list((self.flow.path / "exports").glob("*/manifest.json"))), 1)
            await pilot.press("escape")
            app.query_one("#graph-search", Input).value = "nonexistent value"
            await pilot.pause()
            self.assertIsNone(app.selected_claim)
            self.assertTrue(app.query_one("#edit-claim", Button).disabled)
            await pilot.click("#add-detail")
            await self.settle(app, pilot)
            self.assertEqual(app.query_one("#tabs", TabbedContent).active, "capture-tab")

    async def test_existing_skills_skip_initial_question_and_correction_is_visible(self):
        graph = Knowledge(self.flow.path, "synthetic")
        cid = graph.remember("I can sketch fixtures.", "claimed_skills")
        app = FoundryApp(graph)
        async with app.run_test(size=(100, 36)) as pilot:
            await self.settle(app, pilot)
            self.assertNotEqual(app.query_one("#topic", Select).value, "claimed_skills")
            await self.tab(app, pilot, "graph-tab")
            app.selected_claim = cid
            app.show_graph()
            await pilot.pause()
            await pilot.click("#edit-claim")
            app.screen.query_one("#edit-text", TextArea).load_text("I can sketch basic fixtures with help.")
            await pilot.click("#save-edit")
            await self.settle(app, pilot)
            self.assertEqual(graph.load()["core"]["claims"][0]["status"], "excluded")
            self.assertEqual(graph.load()["core"]["claims"][-1]["text"], "I can sketch basic fixtures with help.")

    async def test_local_resume_intake_and_single_click_review(self):
        from tests.test_intake import RESUME
        from foundry.workflow import selected_file
        path = self.root / "resume.txt"
        path.write_text(RESUME)
        self.flow.add_source(selected_file(path), authorship="my_words", dataset="synthetic")
        app = FoundryApp(self.flow)
        async with app.run_test(size=(110, 40)) as pilot:
            await self.settle(app, pilot)
            await self.tab(app, pilot, "sources-tab")
            await pilot.click("#extract-listed")
            await self.settle(app, pilot)
            self.assertEqual(app.query_one("#tabs", TabbedContent).active, "profile-tab")
            self.assertEqual(len(self.flow.load()["proposals"]), 8)
            app.query_one("#review-topic", Select).value = "claimed_skills"
            await pilot.pause()
            await pilot.click("#accept-claim")
            await self.settle(app, pilot)
            self.assertEqual(len(self.flow.load()["core"]["claims"]), 1)
            self.assertEqual(self.flow.load()["runs"], [])
            self.assertEqual(self.flow.load()["proposals"][0]["status"], "accepted")

    async def test_failure_is_visible_and_import_does_not_block_interface(self):
        sid, _ = import_proposal(self.flow, self.root)
        run = self.flow.prepare("claims", source_id=sid)
        self.flow.approve_export(run, approved=True)
        app = FoundryApp(self.flow)
        original = app.workflow.import_response
        def delayed(*args):
            time.sleep(0.5)
            return original(*args)
        async with app.run_test(size=(115, 40)) as pilot:
            await self.settle(app, pilot)
            await self.tab(app, pilot, "sources-tab")
            await pilot.click("#open-response")
            app.screen.query_one("#response-paste", TextArea).load_text("not valid JSON")
            with patch.object(app.workflow, "import_response", side_effect=delayed):
                await pilot.click("#import-response")
                ticks = []
                app.set_timer(0.05, lambda: ticks.append(True))
                await asyncio.sleep(0.15)
                self.assertTrue(ticks, "UI timers must run while analysis response is being handled")
                await self.settle(app, pilot)
            text = str(app.screen.query_one("#response-error").render())
            self.assertIn("Import failed", text)
            self.assertEqual(self.flow.load()["runs"][-1]["status"], "failed")
            self.assertEqual(len(self.flow.load()["proposals"]), 1)

    async def test_keyboard_help_resize_and_literal_imported_markup(self):
        _, pid = populated(self.flow, self.root)[:2]
        self.flow.review(pid, "correct", "[link=https://invalid.example]Literal source markup[/link]")
        app = FoundryApp(self.flow)
        async with app.run_test(size=(90, 32)) as pilot:
            await self.settle(app, pilot)
            await pilot.press("f1")
            self.assertIsInstance(app.screen, Reading)
            await pilot.press("escape")
            await pilot.resize_terminal(80, 30)
            await self.tab(app, pilot, "profile-tab")
            app.query_one("#review-filter", Select).value = "all"
            await pilot.pause()
            self.assertIn("[link=", app.query_one("#profile-content", TextArea).text)
            await pilot.press("tab", "shift+tab", "f2")
            self.assertIsInstance(app.screen, Reading)
            await pilot.press("escape")
            await pilot.press("ctrl+q")


if __name__ == "__main__":
    unittest.main()
