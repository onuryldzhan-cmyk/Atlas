"""
============================================================
ATLAS EXECUTION CONTROLLER v3.0
============================================================

Institutional Execution Orchestrator


Responsibilities
----------------

- Execute trading requests
- Risk validation
- Capital validation
- Portfolio synchronization
- Execution tracking
- Event generation
- Learning integration
- State persistence


Architecture


                Atlas Brain

                    |

                    v


          Execution Controller


          /          |          \


         v           v           v


    Risk Gate   Capital     Portfolio
                Manager     Manager


                    |

                    v


          Paper Execution Engine


                    |

                    v


              Learning Layer


============================================================
"""


from __future__ import annotations


import logging


from datetime import datetime, UTC


logger = logging.getLogger(
    "AtlasAI.ExecutionController"
)



class ExecutionController:


    VERSION = "3.0"


    NAME = "ExecutionController"



    def __init__(

        self,

        execution_engine,

        risk_engine=None,

        capital_manager=None,

        portfolio_manager=None,

        event_bus=None,

        learning_engine=None,

    ):


        self.execution_engine = (
            execution_engine
        )


        self.risk_engine = (
            risk_engine
        )


        self.capital_manager = (
            capital_manager
        )


        self.portfolio_manager = (
            portfolio_manager
        )


        self.event_bus = (
            event_bus
        )


        self.learning_engine = (
            learning_engine
        )



        self.executions = 0


        self.rejected = 0


        self.errors = 0



        self.history = []



        self.started = datetime.now(
            UTC
        ).isoformat()



        logger.info(
            "ExecutionController v3.0 initialized"
        )



    # =====================================================
    # TIME
    # =====================================================


    def now(self):

        return datetime.now(
            UTC
        ).isoformat()
    # =====================================================
    # RISK VALIDATION
    # =====================================================


    def check_risk(

        self,

        request,

    ):


        if self.risk_engine is None:

            return True, "NO_RISK_ENGINE"



        try:


            result = self.risk_engine.check_request(

                request

            )


            return result



        except Exception as e:


            logger.exception(

                "Risk validation failed"

            )


            self.errors += 1


            return False, "RISK_ENGINE_ERROR"



    # =====================================================
    # CAPITAL VALIDATION
    # =====================================================


    def check_capital(

        self,

        request,

    ):


        if self.capital_manager is None:

            return True, "NO_CAPITAL_MANAGER"



        try:


            allowed = self.capital_manager.can_execute(

                request

            )



            if allowed:

                return True, "CAPITAL_APPROVED"



            return False, "CAPITAL_REJECTED"



        except Exception as e:


            logger.exception(

                "Capital validation failed"

            )


            self.errors += 1


            return False, "CAPITAL_ERROR"



    # =====================================================
    # PORTFOLIO VALIDATION
    # =====================================================


    def check_portfolio(

        self,

        request,

    ):


        if self.portfolio_manager is None:

            return True, "NO_PORTFOLIO_MANAGER"



        try:


            status = self.portfolio_manager.status()



            positions = status.get(

                "positions",

                0

            )



            if positions >= 10:


                return False, "MAX_POSITIONS_REACHED"



            return True, "PORTFOLIO_APPROVED"



        except Exception as e:


            logger.exception(

                "Portfolio validation failed"

            )


            self.errors += 1


            return False, "PORTFOLIO_ERROR"



    # =====================================================
    # VALIDATION PIPELINE
    # =====================================================


    def validate_request(

        self,

        request,

    ):


        checks = [

            self.check_risk(request),

            self.check_capital(request),

            self.check_portfolio(request),

        ]



        for ok, message in checks:


            if not ok:


                return False, message



        return True, "APPROVED"
    # =====================================================
    # MAIN EXECUTION PIPELINE
    # =====================================================


    def execute(

        self,

        request,

    ):


        # -------------------------------------------------
        # VALIDATION
        # -------------------------------------------------


        approved, reason = self.validate_request(

            request

        )


        if not approved:


            self.rejected += 1


            return self.rejected_response(

                request,

                reason

            )



        # -------------------------------------------------
        # EXECUTION ENGINE
        # -------------------------------------------------


        try:


            result = self.execution_engine.execute(

                request

            )


        except Exception as e:


            logger.exception(

                "Execution engine failure"

            )


            self.errors += 1


            return {


                "success":

                    False,


                "error":

                    str(e)

            }



        # -------------------------------------------------
        # POST EXECUTION PROCESS
        # -------------------------------------------------


        if result.success:


            self.sync_components(

                request,

                result

            )



        else:


            self.rejected += 1



        # -------------------------------------------------
        # STATISTICS
        # -------------------------------------------------


        self.executions += 1



        record = {


            "timestamp":

                self.now(),


            "symbol":

                request.symbol,


            "action":

                request.action,


            "status":

                result.status,


            "success":

                result.success,


            "execution_id":

                result.execution_id,


        }



        self.history.append(

            record

        )



        # -------------------------------------------------
        # EVENT + LEARNING
        # -------------------------------------------------


        event = self.create_event(

            request,

            result

        )


        learning = self.create_learning_record(

            request,

            result

        )



        self.publish_event(

            event

        )



        self.learn(

            learning

        )



        return {


            "result":

                result,


            "event":

                event,


            "learning":

                learning

        }



    # =====================================================
    # COMPONENT SYNCHRONIZATION
    # =====================================================


    def sync_components(

        self,

        request,

        result,

    ):


        action = request.action.upper()



        # -------------------------------
        # CAPITAL
        # -------------------------------


        if self.capital_manager:


            try:


                if action == "BUY":


                    self.capital_manager.register_position(

                        request

                    )


                elif action == "SELL":


                    self.capital_manager.close_position(

                        request.symbol

                    )


            except Exception as e:


                logger.error(

                    f"Capital sync error: {e}"

                )



        # -------------------------------
        # PORTFOLIO
        # -------------------------------


        if self.portfolio_manager:


            try:


                if action == "BUY":


                    self.portfolio_manager.open_position(

                        symbol=request.symbol,


                        amount=request.amount,


                        price=request.price,


                        risk=request.risk,


                        strategy=request.strategy,


                        confidence=request.confidence

                    )



                elif action == "SELL":


                    self.portfolio_manager.close_position(

                        symbol=request.symbol,


                        exit_price=request.price

                    )


            except Exception as e:


                logger.error(

                    f"Portfolio sync error: {e}"

                )
    # =====================================================
    # REJECT RESPONSE
    # =====================================================


    def rejected_response(

        self,

        request,

        reason,

    ):


        return {


            "success":

                False,


            "symbol":

                request.symbol,


            "action":

                request.action,


            "reason":

                reason,


            "timestamp":

                self.now()

        }



    # =====================================================
    # EVENT CREATION
    # =====================================================


    def create_event(

        self,

        request,

        result,

    ):


        return {


            "event":

                "EXECUTION_RESULT",


            "timestamp":

                self.now(),


            "success":

                result.success,


            "status":

                result.status,


            "symbol":

                request.symbol,


            "action":

                request.action,


            "price":

                request.price,


            "amount":

                request.amount,


            "execution_id":

                result.execution_id,


            "position_id":

                result.position_id,


            "fee":

                result.fee,


            "pnl":

                result.pnl,

        }



    # =====================================================
    # LEARNING RECORD
    # =====================================================


    def create_learning_record(

        self,

        request,

        result,

    ):


        return {


            "symbol":

                request.symbol,


            "action":

                request.action,


            "strategy":

                request.strategy,


            "confidence":

                request.confidence,


            "risk":

                request.risk,


            "entry_price":

                request.price,


            "amount":

                request.amount,


            "pnl":

                result.pnl,


            "fee":

                result.fee,


            "success":

                result.success,


            "execution_status":

                result.status,


            "execution_id":

                result.execution_id,


            "timestamp":

                self.now()

        }



    # =====================================================
    # EVENT BUS PUBLISH
    # =====================================================


    def publish_event(

        self,

        event,

    ):


        if self.event_bus is None:

            return



        try:


            self.event_bus.publish(

                event

            )


        except Exception as e:


            logger.error(

                f"Event publish failed: {e}"

            )



    # =====================================================
    # LEARNING ENGINE UPDATE
    # =====================================================


    def learn(

        self,

        record,

    ):


        if self.learning_engine is None:

            return



        try:


            self.learning_engine.store(

                record

            )


        except Exception as e:


            logger.error(

                f"Learning update failed: {e}"

            )
    # =====================================================
    # STATUS
    # =====================================================


    def status(self):


        return {


            "version":

                self.VERSION,


            "controller":

                self.NAME,


            "executions":

                self.executions,


            "rejected":

                self.rejected,


            "errors":

                self.errors,


            "engine":

                self.execution_engine.name,


            "risk_connected":

                self.risk_engine is not None,


            "capital_connected":

                self.capital_manager is not None,


            "portfolio_connected":

                self.portfolio_manager is not None,


            "event_bus_connected":

                self.event_bus is not None,


            "learning_connected":

                self.learning_engine is not None,

        }



    # =====================================================
    # HEALTH
    # =====================================================


    def health(self):


        return {


            "healthy":

                self.errors == 0,


            "controller":

                self.NAME,


            "version":

                self.VERSION,


            "executions":

                self.executions,


            "rejected":

                self.rejected,


            "errors":

                self.errors,


            "started":

                self.started,

        }



    # =====================================================
    # DIAGNOSTICS
    # =====================================================


    def diagnostics(self):


        return {


            "controller":

                self.NAME,


            "version":

                self.VERSION,


            "statistics":{


                "executions":

                    self.executions,


                "rejected":

                    self.rejected,


                "errors":

                    self.errors,


                "history":

                    len(self.history),

            },


            "dependencies":{


                "execution_engine":

                    self.execution_engine.name,


                "risk_engine":

                    self.risk_engine is not None,


                "capital_manager":

                    self.capital_manager is not None,


                "portfolio_manager":

                    self.portfolio_manager is not None,


                "event_bus":

                    self.event_bus is not None,


                "learning_engine":

                    self.learning_engine is not None,

            }

        }



    # =====================================================
    # SNAPSHOT
    # =====================================================


    def snapshot(self):


        return {


            "version":

                self.VERSION,


            "executions":

                self.executions,


            "rejected":

                self.rejected,


            "errors":

                self.errors,


            "history":

                list(

                    self.history

                ),


            "started":

                self.started,

        }



    # =====================================================
    # EXPORT STATE
    # =====================================================


    def export_state(self):


        return self.snapshot()



    # =====================================================
    # IMPORT STATE
    # =====================================================


    def import_state(

        self,

        state: dict,

    ):


        self.executions = state.get(

            "executions",

            0

        )


        self.rejected = state.get(

            "rejected",

            0

        )


        self.errors = state.get(

            "errors",

            0

        )


        self.history = list(

            state.get(

                "history",

                []

            )

        )


        self.started = state.get(

            "started",

            self.started

        )



    # =====================================================
    # RESET
    # =====================================================


    def reset(self):


        self.executions = 0


        self.rejected = 0


        self.errors = 0


        self.history.clear()



        logger.warning(

            "ExecutionController reset"

        )



    # =====================================================
    # MAGIC METHODS
    # =====================================================


    def __repr__(self):


        return (

            f"<ExecutionController "

            f"version={self.VERSION} "

            f"executions={self.executions} "

            f"errors={self.errors}>"

        )



    def __str__(self):


        return (

            f"{self.NAME} "

            f"v{self.VERSION}"

        )