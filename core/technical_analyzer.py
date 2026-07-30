"""
Atlas Technical Analyzer v2.0

Technical intelligence layer.

Input:
    normalized candles

Output:
    technical features

Features:
    EMA20
    EMA50
    RSI
    ADX
    Momentum
    Volatility
    Volume Pressure
    Trend
"""


from __future__ import annotations

import logging
import statistics


logger = logging.getLogger(
    "AtlasAI.TechnicalAnalyzer"
)



class TechnicalAnalyzer:


    def __init__(self):

        self.version = "2.0"



    # =====================================
    # EMA
    # =====================================


    def ema(
        self,
        prices,
        period
    ):


        if len(prices) < period:

            return None



        multiplier = 2 / (period + 1)


        value = sum(
            prices[:period]
        ) / period



        for price in prices[period:]:

            value = (

                (price - value)
                *
                multiplier

            ) + value



        return round(
            value,
            4
        )



    # =====================================
    # RSI
    # =====================================


    def rsi(
        self,
        prices,
        period=14
    ):


        if len(prices) <= period:

            return None



        gains = []

        losses = []



        for i in range(1,len(prices)):


            diff = prices[i]-prices[i-1]


            gains.append(
                max(diff,0)
            )


            losses.append(
                max(-diff,0)
            )



        avg_gain = (

            sum(
                gains[-period:]
            )
            /
            period

        )


        avg_loss = (

            sum(
                losses[-period:]
            )
            /
            period

        )



        if avg_loss == 0:

            return 100



        rs = avg_gain / avg_loss


        return round(
            100 -
            (
                100 /
                (1+rs)
            ),
            2
        )



    # =====================================
    # VOLATILITY
    # =====================================


    def volatility(
        self,
        prices
    ):


        if len(prices)<10:

            return 0



        returns=[]


        for i in range(1,len(prices)):

            returns.append(

                (
                    prices[i]-prices[i-1]
                )
                /
                prices[i-1]

            )



        return round(

            statistics.stdev(
                returns
            )
            *
            100,

            3

        )



    # =====================================
    # MOMENTUM
    # =====================================


    def momentum(
        self,
        prices,
        period=10
    ):


        if len(prices)<period:

            return 0



        return round(

            (
                prices[-1]
                -
                prices[-period]
            )
            /
            prices[-period]
            *
            100,

            3

        )



    # =====================================
    # VOLUME PRESSURE
    # =====================================


    def volume_pressure(
        self,
        candles
    ):


        if len(candles)<10:

            return 0



        recent = candles[-10:]


        up = 0

        down = 0



        for c in recent:


            if c["close"] > c["open"]:

                up += c["volume"]


            else:

                down += c["volume"]



        total = up + down


        if total == 0:

            return 0



        return round(

            (
                up-down
            )
            /
            total,

            3

        )



    # =====================================
    # MAIN ANALYSIS
    # =====================================


    def analyze(
        self,
        candles
    ):


        if not candles:

            return {}



        closes=[

            c["close"]

            for c in candles

        ]



        ema20=self.ema(
            closes,
            20
        )


        ema50=self.ema(
            closes,
            50
        )


        rsi=self.rsi(
            closes
        )


        trend="NEUTRAL"



        if ema20 and ema50:


            if ema20 > ema50:

                trend="BULLISH"


            elif ema20 < ema50:

                trend="BEARISH"



        return {


            "ema20":
                ema20,


            "ema50":
                ema50,


            "rsi":
                rsi,


            "trend":
                trend,


            "volatility":
                self.volatility(
                    closes
                ),


            "momentum":
                self.momentum(
                    closes
                ),


            "volume_pressure":
                self.volume_pressure(
                    candles
                ),


            "last_close":
                closes[-1]

        }