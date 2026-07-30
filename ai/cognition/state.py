"""
Atlas AI Cognitive State

Stores temporary brain state information.
"""


from datetime import datetime, timezone



class BrainState:
    """
    Runtime state container
    for Atlas cognition layer.
    """


    def __init__(self):

        self.last_input = None

        self.last_analysis = None

        self.last_decision = None

        self.last_update = None



    def update_time(self):

        self.last_update = datetime.now(
            timezone.utc
        )