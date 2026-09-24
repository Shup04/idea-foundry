from copy import deepcopy
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from foundry.cli import main
from foundry.evaluation import evaluate, payback
from foundry.evidence import add_claim, claim_statuses, correct, support_origins
from foundry.outcomes import proposals, record_outcome
from foundry.render import evaluations, profile
from foundry.storage import Store, encoded
from foundry.validation import Invalid, MAX_BYTES, read_json, validate_policy, validate_state
from tests.fixtures import band, bundle, claim, correction, fact, idea, outcome, ref, source

ROOT = Path(__file__).resolve().parents[1]


def policy():
    return read_json(ROOT / "config/practicality.default.json")


class EvidenceTests(unittest.TestCase):
    def test_original_source_quote_and_hash_are_required(self):
        for mutation in ("hash", "quote", "missing"):
            state = bundle()
            if mutation == "hash":
                state["sources"][0]["text"] = "Changed source bytes"
            elif mutation == "quote":
                state["claims"][0]["sources"][0]["quote"] = "Invented quotation"
            else:
                state["claims"][0]["sources"][0]["source"] = "absent"
            with self.subTest(mutation=mutation), self.assertRaises(Invalid):
                validate_state(state)

    def test_generated_ideas_never_become_personal_evidence_even_via_summary(self):
        for indirect in (False, True):
            state = bundle()
            state["sources"].append(source("GEN", kind="generated"))
            sid = "GEN"
            if indirect:
                state["sources"].append(source("COPY", kind="user_supplied_summary", parents=["GEN"]))
                sid = "COPY"
            state["claims"][0].update(kind="interpretation", sources=[ref(sid)])
            with self.subTest(indirect=indirect), self.assertRaisesRegex(Invalid, "generated material"):
                validate_state(state)

    def test_cyclic_ancestry_and_duplicate_ids_rejected(self):
        state = bundle()
        state["sources"][0]["parents"] = ["S1"]
        with self.assertRaisesRegex(Invalid, "cyclic"):
            validate_state(state)
        state = bundle()
        state["claims"].append(claim())
        with self.assertRaisesRegex(Invalid, "duplicate"):
            validate_state(state)

    def test_shared_ancestry_is_bounded_and_still_rejects_generated_roots(self):
        state = bundle()
        state["sources"].append(source("GEN", kind="generated"))
        parents = ["S1", "GEN"]
        for n in range(45):
            sid = f"DERIVED{n}"
            state["sources"].append(source(sid, kind="user_supplied_summary", parents=list(parents)))
            parents = [parents[-1], sid]
        state["claims"][0].update(kind="interpretation", sources=[ref(parents[-1])])
        with self.assertRaisesRegex(Invalid, "generated material"):
            validate_state(state)

    def test_summary_is_not_direct_speech_and_project_is_not_demonstrated_skill(self):
        state = bundle()
        state["sources"][0]["kind"] = "user_supplied_summary"
        with self.assertRaisesRegex(Invalid, "direct user"):
            validate_state(state)
        state["claims"][0]["kind"] = "reported"
        validate_state(state)
        state["claims"][0]["facet"] = "demonstrated_skills"
        with self.assertRaisesRegex(Invalid, "do not demonstrate"):
            validate_state(state)
        state["claims"][0]["kind"] = "observed"
        with self.assertRaisesRegex(Invalid, "inspected artifact"):
            validate_state(state)

    def test_observed_contribution_supported_without_inferring_mastery(self):
        state = bundle()
        state["sources"].append(source("OBS", "Synthetic person fixed one indexing defect.", "observation"))
        state["claims"].append(claim("C2", "bounded_contribution", kind="observed", facet="demonstrated_skills",
                                     text="Fixed one specific indexing defect; general mastery unestablished.",
                                     sources=[ref("OBS", "Synthetic person fixed one indexing defect.")]))
        validate_state(state)
        self.assertTrue(claim_statuses(state)["C2"]["usable"])

    def test_rejection_is_not_opposite_biography_and_cannot_return_under_new_id(self):
        state = bundle()
        original = deepcopy(state["claims"][0])
        correct(state, correction())
        validate_state(state)
        self.assertEqual(len(state["claims"]), 1)
        self.assertEqual(state["claims"][0]["text"], original["text"])
        self.assertEqual(state["claims"][0]["stance"], "asserts")
        self.assertFalse(claim_statuses(state)["C1"]["usable"])
        state["claims"].append(claim("C2"))
        with self.assertRaisesRegex(Invalid, "cannot return"):
            validate_state(state)

    def test_exclusion_changes_future_evaluation_without_changing_original_idea(self):
        state = bundle()
        before = deepcopy(state["ideas"])
        correct(state, correction("exclude"))
        report = evaluate(state, policy())
        self.assertEqual(report["evaluations"][0]["facts"]["adoption_fit"]["basis"], "unknown")
        self.assertEqual(state["ideas"], before)

    def test_contradictions_withhold_both_sides(self):
        state = bundle()
        state["claims"].append(claim("C2", stance="denies"))
        validate_state(state)
        for status in claim_statuses(state).values():
            self.assertEqual(status["status"], "contradicted")
            self.assertFalse(status["usable"])
        self.assertEqual(evaluate(state, policy())["evaluations"][0]["facts"]["adoption_fit"]["basis"], "unknown")

    def test_rejecting_inference_preserves_independent_opposite_user_statement(self):
        state = bundle()
        statement = "I am not interested in weather photographs; that was a fictional example."
        state["sources"].append(source("S2", statement))
        state["claims"].append(claim("C2", stance="denies", text=statement, sources=[ref("S2", statement)]))
        correct(state, correction())
        validate_state(state)
        self.assertEqual(claim_statuses(state)["C1"]["status"], "rejected")
        self.assertTrue(claim_statuses(state)["C2"]["usable"])
        self.assertEqual(state["claims"][1]["text"], statement)

    def test_tentative_personal_fit_not_promoted(self):
        state = bundle()
        state["claims"][0]["kind"] = "interpretation"
        self.assertIn("withheld", evaluate(state, policy())["evaluations"][0]["facts"]["adoption_fit"]["reason"])

    def test_duplicate_origin_does_not_add_support(self):
        state = bundle()
        state["sources"].append(source("S2", origin="S1"))
        state["claims"][0]["sources"].append(ref("S2"))
        validate_state(state)
        self.assertEqual(support_origins(state["claims"][0], state), ["S1"])
        self.assertEqual(state["claims"][0]["confidence"], "strong")

    def test_identical_import_with_different_origin_is_not_independent(self):
        state = bundle()
        state["sources"].append(source("S2", origin="new_import_origin"))
        state["claims"][0]["sources"].append(ref("S2"))
        self.assertEqual(len(support_origins(state["claims"][0], state)), 1)

    def test_every_facet_and_correction_is_inspectable(self):
        state = bundle()
        correct(state, correction())
        rendered = profile(state)
        self.assertIn("Demonstrated Skills", rendered)
        self.assertIn("Unknown — no qualifying evidence", rendered)
        self.assertIn("REJECTED", rendered)
        self.assertIn("does not establish its opposite", rendered)
        self.assertIn("Source excerpts", rendered)


class PolicyTests(unittest.TestCase):
    def test_policy_is_configurable_and_no_opaque_single_score(self):
        state, config = bundle(), policy()
        old = evaluate(state, config)
        config["policies"]["personal"]["hard_constraints"][0]["limit"] = 10
        config["policies"]["personal"]["criteria"][0]["weight"] = 0
        config["policies"]["personal"]["priorities"].reverse()
        new = evaluate(state, config)
        self.assertNotEqual(old["policy_sha256"], new["policy_sha256"])
        self.assertIn("Outside", new["evaluations"][0]["readiness"])
        self.assertNotEqual(old["evaluations"][0]["preference_balance"], new["evaluations"][0]["preference_balance"])
        self.assertEqual(new["evaluations"][0]["criteria"][0]["id"], "observed_usefulness")
        self.assertNotIn("score", new["evaluations"][0])

    def test_unknown_and_straddling_hard_constraints_are_not_passes(self):
        state = bundle()
        for value in (None, band(20, 40), band(1, 2, "hours")):
            state["ideas"][0]["facts"]["experiment_minutes"] = fact(value)
            report = evaluate(state, policy())["evaluations"][0]
            self.assertEqual(report["constraints"][0]["result"], "unknown")
            self.assertIn("Resolve", report["readiness"])

    def test_hard_failure_cannot_be_offset_by_all_strong_preferences(self):
        state = bundle()
        state["ideas"][0]["facts"]["experiment_minutes"] = fact(band(100, 150))
        for item in state["ideas"][0]["facts"].values():
            item["assessment"] = "strong"
        result = evaluate(state, policy())["evaluations"][0]
        self.assertIn("Outside", result["readiness"])

    def test_three_categories_have_different_evaluations(self):
        state = bundle()
        state["ideas"] += [idea("B1", "commercial"), idea("X1", "creative")]
        state["ideas"][2]["facts"]["attention_minutes"] = fact(band(5, 10))
        result = evaluate(state, policy())["evaluations"]
        self.assertIsNotNone(result[0]["payback"])
        self.assertIsNone(result[1]["payback"])
        self.assertIn("customer", {criterion["id"] for criterion in result[1]["criteria"]})
        self.assertIsNone(result[2]["payback"])
        self.assertIn("Creative provocation", result[2]["readiness"])
        self.assertIn("revisited", {criterion["id"] for criterion in result[2]["criteria"]})

    def test_payback_is_range_arithmetic_and_does_not_invent_unknowns(self):
        facts = bundle()["ideas"][0]["facts"]
        result = payback(facts)
        self.assertEqual(result["net_minutes_per_month"], [8, 38])
        self.assertAlmostEqual(result["months"][0], 30 / 38)
        self.assertEqual(result["months"][1], 7.5)
        facts["ongoing_minutes_monthly"] = fact(band(10, 15, "minutes/month"))
        self.assertIsNone(payback(facts)["months"][1])
        facts["ongoing_minutes_monthly"] = fact(band(50, 60, "minutes/month"))
        self.assertEqual(payback(facts)["status"], "no time payback in this range")
        del facts["frequency_monthly"]
        self.assertEqual(payback(facts)["status"], "unknown")

    def test_supported_fact_cannot_cite_generated_text_as_evidence(self):
        state = bundle()
        state["sources"].append(source("GEN", kind="generated"))
        state["ideas"][0]["facts"]["adoption_fit"] = fact("Great fit", "supported", "strong", [ref("GEN")])
        with self.assertRaisesRegex(Invalid, "generated material"):
            evaluate(state, policy())

    def test_overflow_and_wrong_boolean_type_remain_unknown(self):
        state = bundle()
        state["ideas"][0]["facts"]["frequency_monthly"] = fact(band(1e300, 1e300, "uses/month"))
        state["ideas"][0]["facts"]["minutes_saved_per_use"] = fact(band(1e300, 1e300, "minutes/use"))
        self.assertEqual(payback(state["ideas"][0]["facts"])["status"], "unknown")
        state["ideas"] = [idea("B1", "commercial")]
        state["ideas"][0]["facts"]["requires_live_calls"] = fact("false")
        result = evaluate(state, policy())["evaluations"][0]
        self.assertEqual(next(c for c in result["constraints"] if c["id"] == "live_calls")["result"], "unknown")

    def test_invalid_policy_and_fake_precision_are_rejected(self):
        mutations = [lambda p: p["policies"]["personal"]["criteria"][0].update(weight=87.43),
                     lambda p: p["policies"]["personal"]["criteria"][0].update(rule="eval"),
                     lambda p: p["policies"]["personal"]["hard_constraints"][0].update(op="shell"),
                     lambda p: p["policies"]["personal"].update(priorities=[]),
                     lambda p: p["policies"]["creative"]["required_facts"].append("revenue"),
                     lambda p: p["learning"].update(min_distinct_ideas=1)]
        for mutate in mutations:
            config = policy()
            mutate(config)
            with self.assertRaises(Invalid):
                validate_policy(config)


class OutcomeTests(unittest.TestCase):
    def test_real_attributed_outcome_changes_same_idea_evaluation_not_preferences(self):
        state, config = bundle(), policy()
        before = deepcopy(config)
        record_outcome(state, {"sources": [source("O1", "Synthetic outcome report.", "outcome")], "outcome": outcome()})
        result = evaluate(state, config)["evaluations"][0]
        criterion = next(c for c in result["criteria"] if c["id"] == "observed_usefulness")
        self.assertEqual(criterion["rating"], "strong")
        self.assertEqual(criterion["evidence"]["basis"], "user_report")
        self.assertIn("scope:", criterion["evidence"]["reason"])
        self.assertEqual(config, before)
        self.assertEqual(len(state["claims"]), 1)

    def test_empty_history_does_not_mean_zero_and_latest_nonempty_value_keeps_history(self):
        state = bundle()
        self.assertEqual(evaluate(state, policy())["evaluations"][0]["outcomes"], [])
        self.assertNotIn("money_earned", evaluate(state, policy())["evaluations"][0]["facts"])
        state["sources"].append(source("O1", "Synthetic outcome report.", "outcome"))
        state["outcomes"] = [outcome(), outcome("E2", occurred_at="2026-09-06T12:00:00+00:00", metrics={"actual_usefulness": "weak", "continued_usage": None})]
        result = evaluate(state, policy())["evaluations"][0]
        self.assertEqual(result["facts"]["actual_usefulness"]["value"], "weak")
        self.assertTrue(result["facts"]["continued_usage"]["value"])
        self.assertEqual(len(result["outcomes"]), 2)

    def test_outcome_on_one_idea_does_not_upgrade_other_idea(self):
        state = bundle()
        state["ideas"].append(idea("P2"))
        state["sources"].append(source("O1", "Synthetic outcome report.", "outcome"))
        state["outcomes"].append(outcome())
        results = evaluate(state, policy())["evaluations"]
        self.assertNotIn("actual_usefulness", results[1]["facts"])

    def test_pattern_proposes_only_after_independent_ideas_and_never_changes_policy(self):
        state, config = bundle(), policy()
        state["ideas"].append(idea("P2"))
        state["sources"].append(source("O1", "Synthetic outcome report.", "outcome"))
        first = outcome(event="abandoned", reason_code="unexpected_time",
                        metrics={"implementation_minutes": 150, "reason_abandoned": "Setup exceeded the available time."})
        state["outcomes"] = [first, first | {"id": "E2"}]
        self.assertEqual(proposals(state, config), [])
        state["outcomes"][1]["idea_id"] = "P2"
        self.assertEqual(proposals(state, config), [])  # Same report is not independent evidence.
        state["sources"].append(source("O2", "Separate synthetic abandonment report.", "outcome"))
        state["outcomes"][1]["sources"] = [ref("O2", "Separate synthetic abandonment report.")]
        before_state, before_policy = deepcopy(state), deepcopy(config)
        result = proposals(state, config)
        self.assertEqual(result[0]["status"], "proposal_only")
        self.assertEqual(len(result[0]["evidence"]), 2)
        self.assertEqual(state, before_state)
        self.assertEqual(config, before_policy)

    def test_generated_outcomes_unknown_ideas_and_invalid_metrics_rejected(self):
        for mutation in ("generated", "unknown_idea", "negative_time", "fake_rating"):
            state = bundle()
            state["sources"].append(source("O1", "Synthetic outcome report.", "outcome"))
            event = outcome()
            state["outcomes"].append(event)
            if mutation == "generated":
                state["sources"][-1]["kind"] = "generated"
            elif mutation == "unknown_idea":
                event["idea_id"] = "absent"
            elif mutation == "negative_time":
                event["metrics"]["implementation_minutes"] = -1
            else:
                event["metrics"]["user_rating"] = 87.43
            with self.subTest(mutation=mutation), self.assertRaises(Invalid):
                validate_state(state)


class PersistenceAndCliTests(unittest.TestCase):
    def test_plain_text_outcome_is_attributed_user_report_and_persisted(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            Store(root / "store").initialize(bundle())
            (root / "statement.txt").write_text("Synthetic user reports a useful result after one trial.")
            event = outcome()
            details = {key: value for key, value in event.items() if key not in ("id", "sources", "method")}
            (root / "details.json").write_text(encoded(details))
            with patch("sys.stdout", new_callable=io.StringIO):
                code = main(["--store", str(root / "store"), "record-outcome", "--details", str(root / "details.json"),
                             "--statement-file", str(root / "statement.txt")])
            self.assertEqual(code, 0)
            state = Store(root / "store").load()
            self.assertEqual(state["outcomes"][0]["method"], "user_report")
            self.assertEqual(state["sources"][-1]["kind"], "user_statement")
            self.assertEqual(evaluate(state, policy())["evaluations"][0]["facts"]["actual_usefulness"]["value"], "strong")

    def test_plain_text_correction_records_exact_words_and_survives_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            Store(root / "store").initialize(bundle())
            statement = "This example does not establish a personal interest.\n"
            (root / "correction.txt").write_text(statement)
            with patch("sys.stdout", new_callable=io.StringIO):
                code = main(["--store", str(root / "store"), "correct", "--claim", "C1", "--action", "reject",
                             "--statement-file", str(root / "correction.txt")])
            self.assertEqual(code, 0)
            state = Store(root / "store").load()
            self.assertEqual(state["sources"][-1]["text"], statement)
            self.assertFalse(claim_statuses(state)["C1"]["usable"])

    def test_fresh_process_readback_policy_reload_and_correction_history(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "bundle.json").write_text(encoded(bundle()))
            (root / "policy.json").write_text(encoded(policy()))
            prefix = [sys.executable, "-B", "-m", "foundry", "--store", str(root / "store")]
            initialized = subprocess.run(prefix + ["init", "--bundle", str(root / "bundle.json")], capture_output=True, text=True, cwd=ROOT)
            self.assertEqual(initialized.returncode, 0, initialized.stderr)
            command = prefix + ["evaluate", "--policy", str(root / "policy.json"), "--json"]
            before = json.loads(subprocess.check_output(command, cwd=ROOT))
            config = policy()
            config["policies"]["personal"]["hard_constraints"][0]["limit"] = 10
            (root / "policy.json").write_text(encoded(config))
            after = json.loads(subprocess.check_output(command, cwd=ROOT))
            self.assertNotEqual(before["policy_sha256"], after["policy_sha256"])
            self.assertIn("Outside", after["evaluations"][0]["readiness"])
            store = Store(root / "store")
            store.update(lambda s: correct(s, correction()), "explicit correction")
            reloaded = Store(root / "store").load()
            self.assertEqual(reloaded["claims"][0]["status"], "rejected")
            self.assertEqual(len(list((root / "store/history").glob("*.json"))), 2)

    def test_interruption_before_pointer_replace_preserves_previous_revision(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Store(temp)
            store.initialize(bundle())
            original = store.load()
            with patch("foundry.storage.os.replace", side_effect=InterruptedError("synthetic interruption")):
                with self.assertRaises(InterruptedError):
                    store.update(lambda s: correct(s, correction()), "interrupted correction")
            self.assertEqual(Store(temp).load(), original)
            store.update(lambda s: correct(s, correction()), "retry explicit correction")
            self.assertEqual(store.load()["claims"][0]["status"], "rejected")

    def test_invalid_mutation_does_not_commit_and_existing_store_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Store(temp)
            store.initialize(bundle())
            before = (Path(temp) / "current.json").read_bytes()
            with self.assertRaises(Invalid):
                store.update(lambda s: add_claim(s, {"sources": [], "claim": claim()}), "duplicate")
            with self.assertRaises(Invalid):
                store.initialize(bundle())
            self.assertEqual((Path(temp) / "current.json").read_bytes(), before)

    def test_malformed_output_and_size_budgets(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "bad.json"
            for text in ('{"a": 1, "a": 2}', '{"a": NaN}', '{"a": Infinity}', '{broken', 'x' * (MAX_BYTES + 1)):
                path.write_text(text)
                with self.assertRaises(Invalid):
                    read_json(path)
            state = bundle()
            state["ideas"] = [idea(str(i)) for i in range(4)]
            with self.assertRaisesRegex(Invalid, "budget"):
                validate_state(state)
            path.write_text('{"nonsense": "model refusal"}')
            with patch("sys.stderr", new_callable=io.StringIO) as errors:
                self.assertEqual(main(["--store", str(Path(temp) / "store"), "init", "--bundle", str(path)]), 2)
                self.assertIn("Cannot complete", errors.getvalue())

    def test_generated_text_and_shell_like_configuration_are_only_data(self):
        state = bundle()
        state["ideas"][0]["description"] = "$(touch SHOULD_NOT_EXIST); `sh -c nope`"
        result = evaluations(evaluate(state, policy()))
        self.assertIn("$(touch SHOULD_NOT_EXIST)", result)
        self.assertFalse((ROOT / "SHOULD_NOT_EXIST").exists())


if __name__ == "__main__":
    unittest.main()
