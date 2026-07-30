"""
Atlas Brain Dependency Scanner v1.1

Purpose:
- Find real imports of brain modules
- Ignore archive folders
- Detect active brain usage
"""

import os


TARGETS = [

    "from core.brain",
    "import core.brain",

    "from ai.core.atlas_brain",
    "import ai.core.atlas_brain"

]


IGNORE_DIRS = [

    "__pycache__",
    ".git",
    ".venv",
    "venv"

]


IGNORE_FILES = [

    "brain_dependency_scan.py"

]



def scan():


    print("=" * 60)

    print(
        " ATLAS BRAIN DEPENDENCY SCANNER v1.1 "
    )

    print("=" * 60)



    results = []



    for root, dirs, files in os.walk("."):


        dirs[:] = [

            d for d in dirs

            if not (

                d.startswith("archive")

                or d.startswith("backup")

                or d.startswith("old")

                or d.startswith("temp")

                or d in IGNORE_DIRS

            )

        ]



        for file in files:


            if not file.endswith(".py"):

                continue



            if file in IGNORE_FILES:

                continue



            path = os.path.join(
                root,
                file
            )



            try:

                with open(
                    path,
                    "r",
                    encoding="utf-8"
                ) as f:

                    content = f.read()



                for target in TARGETS:


                    if target in content:


                        results.append(

                            {

                            "target": target,

                            "file": path

                            }

                        )



            except Exception:

                pass




    print("\nDEPENDENCIES FOUND")

    print("-" * 60)



    if not results:


        print(
            "No brain dependencies found."
        )



    for item in results:


        print(

            "\nMODULE:",

            item["target"]

        )


        print(

            "USED BY:",

            item["file"]

        )



    print("\n")

    print(
        "TOTAL REFERENCES:",
        len(results)
    )



    return results




if __name__ == "__main__":

    scan()