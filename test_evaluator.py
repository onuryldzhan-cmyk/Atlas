from assistant.evaluator.performance_evaluator import PerformanceEvaluator



engine = PerformanceEvaluator()



result = engine.evaluate(
    60,
    75
)



print(result)