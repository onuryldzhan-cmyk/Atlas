from assistant.evolution.evolution_engine import EvolutionEngine


engine = EvolutionEngine(".")


result = engine.register_improvement(

    {
        "type":"refactor",
        "target":"core.market_loop",
        "goal":"pipeline iyileştirme"
    }

)


print(result)


print(
    engine.get_progress()
)