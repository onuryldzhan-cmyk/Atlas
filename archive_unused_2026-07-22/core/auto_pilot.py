"""
Atlas AI v6.0
Auto Pilot Engine

Opportunity Selection + Continuous Trading Logic
"""


import logging
import time


logger = logging.getLogger("AtlasAI")



class AutoPilot:



    def __init__(
        self,
        scanner=None,
        trader=None
    ):


        self.scanner = scanner

        self.trader = trader


        self.running = False


        self.max_positions = 5



    def select_opportunities(
        self
    ):


        if not self.scanner:

            return []



        opportunities = self.scanner.scan()



        selected = []



        for item in opportunities:


            decision = item.get(
                "decision",
                {}
            )


            action = decision.get(
                "action"
            )


            confidence = decision.get(
                "confidence",
                0
            )


            if (

                action in [
                    "BUY",
                    "SELL"
                ]

                and

                confidence >= 70

            ):


                selected.append(
                    item
                )



        return selected




    def execute_cycle(
        self
    ):


        logger.info(
            "Atlas Auto Pilot cycle başladı."
        )


        opportunities = self.select_opportunities()



        if not opportunities:


            print(
                "Atlas: Uygun fırsat bulunamadı."
            )

            return []



        print(
            "\n===== ATLAS AUTO OPPORTUNITIES ====="
        )


        for item in opportunities:


            decision = item["decision"]


            print(
                f"""

COIN:
{item['symbol']}

ACTION:
{decision.get('action')}

CONFIDENCE:
%{decision.get('confidence')}

SCORE:
{item['score']}

"""
            )



        return opportunities




    def start(
        self,
        interval=60
    ):


        self.running = True


        print(
            "Atlas Auto Pilot aktif."
        )



        while self.running:


            try:


                self.execute_cycle()



            except Exception as e:


                logger.error(
                    f"Auto Pilot hata: {e}"
                )



            time.sleep(
                interval
            )




    def stop(
        self
    ):


        self.running = False


        print(
            "Atlas Auto Pilot durduruldu."
        )