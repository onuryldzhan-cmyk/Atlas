from __future__ import annotations

from pathlib import Path
from datetime import datetime, UTC
import json


class ProjectSnapshot:

    VERSION = "1.0"

    def __init__(self, project_root=None):

        if project_root is None:
            project_root = Path(__file__).resolve().parent.parent

        self.root = Path(project_root)


    def create_snapshot(self):

        snapshot = {

            "version": self.VERSION,

            "created_at":
                datetime.now(UTC).isoformat(),

            "project_root":
                str(self.root),

            "folders": [],

            "python_files": [],

            "statistics": {}

        }


        folder_count = 0
        python_count = 0
        total_lines = 0



        for path in self.root.rglob("*"):


            if ".git" in path.parts:
                continue


            if "__pycache__" in path.parts:
                continue



            if path.is_dir():


                folder_count += 1


                snapshot["folders"].append(
                    str(path.relative_to(self.root))
                )

                continue




            if path.suffix != ".py":
                continue



            python_count += 1



            try:

                text = path.read_text(
                    encoding="utf-8",
                    errors="ignore"
                )


                line_count = len(
                    text.splitlines()
                )


            except Exception:

                line_count = 0




            total_lines += line_count



            snapshot["python_files"].append(

                {

                    "file":
                        str(path.relative_to(self.root)),

                    "lines":
                        line_count

                }

            )



        snapshot["statistics"] = {

            "folders":
                folder_count,

            "python_files":
                python_count,

            "total_lines":
                total_lines

        }


        return snapshot




    def save(
        self,
        filename="project_snapshot.json"
    ):


        data = self.create_snapshot()



        output = self.root / filename



        with open(
            output,
            "w",
            encoding="utf-8"
        ) as f:


            json.dump(

                data,

                f,

                indent=4,

                ensure_ascii=False

            )



        return output





if __name__ == "__main__":


    engine = ProjectSnapshot()



    file = engine.save()



    print(
        "Snapshot oluşturuldu:"
    )


    print(file)



    print(
        engine.create_snapshot()["statistics"]
    )