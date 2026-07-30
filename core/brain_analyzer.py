"""
Atlas Brain Analyzer v1.0

Compares brain modules.
"""

import ast
import os
import json
from datetime import datetime


class BrainAnalyzer:


    def __init__(self):

        self.targets = [

            "core/brain.py",

            "ai/core/atlas_brain.py"

        ]


        self.results = []



    def analyze_file(self, file):


        if not os.path.exists(file):

            return None


        with open(
            file,
            "r",
            encoding="utf-8"
        ) as f:

            source = f.read()



        tree = ast.parse(source)



        classes = []

        functions = []

        imports = []



        for node in ast.walk(tree):


            if isinstance(
                node,
                ast.ClassDef
            ):

                classes.append(
                    node.name
                )


            elif isinstance(
                node,
                ast.FunctionDef
            ):

                functions.append(
                    node.name
                )


            elif isinstance(
                node,
                ast.Import
            ):

                for item in node.names:

                    imports.append(
                        item.name
                    )


            elif isinstance(
                node,
                ast.ImportFrom
            ):

                if node.module:

                    imports.append(
                        node.module
                    )



        return {

            "file": file,

            "lines":
                len(source.splitlines()),

            "classes":
                classes,

            "functions":
                functions,

            "imports":
                imports

        }



    def run(self):


        for file in self.targets:


            result = self.analyze_file(file)


            if result:

                self.results.append(
                    result
                )



        with open(
            "brain_analysis.json",
            "w",
            encoding="utf-8"
        ) as f:


            json.dump(

                {

                "generated":
                    datetime.now().isoformat(),

                "brains":
                    self.results

                },

                f,

                indent=4,

                ensure_ascii=False

            )



        return self.results




if __name__ == "__main__":


    print("="*60)

    print(
        " ATLAS BRAIN ANALYZER v1.0 "
    )

    print("="*60)



    analyzer = BrainAnalyzer()


    results = analyzer.run()



    for brain in results:


        print("\nFILE:")
        print(
            brain["file"]
        )


        print(
            "LINES:",
            brain["lines"]
        )


        print(
            "\nCLASSES:"
        )


        for c in brain["classes"]:

            print(
                " -",
                c
            )


        print(
            "\nFUNCTION COUNT:",
            len(brain["functions"])
        )


        print(
            "\nIMPORT COUNT:",
            len(brain["imports"])
        )