"""
============================================================
ATLAS AI POSITION LIFECYCLE TEST v1.0
============================================================

Test:

BUY
 |
OPEN POSITION
 |
PRICE UPDATE
 |
PNL CALCULATION
 |
TAKE PROFIT
 |
CLOSE
 |
REPORT


============================================================
"""


from core.position_controller import PositionManager



def banner():

    print("=" * 70)

    print(
        "ATLAS AI POSITION LIFECYCLE TEST v1.0"
    )

    print("=" * 70)



def main():


    banner()


    print("\n[INIT] Loading Position Manager\n")


    manager = PositionManager()



    print(
        manager.status()
    )



    # ==========================================
    # OPEN POSITION
    # ==========================================


    trade = {


        "execution_id":

        "LIFECYCLE_TEST_001",


        "symbol":

        "BTCUSDT",


        "side":

        "BUY",


        "price":

        65000,


        "amount":

        1500,


        "confidence":

        85,


        "strategy":

        "Lifecycle_Test",


        "risk":

        "MEDIUM"


    }




    print(
        "\n[OPEN POSITION]"
    )


    position = manager.register(
        trade
    )


    print(position)



    # ==========================================
    # SET RISK LEVELS
    # ==========================================


    print(
        "\n[SETTING TP / SL]"
    )


    manager.set_take_profit(

        "BTCUSDT",

        66000

    )


    manager.set_stop_loss(

        "BTCUSDT",

        64000

    )



    print(
        "TP : 66000"
    )

    print(
        "SL : 64000"
    )



    # ==========================================
    # PRICE UPDATE
    # ==========================================


    print(
        "\n[PRICE UPDATE]"
    )


    updated = manager.update_price(

        "BTCUSDT",

        66000

    )


    print(updated)



    print(
        "\nUNREALIZED PNL:"
    )


    print(

        updated.unrealized_pnl,

        "%"

    )




    # ==========================================
    # EXIT CHECK
    # ==========================================


    print(
        "\n[EXIT CONDITION CHECK]"
    )


    reason = manager.check_exit_conditions(

        "BTCUSDT"

    )


    print(

        "EXIT REASON:",

        reason

    )




    # ==========================================
    # CLOSE POSITION
    # ==========================================


    print(
        "\n[CLOSING POSITION]"
    )


    closed = manager.close(

        "BTCUSDT",

        66000

    )


    print(closed)




    # ==========================================
    # REPORT
    # ==========================================


    print(
        "\n[FINAL PERFORMANCE]"
    )


    print(

        manager.performance_report()

    )



    print("\n")

    print("=" * 70)

    print(
        "ATLAS POSITION LIFECYCLE TEST COMPLETED"
    )

    print("=" * 70)




if __name__ == "__main__":

    main()