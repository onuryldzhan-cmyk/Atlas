from core.atlas_brain import AtlasBrain


print("==============================")
print(" ATLAS EVOLUTION ENGINE TEST ")
print("==============================")


brain = AtlasBrain()


print("\n===== CREATE EXPERIMENT =====")


experiment = brain.experiment_manager.create_experiment(

    module="confidence_engine",

    change="Confidence threshold 70 -> 65",

    reason="Başarı oranını artırmak",

    before={
        "confidence": 70
    },

    after={
        "confidence": 65
    }

)


print(experiment)



print("\n===== EVOLUTION TEST =====")


result = brain.evolution_engine.evaluate_experiment(

    experiment_id=experiment["id"],

    old_score=42,

    new_score=58

)


print(result)



print("\n===== UPGRADE DECISION =====")


decision = brain.evolution_engine.should_upgrade(
    result
)


print(decision)



print("\n===== EXPERIMENT MEMORY =====")


print(
    brain.experiment_manager.report()
)