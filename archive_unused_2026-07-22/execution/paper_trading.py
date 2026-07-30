"""
Atlas AI - Paper Trading Engine
Canli piyasada simulasyon modunda islem yapar
"""
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

# Proje kokunu ekle
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np

# ============ AYARLAR ============
CONFIG = {
    "symbol": "BTCUSDT",
    "timeframe": "1h",
    "initial_balance": 10000.0,
    "position_size_pct": 0.10,  # Bakiyenin %10'u ile islem
    "max_positions": 3,
    "stop_loss_pct": 0.02,      # %2 stop loss
    "take_profit_pct": 0.04,    # %4 take profit
    "paper_mode": True,         # Simulasyon modu
    "data_source": "file",      # "file" veya "api"
    "check_interval_minutes": 60,
    "results_file": "data/paper_trading_results.json",
    "log_file": "logs/paper_trading.log"
}

# ============ VERI YUKLEME ============
def load_price_data():
    """Veri dosyasindan son fiyatlari yukle"""
    data_dir = PROJECT_ROOT / "data"

    # Olası dosya isimleri
    possible_files = [
        "btcusdt_1h.json",
        "btc_usdt_1h.json",
        "market_data.json"
    ]

    for fname in possible_files:
        fpath = data_dir / fname
        if fpath.exists():
            with open(fpath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list) and len(data) > 0:
                    return data
                elif isinstance(data, dict) and 'data' in data:
                    return data['data']

    print("⚠️  Veri dosyasi bulunamadi! Once veri cekmelisiniz.")
    return None

# ============ TEKNIK GOSTERGELER ============
def calculate_rsi(prices, period=14):
    """RSI hesapla"""
    if len(prices) < period + 1:
        return 50

    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)

    avg_gain = np.mean(gains[-period:])
    avg_loss = np.mean(losses[-period:])

    if avg_loss == 0:
        return 100

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calculate_bollinger(prices, period=20, std_dev=2):
    """Bollinger Bantlari hesapla"""
    if len(prices) < period:
        return None, None, None

    recent = np.array(prices[-period:])
    sma = np.mean(recent)
    std = np.std(recent)

    upper = sma + (std_dev * std)
    lower = sma - (std_dev * std)

    return upper, sma, lower

def calculate_sma(prices, period=50):
    """SMA hesapla"""
    if len(prices) < period:
        return prices[-1] if prices else 0
    return np.mean(prices[-period:])

# ============ STRATEJI: MEAN REVERSION (Backtest'ten en iyi) ============
class MeanReversionStrategy:
    def __init__(self):
        self.name = "MeanReversion"

    def generate_signal(self, closes, highs, lows, volumes):
        """
        Sinyal uret: 1=AL, -1=SAT, 0=BEKLE
        """
        if len(closes) < 25:
            return 0, "Yetersiz veri"

        current_price = closes[-1]

        # RSI
        rsi = calculate_rsi(closes, 14)

        # Bollinger
        bb_upper, bb_sma, bb_lower = calculate_bollinger(closes, 20, 2)

        # SMA
        sma20 = calculate_sma(closes, 20)
        sma50 = calculate_sma(closes, 50)

        # Trend kontrolu
        trend_up = sma20 > sma50

        signals = []
        score = 0

        # RSI asiri satim + yukari donus
        if rsi < 35:
            signals.append(f"RSI asiri satim ({rsi:.1f})")
            score += 2
        elif rsi > 65:
            signals.append(f"RSI asiri alim ({rsi:.1f})")
            score -= 2

        # Bollinger alt bandi
        if bb_lower and current_price < bb_lower * 1.01:
            signals.append(f"Fiyat BB alt bandinda")
            score += 2

        # Fiyat SMA'nin altinda
        if current_price < sma20 * 0.98:
            signals.append(f"Fiyat SMA20'nin altinda")
            score += 1

        # Hacim kontrolu
        if len(volumes) >= 20:
            avg_vol = np.mean(volumes[-20:])
            if volumes[-1] > avg_vol * 1.2:
                signals.append("Yuksek hacim")
                score += 1

        # Karar
        if score >= 3 and not trend_up:
            return 1, f"AL | Score:{score} | {' | '.join(signals)}"
        elif score <= -2:
            return -1, f"SAT | Score:{score} | {' | '.join(signals)}"

        return 0, f"BEKLE | Score:{score} | {' | '.join(signals)}"

# ============ PORTFOLYO YONETIMI ============
class PaperPortfolio:
    def __init__(self, initial_balance=10000.0):
        self.balance = initial_balance
        self.initial_balance = initial_balance
        self.positions = []  # Aktif pozisyonlar
        self.closed_trades = []  # Kapatilmis islemler
        self.trade_history = []
        self.total_trades = 0
        self.winning_trades = 0

    def get_position_value(self, current_price):
        """Aktif pozisyonlarin degerini hesapla"""
        total = 0
        for pos in self.positions:
            if pos['side'] == 'LONG':
                total += pos['quantity'] * current_price
            else:  # SHORT
                total += pos['quantity'] * (2 * pos['entry_price'] - current_price)
        return total

    def get_total_value(self, current_price):
        """Toplam portfoy degeri"""
        return self.balance + self.get_position_value(current_price)

    def open_position(self, side, price, quantity, stop_loss, take_profit, signal_reason):
        """Pozisyon ac"""
        cost = price * quantity

        if cost > self.balance * 0.95:
            return False, "Yetersiz bakiye"

        if len(self.positions) >= CONFIG['max_positions']:
            return False, "Max pozisyon sayisina ulasildi"

        position = {
            'id': self.total_trades + 1,
            'side': side,
            'entry_price': price,
            'quantity': quantity,
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'open_time': datetime.now().isoformat(),
            'signal_reason': signal_reason,
            'status': 'OPEN'
        }

        self.positions.append(position)
        self.balance -= cost
        self.total_trades += 1

        return True, f"Pozisyon acildi: {side} @ {price:.2f}"

    def check_positions(self, current_price, current_time):
        """Pozisyonlari kontrol et - SL/TP"""
        closed_trades = []

        for pos in self.positions[:]:
            pnl_pct = 0
            if pos['side'] == 'LONG':
                pnl_pct = (current_price - pos['entry_price']) / pos['entry_price']
            else:
                pnl_pct = (pos['entry_price'] - current_price) / pos['entry_price']

            # Stop Loss
            if pnl_pct <= -CONFIG['stop_loss_pct']:
                trade = self.close_position(pos, current_price, current_time, 'STOP_LOSS')
                if trade:
                    closed_trades.append(trade)

            # Take Profit
            elif pnl_pct >= CONFIG['take_profit_pct']:
                trade = self.close_position(pos, current_price, current_time, 'TAKE_PROFIT')
                if trade:
                    closed_trades.append(trade)

        return closed_trades

    def close_position(self, position, exit_price, exit_time, reason):
        """Pozisyonu kapat"""
        if position['side'] == 'LONG':
            pnl = (exit_price - position['entry_price']) * position['quantity']
            pnl_pct = (exit_price - position['entry_price']) / position['entry_price'] * 100
        else:
            pnl = (position['entry_price'] - exit_price) * position['quantity']
            pnl_pct = (position['entry_price'] - exit_price) / position['entry_price'] * 100

        self.balance += (position['entry_price'] * position['quantity']) + pnl

        trade_record = {
            'id': position['id'],
            'side': position['side'],
            'entry_price': position['entry_price'],
            'exit_price': exit_price,
            'quantity': position['quantity'],
            'pnl': pnl,
            'pnl_pct': pnl_pct,
            'open_time': position['open_time'],
            'close_time': exit_time.isoformat() if isinstance(exit_time, datetime) else exit_time,
            'close_reason': reason,
            'signal_reason': position['signal_reason']
        }

        self.closed_trades.append(trade_record)
        self.positions.remove(position)

        if pnl > 0:
            self.winning_trades += 1

        return trade_record

    def close_all_positions(self, current_price, reason='MANUAL'):
        """Tum pozisyonlari kapat"""
        closed = []
        for pos in self.positions[:]:
            trade = self.close_position(pos, current_price, datetime.now(), reason)
            if trade:
                closed.append(trade)
        return closed

    def get_stats(self, current_price):
        """Istatistikler"""
        total_pnl = sum(t['pnl'] for t in self.closed_trades)
        win_rate = (self.winning_trades / len(self.closed_trades) * 100) if self.closed_trades else 0

        return {
            'balance': self.balance,
            'total_value': self.get_total_value(current_price),
            'active_positions': len(self.positions),
            'total_trades': len(self.closed_trades),
            'winning_trades': self.winning_trades,
            'win_rate': win_rate,
            'total_pnl': total_pnl,
            'pnl_pct': (self.get_total_value(current_price) - self.initial_balance) / self.initial_balance * 100
        }

# ============ PAPER TRADING ENGINE ============
class PaperTradingEngine:
    def __init__(self):
        self.strategy = MeanReversionStrategy()
        self.portfolio = PaperPortfolio(CONFIG['initial_balance'])
        self.data = None
        self.current_index = 0
        self.running = False

    def load_data(self):
        """Veriyi yukle"""
        self.data = load_price_data()
        if not self.data:
            return False

        print(f"✅ {len(self.data)} mum yuklendi")
        print(f"📅 Tarih: {self.data[0].get('timestamp', 'N/A')} -> {self.data[-1].get('timestamp', 'N/A')}")
        print(f"💰 Fiyat: {self.data[0].get('close', 0):.2f} -> {self.data[-1].get('close', 0):.2f}")
        return True

    def run_simulation(self):
        """Paper trading simulasyonu calistir"""
        if not self.load_data():
            return

        print("\n" + "="*60)
        print("ATLAS AI - PAPER TRADING SIMULASYONU")
        print("="*60)
        print(f"Baslangic Bakiyesi: {CONFIG['initial_balance']:.2f} USDT")
        print(f"Strateji: {self.strategy.name}")
        print(f"Sembol: {CONFIG['symbol']}")
        print("="*60 + "\n")

        # Her mum icin simulasyon
        for i in range(50, len(self.data)):
            candle = self.data[i]
            prev_candles = self.data[:i+1]

            closes = [c['close'] for c in prev_candles]
            highs = [c['high'] for c in prev_candles]
            lows = [c['low'] for c in prev_candles]
            volumes = [c.get('volume', 0) for c in prev_candles]

            current_price = candle['close']
            current_time = candle.get('timestamp', f'Mum {i}')

            # Mevcut pozisyonlari kontrol et (SL/TP)
            closed_trades = self.portfolio.check_positions(current_price, current_time)
            for t in closed_trades:
                emoji = "✅" if t['pnl'] > 0 else "❌"
                print(f"{emoji} KAPANDI | #{t['id']} {t['side']} | PnL: {t['pnl']:.2f} ({t['pnl_pct']:.2f}%) | Neden: {t['close_reason']}")

            # Sinyal kontrolu (pozisyon yoksa)
            if len(self.portfolio.positions) < CONFIG['max_positions']:
                signal, reason = self.strategy.generate_signal(closes, highs, lows, volumes)

                if signal == 1:  # AL
                    position_size = self.portfolio.get_total_value(current_price) * CONFIG['position_size_pct']
                    quantity = position_size / current_price

                    stop_loss = current_price * (1 - CONFIG['stop_loss_pct'])
                    take_profit = current_price * (1 + CONFIG['take_profit_pct'])

                    success, msg = self.portfolio.open_position(
                        'LONG', current_price, quantity,
                        stop_loss, take_profit, reason
                    )

                    if success:
                        print(f"🟢 ACILDI | LONG @ {current_price:.2f} | Miktar: {quantity:.6f} | SL: {stop_loss:.2f} | TP: {take_profit:.2f}")
                        print(f"   📝 {reason}")

            # Her 100 mumda rapor
            if i % 100 == 0 and i > 50:
                stats = self.portfolio.get_stats(current_price)
                print(f"\n📊 Mum {i}/{len(self.data)} | Bakiye: {stats['total_value']:.2f} | PnL: {stats['pnl_pct']:.2f}% | Aktif: {stats['active_positions']}")

        # Final rapor
        self.print_final_report(current_price)
        self.save_results()

    def print_final_report(self, current_price):
        """Final rapor"""
        stats = self.portfolio.get_stats(current_price)

        print("\n" + "="*60)
        print("PAPER TRADING - FINAL RAPOR")
        print("="*60)
        print(f"Baslangic Bakiyesi: {CONFIG['initial_balance']:.2f} USDT")
        print(f"Guncel Bakiye:      {stats['balance']:.2f} USDT")
        print(f"Toplam Deger:       {stats['total_value']:.2f} USDT")
        print(f"Toplam PnL:         {stats['total_pnl']:.2f} USDT ({stats['pnl_pct']:.2f}%)")
        print(f"-"*60)
        print(f"Toplam Islem:       {stats['total_trades']}")
        print(f"Kazanilan:          {stats['winning_trades']}")
        print(f"Kaybedilen:         {stats['total_trades'] - stats['winning_trades']}")
        print(f"Win Rate:           {stats['win_rate']:.1f}%")
        print(f"Aktif Pozisyon:     {stats['active_positions']}")
        print("="*60)

        if self.portfolio.closed_trades:
            print("\n📋 ISLEM GECMISI:")
            print("-"*60)
            for t in self.portfolio.closed_trades[:10]:  # Son 10
                emoji = "✅" if t['pnl'] > 0 else "❌"
                print(f"{emoji} #{t['id']} | {t['side']} | {t['entry_price']:.2f} -> {t['exit_price']:.2f} | PnL: {t['pnl']:.2f} ({t['pnl_pct']:.2f}%) | {t['close_reason']}")

            if len(self.portfolio.closed_trades) > 10:
                print(f"... ve {len(self.portfolio.closed_trades) - 10} islem daha")

    def save_results(self):
        """Sonuclari kaydet"""
        results = {
            'timestamp': datetime.now().isoformat(),
            'config': CONFIG,
            'portfolio_stats': self.portfolio.get_stats(self.data[-1]['close'] if self.data else 0),
            'closed_trades': self.portfolio.closed_trades,
            'active_positions': self.portfolio.positions
        }

        # Klasor olustur
        os.makedirs(PROJECT_ROOT / "data", exist_ok=True)

        with open(PROJECT_ROOT / CONFIG['results_file'], 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False, default=str)

        print(f"\n💾 Sonuclar kaydedildi: {CONFIG['results_file']}")

# ============ ANA CALISTIRMA ============
if __name__ == "__main__":
    engine = PaperTradingEngine()
    engine.run_simulation()
    print("\n✅ Paper Trading Simulasyonu Tamamlandi!")

