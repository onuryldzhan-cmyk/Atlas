"""
Atlas AI - Background Intelligence Service
Arka planda calisan, dosya analizi yapan servis
"""
import json
import os
import sys
import ast
from datetime import datetime
from pathlib import Path
from typing import Dict, List

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

class FileUsageAnalyzer:
    def __init__(self):
        self.usage_db = PROJECT_ROOT / "data" / "file_usage_db.json"
        self._load_db()

    def _load_db(self):
        if self.usage_db.exists():
            with open(self.usage_db, "r", encoding="utf-8") as f:
                self.db = json.load(f)
        else:
            self.db = {"files": {}, "last_scan": None}

    def _save_db(self):
        os.makedirs(self.usage_db.parent, exist_ok=True)
        with open(self.usage_db, "w", encoding="utf-8") as f:
            json.dump(self.db, f, indent=2, ensure_ascii=False, default=str)

    def scan_imports(self):
        imports = {}
        imported_by = {}
        py_files = [f for f in PROJECT_ROOT.rglob("*.py") if "__pycache__" not in str(f)]

        for py_file in py_files:
            rel_path = str(py_file.relative_to(PROJECT_ROOT)).replace("\\", "/")
            imports[rel_path] = []
            try:
                with open(py_file, "r", encoding="utf-8") as f:
                    content = f.read()
                tree = ast.parse(content)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            imports[rel_path].append(alias.name)
                    elif isinstance(node, ast.ImportFrom):
                        module = node.module or ""
                        imports[rel_path].append(module)
                        if module not in imported_by:
                            imported_by[module] = []
                        imported_by[module].append(rel_path)
            except: pass
        return imports, imported_by

    def find_unused_files(self):
        imports, imported_by = self.scan_imports()
        unused = []
        py_files = [f for f in PROJECT_ROOT.rglob("*.py") if "__pycache__" not in str(f)]

        for py_file in py_files:
            rel_path = str(py_file.relative_to(PROJECT_ROOT)).replace("\\", "/")
            module_name = rel_path.replace("/", ".").replace(".py", "")
            is_imported = any(module_name in imp or imp in module_name for imp in imported_by.keys())

            if py_file.name in ["main.py", "__init__.py"]:
                continue

            mtime = datetime.fromtimestamp(py_file.stat().st_mtime)
            age_days = (datetime.now() - mtime).days
            size = py_file.stat().st_size

            if not is_imported and age_days > 7:
                unused.append({
                    "file": rel_path, "size_bytes": size, "age_days": age_days,
                    "reason": "Hic import edilmiyor", "contribution_score": 0,
                    "recommendation": "SIL" if age_days > 30 else "INCELE"
                })
        return sorted(unused, key=lambda x: x["age_days"], reverse=True)

    def calculate_contribution(self, file_path):
        rel_path = str(file_path.relative_to(PROJECT_ROOT)).replace("\\", "/")
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            lines = content.split("\n")
            total_lines = len(lines)
            code_lines = len([l for l in lines if l.strip() and not l.strip().startswith("#")])
            comment_lines = len([l for l in lines if l.strip().startswith("#")])
            func_count = content.count("def ")
            class_count = content.count("class ")
            complexity = content.count("if ") + content.count("for ") + content.count("while ")

            score = min(100, (code_lines / 10) + (func_count * 5) + (class_count * 10) + (comment_lines * 2) + (complexity * 0.5))
            return {
                "file": rel_path, "total_lines": total_lines, "code_lines": code_lines,
                "comment_lines": comment_lines, "functions": func_count, "classes": class_count,
                "complexity": complexity, "contribution_score": round(score, 1),
                "grade": "A" if score > 80 else "B" if score > 60 else "C" if score > 40 else "D"
            }
        except Exception as e:
            return {"file": rel_path, "error": str(e), "contribution_score": 0, "grade": "F"}

    def generate_recommendations(self):
        recommendations = []
        unused = self.find_unused_files()
        for u in unused[:10]:
            priority = "HIGH" if u["recommendation"] == "SIL" else "MEDIUM"
            recommendations.append({
                "priority": priority, "type": "CLEANUP", "file": u["file"],
                "message": f"'{u['file']}' kullanilmiyor ({u['age_days']} gun). {u['recommendation']}.",
                "contribution": u["contribution_score"], "action": u["recommendation"]
            })

        for py_file in PROJECT_ROOT.rglob("*.py"):
            if "__pycache__" in str(py_file): continue
            stats = self.calculate_contribution(py_file)
            if stats.get("total_lines", 0) > 500:
                recommendations.append({
                    "priority": "MEDIUM", "type": "REFACTOR", "file": stats["file"],
                    "message": f"'{stats['file']}' {stats['total_lines']} satir. Bolunmeli.",
                    "contribution": stats["contribution_score"], "action": "SPLIT"
                })
        return sorted(recommendations, key=lambda x: (x["priority"] != "HIGH", x["priority"] != "MEDIUM"))

    def full_analysis(self):
        print("[ANALIZ] Dosya analizi baslatiliyor...")
        unused = self.find_unused_files()
        all_scores = []
        for py_file in PROJECT_ROOT.rglob("*.py"):
            if "__pycache__" not in str(py_file):
                all_scores.append(self.calculate_contribution(py_file))
        all_scores.sort(key=lambda x: x.get("contribution_score", 0), reverse=True)
        recommendations = self.generate_recommendations()

        self.db["last_scan"] = datetime.now().isoformat()
        self.db["files"] = {s["file"]: s for s in all_scores}
        self._save_db()

        return {
            "timestamp": datetime.now().isoformat(), "total_files": len(all_scores),
            "unused_files": unused, "top_contributors": all_scores[:10],
            "bottom_contributors": all_scores[-10:], "recommendations": recommendations,
            "summary": {
                "cleanup": len([r for r in recommendations if r["action"] == "SIL"]),
                "refactor": len([r for r in recommendations if r["action"] == "SPLIT"]),
                "review": len([r for r in recommendations if r["action"] == "INCELE"])
            }
        }

class BackgroundService:
    def __init__(self):
        self.analyzer = FileUsageAnalyzer()

    def run_once(self):
        print("\n" + "="*60)
        print("ATLAS AI - BACKGROUND INTELLIGENCE SERVICE")
        print("="*60)
        report = self.analyzer.full_analysis()

        print(f"\n[OZET]")
        print(f"   Toplam dosya: {report['total_files']}")
        print(f"   Silinmesi gereken: {report['summary']['cleanup']}")
        print(f"   Bolunmesi gereken: {report['summary']['refactor']}")
        print(f"   Incelenmesi gereken: {report['summary']['review']}")

        if report["recommendations"]:
            print(f"\n[ONERILER] ({len(report['recommendations'])})")
            print("-"*60)
            for i, rec in enumerate(report["recommendations"][:15], 1):
                marker = "[!]" if rec["priority"] == "HIGH" else "[*]" if rec["priority"] == "MEDIUM" else "[i]"
                print(f"{marker} #{i} [{rec['priority']}] {rec['type']}")
                print(f"   FILE: {rec['file']}")
                print(f"   MSG: {rec['message']}")
                print(f"   KATKI: {rec['contribution']}/100")
                print()

        print(f"\n[EN KATKILI DOSYALAR]")
        print("-"*60)
        for s in report["top_contributors"][:10]:
            marker = "[A]" if s["grade"] == "A" else "[B]" if s["grade"] == "B" else "[C]"
            print(f"{marker} {s['file']:40s} | Skor: {s['contribution_score']:5.1f} | Not: {s['grade']}")

        os.makedirs(PROJECT_ROOT / "data", exist_ok=True)
        with open(PROJECT_ROOT / "data" / "background_analysis.json", "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False, default=str)
        print(f"\n[KAYIT] data/background_analysis.json")
        print("="*60)
        return report

def main():
    service = BackgroundService()
    service.run_once()

if __name__ == "__main__":
    main()

