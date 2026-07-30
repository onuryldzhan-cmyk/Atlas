from ai.core.validation.decision_validator import DecisionValidator


from core.decision import (
    Decision,
    DecisionAction
)



validator = DecisionValidator()



d = Decision(

    action=DecisionAction.BUY,

    symbol="BTCUSDT",

    confidence=75,

    reasoning="test"

)



print(
    validator.validate(d)
)