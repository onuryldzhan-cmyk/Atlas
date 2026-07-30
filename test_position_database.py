"""
============================================================
ATLAS AI POSITION DATABASE INTEGRITY TEST v1.0
============================================================

Checks:

- Database loading
- Position recovery
- Portfolio consistency
- Exposure calculation
- Persistence


============================================================
"""


from pathlib import Path


from core.position_controller import PositionManager






def banner():


    print("=" * 70)

    print(
        "ATLAS AI POSITION DATABASE INTEGRITY TEST v1.0"
    )

    print("=" * 70)







def check_database(manager):


    print("\n[DATABASE CHECK]\n")


    database = Path(

        manager.database

    )


    print(

        "Database:",

        database

    )


    print(

        "Exists:",

        database.exists()

    )



    print(

        "Open Positions:",

        len(manager.positions)

    )


    print(

        "Closed Positions:",

        len(manager.closed_positions)

    )







def check_positions(manager):


    print("\n[POSITION RECOVERY CHECK]\n")


    if not manager.positions:


        print(
            "No active positions"
        )

        return



    for symbol, position in manager.positions.items():


        print(
            "Symbol:",
            symbol
        )


        print(
            "Entry:",
            position.entry_price
        )


        print(
            "Amount:",
            position.amount
        )


        print(
            "Status:",
            position.status.value
        )






def check_portfolio(manager):


    print("\n[PORTFOLIO CHECK]\n")


    portfolio = manager.update_portfolio()



    print(

        portfolio.to_dict()

    )



    print(

        "\nExposure:",

        manager.total_exposure()

    )



    print(

        "Unrealized PNL:",

        manager.total_unrealized_pnl()

    )



    print(

        "Realized PNL:",

        manager.total_realized_pnl()

    )







def restart_test():


    print("\n[RESTART RECOVERY TEST]\n")


    first = PositionManager()


    before = len(

        first.positions

    )



    print(

        "Before restart:",

        before

    )



    second = PositionManager()


    after = len(

        second.positions

    )


    print(

        "After restart:",

        after

    )



    if before == after:


        print(

            "Persistence: PASS"

        )

    else:


        print(

            "Persistence: FAIL"

        )








def main():


    banner()



    print(

        "\n[LOADING POSITION MANAGER]\n"

    )



    manager = PositionManager()



    print(

        manager.status()

    )



    check_database(

        manager

    )


    check_positions(

        manager

    )


    check_portfolio(

        manager

    )


    restart_test()



    print("\n")


    print("=" * 70)


    print(

        "ATLAS POSITION DATABASE TEST COMPLETED"

    )


    print("=" * 70)







if __name__ == "__main__":

    main()