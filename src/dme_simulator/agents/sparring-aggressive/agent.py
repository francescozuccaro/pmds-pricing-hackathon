"""TEST ONLY - sparring partner that overbids at auction and dumps goods. Never upload.

Bids a high multiple of the reserve for a large share of every lot, builds
everything it can (most valuable recipe first) and sells at a low markup over
material cost, undercutting anyone who prices on value.
"""

from dme_simulator.agents import (
    AssemblyOrder, BaseAgent, Bid, Decision, Listing, Observation,
)
from dme_simulator.config import GoodsConfig

BID_MULT = 2.5       # bid = reserve * BID_MULT
LOT_SHARE = 0.6      # try to take this share of each lot
BUDGET_SHARE = 0.7   # never commit more than this share of capital per turn
SELL_MULT = 3.5      # list price = reserve-based material cost * SELL_MULT


class SparringAggressiveAgent(BaseAgent):
    def decide(self, state: Observation, goods_config: GoodsConfig) -> Decision:
        reserve = {lot.good: lot.reserve_price for lot in state.auction_lots}

        def cost(recipe):
            return sum(reserve.get(m, 10.0) * q for m, q in recipe.inputs.items())

        budget = state.capital * BUDGET_SHARE
        bids = []
        for lot in state.auction_lots:
            price = lot.reserve_price * BID_MULT
            qty = int(lot.quantity * LOT_SHARE)
            if price > 0:
                qty = min(qty, int(budget // price))
            if qty > 0:
                bids.append(Bid(lot.good, qty, price))
                budget -= qty * price

        recipes = sorted(goods_config.recipes.items(), key=lambda kv: -cost(kv[1]))
        assembly = [AssemblyOrder(name, 10_000) for name, _ in recipes]
        listings = [
            Listing(r.output_good, 10_000, max(1.0, cost(r) * SELL_MULT))
            for _, r in recipes
        ]
        return Decision(bids=bids, assembly=assembly, listings=listings)
