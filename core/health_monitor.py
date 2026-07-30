"""
Atlas AI Health Monitor v5.0

Responsibility:
- Monitor Atlas system health
- Detect degraded services
- Provide diagnostics

HealthMonitor does NOT:
- Fix business logic
- Trade
- Analyze markets
"""


from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Any
import logging



logger = logging.getLogger(
    "AtlasAI.Health"
)



class HealthMonitor:
    """
    System health observer.
    """


    def __init__(
        self,
        runtime=None,
        container=None,
        scheduler=None
    ):

        self.runtime = runtime

        self.container = container

        self.scheduler = scheduler


        self.last_check = None


        logger.info(
            "Health Monitor initialized."
        )



    def check(self) -> Dict[str, Any]:
        """
        Run complete health scan.
        """


        result = {

            "timestamp":
                datetime.now(
                    timezone.utc
                ).isoformat(),

            "healthy":
                True,

            "runtime":
                None,

            "scheduler":
                None,

            "services":
                {},

            "warnings":
                []

        }


        self.last_check = (
            datetime.now(
                timezone.utc
            )
        )


        # Runtime check

        if self.runtime:

            try:

                result["runtime"] = (
                    self.runtime.status()
                )


                if not self.runtime.health():

                    result["healthy"] = False

                    result["warnings"].append(
                        "Runtime unhealthy"
                    )


            except Exception as e:

                result["healthy"] = False

                result["warnings"].append(
                    f"Runtime check failed: {e}"
                )



        # Scheduler check

        if self.scheduler:

            try:

                result["scheduler"] = (
                    self.scheduler.status()
                )


                if not self.scheduler.running:

                    result["warnings"].append(
                        "Scheduler not running"
                    )


            except Exception as e:

                result["healthy"] = False

                result["warnings"].append(
                    f"Scheduler check failed: {e}"
                )



        # Service check

        if self.container:

            try:

                services = (
                    self.container.list_services()
                )


                for service in services:

                    result["services"][service] = (
                        "registered"
                    )


            except Exception as e:

                result["warnings"].append(
                    f"Service scan failed: {e}"
                )



        return result



    def is_healthy(self) -> bool:
        """
        Quick health status.
        """

        report = self.check()

        return report["healthy"]



    def report(self):
        """
        Human readable report.
        """

        report = self.check()


        logger.info(
            "Health Report: %s",
            report
        )


        return report