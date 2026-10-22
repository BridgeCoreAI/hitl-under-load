"""Early-warning extension for HITL Under Load.

Subclasses HitlSim without modifying hitl_sim.py, so every published result stays
reproducible. Adds a one minute snapshot of the queue and the time of the first
decision handed to the timeout default, then compares three alert rules.

Thresholds are judgment calls set at the top of the file. They are not findings.

    python3 early_warning.py            # lead time table, 20 seeds per load
"""
import heapq
import statistics

from hitl_sim import Config, HitlSim, TimeoutPolicy

MU, TIMEOUT = 10.0, 10.0
TIMEOUT_OUTCOMES = {"AUTO_APPROVED", "BLOCKED", "DROPPED", "ESCALATED"}

UTIL_LIMIT = 0.8     # rule A: rolling 30 minute utilization above this
PROX_LIMIT = 0.5     # rule B: oldest waiting item older than this share of the timeout
GROW_MINUTES = 10    # rule C: queue deeper than 10 minutes ago, for 10 minutes in a row
MIN_DEPTH = 10       # rule C: ignore tiny queues
SEEDS = range(1, 21)
LAMBDAS = [6, 8, 9, 10, 11, 12, 15]


class TelemetrySim(HitlSim):
    def run(self):
        self.snaps, self.arrival_times = [], []
        self.schedule(0.0, "arrival")
        for m in range(1, int(self.cfg.duration_min) + 1):
            self.schedule(float(m), "sample")
        while self.events:
            time, _, kind, item = heapq.heappop(self.events)
            if time > self.cfg.duration_min:
                break
            self.now = time
            if kind == "arrival":
                self.arrival_times.append(self.now)
                self.on_arrival()
            elif kind == "service_done":
                self.on_service_done(item)
            elif kind == "sample":
                self.snapshot()
        return self.report()

    def snapshot(self):
        q = self.queue
        oldest = (self.now - q[0].arrived_at) if q else 0.0
        overdue = 0
        for it in q:  # queue is in arrival order, so deadlines are ordered
            if it.deadline <= self.now:
                overdue += 1
            else:
                break
        lo = self.now - 30.0
        arrivals_30 = sum(1 for a in self.arrival_times[-1000:] if a > lo)
        self.snaps.append(dict(t=self.now, depth=len(q), oldest=oldest,
                               overdue=overdue, arrivals_30=arrivals_30))

    def first_default_time(self):
        times = [o[2] for o in self.outcomes if o[3] in TIMEOUT_OUTCOMES]
        if self.queue and self.queue[0].deadline <= self.cfg.duration_min:
            times.append(self.queue[0].deadline)
        return min(times) if times else None


def run_one(lam, seed, mu=MU, timeout=TIMEOUT, policy=TimeoutPolicy.FAIL_OPEN):
    sim = TelemetrySim(Config(arrival_rate=float(lam), service_rate=mu,
                              timeout_min=timeout, policy=policy, seed=seed))
    return sim, sim.run()


def rule_A(snaps):
    for s in snaps:
        if s["t"] >= 10 and s["arrivals_30"] / min(s["t"], 30.0) / MU > UTIL_LIMIT:
            return s["t"]


def rule_B(snaps):
    for s in snaps:
        if s["oldest"] > PROX_LIMIT * TIMEOUT:
            return s["t"]


def rule_C(snaps):
    run = 0
    for i, s in enumerate(snaps):
        if (i >= GROW_MINUTES and s["depth"] > snaps[i - GROW_MINUTES]["depth"]
                and s["depth"] >= MIN_DEPTH):
            run += 1
        else:
            run = 0
        if run >= GROW_MINUTES:
            return s["t"]


RULES = {"A utilization": rule_A, "B deadline proximity": rule_B, "C queue growth": rule_C}


def evaluate(lambdas=LAMBDAS, seeds=SEEDS):
    out = {}
    for lam in lambdas:
        runs = []
        for seed in seeds:
            sim, _ = run_one(lam, seed)
            runs.append((sim.first_default_time(), {n: f(sim.snaps) for n, f in RULES.items()}))
        out[lam] = runs
    return out


def summarize(runs, name):
    """Return (early, late_or_missed, median_lead_minutes, alerts_on_no_default_days)."""
    d = [r for r in runs if r[0] is not None]
    nd = [r for r in runs if r[0] is None]
    leads = [r[0] - r[1][name] for r in d if r[1][name] is not None and r[1][name] < r[0]]
    fa = sum(1 for r in nd if r[1][name] is not None)
    med = statistics.median(leads) if leads else None
    return len(leads), len(d) - len(leads), med, fa, len(nd)


if __name__ == "__main__":
    res = evaluate()
    print("20 seeds per load. Fail-open, capacity 10 per minute, timeout 10 minutes.\n")
    print(f"{'load':>4} {'runs with':>9}  {'rule':<21} {'early':>6} {'late/missed':>12} "
          f"{'median lead':>12} {'alert, no default':>18}")
    print("-" * 90)
    for lam, runs in res.items():
        nd_days = sum(1 for r in runs if r[0] is None)
        for name in RULES:
            early, late, med, fa, nd = summarize(runs, name)
            m = f"{med:.0f}" if med is not None else "n/a"
            print(f"{lam:>4} {len(runs) - nd:>6}/20  {name:<21} {early:>6} {late:>12} {m:>12} {fa:>14}/{nd}")
        print()
