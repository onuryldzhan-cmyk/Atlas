from core.application import AtlasApplication


print("="*50)
print("ATLAS APPLICATION TEST")
print("="*50)


app = AtlasApplication()


print(app.status())


print(app.start())


print(app.status())


app.stop()