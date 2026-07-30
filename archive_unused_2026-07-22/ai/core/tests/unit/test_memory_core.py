"""
Unit Tests for Atlas Memory Core
"""

import sys
import os
import json
import tempfile
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from atlas_memory_core import AtlasMemoryCore, TradeOutcome


class TestAtlasMemoryCore(unittest.TestCase):
    """Test cases for AtlasMemoryCore"""

    def setUp(self):
        self.memory = AtlasMemoryCore()

    def test_initialization(self):
        """Test memory core initializes correctly"""
        self.assertIsNotNone(self.memory)
        self.assertIsInstance(self.memory.trades, list)
        self.assertIsInstance(self.memory.episodes, list)

    def test_record_trade(self):
        """Test recording a trade"""
        self.memory.record_trade("BTCUSDT", 65000.0, 0.1, "test_strategy")

        self.assertEqual(len(self.memory.trades), 1)
        trade = self.memory.trades[0]
        self.assertEqual(trade.symbol, "BTCUSDT")
        self.assertEqual(trade.entry_price, 65000.0)
        self.assertEqual(trade.position_size, 0.1)

    def test_update_trade_outcome(self):
        """Test updating trade outcome"""
        # First record a trade
        self.memory.record_trade("BTCUSDT", 65000.0, 0.1, "test_strategy")

        # Update outcome
        self.memory.update_trade_outcome("BTCUSDT", 70000.0, 7.69, TradeOutcome.WIN)

        # Check outcome was updated
        self.assertEqual(len(self.memory.episodes), 1)
        episode = self.memory.episodes[0]
        self.assertEqual(episode.outcome, TradeOutcome.WIN)

    def test_multiple_trades(self):
        """Test recording multiple trades"""
        symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
        for symbol in symbols:
            self.memory.record_trade(symbol, 1000.0, 0.1, "test")

        self.assertEqual(len(self.memory.trades), 3)

    def test_trade_outcome_enum(self):
        """Test TradeOutcome enum values"""
        self.assertEqual(TradeOutcome.WIN.value, "win")
        self.assertEqual(TradeOutcome.LOSS.value, "loss")
        self.assertEqual(TradeOutcome.BREAKEVEN.value, "breakeven")


class TestAtlasMemoryPersistence(unittest.TestCase):
    """Test memory persistence"""

    def setUp(self):
        self.temp_file = os.path.join(tempfile.mkdtemp(), "test_memory.json")
        self.memory = AtlasMemoryCore()

    def tearDown(self):
        import shutil
        if os.path.exists(os.path.dirname(self.temp_file)):
            shutil.rmtree(os.path.dirname(self.temp_file), ignore_errors=True)

    def test_save_and_load(self):
        """Test saving and loading memory"""
        # Record some data
        self.memory.record_trade("BTCUSDT", 65000.0, 0.1, "test_strategy")
        self.memory.update_trade_outcome("BTCUSDT", 70000.0, 7.69, TradeOutcome.WIN)

        # Save
        self.memory.save(self.temp_file)
        self.assertTrue(os.path.exists(self.temp_file))

        # Load
        new_memory = AtlasMemoryCore()
        new_memory.load(self.temp_file)

        # Verify data persisted
        self.assertEqual(len(new_memory.trades), 1)
        self.assertEqual(len(new_memory.episodes), 1)


if __name__ == "__main__":
    unittest.main()
