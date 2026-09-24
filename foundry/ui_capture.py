"""One place to add personal information and preview selected cloud inputs."""

from textual import on, work
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Collapsible, Input, Label, Select, Static, TextArea

from . import capture, skillmap, understanding


class CaptureDialog(ModalScreen):
    BINDINGS = [("escape", "back", "Back")]

    def __init__(self, flow, draft=None):
        super().__init__()
        self.flow = flow
        self.state = flow.load()
        self.draft = draft or {}
        self.plan = None
        self.busy = False

    def compose(self):
        experiences = [(n["label"], n["id"]) for n in skillmap.catalog(self.state)["nodes"]
                       if n["kind"] in skillmap.EXPERIENCES]
        with Vertical(classes="dialog capture-dialog"):
            yield Label("Add information")
            with Vertical(id="capture-entry"):
                with VerticalScroll(id="capture-fields"):
                    yield Static(self.draft.get("title") or "Tell me anything worth remembering about you. A story, preference, project, or change of plans.", markup=False)
                    yield TextArea(self.draft.get("text", ""), id="information-text")
                    with Collapsible(title="Files and context (optional)", collapsed=True, id="capture-options"):
                        yield Input(self.draft.get("title", ""), placeholder="Title or context", id="information-title")
                        yield Select([("General — about me", ""), *experiences],
                                     value=self.draft.get("experience") or "", allow_blank=False,
                                     id="information-experience")
                        yield Label("Exact text, Markdown, JSON or CSV file paths, one per line")
                        yield TextArea(self.draft.get("paths", ""), id="information-paths")
                with Horizontal(classes="row"):
                    yield Button("Preview", id="preview-information", variant="primary")
                    yield Button("Files / context", id="capture-options-toggle")
                    yield Button("Back", id="close-information")
                pending = capture.progress(self.state)["pending_chunks"]
                if pending:
                    yield Button(f"Continue saved information ({pending} parts)", id="continue-information")
            with Vertical(id="capture-preview-stage"):
                yield Static("Review the selected information and existing context below. Suggestions will wait for your review.", markup=False)
                yield TextArea("", read_only=True, id="information-preview")
                with Horizontal(classes="row"):
                    yield Button("Save & understand", id="understand-information", variant="primary",
                                 disabled=not understanding.enabled(self.state))
                    yield Button("Save locally", id="save-information")
                    yield Button("Edit", id="edit-information")
            yield Static("", id="information-status", markup=False)

    def on_mount(self):
        self.query_one("#capture-preview-stage").display = False
        self.query_one("#capture-options").display = False
        self.query_one("#information-text", TextArea).focus()

    def values(self):
        return {"text": self.query_one("#information-text", TextArea).text,
                "title": self.query_one("#information-title", Input).value,
                "paths": self.query_one("#information-paths", TextArea).text,
                "experience": self.query_one("#information-experience", Select).value or None}

    def action_back(self):
        if self.busy:
            return
        if self.plan is not None:
            self.edit()
        else:
            self.app.capture_draft = self.values()
            self.dismiss()

    def edit(self):
        self.plan = None
        self.query_one("#capture-preview-stage").display = False
        self.query_one("#capture-entry").display = True
        self.query_one("#information-status", Static).update("")
        self.query_one("#information-text", TextArea).focus()

    @on(Button.Pressed)
    @work(group="capture-action")
    async def clicked(self, event):
        event.stop()
        if self.busy:
            return
        name = event.button.id
        if name == "close-information":
            self.action_back()
            return
        if name == "edit-information":
            self.edit()
            return
        if name == "capture-options-toggle":
            options = self.query_one("#capture-options", Collapsible)
            options.display = not options.display
            options.collapsed = not options.display
            if options.display:
                self.query_one("#information-paths", TextArea).focus()
            else:
                self.query_one("#information-text", TextArea).focus()
            return
        if name == "continue-information":
            self.app.capture_draft = self.values()
            self.dismiss({"continue": True})
            return
        self.busy = True
        try:
            from .ui import offload
            values = self.values()
            values["paths"] = [line.strip() for line in values["paths"].splitlines() if line.strip()]
            if name == "preview-information":
                self.query_one("#information-status", Static).update("Preparing your preview…")
                self.plan = await offload(capture.preview, self.flow, **values)
                self.query_one("#information-preview", TextArea).load_text(capture.preview_text(self.plan))
                self.query_one("#capture-entry").display = False
                self.query_one("#capture-preview-stage").display = True
                self.query_one("#information-status", Static).update("" if understanding.enabled(self.state) else
                    "AI is paused. Save locally now; enable AI from More when you want suggestions.")
                self.query_one("#information-preview", TextArea).focus()
            elif name in ("save-information", "understand-information") and self.plan is not None:
                self.query_one("#information-status", Static).update("Saving your original information…")
                entries = await offload(capture.save, self.flow, plan=self.plan)
                self.app.capture_draft = {}
                self.dismiss({"entries": entries, "plan": self.plan,
                              "understand": name == "understand-information"})
        except (ValueError, OSError, KeyError, TypeError) as exc:
            self.query_one("#information-status", Static).update(str(exc))
        finally:
            self.busy = False


class PendingCaptureDialog(ModalScreen):
    """Explicitly preview and resume already saved information."""

    BINDINGS = [("escape", "dismiss", "Back")]

    def __init__(self, flow, plan):
        super().__init__()
        self.flow, self.plan = flow, plan

    def compose(self):
        with Vertical(classes="dialog"):
            yield Label("Continue understanding")
            yield Static("Your originals are already saved. Review the next selected information and context before continuing.", markup=False)
            yield TextArea(capture.preview_text(self.plan), read_only=True, id="pending-information-preview")
            if not understanding.enabled(self.flow.load()):
                yield Static("AI is paused. Enable it from More → AI understanding when you want suggestions.", markup=False)
            with Horizontal(classes="row"):
                yield Button("Understand saved information", id="resume-information", variant="primary",
                             disabled=not understanding.enabled(self.flow.load()))
                yield Button("Back", id="close-pending-information")

    @on(Button.Pressed)
    def clicked(self, event):
        event.stop()
        self.dismiss(self.plan if event.button.id == "resume-information" else None)
