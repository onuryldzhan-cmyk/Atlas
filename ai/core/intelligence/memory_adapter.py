"""
Atlas AI Memory Adapter v10.0

Memory intelligence bridge.

Responsibilities:

- Connect Atlas Brain with memory system
- Read historical performance
- Calculate learning influence
- Provide feedback signals

"""


from __future__ import annotations

import logging as _logging

# Diagnostics go to the log, not stdout (registry v5.50: 20 coins x every cycle flooded the console).
_log = _logging.getLogger(__name__)





class MemoryAdapter:



    VERSION = "10.0"





    def __init__(
        self,
        memory_core=None,
        closed_trades_reader=None
    ):


        self.memory = memory_core
        # BRAIN-MEM-001: a callable returning the durable closed-position
        # archive records (read-only). None keeps the historical behaviour.
        self.closed_trades_reader = closed_trades_reader
        # Last readable evidence per coin (BRAIN-MEM-001 M-1): losing access to
        # the archive must never make Atlas less cautious than it last was.
        self._last_good: dict = {}



        _log.debug(
            "[MEMORY] Memory Adapter v10.0 initialized"
        )






    # =====================================================
    # MEMORY ANALYSIS
    # =====================================================


    def analyze(self, symbol=None):
        if self.closed_trades_reader is not None and symbol:
            return self._trade_book(symbol)



        if not self.memory:



            return {


                "trades":

                    0,


                "win_rate":

                    0,


                "effect":

                    0


            }







        try:



            trades = len(

                self.memory.trades

            )



            win_rate = (

                self.memory
                .get_win_rate()

            )




        except Exception as e:



            _log.debug(

                f"[MEMORY ERROR] {e}"

            )



            trades = 0

            win_rate = 0







        effect = self.calculate_effect(

            trades,

            win_rate

        )







        _log.debug(

            f"[MEMORY] "
            f"trades={trades} "
            f"winrate={win_rate}"

        )






        return {



            "trades":

                trades,



            "win_rate":

                win_rate,



            "effect":

                effect

        }







    # =====================================================
    # LEARNING IMPACT
    # =====================================================



    def calculate_effect(
        self,
        trades,
        win_rate
    ):



        """
        Historical performance adjustment.

        Positive:
            good historical behavior

        Negative:
            poor historical behavior

        """



        if trades < 10:


            return 0






        if win_rate >= 60:



            return 0.05






        if win_rate < 40:



            return -0.05






        return 0

    def _trade_book(self, symbol):
        """Per-coin evidence from Atlas's own closed trades.

        Unreadable archive or a malformed record for this coin (M-1, NB-4):
        the last readable evidence for the coin is reused; with none, BUYs
        get the losing-book caution (fail closed). Removing evidence can
        therefore never raise confidence.
        """

        from ai.core.intelligence.trade_evidence import LOSING_EFFECT, symbol_evidence

        try:
            records = list(self.closed_trades_reader())
            evidence = symbol_evidence(records, symbol)
            failure = None if evidence.get("available", True) else evidence.get("reason", "MALFORMED_ARCHIVE_RECORD")
        except Exception as exc:
            _log.warning("closed-trade archive unreadable for memory: %s", type(exc).__name__)
            failure = "ARCHIVE_UNREADABLE"
        if failure is None:
            evidence["source"] = "closed_position_archive"
            evidence.setdefault("trades", 0)
            self._last_good[symbol] = dict(evidence)
            return evidence
        last = self._last_good.get(symbol)
        if last is not None:
            return {**last, "source": "last_good_closed_position_archive", "degraded_reason": failure}
        return {"source": "closed_position_archive", "symbol": symbol, "available": False,
                "reason": failure + "_FAIL_CLOSED", "trades": 0, "effect": LOSING_EFFECT}
