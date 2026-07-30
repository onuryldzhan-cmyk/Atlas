"""
Atlas Config Manager
Central Configuration System
"""

import json
import os


class ConfigManager:

    def __init__(self):

        self.config = {

            # ===========================
            # TRADING
            # ===========================

            "capital": 1000,

            "risk_percent": 0.02,

            "max_positions": 5,

            "timeframe": "5m",

            # ===========================
            # DECISION
            # ===========================

            "buy_threshold": 80,

            "sell_threshold": 30,

            "confidence_buy": 70,

            "confidence_sell": 70,

            # ===========================
            # SCANNER
            # ===========================

            "scan_interval": 60,

            "top_symbols": 20,

            # ===========================
            # LEARNING
            # ===========================

            "learning_enabled": True,

            "adaptive_weights": True,

            # ===========================
            # LOGGING
            # ===========================

            "debug": True,

            "save_logs": True

        }

    # ===================================

    def get(self, key, default=None):

        return self.config.get(
            key,
            default
        )

    # ===================================

    def set(self, key, value):

        self.config[key] = value

    # ===================================

    def load(self, filename):

        if not os.path.exists(filename):
            return

        with open(
            filename,
            "r",
            encoding="utf-8"
        ) as f:

            self.config.update(
                json.load(f)
            )

    # ===================================

    def save(self, filename):

        with open(
            filename,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                self.config,
                f,
                indent=4,
                ensure_ascii=False
            )

    # ===================================

    def all(self):

        return self.config