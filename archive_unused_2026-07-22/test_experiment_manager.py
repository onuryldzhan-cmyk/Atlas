from core.atlas_brain import AtlasBrain


print("==============================")
print(" ATLAS EXPERIMENT TEST ")
print("==============================")


brain = AtlasBrain()


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


print("\n===== CREATED EXPERIMENT =====")
print(experiment)


print("\n===== REPORT =====")

print(
    brain.experiment_manager.report()
)