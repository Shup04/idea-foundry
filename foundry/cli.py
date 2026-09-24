"""File-oriented interface; never executes input text or configuration."""

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys
import uuid

from . import evidence, outcomes, render
from .evaluation import evaluate
from .storage import Store, atomic_text, encoded
from .validation import MAX_BYTES, Invalid, digest, keys, read_json, require, validate_policy, words


def source_from_text(path, prefix):
    with Path(path).open("r", encoding="utf-8") as handle:
        statement = handle.read(20001)
    words(statement, "user statement")
    sid = prefix + uuid.uuid4().hex
    return {"id": sid, "kind": "user_statement", "origin": sid, "version": 1,
            "text": statement, "sha256": digest(statement), "locator": str(path), "parents": []}


def correction_from_text(claim_id, action, path):
    source = source_from_text(path, "user-correction-")
    statement, sid = source["text"], source["id"]
    return {
        "source": source,
        "correction": {"id": "action-" + uuid.uuid4().hex, "claim_id": claim_id, "action": action,
                       "reason": statement, "sources": [{"source": sid, "quote": statement}],
                       "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds")},
    }


def outcome_from_text(details_path, statement_path):
    details = read_json(details_path)
    keys(details, ("idea_id", "event", "occurred_at", "scope", "metrics", "reason_code"))
    source = source_from_text(statement_path, "user-outcome-")
    return {"sources": [source], "outcome": {
        **details, "id": "outcome-" + uuid.uuid4().hex, "method": "user_report",
        "sources": [{"source": source["id"], "quote": source["text"]}],
    }}


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "ui":
        return ui_main(arguments[1:])
    if arguments and arguments[0] == "graph":
        return ui_main(arguments[1:], graph_only=True)
    if arguments and arguments[0] == "understand":
        return understanding_main(arguments[1:])
    parser = argparse.ArgumentParser(description="Local personal-evidence and practicality prototype")
    parser.add_argument("--store", required=True, help="private store directory")
    commands = parser.add_subparsers(dest="command", required=True)
    initialize = commands.add_parser("init", help="initialize a new store from an explicitly selected JSON bundle")
    initialize.add_argument("--bundle", required=True)
    profile = commands.add_parser("profile", help="render all personal claims, corrections and unknowns")
    profile.add_argument("--output")
    evaluation = commands.add_parser("evaluate", help="reload policy and evaluate at most three supplied ideas")
    evaluation.add_argument("--policy", required=True)
    evaluation.add_argument("--output")
    evaluation.add_argument("--json", action="store_true")
    proposals = commands.add_parser("proposals", help="read outcomes and suggest changes; never apply them")
    proposals.add_argument("--policy", required=True)
    proposals.add_argument("--output")
    correction = commands.add_parser("correct", help="record an explicit user rejection, exclusion or reinstatement")
    correction_input = correction.add_mutually_exclusive_group(required=True)
    correction_input.add_argument("--input", help="complete source/correction JSON contract")
    correction_input.add_argument("--claim", help="claim ID; use with --action and --statement-file")
    correction.add_argument("--action", choices=("reject", "exclude", "reinstate"))
    correction.add_argument("--statement-file", help="your own plain-text correction; saved verbatim with a source hash")
    outcome = commands.add_parser("record-outcome", help="record an actual attributed outcome; no preference updates")
    outcome_input = outcome.add_mutually_exclusive_group(required=True)
    outcome_input.add_argument("--input", help="complete source/outcome JSON contract")
    outcome_input.add_argument("--details", help="event details JSON, paired with your own statement file")
    outcome.add_argument("--statement-file")
    for command in ("add-claim",):
        sub = commands.add_parser(command, help="record an explicit, source-linked local action")
        sub.add_argument("--input", required=True)
    commands.add_parser("validate", help="validate persisted references, hashes and contracts")
    args = parser.parse_args(argv)
    store = Store(args.store)
    try:
        if args.command == "init":
            store.initialize(read_json(args.bundle))
            result = "Initialized source bundle; human review remains pending.\n"
        elif args.command in ("correct", "add-claim", "record-outcome"):
            if args.command == "correct" and args.claim:
                require(args.action and args.statement_file, "--claim needs --action and --statement-file")
                request = correction_from_text(args.claim, args.action, args.statement_file)
            elif args.command == "record-outcome" and args.details:
                require(args.statement_file, "--details needs --statement-file")
                request = outcome_from_text(args.details, args.statement_file)
            else:
                if args.command == "correct":
                    require(not args.action and not args.statement_file, "use --input or the text-file form, not both")
                if args.command == "record-outcome":
                    require(not args.statement_file, "use --input or the text-file form, not both")
                request = read_json(args.input)
            operation = {"correct": evidence.correct, "add-claim": evidence.add_claim,
                         "record-outcome": outcomes.record_outcome}[args.command]
            store.update(lambda state: operation(state, request), f"explicit {args.command}")
            result = "Recorded a new revision. Existing reports are snapshots; render again to see the change.\n"
        else:
            state = store.load()
            if args.command == "profile":
                result = render.profile(state)
            elif args.command in ("evaluate", "proposals"):
                policy = validate_policy(read_json(args.policy))
                if args.command == "proposals":
                    result = encoded({"status": "proposal_only", "changes": outcomes.proposals(state, policy)})
                else:
                    report = evaluate(state, policy)
                    result = encoded(report) if args.json else render.evaluations(report)
            else:
                result = "Valid persisted state and source references. This does not establish truth or usefulness.\n"
        require(len(result.encode("utf-8")) <= MAX_BYTES, "rendered output budget exceeded")
        if getattr(args, "output", None):
            atomic_text(args.output, result)
        else:
            sys.stdout.write(result)
        return 0
    except (Invalid, OSError, KeyError, TypeError, ValueError, RecursionError) as exc:
        print(f"Cannot complete {args.command}: {exc}", file=sys.stderr)
        return 2


def ui_main(argv, graph_only=False):
    parser = argparse.ArgumentParser(description="Personal knowledge graph: guided capture, selected sources and review")
    parser.add_argument("--workspace", help="new/private workflow directory; never an old prototype store")
    parser.add_argument("--dataset", choices=("personal", "synthetic"), default="personal")
    parser.add_argument("--copy-legacy", help="copy an explicitly selected v1 personal store into a new workspace; never modifies it")
    parser.add_argument("--check", action="store_true", help="open/validate state and show counts without starting the terminal UI")
    if graph_only:
        parser.add_argument("--export", action="store_true", help="save the current profile and graph locally")
        parser.add_argument("--visual", action="store_true", help="export an offline interactive solar map")
        parser.add_argument("--open", action="store_true", help="open the visual export in your browser (with --visual)")
        parser.add_argument("--search", help="search reviewed knowledge and its supporting passages locally")
    args = parser.parse_args(argv)
    path = args.workspace or f".foundry-data/workspaces/{args.dataset}"
    try:
        from .knowledge import Knowledge, inventory, profile_text
        workflow = Knowledge(path, args.dataset)
        if not (workflow.path / "state/current.json").exists():
            workflow.initialize(args.copy_legacy)
        elif args.copy_legacy:
            raise Invalid("copy destination already exists; choose a new workspace")
        if args.check:
            state = workflow.load()
            print(" · ".join(f"{sum(p['status'] == status for p in state['proposals'])} {status}"
                             for status in ("proposed", "accepted", "corrected", "rejected", "excluded")))
            for row in inventory(state):
                print(f"{row['label']}: {row['current']} current, {row['pending']} awaiting review")
            print("Idea generation is deferred. Personal accuracy requires your review.")
        elif graph_only:
            if args.open and not args.visual:
                raise Invalid("--open requires --visual")
            if args.visual:
                from .solar import export
                document = export(workflow)
                print(document)
                if args.open:
                    import webbrowser
                    webbrowser.open(document.resolve().as_uri())
            elif args.export:
                print(workflow.export_profile())
            else:
                from .profile import render as render_profile
                print(render_profile(workflow.load(), query=args.search or ""))
        else:
            try:
                from .ui import FoundryApp
            except ModuleNotFoundError as exc:
                raise Invalid("Textual UI dependencies missing. Run make deps ui-env, then .venv/bin/python -B -m foundry ui") from exc
            FoundryApp(workflow).run()
        return 0
    except (Invalid, OSError, KeyError, TypeError, ValueError, RecursionError) as exc:
        print(f"Cannot open workflow: {exc}", file=sys.stderr)
        return 2


def understanding_main(argv):
    from . import openai_api, understanding
    from .knowledge import Knowledge
    parser = argparse.ArgumentParser(description="OpenAI interview understanding; suggestions always need review")
    parser.add_argument("--workspace", default=".foundry-data/workspaces/personal")
    parser.add_argument("--dataset", choices=("personal", "synthetic"), default="personal")
    parser.add_argument("--budget", type=float, help="approve a cumulative API cap in USD and enable interview processing")
    parser.add_argument("--model", choices=list(openai_api.MODELS))
    parser.add_argument("--run", action="store_true", help="interpret up to eight saved answers and cache embeddings")
    parser.add_argument("--answer", action="append", help="restrict processing to this answer ID; repeat to select more")
    parser.add_argument("--preview", action="store_true", help="show the selected interview context locally; no request")
    parser.add_argument("--pause", action="store_true", help="disable future AI calls; keep all saved data")
    args = parser.parse_args(argv)
    try:
        require(not (args.pause and (args.run or args.budget is not None)), "Use --pause separately from --run/--budget.")
        require(args.model is None or args.budget is not None, "Changing model requires --budget to confirm the total cap.")
        flow = Knowledge(args.workspace, args.dataset)
        state = flow.load()
        if args.budget is not None:
            state = understanding.configure(flow, budget_usd=args.budget,
                model=args.model or state.get("understanding", understanding.empty())["config"]["model"])
        if args.pause:
            state = understanding.pause(flow)
        if args.preview:
            from .storage import encoded
            print(encoded(understanding.public_input(understanding.answer_records(state, args.answer))))
        elif args.run:
            result = understanding.run(flow, answer_ids=args.answer)
            print(f"{len(result['proposals'])} suggestions staged; {result['indexed_answers']} answers indexed; "
                  f"{result['remaining_answers']} answers remain.")
            if result["embedding_error"]:
                print("Related-answer search incomplete: " + result["embedding_error"])
            print(understanding.summary(flow.load()))
        else:
            print(understanding.summary(state))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Cannot understand answers: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
