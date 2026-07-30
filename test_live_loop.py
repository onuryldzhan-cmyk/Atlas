from core.application import AtlasApplication
import time


print("="*50)
print("ATLAS LIVE LOOP TEST")
print("="*50)


app = AtlasApplication()


app.start()


for i in range(30):

    print(
        app.status()
    )

    time.sleep(2)


app.stop()


print("FINISHED")