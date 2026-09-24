"""Operate the experience controls with synthetic data and a fake GitHub transport."""

import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from foundry import skillmap
from foundry.knowledge import Knowledge
from tests.test_skillmap import snapshot

HAS_TEXTUAL = importlib.util.find_spec("textual") is not None
if HAS_TEXTUAL:
    from textual.widgets import Button, Checkbox, OptionList, Select, Static, TextArea
    from foundry.ui import FoundryApp
    from foundry.ui_skillmap import Capability, CheckIn, Reflection, RepositoryDialog


@unittest.skipUnless(HAS_TEXTUAL, "requires pinned Textual")
class ExperienceUITests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.flow = Knowledge(Path(self.temp.name) / "workspace", "synthetic")
        self.flow.initialize()
        self.eid = skillmap.add_experience(self.flow, "Fictional renderer", "project", "I explored geometry.")
        self.sid = skillmap.add_skill(self.flow, self.eid, "Python", "language", "I adapted a plotting example.")

    async def settle(self, app, pilot):
        await pilot.pause(.1)
        await app.workers.wait_for_complete()
        await pilot.pause(.1)

    async def more(self, app, pilot, action):
        if action == "experience-details":
            app.query_one("#experience-select", Select).value = self.eid
            await pilot.pause()
        await pilot.click("#more-nav")
        await self.settle(app, pilot)
        choices = app.screen.query_one("#more-options", OptionList)
        choices.highlighted = choices.get_option_index(action)
        await pilot.press("enter")
        await self.settle(app, pilot)

    async def test_reflection_capability_checkin_and_offline_export(self):
        app = FoundryApp(self.flow)
        async with app.run_test(size=(120, 44)) as pilot:
            await self.settle(app, pilot)
            app.query_one("#experience-select", Select).value = self.eid
            await pilot.pause()
            self.assertIn("Fictional renderer", str(app.query_one("#experience-summary", Static).render()))
            self.assertIn("personally", str(app.query_one("#next-question", Static).render()))
            await pilot.click("#reflect-experience")
            await self.settle(app, pilot)
            self.assertIsInstance(app.screen, Reflection)
            app.screen.query_one("#reflection-answer", TextArea).load_text("I designed the geometry; AI helped with Python.")
            await pilot.click("#save-reflection")
            await self.settle(app, pilot)
            self.assertEqual(len(self.flow.load()["skillmap"]["answers"]), 1)
            await self.more(app, pilot, "experience-details")
            await pilot.click("#assess-skill")
            await self.settle(app, pilot)
            self.assertIsInstance(app.screen, Capability)
            app.screen.query_one("#cap-explain", Select).value = "with_help"
            app.screen.query_one("#cap-role", Select).value = "supporting"
            app.screen.query_one("#cap-assistance", Select).value = "ai_assisted"
            app.screen.query_one("#cap-note", TextArea).load_text("I can adapt a plot with an example.")
            await pilot.click("#save-capability")
            await self.settle(app, pilot)
            await self.more(app, pilot, "experience-details")
            self.assertIn("With help", app.screen.query_one("#experience-detail", TextArea).text)
            await pilot.press("escape")
            await self.more(app, pilot, "current-circumstances")
            await self.settle(app, pilot)
            self.assertIsInstance(app.screen, CheckIn)
            app.screen.query_one("#checkin-text", TextArea).load_text("Occasional evenings for learning.")
            await pilot.click("#save-checkin")
            await self.settle(app, pilot)
            with patch("foundry.ui_skillmap.webbrowser.open", return_value=False) as browser:
                await pilot.click("#solar-view")
                await self.settle(app, pilot)
                browser.assert_called_once()
            self.assertEqual(len(list((self.flow.path / "exports").glob("*/index.html"))), 1)
        reopened = Knowledge(self.flow.path, "synthetic").load()
        self.assertEqual(reopened["skillmap"]["assessments"][0]["assistance"], "ai_assisted")
        self.assertEqual(len(reopened["skillmap"]["checkins"]), 1)

    async def test_private_repository_selected_files_only_and_no_model_call(self):
        data = snapshot()
        app = FoundryApp(self.flow)
        with patch("foundry.github.GitHub.repositories", return_value={"login":"fictional", "more":False,
                  "repositories":[{"name":data["repository"],"private":True,"archived":False}]}), \
             patch("foundry.github.GitHub.inventory", return_value=data), \
             patch("foundry.github.GitHub.snapshot", return_value=data) as capture:
            async with app.run_test(size=(120,44)) as pilot:
                await self.settle(app,pilot)
                await self.more(app, pilot, "experience-details")
                await pilot.click("#github-evidence")
                await self.settle(app,pilot)
                self.assertIsInstance(app.screen,RepositoryDialog)
                await pilot.click("#github-connect")
                await self.settle(app,pilot)
                app.screen.query_one("#github-repo",Select).value=data["repository"]
                await pilot.pause()
                await pilot.click("#github-preview")
                await self.settle(app,pilot)
                app.screen.query_one("#repo-file-0",Checkbox).value=True
                await pilot.click("#github-import")
                await self.settle(app,pilot)
                capture.assert_called_once_with(data,["src/main.py"])
                self.assertEqual(self.flow.load()["runs"],[])
                await self.more(app, pilot, "experience-details")
                self.assertIn("Repository evidence selected",app.screen.query_one("#experience-detail",TextArea).text)

    async def test_home_has_one_primary_action_and_tools_are_disclosed_on_demand(self):
        app = FoundryApp(self.flow)
        async with app.run_test(size=(100,35)) as pilot:
            await self.settle(app,pilot)
            app.query_one("#experience-select", Select).value = self.eid
            await pilot.pause()
            visible = [b for b in app.query(Button) if b.region.width and b.region.height]
            self.assertEqual({b.id for b in visible}, {"review-nav", "more-nav", "solar-view", "reflect-experience", "add-information", "about-me"})
            self.assertEqual([b.id for b in visible if b.variant == "primary"], ["add-information"])
            await self.more(app, pilot, "graph-tab")
            self.assertTrue(app.query_one("#graph-search").region.width)
            await pilot.click("#home-nav")
            await self.settle(app,pilot)
            self.assertTrue(app.query_one("#reflect-experience").region.width)
            await pilot.click("#more-nav")
            choices = app.screen.query_one("#more-options", OptionList)
            choices.highlighted = choices.get_option_index("sources-tab")
            await pilot.pause()
            self.assertIn("manual Codex", str(app.screen.query_one("#more-description", Static).render()))
            screenshot = app.export_screenshot()
            self.assertIn("Experience", screenshot)
            self.assertIn("extraction", screenshot)
            await pilot.press("escape")
            await self.settle(app,pilot)
            self.assertTrue(app.query_one("#more-nav").has_focus)
            await pilot.resize_terminal(80,24)
            await pilot.pause()
            primary = app.query_one("#add-information", Button)
            self.assertLessEqual(primary.region.bottom, 23)
            prompt = app.query_one("#next-question", Static)
            self.assertGreaterEqual(app.query_one("#question-content").region.height, 2)
            self.assertLess(prompt.region.y, app.query_one("#reflect-experience").region.y)
            self.assertTrue(await pilot.click("#reflect-experience"))
            self.assertIsInstance(app.screen, Reflection)
