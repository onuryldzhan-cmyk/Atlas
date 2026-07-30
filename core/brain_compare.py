"""
Atlas Brain Compare v1.0

Compare active and legacy brain modules.
"""

import ast
import os



FILES = [

    "core/brain.py",

    "ai/core/atlas_brain.py"

]



def analyze(file):


    if not os.path.exists(file):

        return None



    with open(
        file,
        "r",
        encoding="utf-8"
    ) as f:

        source = f.read()



    tree = ast.parse(source)



    result = {

        "file": file,

        "classes": {},

        "imports": []

    }



    for node in ast.walk(tree):


        if isinstance(
            node,
            ast.ClassDef
        ):


            methods = []


            for item in node.body:


                if isinstance(
                    item,
                    ast.FunctionDef
                ):

                    methods.append(
                        item.name
                    )


            result["classes"][node.name] = methods



        elif isinstance(
            node,
            ast.Import
        ):


            for name in node.names:

                result["imports"].append(
                    name.name
                )



        elif isinstance(
            node,
            ast.ImportFrom
        ):


            if node.module:

                result["imports"].append(
                    node.module
                )



    return result





if __name__ == "__main__":


    print("="*60)

    print(
        " ATLAS BRAIN COMPARE v1.0 "
    )

    print("="*60)



    for file in FILES:


        data = analyze(file)



        if not data:

            continue



        print("\nFILE:")
        print(
            data["file"]
        )



        print("\nCLASSES:")



        for cls, methods in data["classes"].items():


            print(
                "\n",
                cls
            )


            for method in methods:

                print(
                    "  -",
                    method
                )



        print("\nIMPORTS:")


        for imp in data["imports"]:

            print(
                " -",
                imp
            )