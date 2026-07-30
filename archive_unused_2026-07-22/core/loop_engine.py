import time
import sys
import os


sys.path.append(
    os.path.dirname(
        os.path.dirname(
            os.path.abspath(__file__)
        )
    )
)


from core.engine import AtlasEngine



class LoopEngine:


    def __init__(self):

        self.engine = AtlasEngine()



    def start(self):

        print("==============================")
        print("Atlas 24/7 Engine Başladı")
        print("==============================")


        while True:

            try:

                self.engine.start()


                print("Yeni döngü tamamlandı.")
                print("60 saniye bekleniyor...")


                time.sleep(60)



            except Exception as e:

                print("Sistem hatası:", e)

                time.sleep(30)




if __name__ == "__main__":

    bot = LoopEngine()

    bot.start()