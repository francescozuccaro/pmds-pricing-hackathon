"""Evaluate one candidate agent bundle across scenarios, seeds and fixed rosters.

Examples:
    uv run python benchmarks/eval_zuccaro.py
    uv run python benchmarks/eval_zuccaro.py --scenarios default extended --seeds 10
    uv run python benchmarks/eval_zuccaro.py --candidate /path/to/snapshot --label v1

For every scenario it prints the candidate's mean / min final capital, mean rank
among all teams, and the slowest single decide() call. Per-run results are saved
to benchmarks/results/<label>.json so versions can be compared later.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = ROOT / "src" / "dme_simulator" / "agents"
CANDIDATE_ID = "zuccaro-agent"

# 7-team roster for the short scenarios.
SMALL_ROSTER = {
    "DummyAgent": 1, "PatientAgent": 1, "PriceWarAgent": 1,
    "sparring-clone": 1, "sparring-aggressive": 1, "sparring-cautious": 1,
}
# 39 opponents + candidate = 40 teams, like the public leaderboard.
LARGE_ROSTER = {
    "sparring-clone": 10, "sparring-aggressive": 6, "sparring-cautious": 8,
    "DummyAgent": 7, "PriceWarAgent": 6, "PatientAgent": 2,
}

# Strong field: several copies of our own (frozen) strategy.
STRONG_SMALL = dict(SMALL_ROSTER, **{"sparring-selfplay": 2})
STRONG_LARGE = {
    "sparring-selfplay": 10, "sparring-clone": 6, "sparring-aggressive": 6,
    "sparring-cautious": 6, "DummyAgent": 5, "PriceWarAgent": 5, "PatientAgent": 1,
}

# Arenas: many copies of the frozen champion; a better candidate ranks above them.
ARENA_SMALL = {"sparring-selfplay": 3, "sparring-clone": 1, "PriceWarAgent": 1,
               "sparring-cautious": 1}
ARENA_LARGE = {"sparring-selfplay": 15, "sparring-clone": 6, "sparring-aggressive": 4,
               "sparring-cautious": 6, "DummyAgent": 4, "PriceWarAgent": 4}

# Closer to the public leaderboard: few floor-price dumpers, many slow/cautious
# teams, a handful of capable rivals (copies of our champion).
REAL_LARGE = {"sparring-selfplay": 5, "sparring-cautious": 12, "DummyAgent": 8,
              "PriceWarAgent": 5, "PatientAgent": 5, "sparring-clone": 2,
              "sparring-aggressive": 2}

# Fewer cheap sellers, many starter-like and cautious teams.
REAL2_LARGE = {"sparring-starter": 14, "sparring-cautious": 10, "sparring-selfplay": 5,
               "PriceWarAgent": 3, "DummyAgent": 2, "PatientAgent": 3,
               "sparring-clone": 1, "sparring-aggressive": 1}

# Price-discovery / ramp benchmark: we are the only seller.
MONOPOLY = {"PatientAgent": 39}
# High-price field: rivals that sell slowly at value-ish prices.
HIGHPRICE = {"sparring-cautious": 20, "sparring-starter": 10, "PatientAgent": 9}

SCENARIOS = {
    "default": (ROOT / "config/default.yaml", SMALL_ROSTER, None),
    "scaled": (ROOT / "config/scaled_market.yaml", SMALL_ROSTER, None),
    "extended": (ROOT / "benchmarks/configs/default_extended.yaml", LARGE_ROSTER, None),
    "highdemand": (ROOT / "benchmarks/configs/high_demand.yaml", LARGE_ROSTER, None),
    # same market, small roster: isolates our own scaling over 240 turns
    "extended_small": (ROOT / "benchmarks/configs/default_extended.yaml", SMALL_ROSTER, None),
    "default_strong": (ROOT / "config/default.yaml", STRONG_SMALL, None),
    "extended_strong": (ROOT / "benchmarks/configs/default_extended.yaml", STRONG_LARGE, None),
    "highdemand_strong": (ROOT / "benchmarks/configs/high_demand.yaml", STRONG_LARGE, None),
    "observe_all": (ROOT / "benchmarks/configs/observe_all.yaml", STRONG_LARGE, None),
    "capacity_cap": (ROOT / "benchmarks/configs/capacity_cap.yaml", STRONG_LARGE, None),
    "default_arena": (ROOT / "config/default.yaml", ARENA_SMALL, None),
    "ext_arena": (ROOT / "benchmarks/configs/default_extended.yaml", ARENA_LARGE, None),
    "hd_arena": (ROOT / "benchmarks/configs/high_demand.yaml", ARENA_LARGE, None),
    "ext_real": (ROOT / "benchmarks/configs/default_extended.yaml", REAL_LARGE, None),
    "ext_real2": (ROOT / "benchmarks/configs/default_extended.yaml", REAL2_LARGE, None),
    "ext_monopoly": (ROOT / "benchmarks/configs/default_extended.yaml", MONOPOLY, None),
    "ext_highprice": (ROOT / "benchmarks/configs/default_extended.yaml", HIGHPRICE, None),
    "default_crowd": (ROOT / "config/default.yaml", REAL2_LARGE, None),
    "tut_pricing": (ROOT / "config/tutorial_pricing.yaml", SMALL_ROSTER, None),
    "tut_auction": (ROOT / "config/tutorial_auction.yaml", SMALL_ROSTER, None),
}


def _run(job: dict) -> dict:
    from dme_simulator.agents.loader import discover_bundle_classes
    from dme_simulator.config import load_config
    from dme_simulator.runner import run_simulation

    config_path, roster, turns = SCENARIOS[job["scenario"]]
    config = load_config(config_path)
    config = replace(
        config,
        output=replace(config.output, render_plots=False,
                       progress_interval_turns=0, dashboard="none"),
    )
    classes = discover_bundle_classes([AGENTS_DIR])
    cand_classes = discover_bundle_classes([Path(job["candidate"])])
    cand_class = next(iter(cand_classes.values()))

    agents = {CANDIDATE_ID: cand_class()}
    for agent_id, count in roster.items():
        for i in range(1, count + 1):
            team = agent_id if count == 1 else f"{agent_id}_{i}"
            agents[team] = classes[agent_id]()

    started = time.perf_counter()
    sim = run_simulation(config, agents, seed_override=job["seed"],
                         turns_override=job["turns"] or turns,
                         profile=True, quiet=True)
    capitals = {t: s.capital for t, s in sim.teams_state.items()}
    ordered = sorted(capitals.values(), reverse=True)
    mine = capitals[CANDIDATE_ID]
    # average rank for ties
    better = sum(1 for c in ordered if c > mine)
    equal = sum(1 for c in ordered if c == mine)
    rank = better + (equal + 1) / 2
    durations = sim.history.diagnostics.decision_duration_seconds.get(CANDIDATE_ID, [])
    best_other = max(c for t, c in capitals.items() if t != CANDIDATE_ID)
    inv = sim.teams_state[CANDIDATE_ID].inventory
    return {
        "scenario": job["scenario"], "seed": job["seed"], "capital": mine,
        "rank": rank, "teams": len(capitals), "best_other": best_other,
        "max_ms": max(durations) * 1000 if durations else 0.0,
        "mean_ms": statistics.mean(durations) * 1000 if durations else 0.0,
        "end_inventory": sum(inv.values()),
        "wall_s": time.perf_counter() - started,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--candidate", type=Path, default=AGENTS_DIR / CANDIDATE_ID)
    parser.add_argument("--scenarios", nargs="+", default=list(SCENARIOS),
                        choices=list(SCENARIOS))
    parser.add_argument("--seeds", type=int, default=6)
    parser.add_argument("--seed-base", type=int, default=100)
    parser.add_argument("--turns", type=int, default=None)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--horizons", type=int, nargs="+", default=None,
                        help="run every scenario at each of these turn counts "
                             "(the official ranking averages short and long games)")
    parser.add_argument("--label", default="latest")
    args = parser.parse_args()

    horizons = args.horizons or [args.turns]
    jobs = [
        {"scenario": s, "seed": args.seed_base + i, "turns": h,
         "candidate": str(args.candidate.resolve())}
        for s in args.scenarios for h in horizons for i in range(args.seeds)
    ]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(_run, jobs))
    for job, r in zip(jobs, results):
        r["horizon"] = job["turns"]
        if job["turns"]:
            r["scenario"] = f"{job['scenario']}@{job['turns']}"
    rows = list(dict.fromkeys(r["scenario"] for r in results))

    print(f"\n[{args.label}] candidate={args.candidate}")
    print(f"{'scenario':<22}{'mean cap':>13}{'min cap':>13}{'best other':>13}"
          f"{'mean rank':>11}{'worst':>7}{'max ms':>8}{'end inv':>9}")
    for s in rows:
        rs = [r for r in results if r["scenario"] == s]
        caps = [r["capital"] for r in rs]
        ranks = [r["rank"] for r in rs]
        print(f"{s:<22}{statistics.mean(caps):>13,.0f}{min(caps):>13,.0f}"
              f"{statistics.mean(r['best_other'] for r in rs):>13,.0f}"
              f"{statistics.mean(ranks):>8.2f}/{rs[0]['teams']:<2}{max(ranks):>7.1f}"
              f"{max(r['max_ms'] for r in rs):>8.1f}"
              f"{statistics.mean(r['end_inventory'] for r in rs):>9.0f}")
    print(f"OVERALL mean rank {statistics.mean(r['rank'] for r in results):.3f}  "
          f"worst {max(r['rank'] for r in results):g}  "
          f"rows not won: {sum(1 for s in rows if any(r['rank'] > 1 for r in results if r['scenario'] == s))}/{len(rows)}")
    out = ROOT / "benchmarks" / "results"
    out.mkdir(exist_ok=True)
    (out / f"{args.label}.json").write_text(json.dumps(results, indent=1))


if __name__ == "__main__":
    main()
