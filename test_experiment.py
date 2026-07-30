from assistant.experiment.experiment_engine import ExperimentEngine


engine = ExperimentEngine(".")


result = engine.create_experiment(

    "MarketLoop mimarisini iyileştir"

)


print(result)