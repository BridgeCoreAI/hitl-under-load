"""
HITL Under Load — v2 simulator (GateSim)
BridgeCore AI / Grace M. Adjeli

Question: at what load does "human in the loop" quietly become "acted anyway"?
Method: discrete-event simulation of a human approval queue.
  lambda (arrival_rate) = how fast items knock on the door (items/minute)
  mu     (service_rate) = how fast the human clears them (items/minute)
  timeout_min           = how long an item may wait before the default fires
  policy                = the default nobody wrote down, written down
  gate                  = deterministic admissibility check at arrival (v2)
  violation_rate        = share of arriving traffic that violates a constraint

v2 adds the second layer of the architecture: an admissibility gate.
Every arriving item is either admissible or in violation of a constraint
(unauthorized, malformed, out of bounds). When the gate is on, it checks
each item at arrival, deterministically, in zero time, at zero human cost.
Rejected items never enter the human's queue.

Two failures, two different fixes:
  validity  = an architecture problem (the gate)
  capacity  = a design problem (staffing, timeouts, escalation)

Run:  python3 hitl_sim.py           # case study scenarios
      python3 hitl_sim.py sweep     # lambda sweep behind chart 1
"""

import heapq
import random
import sys
from collections import deque, Counter
from dataclasses import dataclass
from enum import Enum


class TimeoutPolicy(Enum):
    """What the system does when an item waits longer than its timeout."""
    FAIL_OPEN = "fail_open"      # approve it anyway, no human involved
    FAIL_CLOSED = "fail_closed"  # block it, backlog or not
    DEFER = "defer"              # quietly drop it to a log
    ESCALATE = "escalate"        # hand it to a second queue (not modeled here)


@dataclass
class Config:
    arrival_rate: float        # lambda: new items per minute
    service_rate: float        # mu: items per minute the human can clear
    timeout_min: float         # how long an item may wait before the default fires
    policy: TimeoutPolicy
    gate: bool = False         # v2: deterministic admissibility check at arrival
    violation_rate: float = 0.40   # share of arrivals that violate a constraint
    duration_min: float = 480.0    # one workday
    seed: int = 42


@dataclass
class Item:
    id: int
    arrived_at: float
    deadline: float            # arrived_at + timeout: the moment governance quietly expires
    admissible: bool           # v2: does this item satisfy every checkable constraint


class HitlSim:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.rng = random.Random(cfg.seed)
        # separate stream for admissibility: arrival/service timing stays identical
        # across gate-on and gate-off runs, so configurations differ ONLY by policy
        self.gate_rng = random.Random(cfg.seed + 1000)
        self.events = []               # the future: a heap of (time, seq, kind, item)
        self.seq = 0
        self.now = 0.0
        self.queue = deque()           # admissible items waiting for the human
        self.approver_busy = False
        self.outcomes = []             # (item_id, arrived_at, resolved_at, outcome, admissible)
        self.max_queue_depth = 0
        self.next_id = 0

    def schedule(self, time, kind, item=None):
        heapq.heappush(self.events, (time, self.seq, kind, item))
        self.seq += 1

    def run(self):
        self.schedule(0.0, "arrival")
        while self.events:
            time, _, kind, item = heapq.heappop(self.events)
            if time > self.cfg.duration_min:
                break
            self.now = time
            if kind == "arrival":
                self.on_arrival()
            elif kind == "service_done":
                self.on_service_done(item)
        return self.report()

    def on_arrival(self):
        admissible = self.gate_rng.random() >= self.cfg.violation_rate
        item = Item(self.next_id, self.now, self.now + self.cfg.timeout_min, admissible)
        self.next_id += 1
        # schedule the next knock on the door (exponential spacing = realistic randomness)
        self.schedule(self.now + self.rng.expovariate(self.cfg.arrival_rate), "arrival")

        # THE GATE: deterministic, zero-time, zero-human-cost. Violations never queue.
        if self.cfg.gate and not item.admissible:
            self.outcomes.append((item.id, item.arrived_at, self.now, "GATE_REJECTED", False))
            return

        if not self.approver_busy:
            self.start_service(item)
        else:
            self.queue.append(item)
            self.max_queue_depth = max(self.max_queue_depth, len(self.queue))

    def start_service(self, item):
        self.approver_busy = True
        self.schedule(self.now + self.rng.expovariate(self.cfg.service_rate), "service_done", item)

    def resolve_timeout(self, item):
        """The deadline passed with no human decision. The DEFAULT decides now."""
        outcome = {
            TimeoutPolicy.FAIL_OPEN: "AUTO_APPROVED",
            TimeoutPolicy.FAIL_CLOSED: "BLOCKED",
            TimeoutPolicy.DEFER: "DROPPED",
            TimeoutPolicy.ESCALATE: "ESCALATED",
        }[self.cfg.policy]
        self.outcomes.append((item.id, item.arrived_at, item.deadline, outcome, item.admissible))

    def on_service_done(self, item):
        self.outcomes.append((item.id, item.arrived_at, self.now, "HUMAN_APPROVED", item.admissible))
        self.approver_busy = False
        # THE MOMENT THAT MATTERS: drain everything that expired while the human was busy
        while self.queue and self.queue[0].deadline <= self.now:
            self.resolve_timeout(self.queue.popleft())
        if self.queue:
            self.start_service(self.queue.popleft())

    def report(self):
        counts = Counter(o[3] for o in self.outcomes)
        total = len(self.outcomes)
        human = counts.get("HUMAN_APPROVED", 0)
        timeout_decisions = (counts.get("AUTO_APPROVED", 0) + counts.get("BLOCKED", 0)
                             + counts.get("DROPPED", 0))
        inadmissible_executed = sum(
            1 for _, _, _, o, ok in self.outcomes if o == "AUTO_APPROVED" and not ok)
        admissible_blocked = sum(
            1 for _, _, _, o, ok in self.outcomes if o == "BLOCKED" and ok)
        waits = [r - a for _, a, r, o, _ in self.outcomes if o == "HUMAN_APPROVED"]
        return {
            "policy": self.cfg.policy.value,
            "gate": "on" if self.cfg.gate else "off",
            "arrival_rate": self.cfg.arrival_rate,
            "items_processed": total,
            "human_approved": human,
            "auto_approved": counts.get("AUTO_APPROVED", 0),
            "blocked": counts.get("BLOCKED", 0),
            "dropped": counts.get("DROPPED", 0),
            "gate_rejected": counts.get("GATE_REJECTED", 0),
            "timeout_decisions_%": round(100 * timeout_decisions / total, 1) if total else 0.0,
            "inadmissible_executed": inadmissible_executed,
            "admissible_blocked": admissible_blocked,
            "max_queue_depth": self.max_queue_depth,
            "avg_wait_min": round(sum(waits) / len(waits), 1) if waits else 0.0,
            "left_in_queue_at_close": len(self.queue),
        }


def case_study_runs():
    """The configurations behind the case study findings."""
    base = dict(service_rate=10.0, timeout_min=10.0, duration_min=480.0)
    runs = [
        ("Demo load (lambda=6, fail-open)",
         Config(arrival_rate=6.0,  policy=TimeoutPolicy.FAIL_OPEN,   **base)),
        ("Surge (lambda=30, fail-open, no gate)",
         Config(arrival_rate=30.0, policy=TimeoutPolicy.FAIL_OPEN,   **base)),
        ("Surge (lambda=30, fail-closed, no gate)",
         Config(arrival_rate=30.0, policy=TimeoutPolicy.FAIL_CLOSED, **base)),
        ("Surge (lambda=30, fail-open, gate on)",
         Config(arrival_rate=30.0, policy=TimeoutPolicy.FAIL_OPEN, gate=True, **base)),
    ]
    for label, cfg in runs:
        r = HitlSim(cfg).run()
        print(f"\n{label}")
        for k, v in r.items():
            print(f"  {k:24} {v}")


def sweep():
    """Lambda sweep behind Finding 1: where does the human stop being in the loop?"""
    base = dict(service_rate=10.0, timeout_min=10.0, duration_min=480.0)
    print(f"\n{'lambda':>6} {'processed':>10} {'human':>7} {'silent %':>9} {'max queue':>10}")
    for lam in [4, 6, 8, 10, 12, 15, 20, 25, 30]:
        r = HitlSim(Config(arrival_rate=float(lam), policy=TimeoutPolicy.FAIL_OPEN, **base)).run()
        silent = round(100 * r["auto_approved"] / r["items_processed"], 1)
        print(f"{lam:>6} {r['items_processed']:>10} {r['human_approved']:>7} "
              f"{silent:>9} {r['max_queue_depth']:>10}")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "sweep":
        sweep()
    else:
        case_study_runs()


if __name__ == "__main__":
    main()
