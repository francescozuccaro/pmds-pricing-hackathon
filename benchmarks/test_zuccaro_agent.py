"""Minimal safety tests for zuccaro-agent's decide().

Run with pytest if available (uv run --with pytest pytest benchmarks/test_zuccaro_agent.py)
or directly: uv run python benchmarks/test_zuccaro_agent.py
"""

import copy
import importlib.util
import math
import random
from pathlib import Path

from dme_simulator.agents import (
    AuctionLot, AuctionResult, Decision, Observation, SalesPrice,
)
from dme_simulator.config import load_config

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "zuccaro_agent", ROOT / "src/dme_simulator/agents/zuccaro-agent/agent.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
AGENT = _mod.ZuccaroAgent
GC = load_config(ROOT / "config/default.yaml").goods


def _obs(turn=1, capital=12_000.0, inventory=None, lots=None, teams=8, **kw):
    goods = GC.raw_materials + GC.finished_goods
    inv = {g: 0 for g in goods} if inventory is None else inventory
    lots = ([AuctionLot(m, 40, 10.0) for m in GC.raw_materials] if lots is None else lots)
    caps = {f"t{i}": 12_000.0 for i in range(teams - 1)}
    caps["me"] = capital
    invs = {t: {g: 0 for g in goods} for t in caps}
    invs["me"] = dict(inv)
    return Observation(turn=turn, capital=capital, inventory=inv, bankrupt=False,
                       auction_lots=lots, public_inventories=invs, public_capital=caps,
                       auction_transactions=kw.get("auctions", []),
                       sales_transactions=kw.get("sales", []))


def _check(decision):
    assert isinstance(decision, Decision)
    for b in decision.bids:
        assert b.good in GC.raw_materials
        assert isinstance(b.quantity, int) and b.quantity >= 0
        assert math.isfinite(b.price_per_unit) and b.price_per_unit >= 0
    for a in decision.assembly:
        assert a.recipe_name in GC.recipes
        assert isinstance(a.quantity, int) and a.quantity >= 0
    for l in decision.listings:
        assert l.good in GC.finished_goods
        assert isinstance(l.quantity, int) and l.quantity >= 0
        assert math.isfinite(l.price) and l.price >= 0


def _decide(agent, obs):
    before = copy.deepcopy(obs)
    d = agent.decide(obs, GC)
    assert obs == before, "decide() must not mutate its input"
    _check(d)
    return d


def test_first_turn():
    d = _decide(AGENT(), _obs(turn=1))
    assert d.bids, "should try to buy materials on turn 1"


def test_last_turn_and_late_turns():
    agent = AGENT()
    for t in (1, 39, 40, 80, 240, 10_000):
        _decide(agent, _obs(turn=t))


def test_zero_cash_never_bids_money_it_lacks():
    d = _decide(AGENT(), _obs(capital=0.0))
    assert sum(b.quantity * b.price_per_unit for b in d.bids) == 0


def test_negative_cash():
    _decide(AGENT(), _obs(capital=-50.0))


def test_zero_stock_and_no_lots():
    d = _decide(AGENT(), _obs(lots=[]))
    assert not d.bids


def test_full_stock_lists_everything():
    inv = {g: 0 for g in GC.raw_materials + GC.finished_goods}
    inv.update({g: 7 for g in GC.finished_goods})
    d = _decide(AGENT(), _obs(inventory=inv))
    listed = {}
    for l in d.listings:
        listed[l.good] = listed.get(l.good, 0) + l.quantity
    assert all(listed.get(g, 0) >= 7 for g in GC.finished_goods)


def test_weird_inputs():
    lots = [AuctionLot("CHIP", 10, float("nan")), AuctionLot("DISPLAY", 0, 0.0),
            AuctionLot("BATTERY", 5, float("inf")), AuctionLot("UNKNOWN", 3, 1.0)]
    sales = [SalesPrice("PHONE", 2, float("nan"), "me"), SalesPrice("NOPE", 1, 5.0, "me")]
    auctions = [AuctionResult("CHIP", 2, 0.0, "me"), AuctionResult("ZZ", 1, 1.0, "me")]
    agent = AGENT()
    for t in range(1, 6):
        d = agent.decide(_obs(turn=t, lots=lots, sales=sales, auctions=auctions), GC)
        assert isinstance(d, Decision)


def test_random_states_and_crowded_market():
    rng = random.Random(7)
    agent = AGENT()
    goods = GC.raw_materials + GC.finished_goods
    for t in range(1, 200):
        inv = {g: rng.randint(0, 30) for g in goods}
        lots = [AuctionLot(m, rng.randint(0, 300), rng.uniform(0, 40))
                for m in GC.raw_materials if rng.random() < 0.9]
        _decide(agent, _obs(turn=t, capital=rng.uniform(-100, 2e6), inventory=inv,
                            lots=lots, teams=rng.choice([2, 8, 40])))


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"{len(tests)} passed")
