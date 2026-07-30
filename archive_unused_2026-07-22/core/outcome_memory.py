"""
Atlas AI Outcome Memory v6.4

Trade outcome analysis system.
Tracks:
- Strategy performance
- Market regime results
- Win/Loss memory
- Adaptive feedback
"""


import json
import os
import logging


logger = logging.getLogger("AtlasAI")



class OutcomeMemory:


    def __init__(self):

        self.file = "outcome_memory.json"

        self.memory = {

            "total": 0,

            "wins": 0,

            "losses": 0,

            "profit": 0,

            "strategies": {},

            "regimes": {}

        }


        self.load()



    # =====================================
    # LOAD
    # =====================================

    def load(self):

        if os.path.exists(self.file):

            try:

                with open(
                    self.file,
                    "r",
                    encoding="utf-8"
                ) as f:

                    self.memory = json.load(f)


            except Exception as e:

                logger.error(
                    f"Outcome load error: {e}"
                )



    # =====================================
    # SAVE
    # =====================================

    def save(self):

        with open(
            self.file,
            "w",
            encoding="utf-8"
        ) as f:


            json.dump(
                self.memory,
                f,
                indent=4,
                ensure_ascii=False
            )



    # =====================================
    # ANALYZE BEFORE TRADE
    # =====================================

    def analyze(
        self,
        symbol,
        strategy,
        regime
    ):


        strategy_name = self.get_strategy_name(
            strategy
        )


        strategy_score = self.get_strategy_score(
            strategy_name
        )


        regime_score = self.get_regime_score(
            regime
        )


        return {


            "symbol": symbol,


            "strategy": strategy_name,


            "strategy_score": strategy_score,


            "regime_score": regime_score,


            "confidence_bonus":
            self.calculate_bonus(
                strategy_score,
                regime_score
            )

        }



    # =====================================
    # RECORD RESULT
    # =====================================

    def record_trade(
        self,
        strategy,
        regime,
        profit
    ):


        self.memory["total"] += 1


        self.memory["profit"] += profit



        if profit > 0:

            self.memory["wins"] += 1

        else:

            self.memory["losses"] += 1



        self.update_group(

            "strategies",

            strategy,

            profit

        )


        self.update_group(

            "regimes",

            regime,

            profit

        )


        self.save()



        logger.info(
            f"[OUTCOME] Recorded {strategy} {profit}"
        )



    # =====================================
    # GROUP UPDATE
    # =====================================

    def update_group(
        self,
        group,
        name,
        profit
    ):


        if name not in self.memory[group]:


            self.memory[group][name] = {

                "trades":0,

                "wins":0,

                "losses":0,

                "profit":0,

                "score":50

            }



        item = self.memory[group][name]


        item["trades"] += 1

        item["profit"] += profit



        if profit > 0:

            item["wins"] += 1

        else:

            item["losses"] += 1



        win_rate = (

            item["wins"] /
            item["trades"]

        ) * 100



        item["score"] = round(

            max(

                min(

                    win_rate,

                    100

                ),

                0

            ),

            2

        )



    # =====================================
    # HELPERS
    # =====================================

    def get_strategy_name(
        self,
        strategy
    ):


        if isinstance(
            strategy,
            dict
        ):

            return strategy.get(
                "name",
                "UNKNOWN"
            )


        return str(strategy)



    def get_strategy_score(
        self,
        strategy
    ):


        data = self.memory["strategies"].get(
            strategy
        )


        if data:

            return data.get(
                "score",
                50
            )


        return 50




    def get_regime_score(
        self,
        regime
    ):


        name = str(regime)


        data = self.memory["regimes"].get(
            name
        )


        if data:

            return data.get(
                "score",
                50
            )


        return 50




    def calculate_bonus(
        self,
        strategy_score,
        regime_score
    ):


        return round(

            (
                strategy_score +
                regime_score

            ) / 20,


            2

        )



    # =====================================
    # INSIGHT
    # =====================================

    def insight(self):


        total = self.memory["total"]


        win_rate = 0


        if total > 0:

            win_rate = round(

                (
                    self.memory["wins"] /
                    total

                ) * 100,

                2

            )



        return {


            "total":

            total,


            "wins":

            self.memory["wins"],


            "losses":

            self.memory["losses"],


            "win_rate":

            win_rate,


            "profit":

            self.memory["profit"]

        }
    # =====================================
    # CREATE OPEN TRADE MEMORY
    # =====================================

    def create_trade(
        self,
        symbol,
        decision,
        confidence,
        strategy=None,
        regime=None
    ):

        if not hasattr(
            self,
            "open_trades"
        ):

            self.open_trades = []


        trade = {

            "symbol": symbol,

            "action": decision.get(
                "action",
                "UNKNOWN"
            ),

            "entry": decision.get(
                "entry",
                0
            ),

            "stop_loss": decision.get(
                "stop_loss",
                0
            ),

            "take_profit": decision.get(
                "take_profit",
                0
            ),

            "confidence": confidence,

            "strategy": strategy,

            "regime": regime,

            "status": "OPEN"

        }


        self.open_trades.append(
            trade
        )


        logger.info(
            f"[OUTCOME] Open trade memory created: {symbol}"
        )


        return trade