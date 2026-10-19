import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hitl_sim import Config, HitlSim, TimeoutPolicy

BASE = dict(service_rate=10.0, timeout_min=10.0, duration_min=480.0)
LAMBDAS = [4, 6, 8, 10, 12, 15, 20, 25, 30]


def run(arr, policy, gate=False, seed=42):
    cfg = Config(arrival_rate=float(arr), policy=policy, gate=gate, seed=seed, **BASE)
    return HitlSim(cfg).run()


class TestDeterminismAndIsolation(unittest.TestCase):
    def test_same_seed_same_result(self):
        self.assertEqual(run(30, TimeoutPolicy.FAIL_OPEN),
                         run(30, TimeoutPolicy.FAIL_OPEN))

    def test_gate_preserves_admissible_blocks(self):
        """Arrival/admissibility streams are identical across gate on/off, so
        admissible BLOCKED outcomes must match. (Auto-approvals and human
        counts intentionally NOT asserted here: removing inadmissible items
        shifts later service-time draws.)"""
        off = run(30, TimeoutPolicy.FAIL_OPEN, gate=False)
        on = run(30, TimeoutPolicy.FAIL_OPEN, gate=True)
        self.assertEqual(on["blocked"], off["blocked"] - off["admissible_blocked"])


class TestPublishedFindings(unittest.TestCase):
    """Numbers stated in README.md and the case study.
    Every value below was verified against hitl_sim.py before this suite
    was written. If a number fails without an intentional model change,
    the published text is stale: fix the TEXT, not the test."""

    def test_finding1_lambda6_all_human(self):
        r = run(6, TimeoutPolicy.FAIL_OPEN)
        self.assertEqual(r["items_processed"], 2828)
        self.assertEqual(r["human_approved"], 2828)
        self.assertEqual(r["auto_approved"], 0)

    def test_finding1_lambda10_first_64_silent(self):
        r = run(10, TimeoutPolicy.FAIL_OPEN)
        self.assertEqual(r["auto_approved"], 64)

    def test_finding2_fail_open_numbers(self):
        r = run(30, TimeoutPolicy.FAIL_OPEN)
        self.assertEqual(r["timeout_decisions_%"], 66.9)
        self.assertEqual(r["inadmissible_executed"], 3859)
        self.assertEqual(r["admissible_blocked"], 0)

    def test_finding2_fail_closed_numbers(self):
        r = run(30, TimeoutPolicy.FAIL_CLOSED)
        self.assertEqual(r["inadmissible_executed"], 0)
        self.assertEqual(r["admissible_blocked"], 5628)

    def test_finding2_gate_numbers(self):
        r = run(30, TimeoutPolicy.FAIL_OPEN, gate=True)
        self.assertEqual(r["inadmissible_executed"], 0)
        self.assertEqual(r["admissible_blocked"], 0)
        self.assertEqual(r["timeout_decisions_%"], 25.7)
        self.assertGreater(r["gate_rejected"], 0)


class TestInvariants(unittest.TestCase):
    def test_fail_closed_never_executes_inadmissible(self):
        for seed in (7, 123):
            for lam in (6, 15, 30):
                self.assertEqual(run(lam, TimeoutPolicy.FAIL_CLOSED, seed=seed)
                                 ["inadmissible_executed"], 0)

    def test_gate_never_executes_inadmissible_any_policy(self):
        for seed in (7, 123):
            for policy in (TimeoutPolicy.FAIL_OPEN, TimeoutPolicy.FAIL_CLOSED,
                           TimeoutPolicy.DEFER):
                for lam in (6, 15, 30):
                    self.assertEqual(run(lam, policy, gate=True, seed=seed)
                                     ["inadmissible_executed"], 0)

    def test_outcome_accounting_is_complete(self):
        for seed in (7, 123):
            r = run(20, TimeoutPolicy.FAIL_OPEN, gate=True, seed=seed)
            accounted = (r["human_approved"] + r["auto_approved"] + r["blocked"]
                         + r["dropped"] + r["gate_rejected"])
            self.assertEqual(accounted, r["items_processed"])

    def test_gate_rejected_only_when_gate_on(self):
        self.assertEqual(run(20, TimeoutPolicy.FAIL_OPEN, seed=7)["gate_rejected"], 0)

    def test_defer_policy_wires_to_dropped(self):
        r = run(30, TimeoutPolicy.DEFER, seed=7)
        self.assertGreater(r["dropped"], 0)
        self.assertEqual(r["auto_approved"], 0)


class TestSweepShape(unittest.TestCase):
    def test_silence_is_monotonic_in_load(self):
        silents = [round(100 * run(l, TimeoutPolicy.FAIL_OPEN)["auto_approved"]
                         / run(l, TimeoutPolicy.FAIL_OPEN)["items_processed"], 1)
                   for l in LAMBDAS]
        self.assertEqual(silents, sorted(silents))
        self.assertEqual(silents[0], 0.0)
        self.assertEqual(silents[-1], 66.9)


class TestArtifacts(unittest.TestCase):
    def test_case_study_and_charts_exist(self):
        root = Path(__file__).resolve().parent.parent
        for name in ["Case Study — Human Oversight Under Load.md",
                     "chart1_threshold.png", "chart2_gate.png", "README.md"]:
            self.assertTrue((root / name).is_file(), f"missing {name}")
