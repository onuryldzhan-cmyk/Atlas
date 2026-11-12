from ai_core.awareness.project_snapshot import ProjectSnapshotEngine

engine = ProjectSnapshotEngine(".")

snapshot = engine.save("snapshots/latest_snapshot.json")

print(snapshot)