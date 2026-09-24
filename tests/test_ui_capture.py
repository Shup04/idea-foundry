"""Operate the unified input and readable output with fictional evidence."""

import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from foundry import capture, profile, skillmap, understanding
from foundry.knowledge import Knowledge
from tests.test_capture import FakeOpenAI

HAS_TEXTUAL = importlib.util.find_spec("textual") is not None
if HAS_TEXTUAL:
    from textual.widgets import Button, Input, Select, Static, TabbedContent, TextArea
    from foundry.ui import FoundryApp, ProfileContent
    from foundry.ui_capture import CaptureDialog, PendingCaptureDialog


@unittest.skipUnless(HAS_TEXTUAL, "requires pinned Textual")
class CaptureUITests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.flow = Knowledge(Path(self.temp.name) / "workspace", "synthetic")
        self.flow.initialize()

    async def settle(self, app, pilot):
        await pilot.pause(.1)
        await app.workers.wait_for_complete()
        await pilot.pause(.1)

    async def preview(self, app, pilot, text):
        await pilot.click("#add-information")
        await self.settle(app, pilot)
        self.assertIsInstance(app.screen, CaptureDialog)
        app.screen.query_one("#information-text", TextArea).load_text(text)
        await pilot.click("#preview-information")
        await self.settle(app, pilot)

    async def test_originals_save_without_ai_and_preview_preserves_selected_file(self):
        selected = Path(self.temp.name) / "fictional.md"
        selected.write_text("I enjoy repairing fictional clocks.")
        app = FoundryApp(self.flow)
        with patch("foundry.openai_api.OpenAI") as provider:
            async with app.run_test(size=(100, 36)) as pilot:
                await self.settle(app, pilot)
                await pilot.click("#add-information")
                await self.settle(app, pilot)
                await pilot.click("#capture-options-toggle")
                app.screen.query_one("#information-paths", TextArea).load_text(str(selected))
                await pilot.pause()
                await pilot.click("#preview-information")
                await self.settle(app, pilot)
                self.assertIn("fictional clocks", app.screen.query_one("#information-preview", TextArea).text)
                self.assertTrue(app.screen.query_one("#understand-information", Button).disabled)
                selected.write_text("REPLACED AFTER PREVIEW")
                await pilot.click("#save-information")
                await self.settle(app, pilot)
                state = self.flow.load()
                self.assertEqual(capture.progress(state)["pending_chunks"], 1)
                self.assertIn("fictional clocks", capture.pending(state)[0]["text"])
                provider.assert_not_called()
        reopened = FoundryApp(self.flow)
        async with reopened.run_test(size=(80, 24)) as pilot:
            await self.settle(reopened, pilot)
            await pilot.click("#add-information")
            await self.settle(reopened, pilot)
            await pilot.click("#continue-information")
            await self.settle(reopened, pilot)
            self.assertIsInstance(reopened.screen, PendingCaptureDialog)
            self.assertIn("fictional clocks", reopened.screen.query_one("#pending-information-preview", TextArea).text)
            self.assertTrue(reopened.screen.query_one("#resume-information", Button).disabled)

    async def test_failure_preserves_original_and_explicit_retry_uses_saved_input(self):
        understanding.configure(self.flow, budget_usd=1)
        app = FoundryApp(self.flow)
        with patch("foundry.capture.process", side_effect=ValueError("Fictional provider unavailable")):
            async with app.run_test(size=(100, 36)) as pilot:
                await self.settle(app, pilot)
                await self.preview(app, pilot, "I prefer uninterrupted time to explore geometry.")
                await pilot.click("#understand-information")
                await self.settle(app, pilot)
                self.assertEqual(capture.progress(self.flow.load())["pending_chunks"], 1)
                self.assertIn("saved", str(app.query_one("#map-status", Static).render()))
                self.assertFalse(self.flow.load()["proposals"])
                await pilot.click("#add-information")
                await self.settle(app, pilot)
                await pilot.click("#continue-information")
                await self.settle(app, pilot)
                self.assertIn("uninterrupted time", app.screen.query_one("#pending-information-preview", TextArea).text)
                with patch("foundry.capture.process", return_value={"proposals": [], "remaining_chunks": 1,
                        "error": "Fictional retry still unavailable"}) as retry:
                    await pilot.click("#resume-information")
                    await self.settle(app, pilot)
                    retry.assert_called_once()
                    self.assertIsNotNone(retry.call_args.kwargs["plan"])
                self.assertIn("retry still unavailable", str(app.query_one("#map-status", Static).render()))

    async def test_compact_navigation_search_and_unsaved_draft(self):
        self.flow.remember("I enjoy geometric puzzles.", "interests")
        app = FoundryApp(self.flow)
        with patch("foundry.openai_api.OpenAI") as provider:
            async with app.run_test(size=(80, 24)) as pilot:
                await self.settle(app, pilot)
                primary = app.query_one("#add-information", Button)
                self.assertLess(primary.region.bottom, 23)
                self.assertTrue(await pilot.click("#about-me"))
                await self.settle(app, pilot)
                self.assertEqual(app.query_one("#tabs", TabbedContent).active, "about-tab")
                app.query_one("#about-search", Input).value = "geometric"
                await pilot.pause()
                self.assertIn("I enjoy geometric puzzles.", app.query_one("#about-content", ProfileContent).source)
                await pilot.click("#about-add")
                await self.settle(app, pilot)
                app.screen.query_one("#information-text", TextArea).load_text("An unfinished thought")
                await pilot.press("escape")
                await self.settle(app, pilot)
                await pilot.click("#home-nav")
                await pilot.click("#add-information")
                await self.settle(app, pilot)
                self.assertEqual(app.screen.query_one("#information-text", TextArea).text, "An unfinished thought")
                self.assertFalse(capture.pending(self.flow.load()))
                provider.assert_not_called()

    async def test_preview_process_review_and_readable_output(self):
        understanding.configure(self.flow, budget_usd=1)
        app = FoundryApp(self.flow)
        client = FakeOpenAI()
        with patch("foundry.openai_api.OpenAI", return_value=client):
            async with app.run_test(size=(100, 36)) as pilot:
                await self.settle(app, pilot)
                await self.preview(app, pilot, "I enjoy gardening.")
                self.assertIn("I enjoy gardening.", app.screen.query_one("#information-preview", TextArea).text)
                await pilot.click("#understand-information")
                await self.settle(app, pilot)
                self.assertEqual(app.query_one("#tabs", TabbedContent).active, "profile-tab")
                self.assertIn("Proposed action: add", app.query_one("#profile-content", TextArea).text)
                self.assertEqual(capture.progress(self.flow.load())["pending_chunks"], 0)
                await pilot.click("#accept-claim")
                await self.settle(app, pilot)
                self.assertEqual(self.flow.load()["proposals"][0]["status"], "accepted")
                await pilot.click("#home-nav")
                await pilot.click("#about-me")
                await self.settle(app, pilot)
                app.query_one("#about-search", Input).value = "gardening"
                await pilot.pause()
                self.assertIn("I enjoy gardening.", app.query_one("#about-content", ProfileContent).source)
                self.assertEqual(len(client.calls), 1)

    async def test_home_starts_with_broad_gap_and_project_questions_are_optional(self):
        eid = skillmap.add_experience(self.flow, "Fictional renderer", "project", "I explored geometric shapes.")
        self.flow.remember("I enjoy geometry.", "interests")
        app = FoundryApp(self.flow)
        async with app.run_test(size=(80, 24)) as pilot:
            await self.settle(app, pilot)
            self.assertEqual(app.query_one("#experience-select", Select).value, "general")
            question = profile.overview(self.flow.load())["next_question"]
            self.assertIn(question["question"], str(app.query_one("#next-question", Static).render()))
            await pilot.click("#reflect-experience")
            await self.settle(app, pilot)
            self.assertIsInstance(app.screen, CaptureDialog)
            self.assertEqual(app.screen.query_one("#information-title", Input).value, question["question"])
            self.assertEqual(app.screen.query_one("#information-experience", Select).value, "")
            await pilot.press("escape")
            app.query_one("#experience-select", Select).value = eid
            await pilot.pause()
            self.assertIn("personally", str(app.query_one("#next-question", Static).render()))


if __name__ == "__main__":
    unittest.main()
