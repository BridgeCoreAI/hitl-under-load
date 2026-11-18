[![tests](https://github.com/BridgeCoreAI/hitl-under-load/actions/workflows/tests.yml/badge.svg)](https://github.com/BridgeCoreAI/hitl-under-load/actions/workflows/tests.yml)

# HITL Under Load

Recorded runs with commit bindings: see the [Actions tab](https://github.com/BridgeCoreAI/hitl-under-load/actions/workflows/tests.yml). Every number in this README and the case study is re-verified by executable tests on every push.

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

## Early warning: seeing the handoff before it happens

`early_warning.py` extends the simulator without modifying it. A subclass records a
snapshot of the queue every simulated minute and compares three alert rules against
the first decision handed to the timeout default. Thresholds (0.8 utilization, 50% of
the timeout, ten minutes of queue growth) are judgment calls, not findings.

```bash
python3 early_warning.py     # lead times, 20 seeds per load
```

| Load (per min) | A: utilization | B: deadline proximity | C: queue growth |
|---|---|---|---|
| 10 | 246 | 67 | 202 |
| 11 | 76 | 37 | 66 |
| 12 | 44 | 25 | 32 |
| 15 | 20 | 14 | 10 |

Median minutes of warning before the first default. Utilization and queue growth warn
early but are noisy on days with no default; deadline proximity is quiet but gives the
least notice. Suggested tiers: WATCH (A or C), ACT (B), HANDOFF (default share above 0).

## Intervention margin: was the warning early enough to act?

`intervention_margin.py` extends the early warning analysis without modifying it. It
reuses `evaluate` and the three alert rules from `early_warning.py`, so no simulator
or rule logic is duplicated and `hitl_sim.py` and `early_warning.py` are unchanged.

An early alert is not the same as a usable alert. A warning that arrives one minute
before the first default is early, but no person can respond in one minute if the
assumed response takes five. The extension subtracts an assumed response time from
the warning lead time.

```
Warning lead time   = first default time minus alert time
Intervention margin = warning lead time minus required human response time
```

The required human response time is an explicit assumption set by the person running
the analysis. It is not an empirical finding, and the defaults of 2, 5 and 10 minutes
are illustrative only.

Every run, for every alert rule, falls in exactly one of five categories, and the
counts are kept separate:

| Category | Meaning |
|---|---|
| No default | No decision was handed to the timeout default, so there is nothing to warn about |
| No advance alert | A default occurred, but the rule did not alert strictly before it |
| Positive margin | The alert left more time than the assumed human response |
| Zero margin | The alert left exactly the assumed human response time |
| Negative margin | The alert came before the default but left too little time for the assumed response |

A negative margin is not a missed alert, and it is not a sufficient one either. The
alert was early, yet under the stated assumption a person would still have run out of
time. It is counted on its own.

```bash
python3 intervention_margin.py                                    # default response times 2, 5, 10
python3 intervention_margin.py --response-times 3 8 --lambdas 10 12 --seeds 20
python3 -m pytest -q                                              # existing and new tests
```

Observed output with an assumed response time of 10 minutes, 20 seeds per load, fail
open, capacity 10 per minute, timeout 10 minutes. Each rule cell reads positive / zero
/ negative.

| Load (per min) | No default | No advance alert | A: utilization | B: deadline proximity | C: queue growth |
|---|---|---|---|---|---|
| 10 | 7 | 0 | 13 / 0 / 0 | 13 / 0 / 0 | 13 / 0 / 0 |
| 12 | 0 | 0 | 20 / 0 / 0 | 20 / 0 / 0 | 20 / 0 / 0 |
| 15 | 0 | 0 | 20 / 0 / 0 | 20 / 0 / 0 | 11 / 0 / 9 |

Observations from this run only: no rule failed to alert before a default in any of
the 20 seeds at these loads, and the only negative margins appear for queue growth at
15 per minute under the 10 minute assumption. Run the command with other response
times to see the full tables for every load. How these counts bear on a real process
depends on a real response time, which this simulation does not supply.

Verification: the complete suite, 48 tests (20 existing and 28 new), passed with
`python3 -m pytest -q` and with `python3 -m unittest discover -s tests`. The new tests
cover positive, zero and negative margins, no advance alert, no default, different
response times, deterministic reproduction, every alert rule, separate aggregate
counts, and unchanged existing simulator and early warning results.

Limitations: the simulation is synthetic. Arrivals, service times and alert thresholds
are modeling choices. One response time is applied to every run, while real response
times vary. Nothing here measures production effectiveness or real staffing.

## Files

- `hitl_sim.py` — the simulator, single file, no dependencies
- `early_warning.py` — early-warning extension: telemetry subclass and alert rules
- `intervention_margin.py`: intervention margin extension, reuses the early warning rules
- `tests/test_intervention_margin.py`: tests for the intervention margin extension
- `chart1_threshold.png` — Finding 1: the silent-action curve
- `chart2_gate.png` — Finding 2: the gate resolves the dilemma
- `Case Study — Human Oversight Under Load.md` — the full write-up

## License

MIT. Run it against your own numbers. If you operate a human oversight
process and want to know where its threshold is, the instrument is yours.

---

*BridgeCore AI — governance is not what is defined. It is what is enforced at
execution.*
