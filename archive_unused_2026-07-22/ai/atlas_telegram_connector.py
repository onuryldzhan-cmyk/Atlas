# -*- coding: utf-8 -*-
"""
ATLAS LIVE TRADING ENGINE v2.1 + TELEGRAM + KILL SWITCH
Entegre surum - Bildirim + Guvenlik
"""

import json
import time
import requests
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

# =============================================================================
# TELEGRAM NOTIFIER
# =============================================================================

class TelegramNotifier:
    """Telegram Bot API bildirim"""

    def __init__(self, bot_token: str = None, chat_id: str = None):
        self.bot_token = bot_token or "8895160850:AAGIYQlAxL_uMqmlEn0P3tNyenjxFBL6J5E"
        self.chat_id = chat_id or "8921489033"
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
        self.enabled = bool(self.bot_token and self.chat_id)

        if self.enabled:
            print("[TELEGRAM] Bildirim sistemi aktif")
            self._test_connection()
        else:
            print("[TELEGRAM] Kapali")

    def _test_connection(self):
        try:
            r = requests.get(f"{self.base_url}/getMe", timeout=10)
            if r.json().get('ok'):
                print(f"[TELEGRAM] Bot baglandi")
                self.send_message("🚀 *Atlas AI v2.1*\nTrading motoru baslatildi!")
        except Exception as e:
            print(f"[TELEGRAM] Baglanti hatasi: {e}")
            self.enabled = False

    def send_message(self, text: str) -> bool:
        if not self.enabled:
            return False
        try:
            url = f"{self.base_url}/sendMessage"
            payload = {'chat_id': self.chat_id, 'text': text, 'parse_mode': 'Markdown'}
            r = requests.post(url, json=payload, timeout=10)
            return r.json().get('ok', False)
        except Exception as e:
            print(f"[TELEGRAM] Hata: {e}")
            return False

    def trade_open(self, symbol: str, direction: str, price: float, size: float, confidence: float):
        emoji = "🟢" if direction == "LONG" else "🔴"
        self.send_message(
            f"{emoji} *POZISYON ACILDI*\n\n"
            f"📊 `{symbol}` | {direction}\n"
            f"💰 `${price:,.2f}` | 📏 `${size:,.2f}`\n"
            f"🎯 Guven: `{confidence:.2f}`\n"
            f"⏰ {datetime.now().strftime('%H:%M:%S')}"
        )

    def trade_close(self, symbol: str, pnl_usd: float, pnl_pct: float, reason: str):
        emoji = "✅" if pnl_usd > 0 else "❌"
        self.send_message(
            f"{emoji} *POZISYON KAPANDI*\n\n"
            f"📊 `{symbol}`\n"
            f"💵 `${pnl_usd:+.2f}` *(%{pnl_pct:+.2f})*\n"
            f"📋 `{reason}`\n"
            f"⏰ {datetime.now().strftime('%H:%M:%S')}"
        )

    def kill_switch_alert(self, reason: str, loss: float):
        self.send_message(
            f"🚨🚨🚨 *KILL SWITCH AKTIF* 🚨🚨🚨\n\n"
            f"💥 `{reason}`\n"
            f"📉 Zarar: `${loss:,.2f}`\n\n"
            f"⚠️ *Tum islemler DURDURULDU!*"
        )

    def daily_summary(self, equity: float, pnl: float, win_rate: float, trades: int):
        emoji = "📈" if pnl >= 0 else "📉"
        self.send_message(
            f"{emoji} *GUNLUK OZET*\n\n"
            f"💰 `${equity:,.2f}` | 📊 `${pnl:+.2f}`\n"
            f"🏆 `%{win_rate}` | 📝 `{trades}` trades"
        )


# =============================================================================
# KILL SWITCH
# =============================================================================

class KillSwitch:
    def __init__(self, max_daily_loss_pct: float = 5.0, max_drawdown_pct: float = 10.0, notifier=None):
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_drawdown_pct = max_drawdown_pct
        self.notifier = notifier
        self.trading_enabled = True
        self.daily_start_equity = 0
        self.peak_equity = 0
        self.last_reset = datetime.now().date()

    def reset_daily(self, equity: float):
        today = datetime.now().date()
        if today != self.last_reset:
            self.daily_start_equity = equity
            self.peak_equity = equity
            self.last_reset = today
            self.trading_enabled = True
            print("[KILL] Yeni gun basladi")

    def check(self, equity: float) -> bool:
        if not self.trading_enabled:
            return False

        self.reset_daily(equity)
        if equity > self.peak_equity:
            self.peak_equity = equity

        # Gunluk zarar
        if self.daily_start_equity > 0:
            daily_pnl = equity - self.daily_start_equity
            loss_pct = abs(min(0, daily_pnl)) / self.daily_start_equity * 100
            if daily_pnl < 0 and loss_pct >= self.max_daily_loss_pct:
                self.trading_enabled = False
                print(f"🚨 KILL SWITCH: Gunluk zarar %{loss_pct:.2f}")
                if self.notifier:
                    self.notifier.kill_switch_alert(f"Gunluk zarar %{loss_pct:.2f}", daily_pnl)
                return False

        # Drawdown
        if self.peak_equity > 0:
            drawdown = (self.peak_equity - equity) / self.peak_equity * 100
            if drawdown >= self.max_drawdown_pct:
                self.trading_enabled = False
                print(f"🚨 KILL SWITCH: Drawdown %{drawdown:.2f}")
                if self.notifier:
                    self.notifier.kill_switch_alert(f"Drawdown %{drawdown:.2f}", equity - self.peak_equity)
                return False

        return True


# =============================================================================
# ENTEGRE RISK YONETICISI
# =============================================================================

class IntegratedRiskManager:
    def __init__(self, config=None):
        self.config = config or {}
        self.notifier = TelegramNotifier()
        self.kill_switch = KillSwitch(
            max_daily_loss_pct=self.config.get('max_daily_loss_pct', 5.0),
            max_drawdown_pct=self.config.get('max_drawdown_pct', 10.0),
            notifier=self.notifier
        )
        self.max_positions = self.config.get('max_positions', 3)
        self.max_size_pct = self.config.get('max_position_size_pct', 15.0)
        self.min_confidence = self.config.get('min_confidence', 0.45)
        print("[RISK] Entegre Risk Yoneticisi aktif")

    def pre_trade_check(self, symbol, direction, size_pct, confidence, portfolio):
        if not self.kill_switch.check(portfolio.get('equity', 0)):
            return {'allowed': False, 'reason': 'KILL_SWITCH'}
        if portfolio.get('open_positions', 0) >= self.max_positions:
            return {'allowed': False, 'reason': 'MAX_POSITIONS'}
        if size_pct > self.max_size_pct:
            return {'allowed': False, 'reason': 'MAX_SIZE'}
        if confidence < self.min_confidence:
            return {'allowed': False, 'reason': 'LOW_CONFIDENCE'}
        return {'allowed': True, 'reason': 'PASS'}

    def post_trade(self, trade_result, portfolio):
        self.kill_switch.check(portfolio.get('equity', 0))
        if trade_result.get('action') == 'open':
            self.notifier.trade_open(
                trade_result.get('symbol'), trade_result.get('direction'),
                trade_result.get('price', 0), trade_result.get('size', 0),
                trade_result.get('confidence', 0)
            )
        elif trade_result.get('action') == 'close':
            self.notifier.trade_close(
                trade_result.get('symbol'),
                trade_result.get('pnl_usd', 0), trade_result.get('pnl_pct', 0),
                trade_result.get('reason', '')
            )


# =============================================================================
# TEST
# =============================================================================

if __name__ == "__main__":
    print("="*60)
    print("ATLAS TELEGRAM + KILL SWITCH TEST")
    print("="*60)

    risk = IntegratedRiskManager()

    # Test bildirim
    print("\n[Test] Bildirim testi...")
    risk.notifier.send_message("🚀 *Atlas AI Test*\n\nEntegrasyon basarili!")

    # Test pre-trade
    print("\n[Test] Pre-trade check...")
    portfolio = {'equity': 10000, 'open_positions': 0}
    result = risk.pre_trade_check('BTCUSDT', 'LONG', 10, 0.6, portfolio)
    print(f"Sonuc: {result}")

    # Test kill switch
    print("\n[Test] Kill switch...")
    risk.kill_switch.daily_start_equity = 10000
    risk.kill_switch.peak_equity = 10000
    print(f"Equity $9500: {'AKTIF' if risk.kill_switch.check(9500) else 'DURDURULDU'}")
    print(f"Equity $9400: {'AKTIF' if risk.kill_switch.check(9400) else 'DURDURULDU'}")

    print("\n" + "="*60)
    print("TEST TAMAMLANDI")
    print("="*60)