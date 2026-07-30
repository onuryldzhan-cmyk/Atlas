"""
core/loop.py - Atlas AI Main Execution Loop
The heart of Atlas AI. Orchestrates all components in a continuous loop.
"""

import os
import sys
import time
import signal
import logging
import threading
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from config.settings import (
        TRADING, RISK, SIGNAL, API, NOTIFICATION, LEARNING,
        SYSTEM, PATHS, get_config_summary
    )
except ImportError:
    # Fallback if settings not available
    TRADING = type('obj', (object,), {
        'MODE': 'SIMULATION', 'TIMEFRAME': '5m',
        'WATCHLIST': ['BTCUSDT', 'ETHUSDT', 'SOLUSDT'],
        'PAPER_BALANCE': 10000.0
    })()
    RISK = type('obj', (object,), {
        'KILL_SWITCH_ENABLED': True, 'KILL_SWITCH_THRESHOLD': 0.15,
        'MAX_DAILY_LOSS_PCT': 0.05
    })()
    SYSTEM = type('obj', (object,), {
        'DEBUG_MODE': False, 'LOG_LEVEL': 'INFO', 'VERSION': '4.3.0'
    })()


# ═══════════════════════════════════════════════════════════════════════════════
# LOGGING SETUP
# ═══════════════════════════════════════════════════════════════════════════════

def setup_logging():
    """Configure logging for Atlas AI."""
    log_dir = PROJECT_ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    
    log_file = log_dir / f"atlas_{datetime.now().strftime('%Y%m%d')}.log"
    
    level = getattr(logging, SYSTEM.LOG_LEVEL, logging.INFO)
    
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    return logging.getLogger("AtlasAI")


logger = setup_logging()


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN LOOP CLASS
# ═══════════════════════════════════════════════════════════════════════════════

class AtlasLoop:
    """
    Main execution loop for Atlas AI.
    Manages the lifecycle of all trading operations.
    """
    
    def __init__(self):
        self.running = False
        self.paused = False
        self.shutdown_requested = False
        self.iteration_count = 0
        self.start_time = None
        self.last_cycle_time = None
        
        # Component placeholders (will be initialized when available)
        self.brain = None
        self.decision_engine = None
        self.signal_fusion = None
        self.capital_manager = None
        self.order_manager = None
        self.risk_manager = None
        self.portfolio = None
        self.learning_engine = None
        
        # State tracking
        self.state = {
            "mode": TRADING.MODE,
            "balance": TRADING.PAPER_BALANCE,
            "positions": {},
            "signals": [],
            "daily_pnl": 0.0,
            "total_pnl": 0.0,
            "kill_switch_triggered": False,
            "last_update": None,
        }
        
        # Metrics
        self.metrics = {
            "cycles_completed": 0,
            "signals_generated": 0,
            "trades_executed": 0,
            "errors_encountered": 0,
            "avg_cycle_time_ms": 0.0,
        }
        
        # Callbacks
        self.on_cycle_start: List[Callable] = []
        self.on_cycle_end: List[Callable] = []
        self.on_signal: List[Callable] = []
        self.on_trade: List[Callable] = []
        self.on_error: List[Callable] = []
        
        # Register signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Handle system signals for graceful shutdown."""
        logger.info(f"📡 Signal {signum} received. Initiating graceful shutdown...")
        self.shutdown_requested = True
        self.stop()
    
    # ═══════════════════════════════════════════════════════════════════════════
    # COMPONENT REGISTRATION
    # ═══════════════════════════════════════════════════════════════════════════
    
    def register_brain(self, brain):
        """Register the AI brain component."""
        self.brain = brain
        logger.info("🧠 Brain component registered")
    
    def register_decision_engine(self, engine):
        """Register the decision engine."""
        self.decision_engine = engine
        logger.info("🎯 Decision Engine registered")
    
    def register_signal_fusion(self, fusion):
        """Register signal fusion component."""
        self.signal_fusion = fusion
        logger.info("📡 Signal Fusion registered")
    
    def register_capital_manager(self, manager):
        """Register capital manager."""
        self.capital_manager = manager
        logger.info("💰 Capital Manager registered")
    
    def register_order_manager(self, manager):
        """Register order manager."""
        self.order_manager = manager
        logger.info("📋 Order Manager registered")
    
    def register_risk_manager(self, manager):
        """Register risk manager."""
        self.risk_manager = manager
        logger.info("⚠️  Risk Manager registered")
    
    def register_portfolio(self, portfolio):
        """Register portfolio tracker."""
        self.portfolio = portfolio
        logger.info("📊 Portfolio tracker registered")
    
    def register_learning_engine(self, engine):
        """Register learning engine."""
        self.learning_engine = engine
        logger.info("🎓 Learning Engine registered")
    
    # ═══════════════════════════════════════════════════════════════════════════
    # LIFECYCLE MANAGEMENT
    # ═══════════════════════════════════════════════════════════════════════════
    
    def start(self):
        """Start the main loop."""
        if self.running:
            logger.warning("⚠️  Loop is already running!")
            return
        
        self.running = True
        self.start_time = datetime.now()
        self.shutdown_requested = False
        
        logger.info("=" * 60)
        logger.info("🚀 ATLAS AI MAIN LOOP STARTED")
        logger.info(f"   Mode: {self.state['mode']}")
        logger.info(f"   Version: {SYSTEM.VERSION}")
        logger.info(f"   Start Time: {self.start_time.isoformat()}")
        logger.info("=" * 60)
        
        self._main_loop()
    
    def stop(self):
        """Stop the main loop gracefully."""
        logger.info("🛑 Stopping Atlas AI main loop...")
        self.running = False
    
    def pause(self):
        """Pause the loop temporarily."""
        if not self.running:
            logger.warning("⚠️  Cannot pause - loop is not running")
            return
        
        self.paused = True
        logger.info("⏸️  Loop paused")
    
    def resume(self):
        """Resume the paused loop."""
        if not self.running:
            logger.warning("⚠️  Cannot resume - loop is not running")
            return
        
        self.paused = False
        logger.info("▶️  Loop resumed")
    
    def get_status(self) -> Dict:
        """Get current loop status."""
        uptime = datetime.now() - self.start_time if self.start_time else timedelta(0)
        
        return {
            "running": self.running,
            "paused": self.paused,
            "uptime_seconds": uptime.total_seconds(),
            "iteration_count": self.iteration_count,
            "mode": self.state["mode"],
            "balance": self.state["balance"],
            "daily_pnl": self.state["daily_pnl"],
            "total_pnl": self.state["total_pnl"],
            "positions_count": len(self.state["positions"]),
            "signals_count": len(self.state["signals"]),
            "kill_switch": self.state["kill_switch_triggered"],
            "metrics": self.metrics,
        }
    
    # ═══════════════════════════════════════════════════════════════════════════
    # MAIN LOOP
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _main_loop(self):
        """Core execution loop."""
        cycle_interval = self._get_cycle_interval()
        
        while self.running and not self.shutdown_requested:
            cycle_start = time.time()
            self.iteration_count += 1
            
            try:
                # Check pause
                while self.paused and self.running:
                    time.sleep(0.5)
                
                # Execute one cycle
                self._execute_cycle()
                
                # Update metrics
                cycle_time = (time.time() - cycle_start) * 1000  # ms
                self._update_cycle_metrics(cycle_time)
                
                # Sleep until next cycle
                elapsed = time.time() - cycle_start
                sleep_time = max(0, cycle_interval - elapsed)
                if sleep_time > 0 and self.running:
                    time.sleep(sleep_time)
                    
            except Exception as e:
                self.metrics["errors_encountered"] += 1
                logger.error(f"❌ Error in main loop cycle {self.iteration_count}: {e}")
                for callback in self.on_error:
                    try:
                        callback(e)
                    except:
                        pass
                
                if SYSTEM.DEBUG_MODE:
                    import traceback
                    traceback.print_exc()
                
                # Brief pause on error to prevent spam
                time.sleep(1)
        
        # Loop ended
        self._on_shutdown()
    
    def _get_cycle_interval(self) -> float:
        """Get cycle interval in seconds based on timeframe."""
        intervals = {
            "1m": 60, "5m": 300, "15m": 900,
            "1h": 3600, "4h": 14400, "1d": 86400
        }
        return intervals.get(TRADING.TIMEFRAME, 300)
    
    def _execute_cycle(self):
        """Execute one complete trading cycle."""
        self.last_cycle_time = datetime.now()
        self.state["last_update"] = self.last_cycle_time.isoformat()
        
        # Trigger cycle start callbacks
        for callback in self.on_cycle_start:
            try:
                callback(self.iteration_count)
            except Exception as e:
                logger.warning(f"Cycle start callback error: {e}")
        
        # Phase 1: Check kill switch
        if self._check_kill_switch():
            return
        
        # Phase 2: Update market data
        self._update_market_data()
        
        # Phase 3: Generate signals (if brain available)
        if self.brain:
            self._generate_signals()
        
        # Phase 4: Evaluate signals (if decision engine available)
        if self.decision_engine and self.state["signals"]:
            self._evaluate_signals()
        
        # Phase 5: Risk check
        if self.risk_manager:
            self._risk_check()
        
        # Phase 6: Execute trades (if order manager available)
        if self.order_manager and self.state.get("approved_signals"):
            self._execute_trades()
        
        # Phase 7: Update portfolio
        if self.portfolio:
            self._update_portfolio()
        
        # Phase 8: Learning (if learning engine available)
        if self.learning_engine and self.iteration_count % 10 == 0:
            self._learning_step()
        
        # Phase 9: Log cycle summary
        if self.iteration_count % 10 == 0 or SYSTEM.DEBUG_MODE:
            self._log_cycle_summary()
        
        # Trigger cycle end callbacks
        for callback in self.on_cycle_end:
            try:
                callback(self.iteration_count)
            except Exception as e:
                logger.warning(f"Cycle end callback error: {e}")
    
    # ═══════════════════════════════════════════════════════════════════════════
    # CYCLE PHASES
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _check_kill_switch(self) -> bool:
        """Check if kill switch should be triggered."""
        if not RISK.KILL_SWITCH_ENABLED:
            return False
        
        # Check daily loss
        if self.state["daily_pnl"] < -TRADING.PAPER_BALANCE * RISK.MAX_DAILY_LOSS_PCT:
            self.state["kill_switch_triggered"] = True
            logger.critical("🚨 KILL SWITCH TRIGGERED: Daily loss limit exceeded!")
            self.stop()
            return True
        
        # Check total loss
        total_loss_pct = abs(self.state["total_pnl"]) / TRADING.PAPER_BALANCE
        if total_loss_pct > RISK.KILL_SWITCH_THRESHOLD:
            self.state["kill_switch_triggered"] = True
            logger.critical("🚨 KILL SWITCH TRIGGERED: Total loss limit exceeded!")
            self.stop()
            return True
        
        return False
    
    def _update_market_data(self):
        """Fetch and update latest market data."""
        # Placeholder - will be implemented with exchange connector
        logger.debug("📊 Updating market data...")
    
    def _generate_signals(self):
        """Generate trading signals using AI brain."""
        logger.debug("🧠 Generating signals...")
        
        try:
            # Placeholder signal generation
            signals = []
            for symbol in TRADING.WATCHLIST[:3]:  # Limit for testing
                # Simulated signal
                import random
                confidence = random.uniform(0.3, 0.9)
                if confidence > SIGNAL.MIN_CONFIDENCE:
                    signal = {
                        "symbol": symbol,
                        "direction": random.choice(["BUY", "SELL"]),
                        "confidence": confidence,
                        "timestamp": datetime.now().isoformat(),
                        "source": "placeholder",
                    }
                    signals.append(signal)
            
            self.state["signals"] = signals
            self.metrics["signals_generated"] += len(signals)
            
            if signals:
                logger.info(f"📡 Generated {len(signals)} signals")
                for sig in signals:
                    logger.info(f"   {sig['symbol']} | {sig['direction']} | {sig['confidence']:.2%}")
                
                for callback in self.on_signal:
                    try:
                        callback(signals)
                    except:
                        pass
                        
        except Exception as e:
            logger.error(f"❌ Signal generation error: {e}")
    
    def _evaluate_signals(self):
        """Evaluate and filter signals through decision engine."""
        logger.debug("🎯 Evaluating signals...")
        
        approved = []
        for signal in self.state["signals"]:
            # Placeholder evaluation
            if signal["confidence"] > 0.75:
                approved.append(signal)
        
        self.state["approved_signals"] = approved
        logger.info(f"✅ Approved {len(approved)}/{len(self.state['signals'])} signals")
    
    def _risk_check(self):
        """Perform risk checks before trading."""
        logger.debug("⚠️  Running risk checks...")
        
        # Check max positions
        if len(self.state["positions"]) >= RISK.MAX_POSITIONS:
            logger.warning("⚠️  Max positions reached. Blocking new trades.")
            self.state["approved_signals"] = []
    
    def _execute_trades(self):
        """Execute approved trades."""
        logger.info(f"💰 Executing {len(self.state['approved_signals'])} trades...")
        
        for signal in self.state["approved_signals"]:
            # Placeholder trade execution
            trade = {
                "id": f"TRADE_{self.iteration_count}_{int(time.time())}",
                "symbol": signal["symbol"],
                "side": signal["direction"],
                "size": TRADING.PAPER_BALANCE * 0.05,  # 5% per trade
                "entry_price": 0.0,  # Would be fetched from market
                "status": "PENDING",
                "timestamp": datetime.now().isoformat(),
            }
            
            self.state["positions"][trade["id"]] = trade
            self.metrics["trades_executed"] += 1
            
            logger.info(f"   📝 Trade placed: {trade['symbol']} {trade['side']}")
            
            for callback in self.on_trade:
                try:
                    callback(trade)
                except:
                    pass
        
        self.state["approved_signals"] = []
    
    def _update_portfolio(self):
        """Update portfolio state."""
        logger.debug("📊 Updating portfolio...")
    
    def _learning_step(self):
        """Run one learning step."""
        logger.debug("🎓 Running learning step...")
    
    def _update_cycle_metrics(self, cycle_time_ms: float):
        """Update cycle performance metrics."""
        self.metrics["cycles_completed"] = self.iteration_count
        
        # Running average
        n = self.metrics["cycles_completed"]
        old_avg = self.metrics["avg_cycle_time_ms"]
        self.metrics["avg_cycle_time_ms"] = (old_avg * (n - 1) + cycle_time_ms) / n
    
    def _log_cycle_summary(self):
        """Log periodic cycle summary."""
        logger.info("-" * 40)
        logger.info(f"📊 Cycle {self.iteration_count} Summary:")
        logger.info(f"   Signals: {len(self.state['signals'])}")
        logger.info(f"   Positions: {len(self.state['positions'])}")
        logger.info(f"   Daily P&L: ${self.state['daily_pnl']:.2f}")
        logger.info(f"   Total P&L: ${self.state['total_pnl']:.2f}")
        logger.info(f"   Avg Cycle Time: {self.metrics['avg_cycle_time_ms']:.2f}ms")
        logger.info("-" * 40)
    
    def _on_shutdown(self):
        """Cleanup on loop shutdown."""
        end_time = datetime.now()
        uptime = end_time - self.start_time if self.start_time else timedelta(0)
        
        logger.info("=" * 60)
        logger.info("🛑 ATLAS AI MAIN LOOP STOPPED")
        logger.info(f"   Uptime: {uptime}")
        logger.info(f"   Total Cycles: {self.iteration_count}")
        logger.info(f"   Signals Generated: {self.metrics['signals_generated']}")
        logger.info(f"   Trades Executed: {self.metrics['trades_executed']}")
        logger.info(f"   Errors: {self.metrics['errors_encountered']}")
        logger.info("=" * 60)
        
        # Save final state
        self._save_state()
    
    def _save_state(self):
        """Save current state to file."""
        try:
            import json
            state_file = PROJECT_ROOT / "logs" / "last_state.json"
            state_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(state_file, "w", encoding="utf-8") as f:
                json.dump({
                    "timestamp": datetime.now().isoformat(),
                    "state": self.state,
                    "metrics": self.metrics,
                }, f, indent=2, default=str)
            
            logger.info(f"💾 State saved to {state_file}")
        except Exception as e:
            logger.error(f"❌ Failed to save state: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# STANDALONE TEST
# ═══════════════════════════════════════════════════════════════════════════════

def demo_callback(cycle_num):
    """Demo callback for testing."""
    pass  # Silent for clean output

def demo_signal_callback(signals):
    """Demo signal callback."""
    pass

def demo_trade_callback(trade):
    """Demo trade callback."""
    pass

if __name__ == "__main__":
    print("🚀 Atlas AI Main Loop - Test Mode")
    print("=" * 50)
    
    loop = AtlasLoop()
    
    # Register callbacks
    loop.on_cycle_start.append(demo_callback)
    loop.on_cycle_end.append(demo_callback)
    loop.on_signal.append(demo_signal_callback)
    loop.on_trade.append(demo_trade_callback)
    
    print(f"\n📋 Initial Status:")
    for k, v in loop.get_status().items():
        print(f"   {k}: {v}")
    
    print(f"\n▶️  Starting loop for 3 cycles (simulation mode)...")
    print("-" * 50)
    
    # Run for a few cycles then stop
    def auto_stop():
        time.sleep(0.5)  # Let it run briefly
        loop.stop()
    
    stop_thread = threading.Thread(target=auto_stop, daemon=True)
    stop_thread.start()
    
    loop.start()
    
    print(f"\n📋 Final Status:")
    for k, v in loop.get_status().items():
        print(f"   {k}: {v}")
    
    print("\n✅ Main Loop test completed!")
