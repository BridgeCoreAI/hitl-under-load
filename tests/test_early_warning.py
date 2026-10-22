import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hitl_sim import Config, HitlSim, TimeoutPolicy
from early_warning import TelemetrySim, evaluate, summarize, run_one

SEEDS = range(1, 21)


class TestInstrumentationIsInert(unittest.TestCase):
    """The telemetry subclass must not change any published result."""

    def test_identical_to_base_simulator(self):
        for lam in (6, 10, 30):
            cfg = Config(arrival_rate=float(lam), service_rate=10.0, timeout_min=10.0,
                         policy=TimeoutPolicy.FAIL_OPEN)
            self.assertEqual(HitlSim(cfg).run(), TelemetrySim(cfg).run())

    def test_one_snapshot_per_minute(self):
        sim, _ = run_one(10, 42)
        self.assertEqual(len(sim.snaps), 480)


class TestPublishedEarlyWarningNumbers(unittest.TestCase):
    """Lead times stated in the newsletter. If a number fails without an
    intentional model change, fix the TEXT, not the test."""

    @classmethod
    def setUpClass(cls):
        cls.res = evaluate([6, 9, 10, 12, 15], SEEDS)

    def test_no_default_at_6_per_minute(self):
        self.assertTrue(all(r[0] is None for r in self.res[6]))

    def test_defaults_on_13_of_20_days_at_10(self):
        self.assertEqual(sum(r[0] is not None for r in self.res[10]), 13)

    def test_median_lead_times(self):
        expected = {10: (246, 67, 202), 12: (44, 25, 32), 15: (20, 14, 10)}
        names = ["A utilization", "B deadline proximity", "C queue growth"]
        for lam, meds in expected.items():
            for name, want in zip(names, meds):
                _, late, med, _, _ = summarize(self.res[lam], name)
                self.assertEqual(late, 0)
                self.assertEqual(round(med), want, f"{lam}/min rule {name}")

    def test_alerts_on_days_with_no_default(self):
        _, _, _, fa_a, nd = summarize(self.res[9], "A utilization")
        self.assertEqual((fa_a, nd), (20, 20))
        _, _, _, fa_b, _ = summarize(self.res[9], "B deadline proximity")
        self.assertEqual(fa_b, 4)
        _, _, _, fa_c, _ = summarize(self.res[9], "C queue growth")
        self.assertEqual(fa_c, 19)


if __name__ == "__main__":
    unittest.main()
