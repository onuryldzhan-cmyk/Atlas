from pathlib import Path


class ProjectAnalyzer:


    VERSION = "1.0"


    def __init__(self, root="."):

        self.root = Path(root)



    def analyze(self):

        report = {

            "large_files": [],

            "empty_files": [],

            "python_files": 0,

            "total_lines": 0

        }



        for file in self.root.rglob("*.py"):


            if "__pycache__" in file.parts:
                continue


            report["python_files"] += 1



            try:

                lines = len(

                    file.read_text(

                        encoding="utf-8",

                        errors="ignore"

                    ).splitlines()

                )


            except Exception:

                lines = 0



            report["total_lines"] += lines



            if lines == 0:

                report["empty_files"].append(
                    str(file)
                )



            if lines > 500:

                report["large_files"].append(

                    {

                        "file":
                            str(file),

                        "lines":
                            lines

                    }

                )



        return report