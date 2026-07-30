"""
Atlas Class Registry Scanner v1.0

Finds references to brain classes.
"""

import os


TARGETS = [

    "AtlasBrain",
    "BrainState",
    "core.brain",
    "brain.py"

]


IGNORE = [

    "__pycache__",
    ".git",
    ".venv",
    "venv"

]



def scan():


    print("="*60)

    print(
        " ATLAS CLASS REGISTRY SCANNER "
    )

    print("="*60)



    results = []



    for root, dirs, files in os.walk("."):


        dirs[:] = [

            d for d in dirs

            if not (

                d.startswith("archive")

                or d in IGNORE

            )

        ]



        for file in files:


            if not file.endswith(".py"):

                continue



            path=os.path.join(root,file)



            if file in [
                "class_registry_scan.py"
            ]:

                continue



            try:

                with open(
                    path,
                    "r",
                    encoding="utf-8"
                ) as f:

                    content=f.read()



                for target in TARGETS:


                    if target in content:


                        results.append(

                            (
                                target,
                                path
                            )

                        )


            except:

                pass




    for target, path in results:


        print()

        print(
            "FOUND:",
            target
        )

        print(
            "FILE:",
            path
        )



    print()

    print(
        "TOTAL:",
        len(results)
    )



if __name__ == "__main__":

    scan()