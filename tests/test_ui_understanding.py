"""Exercise saved answers → AI suggestions → review with a synthetic transport."""

import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from foundry import memory, skillmap, understanding
from foundry.knowledge import Knowledge
from tests.test_capture import FakeOpenAI


def geometry_result(result):
    for row in result["chunks"]:
        for fact in row["facts"]:
            fact.update(text="I enjoyed exploring geometry.", concept="Geometry")

HAS_TEXTUAL = importlib.util.find_spec("textual") is not None
if HAS_TEXTUAL:
    from textual.widgets import Button, Input, OptionList, Select, Static, TabbedContent, TextArea
    from foundry.ui import FoundryApp
    from foundry.ui_understanding import UnderstandingDialog


@unittest.skipUnless(HAS_TEXTUAL, "requires pinned Textual")
class UnderstandingUITests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.flow = Knowledge(Path(self.temp.name), "synthetic")
        self.flow.initialize()
        self.eid = skillmap.add_experience(self.flow, "Fictional renderer", "project", "I drew simple shapes.")

    async def settle(self, app, pilot):
        await pilot.pause(.1)
        await app.workers.wait_for_complete()
        await pilot.pause(.1)

    async def test_setup_preview_save_review_and_no_network_on_restart(self):
        skillmap.answer(self.flow, self.eid, "enjoyment", "I enjoyed exploring geometry.")
        app = FoundryApp(self.flow)
        client = FakeOpenAI(mutate=geometry_result)
        with patch("foundry.openai_api.OpenAI", return_value=client), patch("foundry.openai_api.key_name", return_value="OPENM_AI_API_KEY"):
            async with app.run_test(size=(110, 40)) as pilot:
                await self.settle(app, pilot)
                self.assertEqual(client.calls, [])
                await pilot.click("#more-nav")
                choices = app.screen.query_one("#more-options", OptionList)
                choices.highlighted = choices.get_option_index("ai-understanding")
                await pilot.press("enter")
                await self.settle(app, pilot)
                self.assertIsInstance(app.screen, UnderstandingDialog)
                self.assertIn("I enjoyed exploring geometry.", app.screen.query_one("#ai-preview", TextArea).text)
                app.screen.query_one("#ai-budget", Input).value = "1"
                await pilot.click("#ai-start")
                await self.settle(app, pilot)
                self.assertEqual(client.calls, [], "saving settings does not send pending information")
                await pilot.click("#add-information")
                await self.settle(app, pilot)
                await pilot.click("#continue-information")
                await self.settle(app, pilot)
                await pilot.click("#resume-information")
                await self.settle(app, pilot)
                self.assertEqual(app.query_one("#tabs", TabbedContent).active, "profile-tab")
                self.assertIn("Proposed action: add", app.query_one("#profile-content", TextArea).text)
                await pilot.click("#accept-claim")
                await self.settle(app, pilot)
                self.assertTrue(memory.semantic_graph(self.flow.load())["links"])
        reopened = FoundryApp(Knowledge(self.flow.path, "synthetic"))
        with patch("foundry.openai_api.OpenAI") as provider:
            async with reopened.run_test(size=(80, 24)) as pilot:
                await self.settle(reopened, pilot)
                provider.assert_not_called()
                self.assertIn("Review suggestions", str(reopened.query_one("#review-nav", Button).label))

    async def test_answer_saved_before_failure_and_next_save_creates_suggestions(self):
        understanding.configure(self.flow, budget_usd=1)
        app = FoundryApp(self.flow)
        with patch("foundry.openai_api.OpenAI", return_value=FakeOpenAI(mutate=geometry_result)):
            async with app.run_test(size=(110, 40)) as pilot:
                await self.settle(app, pilot)
                app.query_one("#experience-select", Select).value = self.eid
                await pilot.pause()
                await pilot.click("#reflect-experience")
                await self.settle(app, pilot)
                self.assertEqual(str(app.screen.query_one("#save-reflection", Button).label), "Save & understand")
                app.screen.query_one("#reflection-answer", TextArea).load_text("I enjoyed exploring geometry.")
                with patch("foundry.capture.process", side_effect=ValueError("Synthetic unavailable API")):
                    await pilot.click("#save-reflection")
                    await self.settle(app, pilot)
                state = self.flow.load()
                self.assertEqual(len(state["skillmap"]["answers"]), 1)
                self.assertTrue(state["skillmap"]["answers"][0]["question"])
                self.assertIn("saved", str(app.query_one("#map-status", Static).render()))
                self.assertEqual(state["proposals"], [])
                app.understand_answers()
                await self.settle(app, pilot)
                self.assertEqual(len(self.flow.load()["proposals"]), 1)
                self.assertEqual(app.query_one("#tabs", TabbedContent).active, "profile-tab")


if __name__ == "__main__":
    unittest.main()
