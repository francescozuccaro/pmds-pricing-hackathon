"""TEST ONLY - cautious sparring partner. Never upload.

Bids just above the reserve for small quantities, keeps little stock and asks
high prices, lowering them slowly when goods do not sell.
"""

from dme_simulator.agents import (
    AssemblyOrder, BaseAgent, Bid, Decision, Listing, Observation,
)
from dme_simulator.config import GoodsConfig

BID_MULT = 1.1
UNITS_PER_RECIPE = 2
START_MULT = 9.0     # initial price = material cost * START_MULT
DECAY = 0.97         # price multiplier decay per turn with unsold stock
MIN_MULT = 3.0


class SparringCautiousAgent(BaseAgent):
    def __init__(self):
        self.mult = {}

    def decide(self, state: Observation, goods_config: GoodsConfig) -> Decision:
        reserve = {lot.good: lot.reserve_price for lot in state.auction_lots}

        def cost(recipe):
            return sum(reserve.get(m, 10.0) * q for m, q in recipe.inputs.items())

        want = {}
        for r in goods_config.recipes.values():
            for m, q in r.inputs.items():
                want[m] = want.get(m, 0) + q * UNITS_PER_RECIPE
        bids = [
            Bid(lot.good, max(0, want.get(lot.good, 0) - state.inventory.get(lot.good, 0)),
                lot.reserve_price * BID_MULT)
            for lot in state.auction_lots
        ]
        assembly = [AssemblyOrder(n, UNITS_PER_RECIPE) for n in goods_config.recipes]
        listings = []
        for r in goods_config.recipes.values():
            good = r.output_good
            m = self.mult.get(good, START_MULT)
            if state.inventory.get(good, 0) > 0:
                m = max(MIN_MULT, m * DECAY)
            else:
                m = min(START_MULT, m * 1.05)
            self.mult[good] = m
            listings.append(Listing(good, 10_000, max(1.0, cost(r) * m)))
        return Decision(bids=bids, assembly=assembly, listings=listings)
