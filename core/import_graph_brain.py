"""
Atlas Brain Import Graph v1.0

Real Python import detector.
"""

import ast
import os


TARGETS = [

    "core.brain",

    "ai.core.atlas_brain"

]


IGNORE_DIRS = [

    "__pycache__",
    ".git",
    ".venv",
    "venv"

]



def scan():


    print("="*60)

    print(
        " ATLAS BRAIN IMPORT GRAPH "
    )

    print("="*60)



    for root, dirs, files in os.walk("."):


        dirs[:] = [

            d for d in dirs

            if not (

                d.startswith("archive")

                or d in IGNORE_DIRS

            )

        ]



        for file in files:


            if not file.endswith(".py"):

                continue



            path=os.path.join(
                root,
                file
            )



            try:

                with open(
                    path,
                    "r",
                    encoding="utf-8"
                ) as f:

                    tree=ast.parse(
                        f.read()
                    )



                for node in ast.walk(tree):


                    if isinstance(
                        node,
                        ast.Import
                    ):


                        for item in node.names:


                            if item.name in TARGETS:

                                print()

                                print(
                                    "FILE:",
                                    path
                                )

                                print(
                                    "IMPORT:",
                                    item.name
                                )



                    elif isinstance(
                        node,
                        ast.ImportFrom
                    ):


                        if node.module in TARGETS:


                            print()

                            print(
                                "FILE:",
                                path
                            )

                            print(
                                "IMPORT:",
                                node.module
                            )



            except Exception:

                pass





if __name__ == "__main__":

    scan()