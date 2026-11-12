"""
Atlas World Analyzer v1.0

Market relationship intelligence layer.


Responsibilities:

- Analyze related assets
- Query world model
- Provide market context


"""


class WorldAnalyzer:



    VERSION = "1.0"





    def __init__(

        self,

        world_model=None

    ):


        self.world = world_model






    # =================================================
    # ANALYZE WORLD
    # =================================================


    def analyze(

        self,

        symbol

    ):


        impacts = {}





        if not self.world:


            print(

                "[WORLD] unavailable"

            )


            return impacts







        try:



            asset = symbol.replace(

                "USDT",

                ""

            )





            impacts = self.world.get_impact_chain(

                asset,

                depth=2

            )





        except Exception as e:



            print(

                f"[WORLD ERROR] {e}"

            )



            impacts = {}







        print(

            f"[WORLD] {len(impacts)} related assets"

        )






        return impacts