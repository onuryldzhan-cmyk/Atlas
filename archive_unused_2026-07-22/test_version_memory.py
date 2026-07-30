from core.version_memory import VersionMemory


memory = VersionMemory()


memory.add_upgrade(
    "6.5",
    "6.6",
    "confidence_engine",
    "Confidence ağırlıkları optimize edildi",
    "Başarı oranı düşük",
    {
        "win_rate":42
    }
)


print(
    memory.statistics()
)


print(
    memory.last_upgrade()
)