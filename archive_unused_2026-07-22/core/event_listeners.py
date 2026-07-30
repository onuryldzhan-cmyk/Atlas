"""
Atlas Event Listeners
Professional Event Reaction Layer
"""

import logging


logger = logging.getLogger("AtlasAI")


class AtlasEventListeners:

    def __init__(self, brain):

        self.brain = brain

        self.register_events()


    # =====================================
    # EVENT REGISTRATION
    # =====================================

    def register_events(self):

        self.brain.events.register(
            "MARKET_ANALYZED",
            self.market_analyzed
        )

        self.brain.events.register(
            "DECISION_CREATED",
            self.decision_created
        )

        logger.info(
            "Atlas Event Listeners active."
        )


    # =====================================
    # MARKET ANALYZED EVENT
    # =====================================

    def market_analyzed(
        self,
        data
    ):

        if not data:
            return


        symbol = data.get(
            "symbol",
            "UNKNOWN"
        )


        logger.info(
            f"[LISTENER] Market analyzed: {symbol}"
        )


    # =====================================
    # DECISION CREATED EVENT
    # =====================================

    def decision_created(
        self,
        data
    ):

        if not data:
            return


        symbol = data.get(
            "symbol",
            "UNKNOWN"
        )


        decision = data.get(
            "decision",
            {}
        )


        action = decision.get(
            "action",
            "NONE"
        )


        logger.info(
            f"[LISTENER] Decision: {symbol} -> {action}"
        )