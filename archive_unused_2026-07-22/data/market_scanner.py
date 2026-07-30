from data.data_provider import DataProvider
from strategy.scalper import Scalper
from analysis.technical_analyzer import TechnicalAnalyzer



class MarketScanner:


    def __init__(self):

        self.market = DataProvider()

        self.strategy = Scalper()

        self.analyzer = TechnicalAnalyzer()



        self.symbols = [

            "BTCUSDT",
            "ETHUSDT",
            "SOLUSDT",
            "BNBUSDT",
            "XRPUSDT"

        ]



    def calculate_score(
        self,
        technical,
        analysis
    ):


        score = technical.get(
            "score",
            50
        )


        if analysis["signal"] == "AL":

            score += 10

        else:

            score += 5



        return score



    def scan(self):


        results = []



        for symbol in self.symbols:


            try:


                candles = self.market.get_candles(

                    symbol=symbol,

                    limit=100

                )



                technical = self.analyzer.analyze(

                    candles

                )



                analysis = self.strategy.analyze(

                    candles

                )



                score = self.calculate_score(

                    technical,

                    analysis

                )



                results.append({

                    "symbol": symbol,

                    "trend": technical["trend"],

                    "signal": analysis["signal"],

                    "score": score

                })



            except Exception as e:

                print(
                    symbol,
                    "hata:",
                    e
                )



        results.sort(

            key=lambda x:x["score"],

            reverse=True

        )



        return results