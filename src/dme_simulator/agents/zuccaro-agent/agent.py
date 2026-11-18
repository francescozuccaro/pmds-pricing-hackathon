"""zuccaro-agent: demand-driven, margin-disciplined DME trader.

Each turn (auction -> production -> sales all happen in the same turn):
  1. Learn from our own last-turn fills and sales (which ladder rungs sold).
  2. Plan how many units of each good we want on the shelf (learned demand).
  3. Bid only for the materials that plan needs, at an adaptive price capped by
     what the finished good is worth.
  4. Order assembly for the plan; materials won this turn are usable at once.
  5. List everything on a price ladder around a learned reference price.

Unsold inventory is worth nothing at the end and the horizon is unknown, so the
agent keeps raw and finished stock lean at all times instead of timing an end.
"""

from math import ceil, isfinite

from dme_simulator.agents import (
    AssemblyOrder, BaseAgent, Bid, Decision, Listing, Observation,
)
from dme_simulator.config import GoodsConfig

# ---------------------------------------------------------------- tunables
INIT_PRICE_MULT = 6.0       # first reference price = recipe reserve cost * this
INIT_PRICE_CROWD = 6.0      # same, in a crowded market (more sellers -> lower start)
STEP_NONE_CROWD = 0.92      # price cut when nothing sold, in a crowded market
CORE = (1.0, 1.1, 0.9)      # core rungs (x reference), in listing order
PROBE = 1.6                 # one unit at reference * PROBE to catch rich buyers
PROBE_MIN_STOCK = 2         # only probe when the shelf has at least this many
PROBE_SHARE = 0.0           # premium tier size = share of core quantity (min 1 unit),
                            # stocked on top of the core shelf
PM_ADAPT = False            # learn the premium multiplier per good
PM_UP = 1.05                # premium tier sold      -> multiplier up
PM_DOWN = 0.97              # premium tier unsold    -> multiplier down
PM_MIN = 1.15
PM_MAX = 4.0
# reference-price moves by core sell-through f = sold / listed
STEP_SOLDOUT = 1.08        # f == 1
STEP_GOOD = 1.00            # f >= GOOD_F
GOOD_F = 0.6
STEP_SOME = 0.96            # 0 < f < GOOD_F
STEP_NONE = 0.92            # f == 0
STEP_PROBE = 1.06           # probe unit sold
# elasticity check: if cutting the price did not raise profit, undo the cut
ELAST_W = 0                 # window (turns) compared; 0 = off
ELAST_CUT = 0.08            # only judge after the price fell at least this much
ELAST_GAIN = 1.0            # cut is "useful" only if profit rose above old * this
STEP_REVERT = 1.06          # price move when a cut proved useless
FLOOR_REPLACEMENT = False   # floor on replacement cost instead of paid cost
MIN_MARGIN = 1.25           # lowest rung never below unit cost * this

INIT_QTY = 4.0  # initial core shelf quantity per good
QTY_GROW = 1.6  # sold out -> grow core quantity
QTY_EMA = 0.6               # otherwise move toward sold * QTY_HEADROOM
QTY_HEADROOM = 2.0  
QTY_MIN = 1.0
# safety: shelf quantity never far above what we have actually sold recently
QTY_CAP_MULT = 3.0          # cap = mult * best recent turn + add
QTY_CAP_ADD = 12.0
GUARD_SHARE = 0.0           # below start capital * this, stop refilling unsold goods
HIST_LEN = 6                # turns of sales/revenue history kept

CROWD_TEAMS = 12            # with more teams than this the market counts as crowded
BID_INIT_CROWD = 1.3        # first bid in a crowded market (don't fight early)
# "hot" market: enough rivals are already making money, so the goods sell at
# prices that justify outbidding them -> lift our value cap to at least HOT_CAP
CROWD_CAP = 99.0            # crowded but not hot: never bid above reserve * this
HOT_GAIN = 1.05             # a rival counts as winning above start capital * this
HOT_SHARE = 0.05            # market is hot when this share of rivals is winning
HOT_CAP = 5.0               # minimum bid cap (x reserve) in a hot crowded market...
HOT_COST_SHARE = 1.0        # ...but materials never above this share of bottom-rung price
BID_INIT = 2.0             # first bid = reserve * this
BID_UP = 1.6               # partial fill -> raise multiplier
BID_DOWN = 0.88            # full fill    -> lower multiplier
BID_MIN = 1.0
BID_MAX = 5.0  
MAX_COST_SHARE = 0.75  # materials may cost at most this share of bottom-rung price
BUDGET_SHARE = 0.4          # max share of capital committed in one auction
CROWD_SPEND = 1.0           # crowded market: per-turn spend <= capital * this + revenue
                            # earned in the last turns (1.0 = off)
SPEND_REV_MULT = 1.0        # ...and at most this * recent mean revenue per turn
SPEND_MIN_SHARE = 1.0       # 1.0 disables the revenue-based spend cap (it hurt growth)
COST_EMA = 0.3              # smoothing of the price we actually paid


def _finite(x, default=0.0):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return default
    return x if isfinite(x) else default


class ZuccaroAgent(BaseAgent):
    def __init__(self):
        self.team_id = None
        self.ref_price = {}     # good -> reference sale price
        self.qty = {}           # good -> core shelf quantity
        self.bid_mult = {}      # material -> bid / reserve
        self.paid = {}          # material -> smoothed unit price actually paid
        self.reserve = {}       # material -> latest reserve price
        self.last_ladder = {}   # good -> [(price, qty)] listed last turn
        self.last_bid = {}      # material -> units requested last turn
        self.sold_hist = {}     # good -> recent units sold per turn
        self.price_hist = {}    # good -> recent (reference price, profit) per turn
        self.last_ref = {}      # good -> reference price used when listing
        self.last_cost = {}     # good -> unit cost when listing
        self.pmult = {}         # good -> premium tier multiplier
        self.rev_hist = []      # recent revenue per turn
        self.start_capital = None
        self.crowded = False
        self.n_sales = 0
        self.n_auction = 0

    # ---------------------------------------------------------------- helpers
    def _mat_cost(self, m):
        """Expected cost of one unit of material m (paid history or reserve)."""
        r = self.reserve.get(m)
        p = self.paid.get(m)
        if p is None:
            return r if r is not None else 10.0
        return max(p, r) if r is not None else p

    def _unit_cost(self, recipe):
        return sum(self._mat_cost(m) * q for m, q in recipe.inputs.items())

    def _replacement_cost(self, recipe):
        """What one unit would cost to rebuild at today's reserve and bid level."""
        return sum(self.reserve.get(m, self._mat_cost(m)) * self.bid_mult.get(m, 1.0) * q
                   for m, q in recipe.inputs.items())

    def _reserve_cost(self, recipe):
        return sum(self.reserve.get(m, self._mat_cost(m)) * q
                   for m, q in recipe.inputs.items())

    def _premium_units(self, good):
        """Units kept on the premium tier, on top of the core shelf."""
        return max(1, int(round(PROBE_SHARE * ceil(self.qty.get(good, INIT_QTY)))))

    def _is_mine(self, who):
        # by default only our own transactions are visible
        return self.team_id is None or who == self.team_id

    def _infer_team_id(self, state):
        """Find our team among the public entries (re-checked every turn).

        Teams whose capital and inventory equal ours are indistinguishable from
        us so far; any of them gives the same statistics, so we keep the current
        pick while it stays consistent and otherwise take the first match.
        """
        matches = sorted(
            tid for tid, cap in state.public_capital.items()
            if abs(_finite(cap) - state.capital) < 1e-6
            and state.public_inventories.get(tid) == state.inventory
        )
        if self.team_id not in matches:
            self.team_id = matches[0] if matches else None

    # ---------------------------------------------------------------- learning
    def _learn(self, state):
        # auction fills -> paid cost and bid multiplier
        txs = state.auction_transactions
        won = {}
        for t in txs[self.n_auction:]:
            if self._is_mine(t.buyer) and t.quantity > 0:
                won[t.good] = won.get(t.good, 0) + t.quantity
                old = self.paid.get(t.good)
                price = _finite(t.price)
                self.paid[t.good] = price if old is None else (
                    (1 - COST_EMA) * old + COST_EMA * price)
        self.n_auction = len(txs)
        for m, asked in self.last_bid.items():
            if asked <= 0:
                continue
            if won.get(m, 0) < asked:
                self.bid_mult[m] = min(BID_MAX, self.bid_mult.get(m, BID_INIT) * BID_UP)
            else:
                self.bid_mult[m] = max(BID_MIN, self.bid_mult.get(m, BID_INIT) * BID_DOWN)

        # sales -> which rungs sold
        txs = state.sales_transactions
        sold_at = {}
        for t in txs[self.n_sales:]:
            if self._is_mine(t.seller) and t.quantity > 0:
                sold_at.setdefault(t.good, []).append((_finite(t.price), t.quantity))
        self.n_sales = len(txs)
        self.rev_hist = (self.rev_hist + [sum(
            p * q for v in sold_at.values() for p, q in v)])[-HIST_LEN:]

        for good, ladder in self.last_ladder.items():
            sales = sold_at.get(good, [])
            sold = sum(q for _, q in sales)
            hist = self.sold_hist.setdefault(good, [])
            hist.append(sold)
            del hist[:-HIST_LEN]
            # we list all stock, so the real shelf was what is left plus what
            # sold; listings were honoured in listing order
            shelf = state.inventory.get(good, 0) + sold
            core_listed = probe_listed = 0
            for p, q, is_probe in ladder:
                take = min(q, shelf)
                shelf -= take
                if is_probe:
                    probe_listed += take
                else:
                    core_listed += take
            if core_listed + probe_listed <= 0:
                continue
            probe_price = min((p for p, _, pr in ladder if pr), default=None)
            probe_sold = 0
            if probe_price is not None and probe_listed:
                probe_sold = min(probe_listed, sum(
                    q for p, q in sales if p >= probe_price - 1e-6))
            core_sold = sold - probe_sold

            ref = self.ref_price[good]
            qty = self.qty[good]
            cost = self.last_cost.get(good, 0.0)
            ph = self.price_hist.setdefault(good, [])
            ph.append((self.last_ref.get(good, ref), sum((p - cost) * q for p, q in sales)))
            del ph[:-2 * max(1, ELAST_W)]
            if core_listed > 0:
                f = core_sold / core_listed
                if f >= 1.0:
                    ref *= STEP_SOLDOUT
                    qty = max(qty, core_sold) * QTY_GROW
                else:
                    none = STEP_NONE_CROWD if self.crowded else STEP_NONE
                    step = STEP_GOOD if f >= GOOD_F else (STEP_SOME if f > 0 else none)
                    if step == STEP_SOME and ELAST_W and len(ph) >= 2 * ELAST_W:
                        old, new = ph[:ELAST_W], ph[ELAST_W:]
                        p0 = sum(x for x, _ in old) / ELAST_W
                        p1 = sum(x for x, _ in new) / ELAST_W
                        g0 = sum(y for _, y in old) / ELAST_W
                        g1 = sum(y for _, y in new) / ELAST_W
                        if p1 < p0 * (1 - ELAST_CUT) and g1 <= g0 * ELAST_GAIN:
                            step = STEP_REVERT   # the cut bought no profit: undo it
                            ph.clear()
                    ref *= step
                    qty = (1 - QTY_EMA) * qty + QTY_EMA * core_sold * QTY_HEADROOM
            if probe_sold:
                ref *= STEP_PROBE
            if PM_ADAPT and probe_listed:
                pm = self.pmult.get(good, PROBE) * (PM_UP if probe_sold else PM_DOWN)
                self.pmult[good] = min(PM_MAX, max(PM_MIN, pm))
            self.ref_price[good] = ref
            cap = QTY_CAP_MULT * max(hist) + QTY_CAP_ADD
            self.qty[good] = max(QTY_MIN, min(qty, cap))

    # ---------------------------------------------------------------- decide
    def decide(self, state: Observation, goods_config: GoodsConfig) -> Decision:
        try:
            return self._decide(state, goods_config)
        except Exception:
            return Decision()  # never crash: an empty decision is always valid

    def _decide(self, state, gc):
        self._infer_team_id(state)
        self.crowded = len(state.public_capital) > CROWD_TEAMS
        lots = {}
        for lot in state.auction_lots:
            r = _finite(lot.reserve_price)
            if r < 0:
                continue
            lots[lot.good] = lot
            self.reserve[lot.good] = r
            crowded = len(state.public_capital) > CROWD_TEAMS
            self.bid_mult.setdefault(lot.good, BID_INIT_CROWD if crowded else BID_INIT)

        # one (cheapest) recipe per finished good
        finished = set(gc.finished_goods)
        recipe_for = {}
        for name, r in gc.recipes.items():
            if r.output_good not in finished or not r.inputs:
                continue
            cur = recipe_for.get(r.output_good)
            if cur is None or self._unit_cost(r) < self._unit_cost(cur[1]):
                recipe_for[r.output_good] = (name, r)

        for good, (_, r) in recipe_for.items():
            if good not in self.ref_price:
                mult = INIT_PRICE_CROWD if self.crowded else INIT_PRICE_MULT
                self.ref_price[good] = max(1.0, mult * self._reserve_cost(r))
            self.qty.setdefault(good, INIT_QTY)

        self._learn(state)
        if self.start_capital is None:
            self.start_capital = _finite(state.capital)
        guard = _finite(state.capital) < (self.start_capital or 0.0) * GUARD_SHARE
        crowded = len(state.public_capital) > CROWD_TEAMS
        rivals = [_finite(c) for t, c in state.public_capital.items() if t != self.team_id]
        winning = sum(1 for c in rivals if c > (self.start_capital or 0.0) * HOT_GAIN)
        # only crowded markets lock out late entrants, so only there we lift the cap
        hot = (bool(rivals) and len(state.public_capital) > CROWD_TEAMS
               and winning >= HOT_SHARE * len(rivals))

        # price floor from what materials really cost us
        for good, (_, r) in recipe_for.items():
            # paid cost is sunk: optionally price against what a new unit costs now
            cost = self._replacement_cost(r) if FLOOR_REPLACEMENT else self._unit_cost(r)
            floor = cost * MIN_MARGIN / min(CORE)
            self.ref_price[good] = max(self.ref_price[good], floor, 1.0)

        inv = {k: int(v) for k, v in state.inventory.items()}

        # ---- production plan, most valuable goods first
        def margin(item):
            good, (_, r) = item
            return self.ref_price[good] - self._unit_cost(r)

        ranked = sorted(recipe_for.items(), key=margin, reverse=True)
        plan = {}
        for good, _ in ranked:
            target = ceil(self.qty[good]) + self._premium_units(good)
            if guard and inv.get(good, 0) > 0 and not any(self.sold_hist.get(good, [])):
                target = 0  # losing money and this good is not moving: stop refilling
            plan[good] = max(0, target - inv.get(good, 0))

        # ---- materials needed beyond what we hold
        need = {}
        for good, (_, r) in ranked:
            for m, q in r.inputs.items():
                need[m] = need.get(m, 0) + q * plan[good]
        bids = []
        capital = max(0.0, _finite(state.capital))
        budget = capital * BUDGET_SHARE
        if len(state.public_capital) > CROWD_TEAMS:
            # crowded: grow spending only as fast as goods actually turn into cash
            budget = min(budget, capital * CROWD_SPEND + sum(self.rev_hist))
        if self.rev_hist:
            recent = sum(self.rev_hist) / len(self.rev_hist)
            budget = min(budget, max(capital * SPEND_MIN_SHARE, SPEND_REV_MULT * recent))
        self.last_bid = {}
        for m, total in need.items():
            lot = lots.get(m)
            if lot is None:
                continue
            qty = min(max(0, total - inv.get(m, 0)), int(lot.quantity))
            if qty <= 0:
                continue
            reserve = self.reserve[m]
            # value cap: cheapest affordable share of the goods m goes into
            caps = []
            for good, (_, r) in recipe_for.items():
                if m in r.inputs and plan.get(good, 0) > 0:
                    rc = max(1e-6, self._reserve_cost(r))
                    caps.append(self.ref_price[good] * min(CORE) * MAX_COST_SHARE / rc)
            cap_mult = max(BID_MIN, min(caps)) if caps else BID_MIN
            if crowded and not hot:
                cap_mult = min(cap_mult, CROWD_CAP)
            if hot:
                ceiling = min(
                    (self.ref_price[g] * min(CORE) * HOT_COST_SHARE
                     / max(1e-6, self._reserve_cost(r)))
                    for g, (_, r) in recipe_for.items()
                    if m in r.inputs and plan.get(g, 0) > 0)
                cap_mult = max(cap_mult, min(HOT_CAP, ceiling))
            price = reserve * min(self.bid_mult[m], cap_mult, BID_MAX)
            price = max(price, reserve) + 0.01
            qty = min(qty, int(budget // price)) if price > 0 else qty
            if qty <= 0:
                continue
            bids.append(Bid(m, qty, round(price, 2)))
            budget -= qty * price
            self.last_bid[m] = qty

        # ---- assembly: the plan, in margin order (uses this turn's winnings)
        assembly = [AssemblyOrder(name, plan[good])
                    for good, (name, _) in ranked if plan[good] > 0]

        # ---- listings: ladder over expected shelf stock
        listings = []
        self.last_ladder = {}
        for good, _ in ranked:
            stock = inv.get(good, 0) + plan[good]
            if stock <= 0:
                continue
            ref = self.ref_price[good]
            self.last_ref[good] = ref
            self.last_cost[good] = self._unit_cost(recipe_for[good][1])
            probe = (min(self._premium_units(good), stock - 1)
                     if stock >= PROBE_MIN_STOCK else 0)
            core = stock - probe
            n = len(CORE)
            per = [core // n + (1 if i < core % n else 0) for i in range(n)]
            ladder = []
            for mult, q in zip(CORE, per):
                if q > 0:
                    ladder.append((round(ref * mult, 2), q, False))
            if probe:
                pm = self.pmult.get(good, PROBE) if PM_ADAPT else PROBE
                ladder.append((round(ref * pm, 2), probe, True))
            for p, q, _ in ladder:
                listings.append(Listing(good, q, p))
            self.last_ladder[good] = ladder

        return Decision(bids=bids, assembly=assembly, listings=listings)
