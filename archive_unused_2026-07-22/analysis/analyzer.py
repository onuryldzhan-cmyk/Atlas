class Analyzer:

    def analyze(self, prices):

        if len(prices) < 5:
            return {
                "trend": "YETERSIZ_VERI",
                "signal": "BEKLE",
                "strength": 0
            }

        last = prices[-1]
        prev = prices[-2]

        average = sum(prices) / len(prices)

        momentum = last - prev

        strength = abs(last - average)

        if last > average and momentum > 0:
            trend = "YUKSELIS"
            signal = "AL"

        elif last < average and momentum < 0:
            trend = "DUSUS"
            signal = "SAT"

        else:
            trend = "YATAY"
            signal = "BEKLE"

        return {
            "trend": trend,
            "signal": signal,
            "strength": round(strength, 2),
            "average": round(average, 2),
            "momentum": round(momentum, 2)
        }


if __name__ == "__main__":

    analyzer = Analyzer()

    prices = [
        100,
        100.3,
        100.8,
        101.1,
        101.7,
        102.2
    ]

    print(analyzer.analyze(prices))