"""
Atlas AI - Paper Trading Engine v2
Gelistirilmis risk yonetimi ile canli piyasada simulasyon

Yeni Ozellikler:
- Cooldown: Kayiptan sonra bekleme suresi
- Gunluk kayip limiti
- Trailing Stop
- Komisyon simulasyonu (%0.1)
- Akilli pozisyon yonetimi (fiyat araligi kontrolu)
- Risk/Reward analizi
"""
import json
import os
import sys
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
    "position_size_pct": 0.10,
    "max_positions": 1,           # AYNI ANDA MAX 1 POZISYON!
    "stop_loss_pct": 0.02,
    "take_profit_pct": 0.04,
    "trailing_stop_pct": 0.015,   # Trailing stop mesafesi
    "trailing_activation_pct": 0.02,  # Trailing aktif olma esigi
    "commission_pct": 0.001,      # %0.1 komisyon (Binance spot)
    "cooldown_candles": 5,        # Kayiptan sonra 5 mum bekle
    "max_daily_losses": 2,        # Gunde max 2 kayip islem
    "max_daily_trades": 5,        # Gunde max 5 islem
    "min_price_distance_pct": 0.01,  # Ayni fiyattan 2. pozisyon acma (min %1 fark)
    "paper_mode": True,
    "results_file": "data/paper_trading_v2_results.json",
    "log_file": "logs/paper_trading_v2.log"
}

# ============ VERI YUKLEME ============
def load_price_data():
    """Veri dosyasindan son fiyatlari yukle"""
    data_dir = PROJECT_ROOT / "data"
    possible_files = ["btcusdt_1h.json", "btc_usdt_1h.json", "market_data.json"]

    for fname in possible_files:
        fpath = data_dir / fname
        if fpath.exists():
            with open(fpath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list) and len(data) > 0:
                    return data
                elif isinstance(data, dict) and 'data' in data:
                    return data['data']

    print("⚠️  Veri dosyasi bulunamadi!")
    return None

# ============ TEKNIK GOSTERGELER ============
def calculate_rsi(prices, period=14):
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
    if len(prices) < period:
        return None, None, None
    recent = np.array(prices[-period:])
    sma = np.mean(recent)
    std = np.std(recent)
    return sma + (std_dev * std), sma, sma - (std_dev * std)

def calculate_sma(prices, period=50):
    if len(prices) < period:
        return prices[-1] if prices else 0
    return np.mean(prices[-period:])

def calculate_atr(highs, lows, closes, period=14):
    """Average True Range - Volatilite olcumu"""
    if len(closes) < period + 1:
        return 0
    tr_list = []
    for i in range(1, len(closes)):
        tr1 = highs[i] - lows[i]
        tr2 = abs(highs[i] - closes[i-1])
        tr3 = abs(lows[i] - closes[i-1])
        tr_list.append(max(tr1, tr2, tr3))
    return np.mean(tr_list[-period:])

# ============ STRATEJI: MEAN REVERSION v2 ============
class MeanReversionStrategyV2:
    def __init__(self):
        self.name = "MeanReversion_v2"

    def generate_signal(self, closes, highs, lows, volumes):
        if len(closes) < 50:
            return 0, "Yetersiz veri", {}

        current_price = closes[-1]

        # Gostergeler
        rsi = calculate_rsi(closes, 14)
        bb_upper, bb_sma, bb_lower = calculate_bollinger(closes, 20, 2)
        sma20 = calculate_sma(closes, 20)
        sma50 = calculate_sma(closes, 50)
        sma200 = calculate_sma(closes, 200) if len(closes) >= 200 else sma50
        atr = calculate_atr(highs, lows, closes, 14)

        # Trend analizi
        trend_up = sma20 > sma50
        trend_strong = sma50 > sma200 if len(closes) >= 200 else trend_up

        # Volatilite
        volatility = atr / current_price * 100 if current_price > 0 else 0

        signals = []
        score = 0

        # RSI asiri satim
        if rsi < 30:
            signals.append(f"RSI asiri satim ({rsi:.1f})")
            score += 3
        elif rsi < 40:
            signals.append(f"RSI dusuk ({rsi:.1f})")
            score += 1
        elif rsi > 70:
            signals.append(f"RSI asiri alim ({rsi:.1f})")
            score -= 3

        # Bollinger alt bandi
        if bb_lower and current_price < bb_lower * 1.005:
            signals.append("Fiyat BB alt bandinda")
            score += 2
        elif bb_lower and current_price < bb_lower * 1.02:
            signals.append("Fiyat BB altina yakin")
            score += 1

        # SMA destegi
        if current_price < sma20 * 0.97:
            signals.append("Fiyat SMA20'nin altinda")
            score += 1

        # Hacim
        if len(volumes) >= 20:
            avg_vol = np.mean(volumes[-20:])
            if volumes[-1] > avg_vol * 1.5:
                signals.append("Cok yuksek hacim")
                score += 2
            elif volumes[-1] > avg_vol * 1.2:
                signals.append("Yuksek hacim")
                score += 1

        # Trend filtresi: Guclu dusus trendinde alma
        if trend_up and trend_strong:
            signals.append("Yukari trend (filtre)")
            score -= 1  # Trend yukari = mean reversion zor

        # Volatilite filtresi: Cok dusuk volatilitede islem yapma
        if volatility < 0.5:
            signals.append("Dusuk volatilite (filtre)")
            score -= 2

        # Karar
        context = {
            'rsi': rsi,
            'bb_lower': bb_lower,
            'sma20': sma20,
            'sma50': sma50,
            'trend_up': trend_up,
            'volatility': volatility,
            'atr': atr
        }

        if score >= 4:
            return 1, f"AL | Score:{score} | {' | '.join(signals)}", context
        elif score <= -3:
            return -1, f"SAT | Score:{score} | {' | '.join(signals)}", context

        return 0, f"BEKLE | Score:{score} | {' | '.join(signals)}", context

# ============ GELISMIS PORTFOLYO YONETIMI ============
class PaperPortfolioV2:
    def __init__(self, initial_balance=10000.0):
        self.balance = initial_balance
        self.initial_balance = initial_balance
        self.positions = []
        self.closed_trades = []
        self.total_trades = 0
        self.winning_trades = 0

        # Risk yonetimi state
        self.cooldown_remaining = 0
        self.daily_loss_count = 0
        self.daily_trade_count = 0
        self.last_trade_day = None
        self.total_commission_paid = 0

    def reset_daily_counters(self, current_time):
        """Gunluk sayaclari sifirla"""
        current_day = str(current_time)[:10] if isinstance(current_time, str) else current_time.strftime('%Y-%m-%d') if hasattr(current_time, 'strftime') else str(current_time)[:10]

        if self.last_trade_day != current_day:
            self.daily_loss_count = 0
            self.daily_trade_count = 0
            self.last_trade_day = current_day

    def can_trade(self):
        """Islem yapilabilir mi?"""
        if self.cooldown_remaining > 0:
            return False, f"Cooldown: {self.cooldown_remaining} mum kaldi"
        if self.daily_loss_count >= CONFIG['max_daily_losses']:
            return False, f"Gunluk kayip limitine ulasildi ({self.daily_loss_count})"
        if self.daily_trade_count >= CONFIG['max_daily_trades']:
            return False, f"Gunluk islem limitine ulasildi ({self.daily_trade_count})"
        return True, "OK"

    def get_position_value(self, current_price):
        total = 0
        for pos in self.positions:
            if pos['side'] == 'LONG':
                total += pos['quantity'] * current_price
        return total

    def get_total_value(self, current_price):
        return self.balance + self.get_position_value(current_price)

    def calculate_position_size(self, current_price, atr=None):
        """ATR bazli dinamik pozisyon buyuklugu"""
        base_size = self.get_total_value(current_price) * CONFIG['position_size_pct']

        # ATR bazli ayarlama: Yuksek volatilite = kucuk pozisyon
        if atr and atr > 0:
            atr_factor = min(1.5, max(0.5, 200 / (atr / current_price * 10000)))
            base_size *= atr_factor

        # Kayip serisi = daha kucuk pozisyon
        if self.daily_loss_count > 0:
            loss_factor = max(0.5, 1 - (self.daily_loss_count * 0.2))
            base_size *= loss_factor

        return base_size

    def open_position(self, side, price, context, signal_reason):
        """Pozisyon ac (gelismis)"""
        self.reset_daily_counters(datetime.now())

        can_trade, msg = self.can_trade()
        if not can_trade:
            return False, msg

        if len(self.positions) >= CONFIG['max_positions']:
            return False, "Max pozisyon sayisina ulasildi"

        # Ayni fiyattan cok yakin pozisyon acma kontrolu
        for pos in self.positions:
            price_diff = abs(price - pos['entry_price']) / pos['entry_price']
            if price_diff < CONFIG['min_price_distance_pct']:
                return False, f"Cok yakin fiyatta pozisyon var ({price_diff*100:.2f}%)"

        # Dinamik SL/TP (ATR bazli)
        atr = context.get('atr', price * 0.02)
        atr_pct = atr / price

        sl_pct = max(CONFIG['stop_loss_pct'], atr_pct * 1.5)
        tp_pct = max(CONFIG['take_profit_pct'], atr_pct * 3)

        stop_loss = price * (1 - sl_pct)
        take_profit = price * (1 + tp_pct)

        # Pozisyon buyuklugu
        position_size = self.calculate_position_size(price, atr)
        quantity = position_size / price
        cost = price * quantity

        # Komisyon
        commission = cost * CONFIG['commission_pct']
        total_cost = cost + commission

        if total_cost > self.balance * 0.95:
            return False, "Yetersiz bakiye (komisyon dahil)"

        position = {
            'id': self.total_trades + 1,
            'side': side,
            'entry_price': price,
            'quantity': quantity,
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'trailing_stop': stop_loss,
            'highest_price': price,
            'open_time': datetime.now().isoformat(),
            'signal_reason': signal_reason,
            'context': context,
            'commission_paid': commission,
            'status': 'OPEN'
        }

        self.positions.append(position)
        self.balance -= total_cost
        self.total_trades += 1
        self.daily_trade_count += 1
        self.total_commission_paid += commission

        return True, f"Pozisyon acildi: {side} @ {price:.2f} | SL:{stop_loss:.2f} | TP:{take_profit:.2f} | Kom:{commission:.2f}"

    def update_trailing_stop(self, position, current_price):
        """Trailing stop guncelle"""
        if position['side'] == 'LONG':
            # Yeni zirve
            if current_price > position['highest_price']:
                position['highest_price'] = current_price

                # Kar esigini gecti mi?
                profit_pct = (current_price - position['entry_price']) / position['entry_price']
                if profit_pct >= CONFIG['trailing_activation_pct']:
                    new_trailing = current_price * (1 - CONFIG['trailing_stop_pct'])
                    if new_trailing > position['trailing_stop']:
                        position['trailing_stop'] = new_trailing
                        return True, f"Trailing yukseltildi: {new_trailing:.2f}"
        return False, None

    def check_positions(self, current_price, current_time):
        """Pozisyonlari kontrol et - SL/TP/Trailing"""
        closed_trades = []

        for pos in self.positions[:]:
            # Trailing stop guncelle
            trailing_updated, trailing_msg = self.update_trailing_stop(pos, current_price)

            pnl_pct = (current_price - pos['entry_price']) / pos['entry_price']

            # Stop Loss (normal veya trailing)
            stop_level = max(pos['stop_loss'], pos['trailing_stop'])
            if current_price <= stop_level:
                trade = self.close_position(pos, current_price, current_time, 'STOP_LOSS')
                if trade:
                    closed_trades.append(trade)

            # Take Profit
            elif current_price >= pos['take_profit']:
                trade = self.close_position(pos, current_price, current_time, 'TAKE_PROFIT')
                if trade:
                    closed_trades.append(trade)

        return closed_trades

    def close_position(self, position, exit_price, exit_time, reason):
        """Pozisyonu kapat"""
        pnl = (exit_price - position['entry_price']) * position['quantity']
        pnl_pct = (exit_price - position['entry_price']) / position['entry_price'] * 100

        # Kapanis komisyonu
        exit_commission = (exit_price * position['quantity']) * CONFIG['commission_pct']
        self.total_commission_paid += exit_commission

        net_pnl = pnl - position['commission_paid'] - exit_commission

        self.balance += (position['entry_price'] * position['quantity']) + pnl - exit_commission

        trade_record = {
            'id': position['id'],
            'side': position['side'],
            'entry_price': position['entry_price'],
            'exit_price': exit_price,
            'quantity': position['quantity'],
            'gross_pnl': pnl,
            'commission': position['commission_paid'] + exit_commission,
            'net_pnl': net_pnl,
            'pnl_pct': pnl_pct,
            'open_time': position['open_time'],
            'close_time': exit_time.isoformat() if isinstance(exit_time, datetime) else str(exit_time),
            'close_reason': reason,
            'signal_reason': position['signal_reason'],
            'context': position['context']
        }

        self.closed_trades.append(trade_record)
        self.positions.remove(position)

        # Risk yonetimi guncelle
        if net_pnl < 0:
            self.daily_loss_count += 1
            self.cooldown_remaining = CONFIG['cooldown_candles']
        else:
            self.cooldown_remaining = max(0, self.cooldown_remaining - 1)

        if net_pnl > 0:
            self.winning_trades += 1

        return trade_record

    def tick_cooldown(self):
        """Cooldown sayacini azalt"""
        self.cooldown_remaining = max(0, self.cooldown_remaining - 1)

    def get_stats(self, current_price):
        total_net_pnl = sum(t['net_pnl'] for t in self.closed_trades)
        total_gross_pnl = sum(t['gross_pnl'] for t in self.closed_trades)
        win_rate = (self.winning_trades / len(self.closed_trades) * 100) if self.closed_trades else 0

        # Profit Factor
        gross_profit = sum(t['gross_pnl'] for t in self.closed_trades if t['gross_pnl'] > 0)
        gross_loss = abs(sum(t['gross_pnl'] for t in self.closed_trades if t['gross_pnl'] < 0))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

        # Ortalama kazanclar/kayiplar
        wins = [t['net_pnl'] for t in self.closed_trades if t['net_pnl'] > 0]
        losses = [t['net_pnl'] for t in self.closed_trades if t['net_pnl'] < 0]
        avg_win = np.mean(wins) if wins else 0
        avg_loss = np.mean(losses) if losses else 0

        return {
            'balance': self.balance,
            'total_value': self.get_total_value(current_price),
            'active_positions': len(self.positions),
            'total_trades': len(self.closed_trades),
            'winning_trades': self.winning_trades,
            'win_rate': win_rate,
            'total_gross_pnl': total_gross_pnl,
            'total_net_pnl': total_net_pnl,
            'total_commission': self.total_commission_paid,
            'pnl_pct': (self.get_total_value(current_price) - self.initial_balance) / self.initial_balance * 100,
            'profit_factor': profit_factor,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'daily_loss_count': self.daily_loss_count,
            'cooldown': self.cooldown_remaining
        }

# ============ PAPER TRADING ENGINE v2 ============
class PaperTradingEngineV2:
    def __init__(self):
        self.strategy = MeanReversionStrategyV2()
        self.portfolio = PaperPortfolioV2(CONFIG['initial_balance'])
        self.data = None

    def load_data(self):
        self.data = load_price_data()
        if not self.data:
            return False
        print(f"✅ {len(self.data)} mum yuklendi")
        print(f"📅 Tarih: {self.data[0].get('timestamp', 'N/A')} -> {self.data[-1].get('timestamp', 'N/A')}")
        print(f"💰 Fiyat: {self.data[0].get('close', 0):.2f} -> {self.data[-1].get('close', 0):.2f}")
        return True

    def run_simulation(self):
        if not self.load_data():
            return

        print("\n" + "="*70)
        print("ATLAS AI - PAPER TRADING SIMULASYONU v2")
        print("Gelismis Risk Yonetimi Edition")
        print("="*70)
        print(f"💰 Baslangic Bakiyesi: {CONFIG['initial_balance']:.2f} USDT")
        print(f"📊 Strateji: {self.strategy.name}")
        print(f"📈 Sembol: {CONFIG['symbol']}")
        print(f"⚙️  Max Pozisyon: {CONFIG['max_positions']} | Cooldown: {CONFIG['cooldown_candles']} mum")
        print(f"💸 Komisyon: %{CONFIG['commission_pct']*100} | Gunluk Max Kayip: {CONFIG['max_daily_losses']}")
        print("="*70 + "\n")

        for i in range(50, len(self.data)):
            candle = self.data[i]
            prev_candles = self.data[:i+1]

            closes = [c['close'] for c in prev_candles]
            highs = [c['high'] for c in prev_candles]
            lows = [c['low'] for c in prev_candles]
            volumes = [c.get('volume', 0) for c in prev_candles]

            current_price = candle['close']
            current_time = candle.get('timestamp', f'Mum {i}')

            # Cooldown azalt
            self.portfolio.tick_cooldown()

            # Pozisyonlari kontrol et
            closed_trades = self.portfolio.check_positions(current_price, current_time)
            for t in closed_trades:
                emoji = "✅" if t['net_pnl'] > 0 else "❌"
                print(f"{emoji} KAPANDI | #{t['id']} {t['side']} | Net PnL: {t['net_pnl']:.2f} ({t['pnl_pct']:.2f}%) | {t['close_reason']} | Kom:{t['commission']:.2f}")

            # Sinyal kontrolu
            if len(self.portfolio.positions) < CONFIG['max_positions']:
                signal, reason, context = self.strategy.generate_signal(closes, highs, lows, volumes)

                if signal == 1:
                    can_trade, trade_msg = self.portfolio.can_trade()
                    if can_trade:
                        success, msg = self.portfolio.open_position(
                            'LONG', current_price, context, reason
                        )
                        if success:
                            pos = self.portfolio.positions[-1]
                            print(f"🟢 ACILDI | LONG #{pos['id']} @ {current_price:.2f} | Miktar:{pos['quantity']:.6f} | SL:{pos['stop_loss']:.2f} | TP:{pos['take_profit']:.2f}")
                            print(f"   📝 {reason}")
                        else:
                            print(f"⏸️  PAS | {msg}")
                    else:
                        print(f"⏸️  PAS | {trade_msg}")

            # Her 100 mumda rapor
            if i % 100 == 0 and i > 50:
                stats = self.portfolio.get_stats(current_price)
                print(f"\n📊 Mum {i}/{len(self.data)} | Deger:{stats['total_value']:.2f} | NetPnL:{stats['total_net_pnl']:.2f}({stats['pnl_pct']:.2f}%) | Aktif:{stats['active_positions']} | Cooldown:{stats['cooldown']}")

        self.print_final_report(current_price)
        self.save_results()

    def print_final_report(self, current_price):
        stats = self.portfolio.get_stats(current_price)

        print("\n" + "="*70)
        print("PAPER TRADING v2 - FINAL RAPOR")
        print("="*70)
        print(f"💰 Baslangic Bakiyesi: {CONFIG['initial_balance']:.2f} USDT")
        print(f"💵 Guncel Bakiye:      {stats['balance']:.2f} USDT")
        print(f"📊 Toplam Deger:       {stats['total_value']:.2f} USDT")
        print(f"-"*70)
        print(f"📈 Brut PnL:           {stats['total_gross_pnl']:.2f} USDT")
        print(f"💸 Toplam Komisyon:    {stats['total_commission']:.2f} USDT")
        print(f"📉 Net PnL:            {stats['total_net_pnl']:.2f} USDT ({stats['pnl_pct']:.2f}%)")
        print(f"-"*70)
        print(f"📋 Toplam Islem:       {stats['total_trades']}")
        print(f"✅ Kazanilan:          {stats['winning_trades']}")
        print(f"❌ Kaybedilen:         {stats['total_trades'] - stats['winning_trades']}")
        print(f"🎯 Win Rate:           {stats['win_rate']:.1f}%")
        print(f"⚖️  Profit Factor:     {stats['profit_factor']:.2f}")
        print(f"📊 Ort. Kazanc:        {stats['avg_win']:.2f} USDT")
        print(f"📊 Ort. Kayip:         {stats['avg_loss']:.2f} USDT")
        print(f"🔒 Aktif Pozisyon:     {stats['active_positions']}")
        print("="*70)

        if self.portfolio.closed_trades:
            print("\n📋 ISLEM GECMISI (Son 15):")
            print("-"*70)
            for t in self.portfolio.closed_trades[-15:]:
                emoji = "✅" if t['net_pnl'] > 0 else "❌"
                print(f"{emoji} #{t['id']} | {t['side']} | {t['entry_price']:.2f} -> {t['exit_price']:.2f} | Net:{t['net_pnl']:.2f}({t['pnl_pct']:.2f}%) | {t['close_reason']}")

    def save_results(self):
        results = {
            'timestamp': datetime.now().isoformat(),
            'config': CONFIG,
            'portfolio_stats': self.portfolio.get_stats(self.data[-1]['close'] if self.data else 0),
            'closed_trades': self.portfolio.closed_trades,
            'active_positions': self.portfolio.positions
        }
        os.makedirs(PROJECT_ROOT / "data", exist_ok=True)
        with open(PROJECT_ROOT / CONFIG['results_file'], 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False, default=str)
        print(f"\n💾 Sonuclar kaydedildi: {CONFIG['results_file']}")

if __name__ == "__main__":
    engine = PaperTradingEngineV2()
    engine.run_simulation()
    print("\n✅ Paper Trading v2 Simulasyonu Tamamlandi!")

