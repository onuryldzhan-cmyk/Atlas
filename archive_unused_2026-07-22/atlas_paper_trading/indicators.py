"""Atlas AI - Technical Indicators"""
from typing import List, Tuple
import math

class TechnicalIndicators:
    @staticmethod
    def sma(data: List[float], period: int) -> List[float]:
        if len(data) < period: return []
        return [sum(data[i-period+1:i+1])/period for i in range(period-1, len(data))]

    @staticmethod
    def ema(data: List[float], period: int) -> List[float]:
        if len(data) < period: return []
        mult = 2/(period+1)
        result = [sum(data[:period])/period]
        for i in range(period, len(data)):
            result.append((data[i]-result[-1])*mult + result[-1])
        return result

    @staticmethod
    def rsi(data: List[float], period: int = 14) -> List[float]:
        if len(data) < period+1: return []
        gains, losses = [], []
        for i in range(1, len(data)):
            change = data[i]-data[i-1]
            gains.append(max(change, 0)); losses.append(abs(min(change, 0)))
        if len(gains) < period: return []
        avg_gain, avg_loss = sum(gains[:period])/period, sum(losses[:period])/period
        result = []
        for i in range(period-1, len(gains)):
            if i >= period:
                avg_gain = (avg_gain*(period-1) + gains[i])/period
                avg_loss = (avg_loss*(period-1) + losses[i])/period
            if avg_loss == 0: result.append(100.0)
            else: result.append(100-(100/(1+avg_gain/avg_loss)))
        return result

    @staticmethod
    def macd(data: List[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[List[float], List[float], List[float]]:
        if len(data) < slow+signal: return [], [], []
        ema_fast = TechnicalIndicators.ema(data, fast)
        ema_slow = TechnicalIndicators.ema(data, slow)
        start = slow-fast
        macd_line = [ema_fast[i+start]-ema_slow[i] for i in range(len(ema_slow))]
        signal_line = TechnicalIndicators.ema(macd_line, signal)
        start2 = len(macd_line)-len(signal_line)
        hist = [macd_line[i+start2]-signal_line[i] for i in range(len(signal_line))]
        return macd_line, signal_line, hist

    @staticmethod
    def bollinger(data: List[float], period: int = 20, std_dev: float = 2.0) -> Tuple[List[float], List[float], List[float]]:
        if len(data) < period: return [], [], []
        middle = TechnicalIndicators.sma(data, period)
        upper, lower = [], []
        for i in range(period-1, len(data)):
            slice_d = data[i-period+1:i+1]
            mean = sum(slice_d)/period
            var = sum((x-mean)**2 for x in slice_d)/period
            std = math.sqrt(var)
            upper.append(mean+std_dev*std); lower.append(mean-std_dev*std)
        return upper, middle, lower

    @staticmethod
    def atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> List[float]:
        if len(highs) < period+1: return []
        tr = []
        for i in range(1, len(highs)):
            tr.append(max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1])))
        return TechnicalIndicators.sma(tr, period)

    @staticmethod
    def stochastic(highs: List[float], lows: List[float], closes: List[float], k_period: int = 14, d_period: int = 3) -> Tuple[List[float], List[float]]:
        if len(highs) < k_period: return [], []
        k_vals = []
        for i in range(k_period-1, len(closes)):
            hh, ll = max(highs[i-k_period+1:i+1]), min(lows[i-k_period+1:i+1])
            k_vals.append(50.0 if hh==ll else ((closes[i]-ll)/(hh-ll))*100)
        d_vals = TechnicalIndicators.sma(k_vals, d_period)
        return k_vals[len(k_vals)-len(d_vals):], d_vals

    @staticmethod
    def crossover(data1: List[float], data2: List[float]) -> bool:
        return len(data1) >= 2 and len(data2) >= 2 and data1[-2] <= data2[-2] and data1[-1] > data2[-1]

    @staticmethod
    def crossunder(data1: List[float], data2: List[float]) -> bool:
        return len(data1) >= 2 and len(data2) >= 2 and data1[-2] >= data2[-2] and data1[-1] < data2[-1]
