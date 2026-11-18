"""Tests for the intervention margin extension.

Author: Grace Adjeli | BridgeCore AI LLC

The required human response time is an assumption, so these tests check the
arithmetic and the bookkeeping, not any claim about real staffing.
"""
import contextlib
import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hitl_sim import Config, HitlSim, TimeoutPolicy
from early_warning import LAMBDAS, RULES, SEEDS, evaluate, summarize
import intervention_margin as im
from intervention_margin import (CATEGORIES, NEGATIVE, NO_ADVANCE_ALERT, NO_DEFAULT,
                                 POSITIVE, ZERO, classify, margin_table, summarize_margin)

BASE = dict(service_rate=10.0, timeout_min=10.0, duration_min=480.0)


def sim(arr, policy, gate=False, seed=42):
    cfg = Config(arrival_rate=float(arr), policy=policy, gate=gate, seed=seed, **BASE)
    return HitlSim(cfg).run()


class TestClassify(unittest.TestCase):
    def test_positive_margin(self):
        r = classify(100, 80, 5)          # lead 20, margin 15
        self.assertEqual(r["category"], POSITIVE)
        self.assertEqual(r["lead"], 20)
        self.assertEqual(r["margin"], 15)

    def test_zero_margin(self):
        r = classify(100, 95, 5)          # lead 5, margin 0
        self.assertEqual(r["category"], ZERO)
        self.assertEqual(r["margin"], 0)

    def test_negative_margin(self):
        r = classify(100, 97, 5)          # lead 3, margin -2
        self.assertEqual(r["category"], NEGATIVE)
        self.assertEqual(r["margin"], -2)

    def test_negative_margin_is_not_missed_alert(self):
        r = classify(100, 99, 5)
        self.assertNotEqual(r["category"], NO_ADVANCE_ALERT)
        self.assertEqual(r["category"], NEGATIVE)

    def test_no_alert_before_default(self):
        self.assertEqual(classify(100, None, 5)["category"], NO_ADVANCE_ALERT)
        self.assertEqual(classify(100, 100, 5)["category"], NO_ADVANCE_ALERT)
        self.assertEqual(classify(100, 120, 5)["category"], NO_ADVANCE_ALERT)

    def test_no_default(self):
        self.assertEqual(classify(None, None, 5)["category"], NO_DEFAULT)
        self.assertEqual(classify(None, 50, 5)["category"], NO_DEFAULT)

    def test_no_advance_alert_has_no_margin(self):
        for r in (classify(100, None, 5), classify(None, 50, 5)):
            self.assertIsNone(r["margin"])
            self.assertIsNone(r["lead"])

    def test_response_time_changes_category(self):
        cats = [classify(100, 90, rt)["category"] for rt in (0, 5, 10, 11, 30)]
        self.assertEqual(cats, [POSITIVE, POSITIVE, ZERO, NEGATIVE, NEGATIVE])

    def test_fractional_response_time(self):
        self.assertEqual(classify(100, 90.5, 9.5)["category"], ZERO)

    def test_invalid_response_time(self):
        for bad in (-1, float("nan"), float("inf"), "5", None, True):
            with self.assertRaises(ValueError):
                classify(100, 90, bad)


class TestAggregates(unittest.TestCase):
    RUNS = [
        (None, {"R": None}),        # no default
        (None, {"R": 10}),          # no default, alert fired anyway
        (50, {"R": None}),          # no advance alert
        (50, {"R": 50}),            # no advance alert (not strictly before)
        (50, {"R": 30}),            # lead 20
        (50, {"R": 40}),            # lead 10
        (50, {"R": 45}),            # lead 5
        (50, {"R": 48}),            # lead 2
    ]

    def test_counts_kept_separate(self):
        s = summarize_margin(self.RUNS, "R", 10)
        self.assertEqual(s["counts"], {NO_DEFAULT: 2, NO_ADVANCE_ALERT: 2,
                                       POSITIVE: 1, ZERO: 1, NEGATIVE: 2})
        self.assertEqual(s["runs"], 8)
        self.assertEqual(sum(s["counts"].values()), s["runs"])
        self.assertEqual(s["advance_alerts"], 4)

    def test_all_categories_present_even_when_zero(self):
        s = summarize_margin([(None, {"R": None})], "R", 5)
        self.assertEqual(tuple(s["counts"]), CATEGORIES)
        self.assertEqual(s["counts"][NEGATIVE], 0)

    def test_medians(self):
        s = summarize_margin(self.RUNS, "R", 10)
        self.assertEqual(s["median_lead"], 7.5)      # leads 20, 10, 5, 2
        self.assertEqual(s["median_margin"], -2.5)   # margins 10, 0, -5, -8

    def test_medians_none_without_advance_alerts(self):
        s = summarize_margin([(None, {"R": None}), (50, {"R": None})], "R", 5)
        self.assertIsNone(s["median_lead"])
        self.assertIsNone(s["median_margin"])


class TestAgainstExistingEarlyWarning(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = evaluate(LAMBDAS, SEEDS)

    def test_every_rule_is_handled(self):
        table = margin_table(LAMBDAS, SEEDS, (5.0,))[5.0]
        for lam in LAMBDAS:
            self.assertEqual(set(table[lam]), set(RULES))

    def test_response_time_zero_matches_existing_summary(self):
        """With no required response time, the advance alert, missed alert and
        no default counts must equal early_warning.summarize for every rule."""
        for lam in LAMBDAS:
            for name in RULES:
                early, late, median_lead, _false, no_default = summarize(self.res[lam], name)
                s = summarize_margin(self.res[lam], name, 0)
                c = s["counts"]
                self.assertEqual(s["advance_alerts"], early, (lam, name))
                self.assertEqual(c[POSITIVE], early, (lam, name))
                self.assertEqual(c[NO_ADVANCE_ALERT], late, (lam, name))
                self.assertEqual(c[NO_DEFAULT], no_default, (lam, name))
                self.assertEqual(c[NEGATIVE], 0)
                self.assertEqual(c[ZERO], 0)
                if early:
                    self.assertEqual(s["median_lead"], median_lead, (lam, name))

    def test_published_median_leads_reproduced(self):
        expected = {10: (246, 67, 202), 12: (44, 25, 32), 15: (20, 14, 10)}
        for lam, meds in expected.items():
            got = []
            for name in RULES:
                got.append(round(summarize_margin(self.res[lam], name, 0)["median_lead"]))
            self.assertEqual(tuple(got), meds, lam)

    def test_defaults_on_13_of_20_days_at_10(self):
        for name in RULES:
            c = summarize_margin(self.res[10], name, 5)["counts"]
            self.assertEqual(c[NO_DEFAULT], 7)
            self.assertEqual(sum(c.values()) - c[NO_DEFAULT], 13)

    def test_no_default_at_low_load(self):
        for lam in (6, 8, 9):
            for name in RULES:
                c = summarize_margin(self.res[lam], name, 5)["counts"]
                self.assertEqual(c[NO_DEFAULT], 20)
                self.assertEqual(c[POSITIVE] + c[ZERO] + c[NEGATIVE] + c[NO_ADVANCE_ALERT], 0)

    def test_totals_always_equal_runs(self):
        for rt in (0, 2, 5, 10, 25):
            for lam in LAMBDAS:
                for name in RULES:
                    s = summarize_margin(self.res[lam], name, rt)
                    self.assertEqual(sum(s["counts"].values()), len(SEEDS))
                    self.assertEqual(s["advance_alerts"],
                                     s["counts"][POSITIVE] + s["counts"][ZERO]
                                     + s["counts"][NEGATIVE])

    def test_larger_response_time_never_adds_positives(self):
        for lam in LAMBDAS:
            for name in RULES:
                prev_pos, prev_neg = None, None
                for rt in (0, 2, 5, 10, 25, 100):
                    c = summarize_margin(self.res[lam], name, rt)["counts"]
                    if prev_pos is not None:
                        self.assertLessEqual(c[POSITIVE], prev_pos)
                        self.assertGreaterEqual(c[NEGATIVE] + c[ZERO], 0)
                        self.assertGreaterEqual(c[NEGATIVE], prev_neg)
                    prev_pos, prev_neg = c[POSITIVE], c[NEGATIVE]

    def test_response_time_never_changes_other_categories(self):
        for lam in LAMBDAS:
            for name in RULES:
                a = summarize_margin(self.res[lam], name, 0)["counts"]
                b = summarize_margin(self.res[lam], name, 50)["counts"]
                self.assertEqual(a[NO_DEFAULT], b[NO_DEFAULT])
                self.assertEqual(a[NO_ADVANCE_ALERT], b[NO_ADVANCE_ALERT])

    def test_long_response_time_exposes_negative_margins(self):
        c = summarize_margin(self.res[15], "C queue growth", 10)["counts"]
        self.assertGreater(c[NEGATIVE], 0)
        self.assertEqual(c[NO_ADVANCE_ALERT], 0)


class TestDeterminism(unittest.TestCase):
    def test_same_seeds_same_table(self):
        a = margin_table([10, 15], range(1, 6), (2.0, 10.0))
        b = margin_table([10, 15], range(1, 6), (2.0, 10.0))
        self.assertEqual(a, b)

    def test_cli_output_reproducible(self):
        def run():
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                im.main(["--response-times", "3", "8", "--lambdas", "10", "12", "--seeds", "5"])
            return buf.getvalue()
        self.assertEqual(run(), run())

    def test_cli_rejects_bad_input(self):
        for argv in (["--response-times", "-1"], ["--seeds", "0"]):
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    im.parse_args(argv)


class TestPublishedResultsUnchanged(unittest.TestCase):
    """Importing and running the extension must not change existing results."""

    def setUp(self):
        with contextlib.redirect_stdout(io.StringIO()):
            im.main(["--lambdas", "10", "--seeds", "3"])

    def test_simulator_findings_unchanged(self):
        r = sim(6, TimeoutPolicy.FAIL_OPEN)
        self.assertEqual((r["items_processed"], r["human_approved"], r["auto_approved"]),
                         (2828, 2828, 0))
        self.assertEqual(sim(10, TimeoutPolicy.FAIL_OPEN)["auto_approved"], 64)
        r = sim(30, TimeoutPolicy.FAIL_OPEN)
        self.assertEqual(r["timeout_decisions_%"], 66.9)
        self.assertEqual(r["inadmissible_executed"], 3859)
        r = sim(30, TimeoutPolicy.FAIL_CLOSED)
        self.assertEqual(r["admissible_blocked"], 5628)

    def test_early_warning_findings_unchanged(self):
        res = evaluate(LAMBDAS, SEEDS)
        for lam, meds in {10: (246, 67, 202), 12: (44, 25, 32), 15: (20, 14, 10)}.items():
            got = tuple(round(summarize(res[lam], n)[2]) for n in RULES)
            self.assertEqual(got, meds)
        self.assertEqual(sum(1 for d, _ in res[10] if d is not None), 13)


if __name__ == "__main__":
    unittest.main()
