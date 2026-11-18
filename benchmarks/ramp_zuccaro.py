"""Capital curve of zuccaro-agent at checkpoint turns, averaged over seeds.

    uv run python benchmarks/ramp_zuccaro.py --scenario ext_real --turns 80 --seeds 4
Compares against the public-leaderboard leader read off the chart (80-turn run).
"""
import argparse
import statistics
import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import eval_zuccaro as E  # noqa: E402

LEADER = {10: 60_000, 20: 120_000, 30: 220_000, 40: 240_000, 80: 300_000}
CHECKS = (10, 20, 30, 40, 60, 80, 120, 240)


def run(job):
    from dme_simulator.agents.loader import discover_bundle_classes
    from dme_simulator.config import load_config
    from dme_simulator.runner import run_simulation
    path, roster, _ = E.SCENARIOS[job["scenario"]]
    cfg = load_config(path)
    cfg = replace(cfg, output=replace(cfg.output, render_plots=False,
                                      progress_interval_turns=0, dashboard="none"))
    classes = discover_bundle_classes([E.AGENTS_DIR])
    cand = next(iter(discover_bundle_classes([Path(job["candidate"])]).values()))
    agents = {E.CANDIDATE_ID: cand()}
    for aid, n in roster.items():
        for i in range(1, n + 1):
            agents[aid if n == 1 else f"{aid}_{i}"] = classes[aid]()
    sim = run_simulation(cfg, agents, seed_override=job["seed"],
                         turns_override=job["turns"], quiet=True)
    h = sim.history
    me = E.CANDIDATE_ID
    out = {}
    for t in CHECKS:
        if t <= len(h.turns):
            others = [h.capital[x][t - 1] for x in h.capital if x != me]
            out[t] = (h.capital[me][t - 1], max(others),
                      sum(h.revenue[me][:t]), sum(h.units_sold[me][:t]),
                      sum(sum(h.market_units[g][:t]) for g in h.market_units))
    peak = max(h.capital[me])
    drawdown = max((max(h.capital[me][:i + 1]) - c) / max(h.capital[me][:i + 1])
                   for i, c in enumerate(h.capital[me]))
    return out, peak, drawdown


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--scenario", default="ext_real")
    p.add_argument("--turns", type=int, default=80)
    p.add_argument("--seeds", type=int, default=4)
    p.add_argument("--candidate", type=Path, default=E.AGENTS_DIR / E.CANDIDATE_ID)
    a = p.parse_args()
    jobs = [{"scenario": a.scenario, "turns": a.turns, "seed": 100 + i,
             "candidate": str(a.candidate.resolve())} for i in range(a.seeds)]
    with ProcessPoolExecutor(max_workers=4) as pool:
        res = list(pool.map(run, jobs))
    print(f"{a.scenario} {a.turns}t  turn | me (mean)  best rival | my units sold / market units | leader")
    for t in CHECKS:
        rows = [r[0][t] for r in res if t in r[0]]
        if not rows:
            continue
        me = statistics.mean(x[0] for x in rows)
        rv = statistics.mean(x[1] for x in rows)
        su = statistics.mean(x[3] for x in rows)
        mu = statistics.mean(x[4] for x in rows)
        print(f"  {t:4d} | {me:10,.0f} {rv:10,.0f} | {su:7.0f} / {mu:7.0f} ({su / max(1, mu):5.1%})"
              f" | {LEADER.get(t, ''):>8}")
    print(f"  max drawdown {max(r[2] for r in res):.1%}")


if __name__ == "__main__":
    main()
