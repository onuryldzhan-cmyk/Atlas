"""
core/position_monitor.py
Atlas AI Automatic Position Monitor v1
"""

import time
import threading


class PositionMonitor:


    def __init__(self, trader, interval=5):

        self.trader = trader
        self.interval = interval
        self.running = False



    def start(self):

        if self.running:
            return


        self.running = True


        thread = threading.Thread(
            target=self._loop,
            daemon=True
        )


        thread.start()


        print(
            "[MONITOR ENGINE] Aktif"
        )



    def stop(self):

        self.running = False



    def _loop(self):

        while self.running:

            try:

                self.trader.check_positions()


            except Exception as e:

                print(
                    "[MONITOR ERROR]",
                    e
                )


            time.sleep(
                self.interval
            )