from core.engine import AtlasEngine
import json


def main():

    engine = AtlasEngine()

    print("\n===================================")
    print("      PROJECT ATLAS AI v2")
    print("===================================\n")

    while True:

        try:
            command = input("Komut / Coin: ").upper().strip()

            if command in ["Q", "QUIT", "EXIT"]:
                print("\nAtlas AI kapatıldı.")
                break

            if command == "CLEARTEST":
                engine.cycle.trader.positions.clear()

                try:
                    with open("data/atlas_memory.json", "r") as f:
                        memory = json.load(f)

                    memory = [
                        x for x in memory
                        if x.get("status") != "OPEN"
                    ]

                    with open("data/atlas_memory.json", "w") as f:
                        json.dump(memory, f, indent=4)

                except Exception as e:
                    print("Hafıza temizleme hatası:", e)

                print("\nTEST POZİSYONLARI TEMİZLENDİ.")
                continue

            if command == "DASHBOARD":
                from dashboard.dashboard import Dashboard

                Dashboard().show()
                continue

            if command == "BUYTEST":
                data = engine.cycle.data_provider.get_market_data("BTCUSDT")
                price = float(data["close"].iloc[-1])

                result = engine.cycle.trader.buy(
                    "BTCUSDT",
                    price,
                    metadata={
                        "strategy": "test",
                        "ai_confidence": 50
                    }
                )

                print("\nTEST POZİSYON AÇILDI")
                print(result)
                continue

            if command == "POSITION":
                print("\n===== POSITION =====")
                print(engine.cycle.trader.status())
                print("====================\n")
                continue

            if command == "PORTFOLIO":
                print("\n===== PORTFOLIO =====")
                print(engine.cycle.trader.portfolio.report())
                print("=====================\n")
                continue

            if command == "AUTO":
                from core.auto_scanner import AutoScanner

                scanner = AutoScanner(engine)
                scanner.start()
                continue

            # Yukarıdaki özel komutlardan hiçbiri değilse,
            # girilen değer bir coin/işlem komutu olarak değerlendirilir.
            engine.start(command)

        except KeyboardInterrupt:
            print("\nAtlas AI kapatıldı.")
            break

        except Exception as e:
            print("Hata:", e)


if __name__ == "__main__":
    main()
