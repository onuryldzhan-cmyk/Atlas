from core.codebase_indexer import CodebaseIndexer

print("=" * 40)
print(" ATLAS CODEBASE INDEXER ")
print("=" * 40)

indexer = CodebaseIndexer(".")

index = indexer.build_index()

indexer.save()

print(indexer.summary())

for file, info in list(index.items())[:5]:

    print()

    print(file)

    print(info)