"""AI settings; paid processing stays in the previewed capture workflow."""

from textual import on
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select, Static, TextArea

from . import capture, openai_api, understanding


class UnderstandingDialog(ModalScreen):
    BINDINGS = [("escape", "dismiss", "Back")]

    def __init__(self, flow):
        super().__init__()
        self.flow = flow
        self.state = flow.load()
        self.busy = False

    def compose(self):
        config = self.state.get("understanding", understanding.empty())["config"]
        chosen = understanding.pending(self.state)[:understanding.MAX_ANSWERS]
        key = openai_api.key_name()
        with Vertical(classes="dialog"):
            yield Label("AI understanding settings")
            yield Static(understanding.summary(self.state), id="ai-summary", markup=False)
            yield Static("Saving settings enables OpenAI within your total cap. No information is sent from this screen. "
                         "Use Add information to preview selected text, files and relevant existing knowledge before processing. "
                         "API charges are separate from Codex usage.", markup=False)
            yield Select([(name, name) for name in openai_api.MODELS], value=config["model"], allow_blank=False, id="ai-model")
            yield Input(value=str(config["budget_usd"] or 1), placeholder="Total API spending cap in USD", id="ai-budget")
            yield Static("Total cap in USD, including previous calls. It does not reset on restart.", markup=False)
            preview = capture.pending_preview(self.flow) if capture.pending(self.state) else understanding.preview_text(chosen)
            yield TextArea(preview, read_only=True, id="ai-preview")
            yield Static(f"Key available from {key}" if key else "Set OPENM_AI_API_KEY or OPENAI_API_KEY in the shell that launches Foundry.",
                         id="ai-message", markup=False)
            with Horizontal(classes="row"):
                yield Button("Save settings", id="ai-start", variant="primary", disabled=not key)
                yield Button("Pause AI", id="ai-pause", disabled=not config["enabled"])

    @on(Button.Pressed)
    async def clicked(self, event):
        event.stop()
        if self.busy:
            return
        self.busy = True
        try:
            from .ui import offload
            if event.button.id == "ai-pause":
                await offload(understanding.pause, self.flow)
            elif event.button.id == "ai-start":
                await offload(understanding.configure, self.flow,
                    budget_usd=float(self.query_one("#ai-budget", Input).value),
                    model=self.query_one("#ai-model", Select).value)
                await offload(capture.from_answers, self.flow,
                    answer_ids=[a["id"] for a in understanding.pending(self.flow.load())])
                self.app.notify("AI settings saved. Add information → Continue saved information previews what to understand next.", markup=False)
            self.dismiss(True)
        except (ValueError, OSError) as exc:
            self.query_one("#ai-message", Static).update(str(exc))
        finally:
            self.busy = False
