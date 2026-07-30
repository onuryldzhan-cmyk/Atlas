import os
from datetime import datetime


class PatchGenerator:

    def __init__(self, output_dir="patches"):

        self.output_dir = output_dir

        os.makedirs(output_dir, exist_ok=True)

    def generate(self, proposal):

        filename = (
            proposal["file"]
            .replace("\\", "_")
            .replace("/", "_")
            + ".patch.txt"
        )

        path = os.path.join(self.output_dir, filename)

        with open(path, "w", encoding="utf-8") as f:

            f.write("=" * 60 + "\n")
            f.write("ATLAS AUTO PATCH\n")
            f.write("=" * 60 + "\n\n")

            f.write(f"Date : {datetime.now()}\n")
            f.write(f"Target : {proposal['file']}\n")
            f.write(f"Priority : {proposal['priority']}\n\n")

            f.write("Reason\n")
            f.write("-" * 40 + "\n")
            f.write(proposal["reason"] + "\n\n")

            f.write("Suggested Split\n")
            f.write("-" * 40 + "\n")

            for module in proposal["split_into"]:
                f.write(f"- {module}\n")

        return path