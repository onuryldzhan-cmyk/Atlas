"""
Atlas AI - Temizlik Analiz Araci v2
Detayli dosya analizi ve silme onerileri
"""
import os
import json
from pathlib import Path
from datetime import datetime
from collections import defaultdict

PROJECT_ROOT = Path(".")

def get_file_info(fpath: Path) -> dict:
    """Dosya bilgilerini al"""
    stat = fpath.stat()
    return {
        "path": str(fpath.relative_to(PROJECT_ROOT)),
        "size": stat.st_size,
        "size_mb": stat.st_size / (1024*1024),
        "modified": datetime.fromtimestamp(stat.st_mtime),
        "age_days": (datetime.now() - datetime.fromtimestamp(stat.st_mtime)).days
    }

def analyze():
    print("="*70)
    print("ATLAS AI - TEMIZLIK ANALIZ ARACI v2")
    print("="*70)

    categories = defaultdict(list)
    total_size = 0
    grand_total_files = 0

    for root, dirs, files in os.walk(PROJECT_ROOT):
        root_path = Path(root)

        # __pycache__
        if "__pycache__" in root:
            for f in files:
                fpath = root_path / f
                info = get_file_info(fpath)
                categories["__pycache__"].append(info)
                total_size += info["size"]
            continue

        for f in files:
            fpath = root_path / f
            info = get_file_info(fpath)
            grand_total_files += 1

            # .pyc
            if f.endswith(".pyc"):
                categories[".pyc"].append(info)
                total_size += info["size"]

            # .pyo
            elif f.endswith(".pyo"):
                categories[".pyo"].append(info)
                total_size += info["size"]

            # Log
            elif f.endswith(".log"):
                categories[".log"].append(info)
                total_size += info["size"]

            # Gecici
            elif f.endswith((".tmp", ".temp", "~")):
                categories["temp"].append(info)
                total_size += info["size"]

            # Eski JSON cache
            elif f.endswith(".json") and "cache" in str(fpath).lower():
                categories["json_cache"].append(info)
                total_size += info["size"]

            # Buyuk dosyalar (>10MB)
            elif info["size_mb"] > 10:
                categories["buyuk_dosyalar"].append(info)
                total_size += info["size"]

    # .git analiz
    git_dir = PROJECT_ROOT / ".git"
    if git_dir.exists():
        git_size = sum(f.stat().st_size for f in git_dir.rglob("*") if f.is_file())
        categories[".git"].append({
            "path": ".git",
            "size": git_size,
            "size_mb": git_size / (1024*1024),
            "modified": datetime.now(),
            "age_days": 0
        })

    # Rapor
    print(f"\n[OZET]")
    print(f"Toplam dosya: {grand_total_files}")
    print(f"Silinebilir kategori: {len(categories)}")

    for cat, items in sorted(categories.items(), key=lambda x: sum(i["size"] for i in x[1]), reverse=True):
        cat_size = sum(i["size"] for i in items)
        cat_size_mb = cat_size / (1024*1024)

        print(f"\n[{cat.upper()}] - {len(items)} oge - {cat_size_mb:.2f} MB")
        print("-"*70)

        for item in items[:5]:
            age = f"({item['age_days']} gunluk)" if item['age_days'] > 0 else ""
            size = f"{item['size_mb']:.2f} MB" if item['size_mb'] > 1 else f"{item['size']/1024:.1f} KB"
            print(f"  {item['path']:50s} | {size:>10s} {age}")

        if len(items) > 5:
            print(f"  ... ve {len(items)-5} oge daha")

    print("\n" + "="*70)
    print(f"TOPLAM SILINEBILECEK: {total_size/1024/1024:.2f} MB")
    print("="*70)

    # Guvenli silme komutlari
    print("\n[GUVENLI SILME KOMUTLARI]")
    print("-"*70)

    if categories.get("__pycache__"):
        print("# __pycache__ temizle")
        print("Get-ChildItem -Recurse -Filter '__pycache__' | Remove-Item -Recurse -Force")
        print()

    if categories.get(".pyc"):
        print("# .pyc temizle")
        print("Get-ChildItem -Recurse -Filter '*.pyc' | Remove-Item -Force")
        print()

    if categories.get(".log"):
        print("# Log temizle")
        print("Get-ChildItem -Recurse -Filter '*.log' | Remove-Item -Force")
        print()

    if categories.get("temp"):
        print("# Gecici dosyalar")
        print("Get-ChildItem -Recurse -Filter '*.tmp' | Remove-Item -Force")
        print("Get-ChildItem -Recurse -Filter '*.temp' | Remove-Item -Force")
        print()

    print("# Git optimize")
    print("git gc --aggressive --prune=now")
    print()

    # Tek seferde hepsi
    print("[TEK SEFERDE TUMU]")
    print("-"*70)
    print("Get-ChildItem -Recurse -Filter '__pycache__' | Remove-Item -Recurse -Force; Get-ChildItem -Recurse -Filter '*.pyc' | Remove-Item -Force; Get-ChildItem -Recurse -Filter '*.log' | Remove-Item -Force; git gc --aggressive --prune=now; Write-Host 'TEMIZLIK TAMAMLANDI' -ForegroundColor Green")

if __name__ == "__main__":
    analyze()

