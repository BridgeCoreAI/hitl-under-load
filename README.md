# HITL Under Load

**At what load does "human in the loop" quietly become "acted anyway"?**

A discrete-event simulator of a human approval queue, built to test the claim
behind every human oversight policy: *a person approves every action before it
executes.* That claim is not a property of the system. It is a property of the
load. This instrument measures the threshold.

Part of the evidence series behind the Execution Governance Model (EGM) at
BridgeCore AI.

## What it models

| Parameter | Meaning |
|---|---|
| `arrival_rate` (lambda) | How fast new decisions land in the queue (items/minute) |
| `service_rate` (mu) | How fast one human can clear them (items/minute) |
| `timeout_min` | How long an item may wait before the default fires |
| `policy` | The timeout default: `FAIL_OPEN`, `FAIL_CLOSED`, `DEFER`, `ESCALATE` |
| `gate` | Deterministic admissibility check at arrival (v2) |
| `violation_rate` | Share of arriving traffic that violates a constraint |

Every run simulates one full workday (480 minutes). Fixed random seed: every
number is reproducible.

## Run it

```bash
python3 hitl_sim.py          # the four case study scenarios
python3 hitl_sim.py sweep    # lambda sweep: where the threshold sits
python3 hitl_sim.py demo     # one scenario at a time: demo | surge | closed | gate
```

Requires Python 3.8+, standard library only.

## What it shows

**Finding 1: the threshold is real, and it is exact.** At lambda = 6 against a
human who clears 10 per minute, the system is flawless: 2,828 decisions, the
human approves all of them. At lambda = 10, exactly the human's capacity, the
first 64 silent actions appear. At lambda = 30, 66.9% of the day's decisions
are made by the timeout default. The human's ceiling never moves; everything
above it belongs to the default.

**Finding 2: approval is not verification.** Add a deterministic admissibility
gate at arrival (zero time, zero human cost) and the dilemma dissolves. On a
surge day with 40% of traffic in violation:

| Configuration | Inadmissible executed | Admissible blocked |
|---|---|---|
| Fail open, no gate | 3,859 | 0 |
| Fail closed, no gate | 0 | 5,628 |
| Gate on | 0 | 0 |

**The honest limit.** The gate solves the validity problem completely and the
capacity problem not at all. With the gate on, 25.7% of decisions are still
made by the timeout. Validity is an architecture problem. Capacity is a design
problem. Do not confuse them.

## Files

- `hitl_sim.py` — the simulator, single file, no dependencies
- `chart1_threshold.png` — Finding 1: the silent-action curve
- `chart2_gate.png` — Finding 2: the gate resolves the dilemma
- `Case Study — Human Oversight Under Load.md` — the full write-up

## License

MIT. Run it against your own numbers. If you operate a human oversight
process and want to know where its threshold is, the instrument is yours.

---

*BridgeCore AI — governance is not what is defined. It is what is enforced at
execution.*
