"""
core/database.py
Atlas AI Trade Database v2
"""

import logging

import json
import os
from datetime import datetime


logger = logging.getLogger("AtlasAI.DatabaseManager")


class DatabaseManager:

    def __init__(self, file_path="data/trades.json"):


        logger.debug("DatabaseManager initialization started.")
        self.file_path = file_path
        self._ensure_file()


    def _ensure_file(self):


        logger.debug("Trade database file verification started.")
        if not os.path.exists("data"):
            os.makedirs("data")

        if not os.path.exists(self.file_path):

            with open(self.file_path, "w") as f:
                json.dump([], f, indent=2)



    def save_trade(self, trade_data: dict):


        logger.info("Trade persistence requested.")
        trades = self.get_trades()

        trade_data["id"] = len(trades) + 1
        trade_data["created"] = datetime.now().isoformat()

        trades.append(trade_data)

        self._write(trades)



    def get_trades(self):


        logger.debug("Trade database read requested.")
        with open(self.file_path, "r") as f:
            return json.load(f)



    def update_trade(self, trade_id, updates):


        logger.info("Trade update requested.")
        trades = self.get_trades()

        for trade in trades:

            if trade.get("id") == trade_id:

                trade.update(updates)
                break


        self._write(trades)



    def get_open_trades(self):


        logger.debug("Open-trade query requested.")
        trades = self.get_trades()

        return [
            t for t in trades
            if t.get("status") == "OPEN"
        ]



    def _write(self, data):


        logger.debug("Trade database write requested.")
        with open(self.file_path, "w") as f:
            json.dump(
                data,
                f,
                indent=2
            )



    def save_api_keys(self, user_id, api_key, secret):

        pass