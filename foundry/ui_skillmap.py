"""Experience interviews and explicitly selected repository evidence."""

import webbrowser

from rich.text import Text
from textual import on, work
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Collapsible, Input, Label, Select, Static, TextArea

from . import github, profile, skillmap, solar, understanding
from .validation import require


async def offload(operation, *args, **kwargs):
    from .ui import offload as run
    return await run(operation, *args, **kwargs)


class EntryDialog(ModalScreen):
    BINDINGS = [("escape", "dismiss", "Cancel")]

    def __init__(self, flow):
        super().__init__()
        self.flow = flow
        self.busy = False

    def failed(self, error):
        self.query_one(".entry-error", Static).update(str(error))


class Reflection(EntryDialog):
    def __init__(self, flow, experience):
        super().__init__(flow)
        self.state = flow.load()
        questions = skillmap.questions(self.state, experience)
        self.question = questions[0] if questions else None

    def compose(self):
        with Vertical(classes="dialog"):
            yield Label("Tell me about this experience")
            yield Static(self.question["prompt"] if self.question else "No unanswered questions here right now.", id="reflection-question", markup=False)
            if self.question:
                claims = {c["id"]: c for c in self.state["core"]["claims"]}
                with Collapsible(title="What this question draws on", collapsed=True):
                    yield TextArea("\n\n".join(claims[c]["text"] for c in self.question["claim_ids"]), read_only=True, classes="reflection-evidence")
                yield TextArea(id="reflection-answer")
                if understanding.enabled(self.state):
                    yield Static("Saving sends this answer, question, and relevant existing profile context to OpenAI for reviewed suggestions within your API cap.", markup=False)
                yield Static("", classes="entry-error", markup=False)
                with Horizontal(classes="row"):
                    yield Button("Save & understand" if understanding.enabled(self.state) else "Save answer", id="save-reflection", variant="primary")
                    yield Button("Ask me later", id="later-reflection")
            else:
                yield Button("Close", id="close-reflection")

    @on(Button.Pressed)
    async def clicked(self, event):
        event.stop()
        if self.busy:
            return
        self.busy = True
        try:
            if event.button.id == "save-reflection":
                state = await offload(skillmap.answer, self.flow, self.question["experience"], self.question["topic"],
                              self.query_one("#reflection-answer", TextArea).text, question=self.question["prompt"],
                              follow_up_of=self.question.get("follow_up_of"))
                if understanding.enabled(state):
                    self.app.understand_answers({state["skillmap"]["answers"][-1]["id"]})
            elif event.button.id == "later-reflection":
                await offload(skillmap.snooze, self.flow, self.question["key"])
            self.dismiss(True)
        except (ValueError, OSError) as exc:
            self.failed(exc)
        finally:
            self.busy = False


class Capability(EntryDialog):
    def __init__(self, flow, experience, skill):
        super().__init__(flow)
        self.experience, self.skill = experience, skill
        graph = skillmap.catalog(flow.load())
        names = {n["id"]: n["label"] for n in graph["nodes"]}
        self.heading = f"{names[skill]} in {names[experience]}"
        self.prior = next(l for l in graph["links"] if l["from"] == experience and l["to"] == skill).get("assessment", {})

    def compose(self):
        with Vertical(classes="dialog"):
            yield Label(self.heading, markup=False)
            yield Static("Describe this part of this experience. These answers do not assign a global skill score.")
            yield Select([(v, k) for k, v in skillmap.ROLES.items()], value=self.prior.get("role", "unknown"), allow_blank=False, id="cap-role")
            for key, label in skillmap.DIMENSIONS.items():
                with Horizontal(classes="row"):
                    yield Label(label, classes="cap-label")
                    yield Select([(v, k) for k, v in skillmap.DEPTH.items()], value=self.prior.get("depth", {}).get(key, "unknown"), allow_blank=False, id="cap-" + key)
            yield Label("Assistance on this part")
            yield Select([(v, k) for k, v in skillmap.ASSISTANCE.items()], value=self.prior.get("assistance", "unknown"), allow_blank=False, id="cap-assistance")
            yield Label("One example, and anything you are still unsure about")
            yield TextArea(id="cap-note")
            yield Static("", classes="entry-error", markup=False)
            yield Button("Save context", id="save-capability", variant="primary")

    @on(Button.Pressed, "#save-capability")
    async def save(self, event):
        event.stop()
        if self.busy:
            return
        self.busy = True
        try:
            await offload(skillmap.assess, self.flow, self.experience, self.skill,
                role=self.query_one("#cap-role", Select).value,
                depth={k: self.query_one("#cap-" + k, Select).value for k in skillmap.DIMENSIONS},
                assistance=self.query_one("#cap-assistance", Select).value,
                text=self.query_one("#cap-note", TextArea).text)
            self.dismiss(True)
        except (ValueError, OSError) as exc:
            self.failed(exc)
        finally:
            self.busy = False


class AddEntity(EntryDialog):
    def __init__(self, flow, experience=None):
        super().__init__(flow)
        self.experience = experience

    def compose(self):
        with Vertical(classes="dialog"):
            yield Label("Connect a skill" if self.experience else "Add an experience")
            yield Input(placeholder="Name", id="entity-name")
            choices = skillmap.SKILL_TYPES if self.experience else skillmap.EXPERIENCES
            yield Select([(v, k) for k, v in choices.items()], value=next(iter(choices)), allow_blank=False, id="entity-kind")
            yield Label("Describe your experience with it, in your own words")
            yield TextArea(id="entity-note")
            yield Static("", classes="entry-error", markup=False)
            yield Button("Save", id="save-entity", variant="primary")

    @on(Button.Pressed, "#save-entity")
    async def save(self, event):
        event.stop()
        if self.busy:
            return
        self.busy = True
        try:
            args = (self.query_one("#entity-name", Input).value, self.query_one("#entity-kind", Select).value,
                    self.query_one("#entity-note", TextArea).text)
            if self.experience:
                await offload(skillmap.add_skill, self.flow, self.experience, *args)
            else:
                await offload(skillmap.add_experience, self.flow, *args)
            self.dismiss(True)
        except (ValueError, OSError) as exc:
            self.failed(exc)
        finally:
            self.busy = False


class CheckIn(EntryDialog):
    def __init__(self, flow):
        super().__init__(flow)
        state = flow.load()
        saved = state.get("skillmap", skillmap.empty_map())
        self.prior = ""
        if saved["checkins"]:
            cid = saved["checkins"][-1]["claim_id"]
            self.prior = next(c["text"] for c in state["core"]["claims"] if c["id"] == cid and c["status"] == "active") if any(c["id"] == cid and c["status"] == "active" for c in state["core"]["claims"]) else ""

    def compose(self):
        with Vertical(classes="dialog"):
            yield Label("How life looks lately")
            yield Static("Rough availability, current priorities, and any limits that matter. Update when life changes; we will offer another check-in in about three months.")
            yield TextArea(self.prior, id="checkin-text")
            yield Static("", classes="entry-error", markup=False)
            with Horizontal(classes="row"):
                yield Button("Save update", id="save-checkin", variant="primary")
                yield Button("Still accurate", id="confirm-checkin", disabled=not self.prior)
                yield Button("Ask me later", id="later-checkin")

    @on(Button.Pressed)
    async def save(self, event):
        event.stop()
        if self.busy:
            return
        self.busy = True
        try:
            if event.button.id == "later-checkin":
                await offload(skillmap.snooze, self.flow, "circumstances")
            else:
                await offload(skillmap.check_in, self.flow, self.prior if event.button.id == "confirm-checkin" else self.query_one("#checkin-text", TextArea).text)
            self.dismiss(True)
        except (ValueError, OSError) as exc:
            self.failed(exc)
        finally:
            self.busy = False


class RepositoryDialog(EntryDialog):
    def __init__(self, flow, experience):
        super().__init__(flow)
        self.experience, self.client, self.inventory = experience, github.GitHub(), None
        self.page = 1

    def compose(self):
        with Vertical(classes="dialog"):
            yield Label("Connect repository evidence")
            yield Static("Use your existing GitHub CLI login, including private repositories. Choose a repository, then up to eight files. Imports stay local; source code is never run. Codex analysis is a separate, explicit handoff.")
            with Horizontal(classes="row"):
                yield Button("Load my repos", id="github-connect", variant="primary")
                yield Button("Next page", id="github-more", disabled=True)
                yield Button("Login help", id="github-help")
            yield Select([], prompt="Choose your repository", id="github-repo")
            yield Button("Choose files", id="github-preview")
            yield VerticalScroll(id="github-files")
            yield Static("", id="github-status", classes="entry-error", markup=False)
            yield Button("Import selected files", id="github-import", disabled=True)

    @on(Select.Changed, "#github-repo")
    def changed(self):
        self.inventory = None
        self.query_one("#github-import", Button).disabled = True
        self.query_one("#github-files").remove_children()

    @on(Button.Pressed)
    def clicked(self, event):
        event.stop()
        if not self.busy:
            self.fetch(event.button.id)

    @work()
    async def fetch(self, action):
        if self.busy:
            return
        self.busy = True
        status = self.query_one("#github-status", Static)
        selector = self.query_one("#github-repo", Select)
        selector.disabled = True
        try:
            if action == "github-help":
                status.update("In a terminal, run: gh auth login --hostname github.com --web\nComplete GitHub's browser login, then choose Load my repos. Credentials stay with GitHub CLI.")
            elif action in ("github-connect", "github-more"):
                self.page = self.page + 1 if action == "github-more" else 1
                status.update("Reading your repository list…")
                result = await offload(self.client.repositories, self.page)
                selector.set_options([(Text(r["name"] + (" · private" if r["private"] else "")), r["name"]) for r in result["repositories"]])
                self.query_one("#github-more", Button).disabled = not result["more"]
                status.update(f"Signed in as {result['login']}. Choose a repository you want to import.")
            elif action == "github-preview":
                require(selector.value is not Select.NULL, "Choose a repository first")
                self.inventory = None
                self.query_one("#github-import", Button).disabled = True
                status.update("Reading filenames and recent commit summaries…")
                inventory = await offload(self.client.inventory, selector.value)
                area = self.query_one("#github-files", VerticalScroll)
                await area.remove_children()
                await area.mount_all([Checkbox(Text(f"{f['path']} · {f['size']} bytes"), id=f"repo-file-{i}") for i, f in enumerate(inventory["files"])])
                self.inventory = inventory
                self.query_one("#github-import", Button).disabled = False
                status.update(f"Commit {inventory['commit'][:12]}. Select up to 8 files / 80 KB total. " + ("File listing is partial." if inventory["truncated"] else ""))
            elif action == "github-import":
                require(self.inventory is not None, "Choose a repository and preview its files first")
                paths = [f["path"] for i, f in enumerate(self.inventory["files"]) if self.query_one(f"#repo-file-{i}", Checkbox).value]
                status.update("Reading only the selected files…")
                snapshot = await offload(self.client.snapshot, self.inventory, paths)
                await offload(github.import_snapshot, self.flow, self.experience, snapshot)
                self.dismiss(True)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            self.failed(exc)
        finally:
            selector.disabled = False
            self.busy = False


class ExperienceDetails(ModalScreen):
    """Evidence and occasional editing tools, opened for one experience."""

    BINDINGS = [("escape", "dismiss", "Back")]

    def __init__(self, state, experience):
        super().__init__()
        self.state, self.experience = state, experience

    def compose(self):
        graph = skillmap.catalog(self.state)
        connected = {l["to"] for l in graph["links"] if l["from"] == self.experience}
        options = [(Text(n["label"]), n["id"]) for n in graph["nodes"] if n["id"] in connected]
        with Vertical(classes="dialog"):
            yield Label("Experience details")
            yield TextArea(skillmap.describe(self.state, self.experience), read_only=True, id="experience-detail")
            yield Label("Describe your knowledge of a connected skill")
            with Horizontal(classes="row"):
                yield Select(options, prompt="Choose a skill", value=options[0][1] if options else Select.NULL, id="experience-skill")
                yield Button("Describe skill", id="assess-skill", disabled=not options)
            with Horizontal(classes="row"):
                yield Button("Connect another skill", id="add-skill")
                yield Button("Import from GitHub", id="github-evidence")

    @on(Button.Pressed)
    def choose(self, event):
        event.stop()
        self.dismiss((event.button.id, self.query_one("#experience-skill", Select).value))


class ExperiencePanel(Vertical):
    def __init__(self, workflow):
        super().__init__()
        self.flow, self.state = workflow, workflow.load()

    def compose(self):
        yield Static("", id="map-summary", markup=False)
        with Horizontal(classes="row"):
            yield Button("Add information", id="add-information", variant="primary")
            yield Button("About me", id="about-me")
        with Horizontal(classes="row"):
            yield Select([], prompt="Choose an experience", id="experience-select")
            yield Button("View map", id="solar-view")
        with Vertical(id="next-step"):
            with VerticalScroll(id="question-content"):
                yield Label("Let's fill in the story", id="next-heading")
                yield Static("", id="experience-summary", markup=False)
                yield Static("", id="next-question", markup=False)
            yield Button("Answer question", id="reflect-experience")
            yield Static("One answer is enough for now. You can come back whenever you like.", id="question-reassurance")
        yield Static("", id="map-status", markup=False)

    def update_state(self, state):
        self.state = state
        graph = skillmap.catalog(state)
        experiences = [n for n in graph["nodes"] if n["kind"] in skillmap.EXPERIENCES]
        selector = self.query_one("#experience-select", Select)
        old = selector.value
        selector.set_options([("About me as a whole", "general"), *((Text(n["label"]), n["id"]) for n in experiences)])
        selector.value = old if old == "general" or any(n["id"] == old for n in experiences) else "general"
        self.query_one("#map-summary", Static).update("Your knowledge graph" if experiences else "Start your knowledge graph")
        selector.display = bool(experiences)
        self.query_one("#solar-view", Button).display = bool(experiences)
        self.show_experience()

    @on(Select.Changed, "#experience-select")
    def show_experience(self):
        eid = self.query_one("#experience-select", Select).value
        graph = skillmap.catalog(self.state)
        node = next((n for n in graph["nodes"] if n["id"] == eid), None)
        questions = skillmap.questions(self.state, eid) if node else []
        self.broad_question = profile.overview(self.state).get("next_question") if not questions else None
        self.query_one("#experience-summary", Static).update(
            f"{node['label']} · {skillmap.EXPERIENCES[node['kind']]}" if node else
            "Your interests, experiences and preferences belong here.")
        self.query_one("#next-question", Static).update(questions[0]["prompt"] if questions else
            self.broad_question["question"] if self.broad_question else
            "Add something when it comes to mind, or explore what you've already shared.")
        button = self.query_one("#reflect-experience", Button)
        button.label = "Answer question" if questions or self.broad_question else "Add information"
        self.query_one("#next-heading", Label).update("One optional question")

    @on(Button.Pressed)
    def clicked(self, event):
        event.stop()
        self.act(event.button.id)

    @work(exclusive=True)
    async def act(self, action, skill=None):
        eid = self.query_one("#experience-select", Select).value
        if eid == "general":
            eid = Select.NULL
        try:
            if action == "add-information":
                self.app.open_capture()
                return
            if action == "about-me":
                self.app.navigate("about-tab")
                return
            if action == "solar-view":
                path = await offload(solar.export, self.flow)
                opened = await offload(webbrowser.open, path.resolve().as_uri())
                self.query_one("#map-status", Static).update(("Opened snapshot: " if opened else "Open this file in your browser: ") + str(path))
                return
            dialog = None
            if action == "reflect-experience":
                if self.broad_question:
                    self.app.open_capture(question=self.broad_question["question"])
                    return
                if eid is Select.NULL or not skillmap.questions(self.state, eid):
                    self.app.open_capture()
                    return
            if action == "experience-details" and eid is not Select.NULL:
                self.app.push_screen(ExperienceDetails(self.state, eid), self.details_action)
                return
            if action == "add-experience":
                dialog = AddEntity(self.flow)
            elif action == "current-circumstances":
                dialog = CheckIn(self.flow)
            elif eid is not Select.NULL:
                if action == "reflect-experience":
                    dialog = Reflection(self.flow, eid)
                elif action == "add-skill":
                    dialog = AddEntity(self.flow, eid)
                elif action == "github-evidence":
                    dialog = RepositoryDialog(self.flow, eid)
                elif action == "assess-skill":
                    if skill is not None and skill is not Select.NULL:
                        dialog = Capability(self.flow, eid, skill)
            if dialog:
                self.app.push_screen(dialog, self.app.reload)
        except (ValueError, OSError) as exc:
            self.query_one("#map-status", Static).update(str(exc))

    def details_action(self, choice):
        if choice:
            self.act(*choice)
