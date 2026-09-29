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
        memory_core=None
    ):


        self.memory = memory_core



        _log.debug(
            "[MEMORY] Memory Adapter v10.0 initialized"
        )






    # =====================================================
    # MEMORY ANALYSIS
    # =====================================================


    def analyze(self):



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