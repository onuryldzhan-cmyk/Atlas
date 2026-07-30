"""
Atlas Learning Listener v6.3
Event Based Learning + Outcome Tracking
"""

import logging


logger = logging.getLogger("AtlasAI")



class LearningListener:


    def __init__(
        self,
        brain
    ):

        self.brain = brain

        self.register_events()



    # =====================================
    # REGISTER
    # =====================================

    def register_events(
        self
    ):


        self.brain.events.register(
            "MARKET_ANALYZED",
            self.market_analyzed
        )


        self.brain.events.register(
            "DECISION_CREATED",
            self.decision_created
        )


        logger.info(
            "Learning Listener v6.3 active."
        )



    # =====================================
    # MARKET LEARNING
    # =====================================

    def market_analyzed(
        self,
        data
    ):


        if not data:

            return



        symbol = data.get(
            "symbol"
        )


        fusion = data.get(
            "fusion"
        )



        try:


            self.brain.learning_engine.learn_market(
                symbol,
                fusion
            )


            logger.info(
                f"[LEARNING] Market learned: {symbol}"
            )



        except Exception as e:


            logger.exception(e)



    # =====================================
    # DECISION LEARNING
    # =====================================

    def decision_created(
        self,
        data
    ):


        if not data:

            return



        symbol = data.get(
            "symbol"
        )


        decision = data.get(
            "decision",
            {}
        )


        try:


            # MEMORY

            self.brain.trade_memory.record_decision(
                symbol,
                decision
            )



            action = decision.get(
                "action",
                "BEKLE"
            )


            # ==============================
            # CREATE OUTCOME TRADE
            # ==============================

            if action in [
                "BUY",
                "SELL"
            ]:


                self.brain.outcome_memory.create_trade(

    symbol=symbol,

    decision=decision,

    confidence=data.get(
        "confidence",
        0
    ),

    strategy=decision.get(
        "strategy",
        "UNKNOWN"
    )

)


                logger.info(
                    f"[OUTCOME] Open trade created: {symbol}"
                )



            logger.info(
                f"[LEARNING] Decision stored: {symbol}"
            )



        except Exception as e:


            logger.exception(e)