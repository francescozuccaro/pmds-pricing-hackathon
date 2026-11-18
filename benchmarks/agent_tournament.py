"""Local tournament: zuccaro-agent vs baselines and synthetic rivals.

Plays both visible scenarios like the portal does:
  * default           - config/default.yaml, 40 turns, 12k start
  * default_extended  - benchmarks/configs/default_extended.yaml, 80 turns, 40k start
For every agent it prints mean / min final capital, mean rank per scenario and
the aggregate mean rank (the official score), and writes the capital curves to
benchmarks/results/tournament_curves.csv.

    uv run python benchmarks/agent_tournament.py                 # 20 seeds, small field
    uv run python benchmarks/agent_tournament.py --field large   # ~38 teams like the portal
    uv run python benchmarks/agent_tournament.py --seeds 30 --ext-turns 240
"""

from __future__ import annotations

import argparse
import csv
import statistics
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = ROOT / "src" / "dme_simulator" / "agents"
OURS = "zuccaro-agent"

# baselines on the leaderboard + synthetic rivals mimicking observed behaviours
SMALL_FIELD = {
    "DummyAgent": 1, "PatientAgent": 1, "PriceWarAgent": 1,
    "sparring-compounder": 1,   # reinvests aggressively
    "sparring-steady": 1,       # small profits, then stops
    "sparring-selfplay": 1,     # a capable adaptive rival (frozen copy of us)
    "sparring-starter": 1,      # the README starter, common among teams
}
LARGE_FIELD = {  # 37 rivals + us = 38 teams
    "DummyAgent": 1, "PatientAgent": 1, "PriceWarAgent": 1,
    "sparring-compounder": 8, "sparring-steady": 8, "sparring-selfplay": 6,
    "sparring-starter": 6, "sparring-cautious": 4, "sparring-aggressive": 2,
}
SCENARIOS = {
    "default": (ROOT / "config/default.yaml", 40),
    "default_extended": (ROOT / "benchmarks/configs/default_extended.yaml", 80),
}


def _group(team: str) -> str:
    """Team id -> agent id (copies are suffixed _1, _2, ...)."""
    head, _, tail = team.rpartition("_")
    return head if tail.isdigit() and head else team


def _play(job: dict) -> dict:
    from dme_simulator.agents.loader import discover_bundle_classes
    from dme_simulator.config import load_config
    from dme_simulator.runner import run_simulation

    path, turns = SCENARIOS[job["scenario"]]
    turns = job["turns"] or turns
    cfg = load_config(path)
    cfg = replace(cfg, output=replace(cfg.output, render_plots=False,
                                      progress_interval_turns=0, dashboard="none"))
    classes = discover_bundle_classes([AGENTS_DIR])
    ours = next(iter(discover_bundle_classes([Path(job["candidate"])]).values()))
    agents = {OURS: ours()}
    for agent_id, n in job["field"].items():
        for i in range(1, n + 1):
            agents[agent_id if n == 1 else f"{agent_id}_{i}"] = classes[agent_id]()
    t0 = time.perf_counter()
    sim = run_simulation(cfg, agents, seed_override=job["seed"], turns_override=turns,
                         profile=True, quiet=True)
    caps = {t: s.capital for t, s in sim.teams_state.items()}
    order = sorted(caps.values(), reverse=True)
    ranks = {t: sum(1 for c in order if c > v) + (sum(1 for c in order if c == v) + 1) / 2
             for t, v in caps.items()}
    durations = sim.history.diagnostics.decision_duration_seconds.get(OURS, [])
    return {
        "scenario": job["scenario"], "seed": job["seed"], "capital": caps,
        "rank": ranks, "curves": {t: list(v) for t, v in sim.history.capital.items()},
        "max_ms": max(durations) * 1000 if durations else 0.0,
        "wall": time.perf_counter() - t0,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--candidate", type=Path, default=AGENTS_DIR / OURS)
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--seed-base", type=int, default=1000)
    ap.add_argument("--field", choices=["small", "large"], default="small")
    ap.add_argument("--ext-turns", type=int, default=None,
                    help="override default_extended length (e.g. 240)")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--csv", type=Path, default=ROOT / "benchmarks/results/tournament_curves.csv")
    args = ap.parse_args()

    field = SMALL_FIELD if args.field == "small" else LARGE_FIELD
    jobs = [{"scenario": s, "seed": args.seed_base + i, "field": field,
             "turns": args.ext_turns if s == "default_extended" else None,
             "candidate": str(args.candidate.resolve())}
            for s in SCENARIOS for i in range(args.seeds)]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(_play, jobs))

    # per agent group: capitals and ranks per scenario
    caps = defaultdict(lambda: defaultdict(list))
    ranks = defaultdict(lambda: defaultdict(list))
    for r in results:
        for team, c in r["capital"].items():
            caps[_group(team)][r["scenario"]].append(c)
            ranks[_group(team)][r["scenario"]].append(r["rank"][team])
    teams = len(results[0]["capital"])
    scen = list(SCENARIOS)
    print(f"\nTournament: {args.seeds} seeds x {len(scen)} scenarios, {teams} teams "
          f"({args.field} field), candidate={args.candidate.name}")
    head = "".join(f"{s + ' mean':>20}{'min':>10}{'rank':>7}" for s in scen)
    print(f"{'agent':22}{head}{'AGG rank':>10}")
    rows = []
    for g in caps:
        agg = statistics.mean(x for s in scen for x in ranks[g][s])
        rows.append((agg, g))
    for agg, g in sorted(rows):
        line = f"{g:22}"
        for s in scen:
            line += (f"{statistics.mean(caps[g][s]):>20,.0f}{min(caps[g][s]):>10,.0f}"
                     f"{statistics.mean(ranks[g][s]):>7.2f}")
        mark = "  <== us" if g == OURS else ""
        print(f"{line}{agg:>10.2f}{mark}")
    print(f"max decide() time for us: {max(r['max_ms'] for r in results):.1f} ms")

    args.csv.parent.mkdir(parents=True, exist_ok=True)
    with args.csv.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["scenario", "seed", "team", "turn", "capital"])
        for r in results:
            for team, curve in r["curves"].items():
                for t, c in enumerate(curve, start=1):
                    w.writerow([r["scenario"], r["seed"], team, t, round(c, 2)])
    print(f"capital curves -> {args.csv}")


if __name__ == "__main__":
    main()
