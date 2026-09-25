"""
============================================================
ATLAS PAPER TRADER v11.0
============================================================

Professional Paper Execution Engine


Responsibilities
----------------

- Simulated BUY execution
- Simulated SELL execution
- Position management
- Balance tracking
- Trade history
- PnL calculation
- ExecutionManager integration
- Persistent storage


Pipeline


Decision

   |

ExecutionManager

   |

PaperTrader

   |

Portfolio


============================================================
"""


from __future__ import annotations


import json
import os
import logging


from datetime import datetime, UTC



logger = logging.getLogger(
    "AtlasAI.PaperTrader"
)





class PaperTrader:


    VERSION = "11.0"



    def __init__(

        self,

        capital=None,

        database=None,

        filename="paper_trades.json"

    ):


        self.capital = capital

        self.database = database

        self.filename = filename


        self.balance = 10000.0


        self.positions = {}

        self.history = []

        # OK / MISSING / CORRUPT / UNREADABLE, set by load().
        self.load_status = None


        self.load()



        logger.info(
            "Paper Trader v%s initialized",
            self.VERSION
        )






    # ==================================================
    # EXECUTION ENTRY
    # ==================================================


    def execute(

        self,

        request

    ):


        symbol = request.get(
            "symbol"
        )


        action = request.get(
            "action"
        )


        price = request.get(
            "price",
            0
        )



        if not symbol or not price:


            return {

                "status":
                "FAILED",

                "reason":
                "Invalid request"

            }




        if action == "BUY":


            return self.open_trade(

                symbol,

                price

            )



        elif action == "SELL":


            return self.close_trade(

                symbol

            )



        return {


            "status":
            "IGNORED",

            "reason":
            "Unsupported action"


        }







    # ==================================================
    # OPEN POSITION
    # ==================================================


    def open_trade(

        self,

        symbol,

        price,

        amount=100

    ):



        if symbol in self.positions:


            return {

                "status":
                "FAILED",

                "reason":
                "Position exists"

            }



        position = {


            "symbol":

            symbol,


            "entry_price":

            price,


            "current_price":

            price,


            "amount":

            amount,


            "opened":

            datetime.now(
                UTC
            ).isoformat()


        }



        self.positions[symbol]=position



        self.history.append({

            "type":
            "BUY",

            "symbol":
            symbol,

            "price":
            price,

            "time":
            datetime.now(
                UTC
            ).isoformat()

        })



        self.save()



        logger.info(

            "[PAPER BUY] %s %.4f",

            symbol,

            price

        )



        return {


            "status":
            "OPENED",


            "position":
            position


        }







    # ==================================================
    # CLOSE POSITION
    # ==================================================


    def close_trade(

        self,

        symbol

    ):


        if symbol not in self.positions:


            return {

                "status":
                "FAILED",

                "reason":
                "No position"

            }



        position=self.positions.pop(
            symbol
        )



        profit=self.calculate_profit(
            position
        )



        self.history.append({

            "type":
            "SELL",

            "symbol":
            symbol,

            "profit":
            profit,

            "time":
            datetime.now(
                UTC
            ).isoformat()

        })


        self.save()



        logger.info(

            "[PAPER SELL] %s profit=%s",

            symbol,

            profit

        )



        return {


            "status":
            "CLOSED",

            "profit":
            profit


        }







    # ==================================================
    # PRICE UPDATE
    # ==================================================


    def update_price(

        self,

        symbol,

        price

    ):


        if symbol in self.positions:


            self.positions[symbol][

                "current_price"

            ] = price



            self.save()







    # ==================================================
    # PROFIT
    # ==================================================


    def calculate_profit(

        self,

        position

    ):


        return round(

            position["current_price"]

            -

            position["entry_price"],

            4

        )







    # ==================================================
    # DURABLE PROJECTION
    # ==================================================


    def apply_projection(

        self,

        *,

        symbol,

        position,

        history_entry=None,

    ):

        """Overwrite one symbol's record from the durable authority.

        ExecutionPortfolioFoundation owns position truth; this book only
        mirrors it, so nothing here is derived, averaged, or accumulated.
        ``position`` is that authority's own snapshot record, or ``None``
        when the symbol is flat, in which case the symbol is dropped.

        Schema: the authority's decimal-string fields are stored verbatim
        under their own names, plus the legacy float ``entry_price`` /
        ``current_price`` display pair that ``calculate_profit()`` and
        older readers of this file still expect. The legacy ``amount``
        field is deliberately NOT written: it held quote capital, while
        the authority records ``base_quantity`` in base units, and a
        mirrored record must never blur the two.
        """

        if position is None:

            self.positions.pop(
                symbol,
                None,
            )

        else:

            self.positions[symbol] = (
                self._projected_record(
                    symbol=symbol,
                    position=position,
                )
            )

        if history_entry is not None:

            self.history.append(
                history_entry
            )

        self.save()



    @staticmethod
    def _projected_record(

        *,

        symbol,

        position,

    ):

        """Shape one durable position record for this book."""

        def _text(name):

            value = position.get(
                name
            )

            return None if value is None else str(
                value
            )


        def _display(name):

            try:
                return float(
                    position.get(
                        name
                    )
                )

            except (TypeError, ValueError):
                return None


        return {

            "symbol":
            symbol,

            "position_id":
            _text("position_id"),

            "base_quantity":
            _text("base_quantity"),

            "average_entry_price":
            _text("average_entry_price"),

            "mark_price":
            _text("mark_price"),

            "cost_quote":
            _text("cost_quote"),

            "entry_fees":
            _text("entry_fees"),

            "version":
            position.get("version"),

            "opened_at":
            _text("opened_at"),

            # Legacy display pair, derived from the authority's own
            # figures rather than tracked independently.
            "entry_price":
            _display("average_entry_price"),

            "current_price":
            _display("mark_price"),

            "mirrored_from":
            "execution_financial_state",

        }



    def reproject_all(

        self,

        positions,

    ):

        """Replace every position with the durable authority's snapshot.

        Called once at startup, after ExecutionPortfolioFoundation is known
        ready, so a symbol that never trades again cannot keep a stale or
        missing record indefinitely. ``positions`` is that authority's
        ``snapshot()["positions"]`` mapping. History is left untouched: it
        is a log of past projections, not a position source.

        Returns the sorted symbols whose mirrored record differed from the
        authority before re-projection - the divergence this call repaired.
        """

        projected = {

            symbol: self._projected_record(
                symbol=symbol,
                position=position,
            )

            for symbol, position in positions.items()

        }

        diverged = sorted(

            symbol

            for symbol in set(projected) | set(self.positions)

            if self.positions.get(symbol) != projected.get(symbol)

        )

        self.positions = projected

        self.save()

        return diverged



    # ==================================================
    # STORAGE
    # ==================================================


    def load(self):

        """Load the mirrored book, failing loud rather than silently empty.

        The book is a passive mirror of ExecutionPortfolioFoundation and
        nothing in the runtime reads it, so a bad file must not halt Atlas.
        It must not pass for an empty book either: the outcome is recorded
        in ``load_status`` (``UNREADABLE`` for an I/O failure, ``CORRUPT``
        for content that does not parse or has the wrong shape), the bad
        file is moved aside so the next save cannot erase its history, and
        the book starts empty until the startup re-projection rebuilds its
        positions from the durable authority.
        """

        if not os.path.exists(
            self.filename
        ):

            self.load_status = "MISSING"

            return


        try:

            with open(

                self.filename,

                "r",

                encoding="utf-8",

            ) as f:

                data = json.load(f)

        except OSError:

            self._load_failed("UNREADABLE")

            return

        except ValueError:

            self._load_failed("CORRUPT")

            return


        positions = (
            data.get("positions")
            if isinstance(data, dict)
            else None
        )

        history = (
            data.get("history", [])
            if isinstance(data, dict)
            else None
        )

        if (
            not isinstance(positions, dict)
            or not isinstance(history, list)
        ):

            self._load_failed("CORRUPT")

            return


        self.positions = positions

        self.history = history

        self.load_status = "OK"



    def _load_failed(self, status):

        """Record a failed load and preserve the bad file for the operator."""

        self.positions = {}

        self.history = []

        self.load_status = status

        quarantine = "%s.%s.%s" % (
            self.filename,
            status.lower(),
            datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ"),
        )

        try:

            os.replace(
                self.filename,
                quarantine,
            )

        except OSError:

            quarantine = None

        logger.error(
            "PAPER BOOK MIRROR %s: %s could not be loaded; preserved_as=%s. "
            "The book starts empty and is re-projected from durable "
            "financial state at startup. Prior mirror history is not "
            "carried forward. Durable financial state is unaffected.",
            status,
            self.filename,
            quarantine,
            exc_info=True,
        )



    def save(self):

        """Persist the book atomically: temp file, fsync, then replace.

        Mirrors FinancialStateStore.save, so a crash mid-write leaves either
        the previous complete file or the new complete file, never a torn
        one.
        """

        # The book location is chosen by the composition root, so its
        # directory is not guaranteed to exist yet. The other durable
        # execution stores create their own parent the same way.
        directory = os.path.dirname(
            self.filename
        )

        if directory:

            os.makedirs(
                directory,
                exist_ok=True,
            )


        temp = self.filename + ".tmp"

        with open(

            temp,

            "w",

            encoding="utf-8",

            newline="\n",

        ) as f:


            json.dump(

                {

                "positions":
                self.positions,


                "history":
                self.history


                },

                f,

                indent=4

            )

            f.flush()

            os.fsync(
                f.fileno()
            )


        os.replace(
            temp,
            self.filename,
        )







    # ==================================================
    # STATUS
    # ==================================================


    def status(self):


        return {


            "version":
            self.VERSION,


            "balance":
            self.balance,


            "positions":
            len(
                self.positions
            ),


            "trades":
            len(
                self.history
            ),


            "load_status":
            self.load_status

        }