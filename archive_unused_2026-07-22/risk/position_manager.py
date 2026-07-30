"""
Atlas AI v5.1
Position Manager

Görevler:
- Pozisyon yönetimi
- Açma / kapama
- Stop kontrolü
- Partial close
- JSON kayıt
- Restart sonrası yükleme
"""


from typing import Dict, Any, List
from pathlib import Path
import json


from risk.position import Position




class PositionManager:


    def __init__(
        self,
        storage_file="positions.json"
    ):

        self.positions: Dict[str, Position] = {}

        self.storage_file = Path(storage_file)

        self.load_positions()



    # ==========================
    # CREATE
    # ==========================

    def create_position(
        self,
        symbol: str,
        price: float,
        amount: float,
        side: str = "LONG",
        risk_level: str = "medium",
        confidence: float = 0
    ):


        position = Position(

            symbol=symbol,

            entry_price=price,

            amount=amount,

            side=side,

            risk_level=risk_level,

            confidence_at_entry=confidence

        )


        pid = position.position_id


        self.positions[pid] = position


        self.save_positions()


        print(
            f"📌 Pozisyon açıldı: {symbol} "
            f"ID:{pid}"
        )


        return position




    # ==========================
    # GET
    # ==========================


    def get_position(
        self,
        position_id:str
    ):


        return self.positions.get(
            position_id
        )




    def get_positions(self):


        return {

            pid:
            pos.to_dict()

            for pid,pos
            in self.positions.items()

        }




    # ==========================
    # CLOSE
    # ==========================


    def close_position(
        self,
        position_id:str,
        price:float,
        reason="MANUAL"
    ):


        position = self.positions.get(
            position_id
        )


        if not position:

            return False



        pnl = position.close(
    price,
    reason
)

del self.positions[position_id]

self.save_positions()


        print(
            f"🔒 Kapandı: "
            f"{position.symbol} "
            f"PnL:{pnl:+.2f}"
        )


        return pnl





    # ==========================
    # PARTIAL CLOSE
    # ==========================


    def partial_close(
        self,
        position_id:str,
        percent:float
    ):


        position = self.positions.get(
            position_id
        )


        if not position:

            return False



        amount = position.partial_close(
            percent
        )


        self.save_positions()


        print(
            f"📤 Partial close "
            f"{position.symbol} "
            f"{amount}"
        )


        return amount





    # ==========================
    # PRICE UPDATE
    # ==========================


    def update_prices(
        self,
        prices:Dict[str,float]
    ) -> List[Dict[str,Any]]:


        signals=[]



        for pid,position in list(
            self.positions.items()
        ):


            if position.symbol not in prices:

                continue



            price = prices[
                position.symbol
            ]



            if position.check_stop(
                price
            ):


                signals.append({

                    "position_id":pid,

                    "symbol":
                    position.symbol,

                    "action":
                    "STOP",

                    "price":
                    price,

                    "side":
                    position.side

                })


        self.save_positions()


        return signals





    # ==========================
    # STORAGE
    # ==========================


    def save_positions(self):


        data={}


        for pid,pos in self.positions.items():

            data[pid]=pos.to_dict()



        with open(
            self.storage_file,
            "w",
            encoding="utf-8"
        ) as f:


            json.dump(
                data,
                f,
                indent=4,
                ensure_ascii=False
            )




    def load_positions(self):


        if not self.storage_file.exists():

            return



        try:

            with open(
                self.storage_file,
                "r",
                encoding="utf-8"
            ) as f:


                data=json.load(f)



            for pid,item in data.items():


                position=Position(

                    symbol=item["symbol"],

                    entry_price=item["entry_price"],

                    amount=item["amount"],

                    side=item["side"],

                    risk_level=item["risk_level"],

                    confidence_at_entry=item.get(
                        "confidence",
                        0
                    )

                )


                self.positions[pid]=position



        except Exception as e:

            print(
                "Position load error:",
                e
            )





    # ==========================
    # REPORT
    # ==========================


    def count(self):

        return len(
            self.positions
        )