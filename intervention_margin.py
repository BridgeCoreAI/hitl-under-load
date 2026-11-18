"""Intervention margin extension for HITL Under Load.

Author: Grace Adjeli | BridgeCore AI LLC

The early warning extension measures the warning lead time: the time between an
alert and the first decision handed to the timeout default. A long lead time does
not show that a person could have acted in time. This module asks the next
question: was the warning early enough for an assumed human response?

    Warning lead time   = first default time minus alert time
    Intervention margin = warning lead time minus required human response time

The required human response time is an explicit assumption supplied by the caller.
It is not an empirical finding. The simulation is synthetic, and nothing here
describes production effectiveness or real staffing.

Every run falls in exactly one of five categories:

    NO_DEFAULT         no decision was handed to the timeout default
    NO_ADVANCE_ALERT   a default occurred, but the rule did not alert before it
    POSITIVE           the alert left more time than the assumed human response
    ZERO               the alert left exactly the assumed human response time
    NEGATIVE           the alert came before the default but left too little time

Reuses evaluate, RULES and the telemetry simulator from early_warning.py. It does
not modify hitl_sim.py or early_warning.py, so every published result stays as it was.

    python3 intervention_margin.py
    python3 intervention_margin.py --response-times 3 8 --lambdas 10 12 --seeds 20
"""
import argparse
import math
import statistics
from collections import Counter

from early_warning import LAMBDAS, RULES, SEEDS, evaluate

NO_DEFAULT = "NO_DEFAULT"
NO_ADVANCE_ALERT = "NO_ADVANCE_ALERT"
POSITIVE = "POSITIVE"
ZERO = "ZERO"
NEGATIVE = "NEGATIVE"
CATEGORIES = (NO_DEFAULT, NO_ADVANCE_ALERT, POSITIVE, ZERO, NEGATIVE)

# Illustrative assumptions in minutes. They are inputs, not findings.
DEFAULT_RESPONSE_TIMES = (2.0, 5.0, 10.0)


def check_response_time(required_response_min):
    """The assumed human response time must be a finite number, zero or more."""
    ok = (isinstance(required_response_min, (int, float))
          and not isinstance(required_response_min, bool)
          and math.isfinite(required_response_min)
          and required_response_min >= 0)
    if not ok:
        raise ValueError("required_response_min must be a finite number of minutes, zero or more")


def classify(default_time, alert_time, required_response_min):
    """Classify one run for one alert rule.

    default_time: minute of the first decision handed to the timeout default, or None.
    alert_time: minute the rule first alerted, or None.
    An alert counts as an advance alert only if it came strictly before the default,
    the same test early_warning.py uses for its lead times.
    """
    check_response_time(required_response_min)
    result = {"category": None, "default_time": default_time, "alert_time": alert_time,
              "lead": None, "margin": None}
    if default_time is None:
        result["category"] = NO_DEFAULT
        return result
    if alert_time is None or alert_time >= default_time:
        result["category"] = NO_ADVANCE_ALERT
        return result
    lead = default_time - alert_time
    margin = round(lead - required_response_min, 9)
    result["lead"] = lead
    result["margin"] = margin
    if margin > 0:
        result["category"] = POSITIVE
    elif margin == 0:
        result["category"] = ZERO
    else:
        result["category"] = NEGATIVE
    return result


def summarize_margin(runs, rule, required_response_min):
    """Count the five categories separately for one rule and one response time.

    runs is the list for one load from early_warning.evaluate: one
    (first_default_time, {rule: alert_time}) pair per seed.
    """
    counts = Counter({c: 0 for c in CATEGORIES})
    leads, margins = [], []
    for default_time, alerts in runs:
        r = classify(default_time, alerts[rule], required_response_min)
        counts[r["category"]] += 1
        if r["margin"] is not None:
            leads.append(r["lead"])
            margins.append(r["margin"])
    return {
        "runs": len(runs),
        "counts": {c: counts[c] for c in CATEGORIES},
        "advance_alerts": counts[POSITIVE] + counts[ZERO] + counts[NEGATIVE],
        "median_lead": statistics.median(leads) if leads else None,
        "median_margin": statistics.median(margins) if margins else None,
    }


def margin_table(lambdas=LAMBDAS, seeds=SEEDS, response_times=DEFAULT_RESPONSE_TIMES):
    """Return {response_time: {load: {rule: summary}}} from one set of simulations."""
    res = evaluate(lambdas, seeds)
    return {rt: {lam: {name: summarize_margin(res[lam], name, rt) for name in RULES}
                 for lam in lambdas}
            for rt in response_times}


def fmt(value):
    return "n/a" if value is None else f"{value:.1f}"


def print_table(table, seed_count):
    print(f"{seed_count} seeds per load. Fail open, capacity 10 per minute, timeout 10 minutes.")
    print("The required human response time is an assumption, not a finding.")
    for rt, by_load in table.items():
        print(f"\nAssumed human response time: {rt:g} minutes")
        print(f"{'load':>4}  {'rule':<21} {'no default':>10} {'no advance alert':>17} "
              f"{'positive':>9} {'zero':>5} {'negative':>9} {'median margin':>14}")
        print("-" * 96)
        for lam, by_rule in by_load.items():
            for name, s in by_rule.items():
                c = s["counts"]
                print(f"{lam:>4}  {name:<21} {c[NO_DEFAULT]:>10} {c[NO_ADVANCE_ALERT]:>17} "
                      f"{c[POSITIVE]:>9} {c[ZERO]:>5} {c[NEGATIVE]:>9} "
                      f"{fmt(s['median_margin']):>14}")
            print()


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Intervention margin analysis for HITL Under Load.")
    p.add_argument("--response-times", type=float, nargs="+", default=list(DEFAULT_RESPONSE_TIMES),
                   help="assumed human response times in minutes")
    p.add_argument("--lambdas", type=int, nargs="+", default=list(LAMBDAS),
                   help="arrival rates per minute")
    p.add_argument("--seeds", type=int, default=len(SEEDS),
                   help="number of fixed seeds, 1 to N")
    args = p.parse_args(argv)
    if args.seeds < 1:
        p.error("--seeds must be at least 1")
    for rt in args.response_times:
        try:
            check_response_time(rt)
        except ValueError as exc:
            p.error(str(exc))
    return args


def main(argv=None):
    args = parse_args(argv)
    seeds = range(1, args.seeds + 1)
    table = margin_table(args.lambdas, seeds, args.response_times)
    print_table(table, args.seeds)


if __name__ == "__main__":
    main()
