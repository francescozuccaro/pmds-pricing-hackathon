from dme_simulator.agents import (
    AssemblyOrder, BaseAgent, Bid, Decision, Listing, Observation,
)
from dme_simulator.config import GoodsConfig

# Tunable parameters
INIT_PRICE_MULT = 5.0      # initial list price = material cost * this
PRICE_UP = 1.08            # sold (almost) everything -> raise
PRICE_DOWN = 0.93          # sold little -> lower
LADDER = (0.9, 1.0, 1.15, 1.35)
INIT_BID_MULT = 1.6        # bid = reserve * mult
BID_MULT_MAX = 4.0
BID_MULT_MIN = 1.05
INIT_DEMAND = 4.0          # expected units sold per good per turn
STOCK_COVER = 1.5          # finished-goods target = demand * cover
MAX_CAPITAL_SHARE = 0.5    # max share of capital spent per auction


class ZuccaroAgent(BaseAgent):
    def __init__(self):
        self.price = {}        # reference sale price per good
        self.demand = {}       # EMA of units sold per turn per good
        self.bid_mult = {}     # per-material bid multiplier
        self.last_listed = {}  # good -> units listed last turn
        self.last_bid = {}     # material -> units requested last turn
        self.n_sales = 0
        self.n_auction = 0
        self.mat_cost = {}     # last known reserve per material

    # ------------------------------------------------------------------
    def _recipe_cost(self, recipe):
        return sum(self.mat_cost.get(m, 10.0) * q for m, q in recipe.inputs.items())

    def _learn(self, state):
        # --- sales feedback ---
        new_sales = state.sales_transactions[self.n_sales:]
        self.n_sales = len(state.sales_transactions)
        sold = {}
        for t in new_sales:
            if self.team_id is None or t.seller == self.team_id:
                sold[t.good] = sold.get(t.good, 0) + t.quantity
        for good, listed in self.last_listed.items():
            if listed <= 0:
                continue
            s = sold.get(good, 0)
            frac = s / listed
            if frac >= 0.9:
                self.price[good] *= PRICE_UP
                # sold out: true demand is at least what we sold, likely more
                self.demand[good] = 0.6 * self.demand[good] + 0.4 * (s + 2)
            else:
                if frac < 0.5:
                    self.price[good] *= PRICE_DOWN
                self.demand[good] = 0.6 * self.demand[good] + 0.4 * s
            self.demand[good] = max(1.0, self.demand[good])

        # --- auction feedback ---
        new_auc = state.auction_transactions[self.n_auction:]
        self.n_auction = len(state.auction_transactions)
        won = {}
        for t in new_auc:
            if self.team_id is None or t.buyer == self.team_id:
                won[t.good] = won.get(t.good, 0) + t.quantity
        for mat, asked in self.last_bid.items():
            if asked <= 0:
                continue
            if won.get(mat, 0) < asked * 0.9:
                self.bid_mult[mat] = min(BID_MULT_MAX, self.bid_mult[mat] * 1.15)
            else:
                self.bid_mult[mat] = max(BID_MULT_MIN, self.bid_mult[mat] * 0.97)

    # ------------------------------------------------------------------
    def decide(self, state: Observation, goods_config: GoodsConfig) -> Decision:
        gc = goods_config
        if getattr(self, "team_id", None) is None:
            self.team_id = self._infer_team_id(state)
        for lot in state.auction_lots:
            self.mat_cost[lot.good] = lot.reserve_price
            self.bid_mult.setdefault(lot.good, INIT_BID_MULT)
        recipes_by_good = {r.output_good: (n, r) for n, r in gc.recipes.items()}
        for good in gc.finished_goods:
            if good not in self.price and good in recipes_by_good:
                self.price[good] = INIT_PRICE_MULT * self._recipe_cost(recipes_by_good[good][1])
            self.demand.setdefault(good, INIT_DEMAND)

        self._learn(state)

        inv = dict(state.inventory)

        # --- production: rank goods by margin, build up to target stock ---
        ranked = sorted(
            recipes_by_good.items(),
            key=lambda kv: self.price[kv[0]] - self._recipe_cost(kv[1][1]),
            reverse=True,
        )
        need = {}  # target units to build per good
        for good, (name, r) in ranked:
            target = int(round(self.demand[good] * STOCK_COVER))
            need[good] = max(0, target - inv.get(good, 0))

        assembly = []
        for good, (name, r) in ranked:
            q = min([need[good]] + [inv.get(m, 0) // k for m, k in r.inputs.items()])
            if q > 0:
                assembly.append(AssemblyOrder(name, q))
                for m, k in r.inputs.items():
                    inv[m] -= k * q
                inv[good] = inv.get(good, 0) + q
                need[good] -= q

        # --- bids: materials for the remaining shortfall (next turn's build) ---
        want = {m: 0 for m in gc.raw_materials}
        for good, (name, r) in ranked:
            # replace what we plan to sell this turn plus remaining shortfall
            units = need[good] + int(round(self.demand[good]))
            for m, k in r.inputs.items():
                want[m] += k * units
        bids = []
        budget = state.capital * MAX_CAPITAL_SHARE
        self.last_bid = {}
        lots = sorted(state.auction_lots, key=lambda l: l.reserve_price)
        for lot in lots:
            q = max(0, want.get(lot.good, 0) - inv.get(lot.good, 0))
            q = min(q, lot.quantity)
            p = lot.reserve_price * self.bid_mult[lot.good]
            if q * p > budget:
                q = int(budget // p)
            if q > 0:
                bids.append(Bid(lot.good, q, round(p, 2)))
                budget -= q * p
            self.last_bid[lot.good] = q

        # --- listings: price ladder per good ---
        listings = []
        self.last_listed = {}
        for good in gc.finished_goods:
            stock = inv.get(good, 0)
            if stock <= 0 or good not in recipes_by_good:
                continue
            floor = 1.3 * self._recipe_cost(recipes_by_good[good][1])
            base = max(self.price[good], floor)
            self.price[good] = base
            n = len(LADDER)
            per = [stock // n + (1 if i < stock % n else 0) for i in range(n)]
            for mult, q in zip(LADDER, per):
                if q > 0:
                    listings.append(Listing(good, q, round(base * mult, 2)))
            self.last_listed[good] = stock

        return Decision(bids=bids, assembly=assembly, listings=listings)

    # ------------------------------------------------------------------
    @staticmethod
    def _infer_team_id(state):
        # our capital/inventory equal the public entry for our team
        matches = [
            tid for tid, cap in state.public_capital.items()
            if abs(cap - state.capital) < 1e-6
            and state.public_inventories.get(tid) == state.inventory
        ]
        return matches[0] if len(matches) == 1 else None
