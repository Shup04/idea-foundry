"""Native Textual capture, review and explicitly enabled answer understanding."""

import asyncio
from datetime import date
from concurrent.futures import ThreadPoolExecutor
from functools import partial

from rich.text import Text
from rich.markdown import Markdown
from rich.theme import Theme

from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (Button, Checkbox, Footer, Header, Input, Label, OptionList, Select, Tree,
                             Static, TabbedContent, TabPane, TextArea)
from textual.widgets.option_list import Option

from . import capture, exchange, knowledge, profile, understanding, views
from .storage import atomic_text
from .validation import require
from .workflow import possible_matches, selected_file, uid
from .knowledge import Knowledge
from .ui_skillmap import ExperiencePanel


async def offload(operation, *args, **kwargs):
    # An owned, short-lived executor avoids Python 3.14 default-executor shutdown
    # hangs observed on the native host. Network calls use the same responsive
    # bridge; no nested model process or agent harness is started.
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="foundry-file") as pool:
        future = asyncio.get_running_loop().run_in_executor(pool, partial(operation, *args, **kwargs))
        # Native terminal checks also found delayed cross-thread wakeups when
        # there were no other loop timers. A bounded wait keeps startup moving.
        while not future.done():
            await asyncio.wait((future,), timeout=0.05)
        return future.result()


class ProfileMarkdown(Markdown):
    def __rich_console__(self, console, options):
        with console.use_theme(Theme({"markdown.h2": "bold #e5e5e5 not dim not reverse", "markdown.h3": "bold #e5e5e5 not dim not reverse"})):
            yield from super().__rich_console__(console, options)


class ProfileContent(Static):
    """Readable, local Markdown without Textual's default-executor parser."""

    source = ""

    def show_document(self, text):
        self.source = text
        self.update(ProfileMarkdown(text, hyperlinks=False))


class Reading(ModalScreen):
    BINDINGS = [("escape", "dismiss", "Close")]

    def __init__(self, title, text):
        super().__init__()
        self.heading, self.text = title, text

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(self.heading, markup=False)
            yield TextArea(self.text, read_only=True, id="reading-text")
            yield Button("Close", id="close-reading")

    @on(Button.Pressed, "#close-reading")
    def close(self):
        self.dismiss()


class SourceDialog(ModalScreen):
    BINDINGS = [("escape", "dismiss", "Cancel")]

    def __init__(self, workflow):
        super().__init__()
        self.workflow, self.selection = workflow, None

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label("Add selected text · " + self.workflow.dataset.upper())
            yield Input(placeholder="Exact Markdown or text file path", id="source-path")
            with Horizontal(classes="row"):
                yield Input(value="1", placeholder="First line", id="first-line", type="integer")
                yield Input(placeholder="Last line (blank = end)", id="last-line", type="integer")
                yield Button("Preview", id="preview-source")
            yield Select([("These are my own words", "my_words"),
                          ("A supplied description or summary", "supplied_summary"),
                          ("Generated content (cannot describe you)", "generated")],
                         prompt="Attribute the selected text", id="authorship")
            yield TextArea("Choose a file and preview its selected lines. Nothing is sent for analysis.", read_only=True, id="source-preview")
            yield Checkbox("This is synthetic test material" if self.workflow.dataset == "synthetic" else
                           "This is personal source material, not synthetic/demo history", id="source-attestation")
            yield Static("", id="source-error", markup=False)
            yield Button("Add this selection locally", id="add-selection", disabled=True, variant="primary")

    @on(Input.Changed)
    def invalidate(self):
        self.selection = None
        self.query_one("#add-selection", Button).disabled = True

    @on(Button.Pressed, "#preview-source")
    @work(exclusive=True)
    async def preview(self):
        try:
            first = int(self.query_one("#first-line", Input).value)
            last = self.query_one("#last-line", Input).value
            selection = await offload(selected_file, self.query_one("#source-path", Input).value,
                                                first, int(last) if last else None)
            self.selection = selection
            self.query_one("#source-preview", TextArea).load_text(selection["text"])
            self.query_one("#add-selection", Button).disabled = False
            self.query_one("#source-error", Static).update(f"Lines {selection['first']}–{selection['last']} · {len(selection['text'])} characters. Only this text will be added.")
        except (OSError, ValueError) as exc:
            self.query_one("#source-error", Static).update(str(exc))

    @on(Button.Pressed, "#add-selection")
    @work(exclusive=True)
    async def add(self):
        try:
            require(self.selection is not None, "preview the selection first")
            require(self.query_one("#source-attestation", Checkbox).value, "confirm the source dataset")
            sid = await offload(self.workflow.add_source, self.selection,
                authorship=self.query_one("#authorship", Select).value, dataset=self.workflow.dataset)
            self.dismiss(sid)
        except (OSError, ValueError) as exc:
            self.query_one("#source-error", Static).update(str(exc))


class HandoffDialog(ModalScreen):
    BINDINGS = [("escape", "dismiss", "Cancel")]

    def __init__(self, workflow, request):
        super().__init__()
        self.workflow, self.request = workflow, request

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label("Review exactly what you will hand to Codex")
            yield Static("Manual analysis. Foundry does not launch Codex or send data. Your existing session's permissions remain your responsibility.", markup=False)
            yield TextArea(exchange.prompt(self.request), read_only=True, id="handoff-preview")
            yield Checkbox("I approve this displayed content for model processing via manual handoff", id="approve-content")
            yield Static("", id="handoff-error", markup=False)
            yield Button("Approve & prepare handoff", id="export-handoff", disabled=True, variant="primary")

    @on(Checkbox.Changed, "#approve-content")
    def approval(self, event):
        self.query_one("#export-handoff", Button).disabled = not event.value

    @on(Button.Pressed, "#export-handoff")
    @work(exclusive=True)
    async def export(self):
        try:
            path = await offload(self.workflow.approve_export, self.request,
                                           approved=self.query_one("#approve-content", Checkbox).value)
            self.dismiss(str(path))
        except (OSError, ValueError, KeyError) as exc:
            self.query_one("#handoff-error", Static).update(str(exc))


class ResponseDialog(ModalScreen):
    BINDINGS = [("escape", "dismiss", "Cancel")]

    def __init__(self, workflow, run):
        super().__init__()
        self.workflow, self.run = workflow, run

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label("Import the manual Codex response")
            yield Static("Paste the returned JSON unchanged below, or select the exact saved response file. You do not need to write or edit JSON.", markup=False)
            yield Input(placeholder="Response file path (optional when pasting)", id="response-path")
            yield TextArea(id="response-paste")
            yield Static("", id="response-error", markup=False)
            yield Button("Validate & import", id="import-response", variant="primary")

    @on(Button.Pressed, "#import-response")
    @work(exclusive=True)
    async def import_result(self):
        button = self.query_one("#import-response", Button)
        button.disabled = True
        self.query_one("#response-error", Static).update("Validating response… the interface remains available.")
        try:
            path = self.query_one("#response-path", Input).value.strip()
            text = self.query_one("#response-paste", TextArea).text.strip()
            require(bool(path) != bool(text), "choose a file or paste the response, not both")
            if text:
                require(len(text.encode("utf-8")) <= exchange.MAX_RESPONSE, "response exceeds 120 KB")
                path = self.workflow.path / "exchange" / f"paste-{uid('')}.txt"
                await offload(atomic_text, path, text)
            await offload(self.workflow.import_response, self.run["id"], path)
            self.dismiss(True)
        except (OSError, ValueError, KeyError, TypeError, StopIteration) as exc:
            self.query_one("#response-error", Static).update("Import failed; your knowledge graph is unchanged. " + str(exc))
        finally:
            button.disabled = False


class ReviewDialog(ModalScreen):
    BINDINGS = [("escape", "dismiss", "Cancel")]

    def __init__(self, workflow, proposal, action):
        super().__init__()
        self.workflow, self.proposal, self.review_action = workflow, proposal, action

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label({"accept": "Confirm this statement", "reject": "Reject this interpretation", "correct": "Write the accurate version"}[self.review_action])
            state = self.workflow.load()
            detail = views.claim_detail(self.proposal, state)
            yield TextArea(detail, read_only=True, classes="review-original")
            if self.review_action != "accept":
                yield Label("Your accurate statement" if self.review_action == "correct" else "Why this interpretation is wrong")
                yield TextArea(id="review-text")
            self.needs_ack = self.review_action == "accept" and any(
                cid != self.proposal["core_id"] for cid in possible_matches(self.proposal["claim"], state))
            if self.needs_ack:
                yield Checkbox("I checked the displayed previous corrections; this acceptance is intentional", id="ack-matches")
            yield Static("", id="review-error", markup=False)
            yield Button("Save " + self.review_action, id="save-review", variant="primary")

    @on(Button.Pressed, "#save-review")
    @work(exclusive=True)
    async def save(self):
        try:
            text = self.query_one("#review-text", TextArea).text if self.review_action != "accept" else ""
            await offload(self.workflow.review, self.proposal["id"], self.review_action, text,
                                   acknowledge_matches=self.query_one("#ack-matches", Checkbox).value if self.needs_ack else False)
            self.dismiss(True)
        except (OSError, ValueError, KeyError) as exc:
            self.query_one("#review-error", Static).update(str(exc))


class StatementDialog(ModalScreen):
    BINDINGS = [("escape", "dismiss", "Cancel")]

    def __init__(self, workflow, state, cid, action):
        super().__init__()
        self.workflow, self.state, self.cid, self.operation = workflow, state, cid, action

    def compose(self) -> ComposeResult:
        claim = next(c for c in self.state["core"]["claims"] if c["id"] == self.cid)
        meta = self.state.get("knowledge", knowledge.empty_knowledge())["details"].get(self.cid, {})
        with Vertical(classes="dialog"):
            yield Label("Correct this statement" if self.operation == "correct" else "Exclude from the current profile")
            yield Static(claim["text"], markup=False)
            if self.operation == "correct":
                options = [(knowledge.LABELS[f], f) for f in (*knowledge.TOPICS, "constraints_preferences")]
                yield Select(options, value=claim["facet"] if claim["facet"] in dict((v, k) for k, v in options) else "claimed_skills",
                             allow_blank=False, id="edit-facet")
                yield Input(value=meta.get("context", "General"), placeholder="Context", id="edit-context")
                with Horizontal(classes="row"):
                    yield Input(value=meta.get("valid_from") or "", placeholder="From YYYY-MM-DD (optional)", id="edit-from")
                    yield Input(value=meta.get("valid_until") or "", placeholder="Until YYYY-MM-DD (optional)", id="edit-until")
            yield TextArea(claim["text"] if self.operation == "correct" else "", id="edit-text")
            yield Static("Write the accurate version." if self.operation == "correct" else "Why should this be excluded? The original stays in history.", id="edit-error", markup=False)
            yield Button("Save change", id="save-edit", variant="primary")

    @on(Button.Pressed, "#save-edit")
    @work(exclusive=True)
    async def save(self):
        try:
            options = {}
            if self.operation == "correct":
                options = {"facet": self.query_one("#edit-facet", Select).value,
                           "context": self.query_one("#edit-context", Input).value,
                           "valid_from": self.query_one("#edit-from", Input).value,
                           "valid_until": self.query_one("#edit-until", Input).value}
            await offload(self.workflow.amend, self.cid, self.operation, self.query_one("#edit-text", TextArea).text, **options)
            self.dismiss(True)
        except (OSError, ValueError, KeyError) as exc:
            self.query_one("#edit-error", Static).update(str(exc))


class ConnectionDialog(ModalScreen):
    BINDINGS = [("escape", "dismiss", "Cancel")]

    def __init__(self, workflow, state, cid):
        super().__init__()
        self.workflow, self.state, self.cid = workflow, state, cid

    def compose(self) -> ComposeResult:
        current = knowledge.statuses(self.state)
        source = next(c for c in self.state["core"]["claims"] if c["id"] == self.cid)
        with Vertical(classes="dialog"):
            yield Label("Connect two statements")
            yield Static(source["text"], markup=False)
            yield Select([(v, k) for k, v in knowledge.RELATIONS.items()], value="related_to", allow_blank=False, id="relation")
            yield Select([(Text(c["text"][:100]), c["id"]) for c in self.state["core"]["claims"]
                          if c["id"] != self.cid and current[c["id"]]["usable"]], prompt="Connect to…", id="link-target")
            yield Label("Explain the connection in your words")
            yield TextArea(id="link-reason")
            yield Static("Connections record your explanation. They are not inferred automatically.", id="link-error", markup=False)
            yield Button("Save connection", id="save-link", variant="primary")

    @on(Button.Pressed, "#save-link")
    @work(exclusive=True)
    async def save(self):
        try:
            await offload(self.workflow.connect, self.cid, self.query_one("#relation", Select).value,
                          self.query_one("#link-target", Select).value, self.query_one("#link-reason", TextArea).text)
            self.dismiss(True)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.query_one("#link-error", Static).update(str(exc))


class MoreMenu(ModalScreen):
    BINDINGS = [("escape", "dismiss", "Back")]

    def __init__(self, state, experience):
        super().__init__()
        self.state, self.experience = state, experience

    def compose(self):
        checkins = self.state.get("skillmap", {}).get("checkins", [])
        due = not checkins or date.fromisoformat(checkins[-1]["review_after"]) <= date.today()
        due = due and not any(s["key"] == "circumstances" and date.fromisoformat(s["until"]) > date.today()
                              for s in self.state.get("skillmap", {}).get("snoozed", []))
        choices = [
            ("experience-details", "Experience details", "Read the evidence, describe a skill, or import a GitHub repository."),
            ("add-experience", "Add an experience", "A project, job, research role or course."),
            ("capture-tab", "Save a specific statement", "Add an already clear statement directly, choosing its category yourself."),
            ("current-circumstances", "Update my circumstances", "An optional check-in is due." if due else "Adjust your priorities, availability or limits when life changes."),
            ("ai-understanding", "AI understanding", "Choose the model, pause AI, or adjust your total OpenAI spending cap."),
            ("add-file", "Import a file", "Choose a file and preview the text you want to keep."),
            ("sources-tab", "Sources and extraction", "Revisit imported files or continue a manual Codex extraction."),
            ("graph-tab", "Browse and correct records", "Inspect, correct or export the statements behind your graph."),
        ]
        self.hints = {key: hint for key, _, hint in choices}
        with Vertical(classes="dialog menu-dialog"):
            yield Label("More")
            yield OptionList(*(Option(Text(title), id=key,
                                      disabled=key == "experience-details" and self.experience in (Select.NULL, "general"))
                               for key, title, hint in choices), id="more-options")
            yield Static("", id="more-description", markup=False)
            yield Static("↑ / ↓ to choose · Enter to open · Esc to return")

    @on(OptionList.OptionHighlighted)
    def explain(self, event):
        self.query_one("#more-description", Static).update(self.hints[event.option.id])

    @on(OptionList.OptionSelected)
    def choose(self, event):
        event.stop()
        self.dismiss(event.option.id)


class FoundryApp(App):
    TITLE = "Idea Foundry · My knowledge graph"
    SUB_TITLE = "Understand me first"
    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [("ctrl+q", "quit", "Quit"), ("f1", "help", "Help"), ("f2", "diagnostics", "Details")]
    CSS = """
    Screen { background: #111923; color: #e1e7ed; }
    Header, Footer { background: #203343; }
    #tabs, ContentSwitcher { height: 1fr; }
    #tabs > ContentTabs { display: none; }
    #navigation { height: 3; padding: 0 2; }
    #page-title { width: 1fr; padding: 1 0; }
    #navigation Button { margin-left: 1; }
    TabPane { height: 1fr; padding: 1 2; overflow-y: auto; }
    .row { height: auto; min-height: 3; }
    .row > * { margin-right: 1; }
    .row > Input { width: 1fr; }
    Button { min-width: 10; }
    Select { width: 1fr; }
    TextArea { border: round #38546a; background: #15212d; }
    #status { height: auto; max-height: 3; padding: 0 2; color: #9dd4cc; }
    #graph-summary { height: auto; max-height: 3; margin-bottom: 1; }
    #graph-body { height: 1fr; min-height: 8; }
    #graph-tree { width: 36%; margin-right: 1; }
    #graph-detail { width: 1fr; }
    #source-content, #profile-content { height: 1fr; min-height: 8; }
    #question { height: auto; margin: 1 0; color: #9dd4cc; }
    #known-context { height: 6; }
    #answer { height: 1fr; min-height: 5; }
    #capture-help { height: auto; }
    #capture-error, #profile-summary { height: auto; max-height: 3; }
    #about-scroll { height: 1fr; min-height: 8; }
    #about-content { height: auto; padding: 0 1; background: #15212d; }
    #about-summary { height: auto; max-height: 3; }
    #capture-entry, #capture-preview-stage { height: 1fr; }
    #capture-fields { height: 1fr; }
    #capture-fields > Static, #capture-preview-stage > Static { height: auto; margin-bottom: 1; }
    #information-text, #information-preview { height: 1fr; min-height: 5; }
    #information-paths { height: 4; }
    #capture-options Input, #capture-options Select { margin-bottom: 1; }
    #handoff-bar { height: auto; padding: 0 2; background: #192c38; }
    #handoff-status { width: 1fr; height: auto; }
    .dialog { width: 90%; height: 90%; border: thick #4b8b95; padding: 1 2; background: #15212d; overflow-y: auto; }
    ModalScreen { align: center middle; background: #000000 55%; }
    .dialog > Label { margin-bottom: 1; }
    .dialog > TextArea { height: 1fr; min-height: 5; }
    .dialog > Static { height: auto; max-height: 5; }
    .dialog > Input, .dialog > Select { margin-bottom: 1; }
    .dialog Checkbox { height: auto; min-height: 3; }
    ExperiencePanel { height: 1fr; }
    #experience-detail { height: 1fr; min-height: 8; }
    #map-summary, #map-status { height: auto; max-height: 3; }
    #github-files { height: 1fr; min-height: 8; }
    .cap-label { width: 28; padding: 1 0; }
    #next-step { height: 1fr; padding: 1 2; margin-top: 1; background: #15212d; }
    #question-content { height: 1fr; }
    #next-heading { text-style: bold; height: auto; margin-bottom: 1; }
    #experience-summary { height: auto; color: #b0bec8; margin-bottom: 1; }
    #next-question { height: auto; max-width: 85; margin-bottom: 1; }
    #question-reassurance { height: auto; color: #b0bec8; margin-top: 1; }
    .menu-dialog { max-width: 90; height: 85%; }
    #more-options { height: 1fr; border: none; background: #15212d; }
    #more-options > .option-list--option { padding: 0 1; }
    #more-description { min-height: 3; height: auto; margin: 1; color: #b0bec8; }
    .reflection-evidence { height: 8; }
    #reflection-question { max-height: 100%; }
    Screen.compact #map-summary, Screen.compact #next-heading,
    Screen.compact #experience-summary, Screen.compact #question-reassurance,
    Screen.compact #status { display: none; }
    """

    def __init__(self, workflow):
        super().__init__()
        self.workflow = Knowledge(workflow.path, workflow.dataset)
        self.state = self.workflow.load()
        self.refreshing = False
        self.selected_claim = None
        self.action_pending = False
        self.ai_busy = False
        self.capture_draft = {}

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Static("Fictional demonstration" if self.workflow.dataset == "synthetic" else "Saved on this device", id="status", markup=False)
        with Horizontal(id="navigation"):
            yield Static("", id="page-title", markup=False)
            yield Button("Back to home", id="home-nav")
            yield Button("Review suggestions", id="review-nav")
            yield Button("More", id="more-nav")
        with TabbedContent(id="tabs"):
            with TabPane("Experiences", id="map-tab"):
                yield ExperiencePanel(self.workflow)
            with TabPane("About me", id="about-tab"):
                yield Static("A source-backed view of what you have shared. Search stays on this device.", id="about-summary", markup=False)
                with Horizontal(classes="row"):
                    yield Input(placeholder="Search what you know about me", id="about-search")
                    yield Button("Export", id="export-about")
                with VerticalScroll(id="about-scroll"):
                    yield ProfileContent("", id="about-content", markup=False)
                with Horizontal(classes="row"):
                    yield Button("Add information", id="about-add", variant="primary")
                    yield Button("Explore records", id="about-records")
            with TabPane("My graph", id="graph-tab"):
                yield Static("", id="graph-summary", markup=False)
                with Horizontal(classes="row"):
                    yield Input(placeholder="Search statements and context", id="graph-search")
                    yield Select([("Current profile", "current"), ("Needs attention", "attention"),
                                  ("All history", "all")], value="current", allow_blank=False, id="graph-filter")
                    yield Button("Export", id="export-profile")
                with Horizontal(id="graph-body"):
                    yield Tree("Me", id="graph-tree")
                    yield TextArea("", read_only=True, id="graph-detail")
                with Horizontal(classes="row"):
                    yield Button("Add detail", id="add-detail", variant="primary")
                    yield Button("Correct", id="edit-claim", disabled=True)
                    yield Button("Exclude", id="exclude-claim", disabled=True)
                    yield Button("Connect", id="connect-claim", disabled=True)
                with Horizontal(classes="row"):
                    yield Select([], prompt="Connections for this statement", id="link-select")
                    yield Button("Remove link", id="retire-link", disabled=True)
            with TabPane("Build profile", id="capture-tab"):
                yield Static("Add one detail at a time, or choose Sources to reuse a file. Your wording is saved exactly.", id="capture-help", markup=False)
                yield Select([(topic[0], facet) for facet, topic in knowledge.TOPICS.items()],
                             value=knowledge.next_question(self.state)[0], allow_blank=False, id="topic")
                yield Static("", id="question", markup=False)
                yield TextArea("", read_only=True, id="known-context")
                yield TextArea(id="answer")
                yield Input(placeholder="Context (e.g. professional work, side projects); blank = general", id="answer-context")
                with Horizontal(classes="row"):
                    yield Input(placeholder="From YYYY-MM-DD (optional)", id="answer-from")
                    yield Input(placeholder="Until YYYY-MM-DD (optional)", id="answer-until")
                yield Static("", id="capture-error", markup=False)
                with Horizontal(classes="row"):
                    yield Button("Save detail", id="save-answer", variant="primary")
                    yield Button("Another topic", id="next-topic")
                    yield Button("Import a file", id="capture-import")
            with TabPane("Review", id="profile-tab"):
                yield Static("", id="profile-summary", markup=False)
                with Horizontal(classes="row"):
                    yield Select([("Awaiting review", "pending"), ("Review history", "all")], value="pending", allow_blank=False, id="review-filter")
                    yield Select([("All areas", "all"), *((knowledge.LABELS[f], f) for f in knowledge.FACETS)],
                                 value="all", allow_blank=False, id="review-topic")
                    yield Select([], prompt="Choose a suggested statement", id="claim-select")
                yield TextArea("No suggestions to review. Your own answers go straight into My graph.", read_only=True, id="profile-content")
                with Horizontal(classes="row"):
                    yield Button("Accept", id="accept-claim", variant="primary")
                    yield Button("Correct", id="correct-claim")
                    yield Button("Reject", id="reject-claim")
            with TabPane("Sources", id="sources-tab"):
                with Horizontal(classes="row"):
                    yield Button("Add file", id="add-file", variant="primary")
                    yield Select([], prompt="Choose an existing source", id="source-select")
                yield TextArea("Select a file, preview it, and choose which lines to keep.", read_only=True, id="source-content")
                with Horizontal(classes="row"):
                    yield Button("Read listed details locally", id="extract-listed")
                    yield Button("Extract with Codex", id="analyse-source")
                with Horizontal(id="handoff-bar"):
                    yield Static("No pending extraction", id="handoff-status", markup=False)
                    yield Button("Open handoff", id="open-handoff", disabled=True)
                    yield Button("Import reply", id="open-response", disabled=True)
                    yield Button("Cancel", id="cancel-handoff", disabled=True)
        yield Footer()

    async def on_mount(self):
        await self.reload()
        self.show_navigation()

    def on_resize(self, event):
        if self.screen_stack:
            self.screen_stack[0].set_class(event.size.height < 30, "compact")

    @on(TabbedContent.TabActivated, "#tabs")
    def show_navigation(self):
        if not self.is_mounted:
            return
        active = self.query_one("#tabs", TabbedContent).active
        titles = {"map-tab": "Home", "about-tab": "About me", "graph-tab": "Your records", "capture-tab": "Save a statement",
                  "profile-tab": "Review suggestions", "sources-tab": "Sources and extraction"}
        self.query_one("#page-title", Static).update(titles.get(active, "Home"))
        self.query_one("#home-nav", Button).display = active != "map-tab"
        self.query_one("#review-nav", Button).display = active != "profile-tab"

    def navigate(self, page):
        self.set_focus(None)
        self.query_one("#tabs", TabbedContent).active = page
        self.show_navigation()
        target = {"map-tab": "#add-information", "about-tab": "#about-search", "capture-tab": "#answer", "profile-tab": "#claim-select",
                  "graph-tab": "#graph-search", "sources-tab": "#source-select"}[page]
        self.query_one(target).focus()

    def more_selected(self, action):
        if not action:
            return
        if action.endswith("-tab"):
            self.navigate(action)
        elif action == "add-file":
            self.open_capture()
        elif action == "ai-understanding":
            from .ui_understanding import UnderstandingDialog
            self.push_screen(UnderstandingDialog(self.workflow), self.reload)
        else:
            self.query_one(ExperiencePanel).act(action)

    def choose(self, selector, options):
        widget = self.query_one(selector, Select)
        old = widget.value
        widget.set_options([(Text(title), value) for title, value in options])
        ids = [value for _, value in options]
        widget.value = old if old in ids else ids[0] if ids else Select.NULL

    async def reload(self, _result=None):
        self.refreshing = True
        self.state = await offload(self.workflow.load)
        self.choose("#source-select", [(f"v{s['version']} · {s['text'][:65].replace(chr(10), ' ')}", s["id"])
                                      for s in self.state["core"]["sources"]
                                      if s["origin"].startswith(("file-", "github:")) or s["kind"] == "user_supplied_summary"])
        self.refreshing = False
        self.show_graph()
        self.show_question()
        self.show_reviews()
        self.show_source()
        self.show_about()
        self.query_one(ExperiencePanel).update_state(self.state)
        count = sum(p["status"] == "proposed" for p in self.state["proposals"])
        self.query_one("#review-nav", Button).label = f"Review suggestions ({count})" if count else "Review suggestions"
        run = self.pending()
        self.query_one("#handoff-status", Static).update(
            f"{run['stage']} handoff: {run['status']}" if run else "Manual extraction · No background jobs")
        for name in ("open-handoff", "open-response", "cancel-handoff"):
            self.query_one(f"#{name}", Button).disabled = run is None

    def pending(self):
        return next((r for r in reversed(self.state["runs"]) if r["status"] in ("waiting", "failed")), None)

    def open_capture(self, question=None):
        from .ui_capture import CaptureDialog
        draft = dict(self.capture_draft)
        if question and not draft.get("text"):
            draft["title"] = question
        self.push_screen(CaptureDialog(self.workflow, draft), self.information_saved)

    async def information_saved(self, result):
        await self.reload()
        if not result:
            return
        if result.get("continue"):
            from .ui_capture import PendingCaptureDialog
            try:
                plan = await offload(capture.pending_plan, self.workflow)
                self.push_screen(PendingCaptureDialog(self.workflow, plan), self.continue_information)
            except (ValueError, OSError) as exc:
                self.notify(str(exc), severity="warning", markup=False)
        elif result.get("understand"):
            self.process_information(result["entries"], plan=result["plan"])
        else:
            self.notify("Original information saved. Open Add information to understand it later.", markup=False)

    def continue_information(self, plan):
        if plan:
            self.process_information(plan=plan)

    @work(group="information-understanding")
    async def process_information(self, entry_ids=None, plan=None):
        if self.ai_busy:
            self.notify("Your information is saved. Understanding is already running; continue saved information when it finishes.", markup=False)
            return
        self.ai_busy = True
        try:
            self.query_one("#map-status", Static).update("Your originals are saved. Reading information and its existing context…")
            result = await offload(capture.process, self.workflow, entry_ids=entry_ids, plan=plan)
            await self.reload()
            count = len(result["proposals"])
            message = f"{count} suggestions ready for review." if count else "Your originals are saved; no new suggestions in this pass."
            if result.get("error"):
                message += " " + result["error"]
            if result.get("remaining_chunks"):
                message += " More saved information remains. Continue from Add information."
            if capture.progress(self.state)["incomplete_chunks"]:
                message += " Some details need attention; see About me."
            self.query_one("#map-status", Static).update(message)
            self.notify(message, severity="warning" if result.get("error") else "information", markup=False, timeout=10)
            if count and len(self.screen_stack) == 1:
                self.navigate("profile-tab")
        except (ValueError, OSError, KeyError, TypeError) as exc:
            await self.reload()
            message = "Your originals are saved. " + str(exc) + " Continue from Add information."
            self.query_one("#map-status", Static).update(message)
            self.notify(message, severity="warning", markup=False, timeout=12)
        finally:
            self.ai_busy = False

    def show_about(self):
        query = self.query_one("#about-search", Input).value
        self.query_one("#about-content", ProfileContent).show_document(profile.render(self.state, query=query))

    @on(Input.Changed, "#about-search")
    def about_search_changed(self):
        if self.is_mounted and not self.refreshing:
            self.show_about()
            self.query_one("#about-scroll", VerticalScroll).scroll_home(animate=False)

    @work(group="answer-understanding")
    async def understand_answers(self, answer_ids=None):
        """Bring saved interview evidence into the shared capture/review path."""
        try:
            if answer_ids is None:
                state = await offload(self.workflow.load)
                answer_ids = [answer["id"] for answer in understanding.pending(state)]
            entries = await offload(capture.from_answers, self.workflow, answer_ids=list(answer_ids))
            self.process_information(entries or None)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            await self.reload()
            message = "Your answers are saved. " + str(exc)
            self.query_one("#map-status", Static).update(message)
            self.notify(message, severity="warning", markup=False, timeout=12)

    def show_graph(self):
        status = knowledge.statuses(self.state)
        current = sum(v["usable"] for v in status.values())
        pending = sum(p["status"] == "proposed" for p in self.state["proposals"])
        self.query_one("#graph-summary", Static).update(
            f"{current} current statements · {pending} awaiting review\nChoose a statement for its evidence and connections. Empty areas are prompts to explore.")
        query = self.query_one("#graph-search", Input).value.casefold().strip()
        mode = self.query_one("#graph-filter", Select).value
        tree = self.query_one("#graph-tree", Tree)
        tree.clear()
        selected_node = None
        details = self.state.get("knowledge", knowledge.empty_knowledge())["details"]
        for facet in knowledge.FACETS:
            matches = [c for c in self.state["core"]["claims"] if c["facet"] == facet
                       and (mode == "all" or (status[c["id"]]["usable"] if mode == "current" else
                            status[c["id"]]["status"] in ("contradicted", "expired", "upcoming", "tentative", "source_withdrawn")))
                       and query in (c["text"] + " " + knowledge.LABELS[facet] + " " + details.get(c["id"], {}).get("context", "")).casefold()]
            if not matches and (query or mode != "current"):
                continue
            expand = bool(query) or len(matches) <= 5 or any(c["id"] == self.selected_claim for c in matches)
            group = tree.root.add(Text(f"{knowledge.LABELS[facet]} ({len(matches)})"), expand=expand)
            for claim in matches:
                label = claim["text"].replace("\n", " ")
                node = group.add_leaf(Text(label), data=claim["id"])
                if claim["id"] == self.selected_claim:
                    selected_node = node
        tree.root.expand()
        if selected_node:
            tree.select_node(selected_node)
        else:
            self.selected_claim = None
        self.show_selected()

    def show_selected(self):
        cid = self.selected_claim
        self.query_one("#graph-detail", TextArea).load_text(knowledge.claim_text(self.state, cid) if cid else
            "YOUR KNOWLEDGE GRAPH\n\n" + "\n".join(knowledge.issues(self.state)) +
            "\n\nBuild profile adds your own words. Sources reuses uploaded material. Review checks model suggestions.\n\n"
            + "\n".join(f"{row['label']}: {row['current']} current, {row['pending']} awaiting review" for row in knowledge.inventory(self.state)))
        for name in ("edit-claim", "exclude-claim"):
            self.query_one(f"#{name}", Button).disabled = cid is None
        self.query_one("#connect-claim", Button).disabled = not cid or not knowledge.statuses(self.state)[cid]["usable"]
        links = [l for l in self.state.get("knowledge", knowledge.empty_knowledge())["links"]
                 if cid in (l["from"], l["to"]) and l["status"] == "active"]
        self.choose("#link-select", [(f"{knowledge.RELATIONS[l['relation']]} · {l['reason'][:65]}", l["id"]) for l in links])
        self.query_one("#retire-link", Button).disabled = not links

    @on(Tree.NodeSelected, "#graph-tree")
    def selected_node(self, event):
        self.selected_claim = event.node.data
        self.show_selected()

    def show_question(self):
        facet = self.query_one("#topic", Select).value
        if facet not in knowledge.TOPICS:
            return
        status = knowledge.statuses(self.state)
        facets = {facet, "constraints_preferences"} if facet in ("preferences", "constraints") else {facet}
        accepted = [c["text"] for c in self.state["core"]["claims"] if c["facet"] in facets and status[c["id"]]["usable"]]
        pending = [p["claim"]["text"] for p in self.state["proposals"] if p["claim"]["facet"] in facets and p["status"] == "proposed"]
        topic = knowledge.TOPICS[facet]
        self.query_one("#question", Static).update(topic[2] if accepted or pending else topic[1])
        text = "ALREADY IN YOUR GRAPH\n" + ("\n".join("• " + s for s in accepted) or "No reviewed statement in this area yet.")
        if pending:
            text += "\n\nAWAITING REVIEW\n" + "\n".join(pending)
        self.query_one("#known-context", TextArea).load_text(text)

    def show_reviews(self):
        pending = sum(p["status"] == "proposed" for p in self.state["proposals"])
        self.query_one("#profile-summary", Static).update(f"{pending} suggestions await your review. Check the wording against its passage.")
        mode = self.query_one("#review-filter", Select).value
        facet = self.query_one("#review-topic", Select).value
        def title(proposal):
            action = self.state.get("memory", {}).get("proposals", {}).get(proposal["id"], {}).get("fact", {}).get("action")
            label = {"add": "Add detail", "support": "Add evidence", "update": "Update existing", "resolve": "Answer a question", "conflict": "Possible conflict"}.get(action, proposal["status"].capitalize())
            if action and proposal["status"] != "proposed":
                label = proposal["status"].capitalize() + " · " + label
            return f"{label} · {proposal['claim']['text'][:90]}"
        self.choose("#claim-select", [(title(p), p["id"])
                                     for p in self.state["proposals"] if (mode == "all" or p["status"] == "proposed")
                                     and (facet == "all" or p["claim"]["facet"] == facet)])
        self.show_claim()

    def selected_proposal(self):
        value = self.query_one("#claim-select", Select).value
        return next((p for p in self.state["proposals"] if p["id"] == value), None)

    def show_claim(self):
        p = self.selected_proposal()
        detail = views.claim_detail(p, self.state) if p else "No suggestions awaiting review. Add information whenever you have something to share."
        self.query_one("#profile-content", TextArea).load_text(detail)
        for name in ("accept-claim", "correct-claim", "reject-claim"):
            self.query_one(f"#{name}", Button).disabled = p is None or (name == "accept-claim" and p["status"] != "proposed")

    def show_source(self):
        sid = self.query_one("#source-select", Select).value
        source = next((s for s in self.state["core"]["sources"] if s["id"] == sid), None)
        if source:
            self.query_one("#source-content", TextArea).load_text(f"{source['locator']} · version {source['version']} · {source['kind']}\n\n{source['text']}")
        self.query_one("#analyse-source", Button).disabled = source is None or source["kind"] == "generated"
        self.query_one("#extract-listed", Button).disabled = source is None or source["kind"] == "generated"

    @on(Input.Changed, "#graph-search")
    def search_changed(self):
        if self.is_mounted and not self.refreshing:
            self.show_graph()

    @on(Select.Changed)
    def selection_changed(self, event):
        if self.refreshing or not self.is_mounted:
            return
        handlers = {"topic": self.show_question, "graph-filter": self.show_graph,
                    "review-filter": self.show_reviews, "review-topic": self.show_reviews,
                    "claim-select": self.show_claim, "source-select": self.show_source}
        if event.select.id in handlers:
            handlers[event.select.id]()

    @on(Button.Pressed)
    @work(group="main-action")
    async def clicked(self, event):
        # Do not cancel a file operation after its thread has started. A second
        # click waits for the refreshed state rather than reviewing a stale ID.
        if self.action_pending:
            return
        self.action_pending = True
        name = event.button.id
        try:
            if name == "more-nav":
                eid = self.query_one("#experience-select", Select).value
                self.push_screen(MoreMenu(self.state, eid), self.more_selected)
            elif name in ("home-nav", "review-nav"):
                self.navigate("map-tab" if name == "home-nav" else "profile-tab")
            elif name == "about-add":
                self.open_capture()
            elif name == "about-records":
                self.navigate("graph-tab")
            elif name in ("add-file", "capture-import"):
                self.push_screen(SourceDialog(self.workflow), self.source_added)
            elif name == "save-answer":
                self.selected_claim = await offload(self.workflow.remember, self.query_one("#answer", TextArea).text,
                    self.query_one("#topic", Select).value, context=self.query_one("#answer-context", Input).value,
                    valid_from=self.query_one("#answer-from", Input).value, valid_until=self.query_one("#answer-until", Input).value)
                self.query_one("#answer", TextArea).load_text("")
                for field in ("answer-context", "answer-from", "answer-until"):
                    self.query_one(f"#{field}", Input).value = ""
                await self.reload()
                self.query_one("#capture-error", Static).update("Saved. Add another detail here, or choose Another topic.")
            elif name == "next-topic":
                require(not self.query_one("#answer", TextArea).text.strip(),
                        "Save this detail before moving on, or clear the answer to skip.")
                topics = list(knowledge.TOPICS)
                current = self.query_one("#topic", Select).value
                # Choose a gap after the current topic; skip never becomes an answer.
                ordered = topics[topics.index(current) + 1:] + topics[:topics.index(current) + 1]
                counts = {r["facet"]: r["current"] + r["pending"] for r in knowledge.inventory(self.state)}
                self.query_one("#topic", Select).value = next((f for f in ordered if not counts[f]), ordered[0])
            elif name == "add-detail":
                self.set_focus(None)
                self.query_one("#tabs", TabbedContent).active = "capture-tab"
                self.query_one("#answer", TextArea).focus()
            elif name in ("edit-claim", "exclude-claim") and self.selected_claim:
                self.push_screen(StatementDialog(self.workflow, self.state, self.selected_claim,
                                 "correct" if name == "edit-claim" else "exclude"), self.reload)
            elif name == "connect-claim" and self.selected_claim:
                self.push_screen(ConnectionDialog(self.workflow, self.state, self.selected_claim), self.reload)
            elif name == "retire-link":
                await offload(self.workflow.retire_link, self.query_one("#link-select", Select).value)
                await self.reload()
            elif name in ("export-profile", "export-about"):
                target = await offload(self.workflow.export_profile)
                self.push_screen(Reading("Profile exported locally", f"{target}/about-me.md\n{target}/profile.md\n{target}/graph.json\n\nReadable overview, full reviewed statements, connections and cited passages. Nothing has been transmitted."))
            elif name == "analyse-source":
                request = await offload(self.workflow.prepare, "claims", source_id=self.query_one("#source-select", Select).value)
                self.push_screen(HandoffDialog(self.workflow, request), self.handoff_ready)
            elif name == "extract-listed":
                added = await offload(self.workflow.extract_listed, self.query_one("#source-select", Select).value)
                await self.reload()
                self.set_focus(None)
                self.query_one("#tabs", TabbedContent).active = "profile-tab"
                self.query_one("#claim-select", Select).focus()
                self.notify(f"{len(added)} listed details added for review. No model or network used.")
            elif name in ("accept-claim", "correct-claim", "reject-claim") and self.selected_proposal():
                proposal = self.selected_proposal()
                matches = [cid for cid in possible_matches(proposal["claim"], self.state) if cid != proposal["core_id"]]
                if name == "accept-claim" and not matches:
                    await offload(self.workflow.review, proposal["id"], "accept")
                    await self.reload()
                else:
                    self.push_screen(ReviewDialog(self.workflow, proposal, name.split("-")[0]), self.reload)
            elif name == "open-response" and self.pending():
                self.push_screen(ResponseDialog(self.workflow, self.pending()), self.reload)
            elif name == "open-handoff" and self.pending():
                run = self.pending()
                self.push_screen(Reading("Manual extraction handoff", exchange.prompt(run)))
            elif name == "cancel-handoff" and self.pending():
                await offload(self.workflow.cancel, self.pending()["id"])
                await self.reload()
        except (OSError, ValueError, KeyError, TypeError, StopIteration) as exc:
            self.query_one("#capture-error", Static).update(str(exc))
            self.notify(str(exc), severity="error", markup=False)
        finally:
            self.action_pending = False

    async def source_added(self, sid):
        await self.reload()
        if sid:
            self.set_focus(None)
            self.query_one("#tabs", TabbedContent).active = "sources-tab"
            self.query_one("#source-select", Select).value = sid
            self.query_one("#source-select", Select).focus()

    async def handoff_ready(self, path):
        await self.reload()
        if path:
            self.push_screen(Reading("Ready for manual extraction", f"Open this local file in your Codex session:\n\n{path}\n\nAsk it to follow the extraction contract. Return here and use Import reply. Suggestions await your review before entering your graph."))

    def action_help(self):
        self.push_screen(Reading("Your knowledge graph", "Add information accepts your own words or exact files you choose. Preview shows the information and existing context before you save and understand it. Originals are saved first; you can continue unfinished processing from Add information.\n\n"
            "About me gives you a readable overview, gaps, local evidence search and an export. View map opens the connected graph in your browser. Home offers one question about a gap; choose an experience for its project questions.\n\n"
            "Review suggestions is where you accept, correct or reject interpretations and proposed updates. More → AI understanding controls OpenAI and your cumulative API cap.\n\n"
            "More holds occasional tools. Experience details contains evidence, skill descriptions and GitHub imports for the selected experience. You can also add an experience, import a file, update circumstances, or browse and correct your records. Each menu item explains what it does.\n\n"
            "Back to home returns to the next question. Tab / Shift+Tab moves focus; Enter activates; Escape closes dialogs; Ctrl+Q quits."))

    def action_diagnostics(self):
        self.push_screen(Reading("Workspace details", f"Workspace: {self.workflow.path}\nDataset: {self.workflow.dataset}\n\n"
            + "\n".join(knowledge.issues(self.state)) + "\n\nSources, statements, corrections and relationships are versioned locally. Historical idea records are retained. Model usage and cost are unknown for manual handoffs.\n\n"
            "No file scanning or unattended jobs. Enabled AI understanding runs only when you save a project answer or choose to process saved answers.\n\n"
            + understanding.summary(self.state)))
