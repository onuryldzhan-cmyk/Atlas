from strategy.scalper import Scalper
from ai.decision_engine import DecisionEngine
from ai.atlas_brain import AtlasBrain
from risk.risk_manager import RiskManager
from simulation.simulator import TradeSimulator
from database.trade_history import TradeHistory
from data.data_provider import DataProvider


class AtlasEngine:


    def __init__(self):

        self.market = DataProvider()

        self.strategy = Scalper()

        self.ai = DecisionEngine()

        self.brain = AtlasBrain()

        self.risk = RiskManager()

        self.simulator = TradeSimulator()

        self.history = TradeHistory()



    def start(self):

        print("Atlas Engine çalışıyor...")


        while True:

            try:

                brain_data = self.brain.think()

                print(
                    "Atlas Brain:",
                    brain_data
                )


                candles = self.market.get_candles(5)


                for candle in candles:

                    print(
                        "Mum:",
                        candle
                    )


                analysis = self.strategy.analyze(
                    candles
                )


                signal = analysis["signal"]


                print(
                    "Analiz:",
                    analysis["trend"]
                )

                print(
                    "Sinyal:",
                    signal
                )



                decision = self.ai.decide(
                    signal,
                    brain_data
                )


                print(
                    "AI Karar:",
                    decision
                )



                if decision["decision"] != "ONAY":

                    print(
                        "İşlem reddedildi."
                    )

                    continue



                entry = candles[0]["close"]

                exit_price = candles[-1]["close"]



                risk_status = self.risk.check(
                    signal,
                    entry,
                    exit_price
                )


                print(
                    "Risk:",
                    risk_status
                )



                if risk_status != "İŞLEM UYGUN":

                    print(
                        "Risk uygun değil, işlem açılmadı."
                    )

                    continue



                prices = [
                    c["close"]
                    for c in candles
                ]



                result, reason = self.simulator.simulate(
                    signal,
                    prices
                )


                print(
                    "Simülasyon sonucu:",
                    result,
                    "TL"
                )


                print(
                    "Çıkış sebebi:",
                    reason
                )



                self.history.save(
                    signal,
                    result,
                    reason,
                    {
                        "trend": analysis["trend"],

                        "ai_score": decision["score"],

                        "confidence": brain_data.get(
                            "confidence",
                            50
                        ),

                        "entry_price": entry,

                        "exit_price": exit_price,

                        "volume": candles[-1].get(
                            "volume",
                            0
                        )
                    }
                )



                print(
                    "İşlem geçmişe kaydedildi."
                )


                print(
                    "Atlas bekleme modunda..."
                )


                break



            except Exception as e:

                print(
                    "Sistem hatası:",
                    e
                )

                break