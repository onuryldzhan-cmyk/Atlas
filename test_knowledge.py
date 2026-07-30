from assistant.knowledge.knowledge_core import KnowledgeCore


memory = KnowledgeCore(".")


print(
    memory.remember(
        "architecture",
        "Atlas Self Awareness Engine aktif edildi"
    )
)


print(
    memory.remember(
        "version",
        "Atlas Intelligence v8.0"
    )
)