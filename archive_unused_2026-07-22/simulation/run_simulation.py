import json

from simulation.ai_simulator import AISimulator



def main():


    try:


        with open(
            "data/ai_decisions.json",
            "r"
        ) as f:

            decisions = json.load(f)



    except Exception as e:


        print(
            "AI karar dosyası okunamadı:",
            e
        )

        return




    simulator = AISimulator()


    result = simulator.simulate(
        decisions
    )



    print("\n=================================")
    print("        ATLAS AI SIMULATION")
    print("=================================\n")


    print(
        "Test Sayısı   :",
        result["total_tests"]
    )


    print(
        "Kazanan       :",
        result["wins"]
    )


    print(
        "Kaybeden      :",
        result["losses"]
    )


    print(
        "Başarı        : %",
        result["success_rate"]
    )


    print("\nSTRATEJİLER")
    print("------------------------------")


    for name, data in result["strategies"].items():

        print("\n", name.upper())

        print(
            "Kazanç:",
            data["wins"]
        )

        print(
            "Kayıp :",
            data["losses"]
        )


    print("\n=================================")



if __name__ == "__main__":

    main()