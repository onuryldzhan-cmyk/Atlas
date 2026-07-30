"""
Atlas Market Adapter v5.0

Connects old market providers
with new Atlas Core interfaces.
"""


from __future__ import annotations

import logging


from core.interfaces import MarketProvider



logger = logging.getLogger(
    "AtlasAI.MarketAdapter"
)



class MarketAdapter(
    MarketProvider
):


    def __init__(
        self,
        provider=None
    ):

        self.provider = provider


        logger.info(
            "Market Adapter initialized."
        )



    def get_price(
        self,
        symbol: str
    ) -> float:


        if self.provider:

            return (
                self.provider.get_price(
                    symbol
                )
            )


        return 0.0



    def get_history(
        self,
        symbol: str,
        limit: int = 100
    ):


        if self.provider:

            return (
                self.provider.get_history(
                    symbol,
                    limit
                )
            )


        return []



    def get_symbols(self):

        if self.provider and hasattr(
            self.provider,
            "get_symbols"
        ):

            return (
                self.provider.get_symbols()
            )


        return []