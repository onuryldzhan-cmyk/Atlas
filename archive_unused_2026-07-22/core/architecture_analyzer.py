"""
Atlas AI - Architecture Analyzer
Kod kalitesini analiz eden, sorunlari tespit eden, iyilestirme onerileri sunan sistem.
Dependency Graph ile birlikte calisir.
"""

import ast
import json
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field, asdict
from collections import defaultdict
import re
import hashlib


@dataclass
class CodeIssue:
    """Bulunan bir kod sorunu"""
    file_path: str
    issue_type: str
    severity: str
    message: str
    line_number: int = 0
    suggestion: str = ""

    def to_dict(self) -> dict:
        return {
            "file_path": self.file_path,
            "issue_type": self.issue_type,
            "severity": self.severity,
            "message": self.message,
            "line_number": self.line_number,
            "suggestion": self.suggestion
        }


@dataclass
class ModuleQuality:
    """Bir modulun kalite skorlari"""
    file_path: str
    lines_of_code: int = 0
    function_count: int = 0
    class_count: int = 0
    average_function_length: float = 0.0
    max_function_length: int = 0
    docstring_coverage: float = 0.0
    type_hint_coverage: float = 0.0
    complexity_score: float = 0.0
    duplicate_code_blocks: int = 0
    total_issues: int = 0
    quality_score: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


class ArchitectureAnalyzer:
    """
    Atlas AI kodunu derinlemesine analiz eder.
    """

    CODE_SMELLS = {
        "long_function": {"threshold": 50, "message": "Fonksiyon cok uzun", "severity": "medium"},
        "very_long_function": {"threshold": 100, "message": "Fonksiyon asiri uzun, refactor gerekli", "severity": "high"},
        "many_parameters": {"threshold": 5, "message": "Cok fazla parametre", "severity": "medium"},
        "empty_except": {"pattern": r"except\s*.*:\s*\n\s*pass", "message": "Bos except blogu", "severity": "high"},
        "bare_except": {"pattern": r"except\s*:", "message": "Bare except kullanimi", "severity": "high"},
        "hardcoded_path": {"pattern": r"C:\\|/home/|/Users/", "message": "Hardcoded dosya yolu", "severity": "medium"},
        "todo_without_detail": {"pattern": r"#.*TODO\s*$", "message": "TODO aciklamasiz", "severity": "low"},
        "print_debug": {"pattern": r"print\s*\(", "message": "Debug print ifadesi", "severity": "low"},
        "global_variable": {"pattern": r"^global\s+", "message": "Global degisken kullanimi", "severity": "medium"},
    }

    def __init__(self, root_path: str = "."):
        self.root_path = Path(root_path).resolve()
        self.issues: List[CodeIssue] = []
        self.module_qualities: Dict[str, ModuleQuality] = {}
        self.duplicate_blocks: List[Tuple[str, str, int]] = []
        self.architecture_score: float = 0.0

    def analyze_all(self) -> None:
        """Tum projeyi analiz et"""
        print("Atlas AI mimarisi analiz ediliyor...")

        py_files = list(self.root_path.rglob("*.py"))
        total = len(py_files)

        for i, file_path in enumerate(py_files, 1):
            rel_path = str(file_path.relative_to(self.root_path))
            print(f"  [{i}/{total}] Analiz: {rel_path}")
            self._analyze_single_file(file_path)

        print("\nTekrar eden kod bloklari araniyor (hizli mod)...")
        self._find_duplicate_code_fast(py_files)

        self._calculate_architecture_score()
        self._print_summary()

    def _analyze_single_file(self, file_path: Path) -> None:
        """Tek bir dosyayi analiz et"""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
                lines = content.split("\n")
        except Exception as e:
            self.issues.append(CodeIssue(
                file_path=str(file_path),
                issue_type="error",
                severity="medium",
                message=f"Dosya okunamadi: {e}"
            ))
            return

        rel_path = str(file_path.relative_to(self.root_path))

        try:
            tree = ast.parse(content)
        except SyntaxError:
            return

        quality = ModuleQuality(file_path=rel_path, lines_of_code=len(lines))

        functions = []
        classes = []
        docstring_count = 0
        typed_params = 0
        total_params = 0

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                functions.append(node)
                quality.function_count += 1
                func_length = node.end_lineno - node.lineno if node.end_lineno else 10
                quality.max_function_length = max(quality.max_function_length, func_length)

                if ast.get_docstring(node):
                    docstring_count += 1

                args_count = len(node.args.args) + len(node.args.kwonlyargs)
                if node.args.vararg:
                    args_count += 1
                if node.args.kwarg:
                    args_count += 1
                total_params += args_count

                if node.returns:
                    typed_params += 1
                for arg in node.args.args:
                    if arg.annotation:
                        typed_params += 1

                if func_length > self.CODE_SMELLS["very_long_function"]["threshold"]:
                    self.issues.append(CodeIssue(
                        file_path=rel_path,
                        issue_type="smell",
                        severity="high",
                        message=f"Fonksiyon cok uzun ({func_length} satir)",
                        line_number=node.lineno,
                        suggestion="Fonksiyonu daha kucuk parcalara bolun."
                    ))
                elif func_length > self.CODE_SMELLS["long_function"]["threshold"]:
                    self.issues.append(CodeIssue(
                        file_path=rel_path,
                        issue_type="smell",
                        severity="medium",
                        message=f"Fonksiyon biraz uzun ({func_length} satir)",
                        line_number=node.lineno,
                        suggestion="Fonksiyonu daha kucuk parcalara bolun."
                    ))

                if args_count > self.CODE_SMELLS["many_parameters"]["threshold"]:
                    self.issues.append(CodeIssue(
                        file_path=rel_path,
                        issue_type="smell",
                        severity="medium",
                        message=f"Cok fazla parametre ({args_count})",
                        line_number=node.lineno,
                        suggestion="Parametreleri config dict veya dataclass ile gruplayin."
                    ))

            elif isinstance(node, ast.ClassDef):
                classes.append(node)
                quality.class_count += 1
                if ast.get_docstring(node):
                    docstring_count += 1

        if quality.function_count > 0:
            total_func_lines = sum(
                (n.end_lineno - n.lineno if n.end_lineno else 10) 
                for n in functions
            )
            quality.average_function_length = total_func_lines / quality.function_count

        total_docstring_targets = quality.function_count + quality.class_count
        if total_docstring_targets > 0:
            quality.docstring_coverage = (docstring_count / total_docstring_targets) * 100

        if total_params > 0:
            quality.type_hint_coverage = (typed_params / total_params) * 100

        quality.complexity_score = (
            quality.lines_of_code * 0.1 +
            quality.function_count * 2 +
            quality.class_count * 3 +
            quality.max_function_length * 0.5
        )

        self._regex_checks(rel_path, content)

        quality.quality_score = self._calculate_quality_score(quality)
        quality.total_issues = len([i for i in self.issues if i.file_path == rel_path])

        self.module_qualities[rel_path] = quality

    def _regex_checks(self, file_path: str, content: str) -> None:
        """Regex tabanli kod kokusu kontrolleri"""
        for smell_name, smell_info in self.CODE_SMELLS.items():
            if "pattern" in smell_info:
                pattern = smell_info["pattern"]
                for match in re.finditer(pattern, content, re.MULTILINE):
                    line_num = content[:match.start()].count("\n") + 1
                    self.issues.append(CodeIssue(
                        file_path=file_path,
                        issue_type="smell",
                        severity=smell_info["severity"],
                        message=smell_info["message"],
                        line_number=line_num,
                        suggestion=f"Kod kokusu giderilmeli: {smell_name}"
                    ))

    def _find_duplicate_code_fast(self, py_files: List[Path]) -> None:
        """Hizli tekrar eden kod tespiti - hash tabanli"""
        block_hashes = defaultdict(list)

        for file_path in py_files:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
            except Exception:
                continue

            rel_path = str(file_path.relative_to(self.root_path))

            for i in range(len(lines) - 4):
                block_lines = lines[i:i+5]
                block_text = "".join(block_lines).strip()

                if not block_text or block_text.startswith("#") or len(block_text) < 30:
                    continue

                # Normalize et ve hashle
                normalized = re.sub(r'\s+', ' ', block_text)
                block_hash = hashlib.md5(normalized.encode()).hexdigest()
                block_hashes[block_hash].append((rel_path, i+1))

        # Ayni hash'e sahip olanlari bul
        for block_hash, locations in block_hashes.items():
            if len(locations) >= 2:
                files = list(set(loc[0] for loc in locations))
                if len(files) >= 2:
                    self.duplicate_blocks.append((files[0], files[1], len(locations)))
                    self.issues.append(CodeIssue(
                        file_path=f"{files[0]} <-> {files[1]}",
                        issue_type="duplicate",
                        severity="low",
                        message=f"Benzer kod blogu ({len(locations)} yerde)",
                        suggestion="Ortak kodu bir fonksiyona cikarin."
                    ))

    def _calculate_quality_score(self, quality: ModuleQuality) -> float:
        """Bir modulun kalite skorunu hesapla (0-100)"""
        score = 100.0

        if quality.lines_of_code > 500:
            score -= 10
        if quality.lines_of_code > 1000:
            score -= 20

        if quality.max_function_length > 100:
            score -= 15
        elif quality.max_function_length > 50:
            score -= 5

        if quality.docstring_coverage < 30:
            score -= 15
        elif quality.docstring_coverage < 60:
            score -= 5

        if quality.type_hint_coverage < 20:
            score -= 10

        if quality.complexity_score > 100:
            score -= 10

        return max(0, min(100, score))

    def _calculate_architecture_score(self) -> None:
        """Tum projenin mimari skorunu hesapla"""
        if not self.module_qualities:
            self.architecture_score = 0
            return

        total_score = sum(m.quality_score for m in self.module_qualities.values())
        self.architecture_score = total_score / len(self.module_qualities)

    def get_critical_issues(self, min_severity: str = "high") -> List[CodeIssue]:
        """Belirli ciddiyetin uzerindeki sorunlari getir"""
        severity_order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
        min_level = severity_order.get(min_severity, 1)

        return [
            issue for issue in self.issues
            if severity_order.get(issue.severity, 0) >= min_level
        ]

    def get_worst_modules(self, count: int = 10) -> List[ModuleQuality]:
        """En kotu kalitedeki modulleri getir"""
        return sorted(
            self.module_qualities.values(),
            key=lambda x: x.quality_score
        )[:count]

    def get_health_report(self) -> Dict:
        """Mimari saglik raporu"""
        total_issues = len(self.issues)
        critical = len([i for i in self.issues if i.severity == "critical"])
        high = len([i for i in self.issues if i.severity == "high"])
        medium = len([i for i in self.issues if i.severity == "medium"])
        low = len([i for i in self.issues if i.severity == "low"])

        worst = self.get_worst_modules(5)

        return {
            "total_modules_analyzed": len(self.module_qualities),
            "total_issues": total_issues,
            "severity_breakdown": {
                "critical": critical,
                "high": high,
                "medium": medium,
                "low": low
            },
            "architecture_score": round(self.architecture_score, 2),
            "duplicate_code_pairs": len(self.duplicate_blocks),
            "worst_modules": [
                {
                    "file": m.file_path,
                    "score": round(m.quality_score, 2),
                    "lines": m.lines_of_code,
                    "issues": m.total_issues
                }
                for m in worst
            ],
            "critical_issues": [i.to_dict() for i in self.get_critical_issues("high")]
        }

    def _print_summary(self) -> None:
        """Ozet raporu ekrana yazdir"""
        report = self.get_health_report()

        print("\n" + "="*60)
        print("ATLAS AI - MIMARI ANALIZ RAPORU")
        print("="*60)
        print(f"Analiz Edilen Modul:  {report['total_modules_analyzed']}")
        print(f"Toplam Sorun:        {report['total_issues']}")
        print(f"Kritik:              {report['severity_breakdown']['critical']}")
        print(f"Yuksek:              {report['severity_breakdown']['high']}")
        print(f"Orta:                {report['severity_breakdown']['medium']}")
        print(f"Dusuk:               {report['severity_breakdown']['low']}")
        print(f"Mimari Skor:         {report['architecture_score']}/100")
        print(f"Tekrar Eden Kod:     {report['duplicate_code_pairs']} cift")
        print("="*60)

        if report["worst_modules"]:
            print("\nEN KOTU KALITEDEKI MODULLER:")
            for i, mod in enumerate(report["worst_modules"], 1):
                print(f"   {i}. {mod['file']} (Skor: {mod['score']}, {mod['lines']} satir, {mod['issues']} sorun)")

        if report["critical_issues"]:
            print("\nKRITIK SORUNLAR:")
            for issue in report["critical_issues"][:5]:
                print(f"   [{issue['severity'].upper()}] {issue['file_path']}:{issue['line_number']}")
                print(f"      -> {issue['message']}")
                if issue["suggestion"]:
                    print(f"      {issue['suggestion']}")

    def export_report(self, filepath: str = "architecture_report.json") -> None:
        """Raporu JSON olarak kaydet"""
        report = self.get_health_report()

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        print(f"\nMimari rapor kaydedildi: {filepath}")

    def print_detailed_module_report(self, module_path: str) -> None:
        """Belirli bir modulun detayli raporunu yazdir"""
        quality = self.module_qualities.get(module_path)
        if not quality:
            print(f"Modul bulunamadi: {module_path}")
            return

        print(f"\n{'='*60}")
        print(f"DETAYLI MODUL RAPORU: {module_path}")
        print(f"{'='*60}")
        print(f"Satir Sayisi:           {quality.lines_of_code}")
        print(f"Fonksiyon Sayisi:       {quality.function_count}")
        print(f"Sinif Sayisi:           {quality.class_count}")
        print(f"Ort. Fonk. Uzunlugu:    {quality.average_function_length:.1f}")
        print(f"En Uzun Fonksiyon:      {quality.max_function_length} satir")
        print(f"Docstring Kapsami:      %{quality.docstring_coverage:.1f}")
        print(f"Type Hint Kapsami:     %{quality.type_hint_coverage:.1f}")
        print(f"Karmasiklik:           {quality.complexity_score:.1f}")
        print(f"Kalite Skoru:           {quality.quality_score:.1f}/100")
        print(f"{'='*60}")

        module_issues = [i for i in self.issues if i.file_path == module_path]
        if module_issues:
            print(f"\nBU MODULDEKI SORUNLAR ({len(module_issues)}):")
            for issue in module_issues:
                print(f"   [{issue.severity.upper()}] Satir {issue.line_number}: {issue.message}")
                if issue.suggestion:
                    print(f"      {issue['suggestion']}")


if __name__ == "__main__":
    print("Atlas AI Architecture Analyzer - Test Modu")
    print("-" * 50)

    analyzer = ArchitectureAnalyzer()
    analyzer.analyze_all()
    analyzer.export_report()

    print("\nTest tamamlandi!")

