"""
Atlas AI - Temizlik Analiz Araci
Ne silinebilecegini goster, sen karar ver
"""
import os
from pathlib import Path
from collections import defaultdict

PROJECT_ROOT = Path(".")

def analyze_for_cleanup():
    """Silinebilecek dosyalari analiz et"""

    categories = defaultdict(list)
    total_size = 0

    for root, dirs, files in os.walk(PROJECT_ROOT):
        root_path = Path(root)

        # 1. __pycache__ klasorleri
        if "__pycache__" in dirs:
            pycache = root_path / "__pycache__"
            size = sum(f.stat().st_size for f in pycache.rglob("*") if f.is_file())
            categories["__pycache__"].append((str(pycache.relative_to(PROJECT_ROOT)), size))
            total_size += size
            dirs.remove("__pycache__")  # Altina inme

        # 2. .pyc dosyalari
        for file in files:
            if file.endswith(".pyc"):
                fpath = root_path / file
                size = fpath.stat().st_size
                categories[".pyc"].append((str(fpath.relative_to(PROJECT_ROOT)), size))
                total_size += size

            # 3. .pyo dosyalari
            elif file.endswith(".pyo"):
                fpath = root_path / file
                size = fpath.stat().st_size
                categories[".pyo"].append((str(fpath.relative_to(PROJECT_ROOT)), size))
                total_size += size

            # 4. Log dosyalari
            elif file.endswith(".log"):
                fpath = root_path / file
                size = fpath.stat().st_size
                categories[".log"].append((str(fpath.relative_to(PROJECT_ROOT)), size))
                total_size += size

            # 5. Gecici dosyalar
            elif file.endswith((".tmp", ".temp", "~")):
                fpath = root_path / file
                size = fpath.stat().st_size
                categories["temp"].append((str(fpath.relative_to(PROJECT_ROOT)), size))
                total_size += size

    # 6. .git klasoru (ozel)
    git_dir = PROJECT_ROOT / ".git"
    if git_dir.exists():
        git_size = sum(f.stat().st_size for f in git_dir.rglob("*") if f.is_file())
        categories[".git (tum)"].append((".git", git_size))

        # Eski commit objeleri
        objects_dir = git_dir / "objects"
        if objects_dir.exists():
            old_objects = list(objects_dir.rglob("*"))
            categories[".git/objects"].append((f"{len(old_objects)} obje", sum(f.stat().st_size for f in old_objects if f.is_file())))

    # 7. data klasorundeki buyuk dosyalar
    data_dir = PROJECT_ROOT / "data"
    if data_dir.exists():
        for f in data_dir.rglob("*"):
            if f.is_file() and f.stat().st_size > 1024*1024:  # 1MB ustu
                categories["data/buyuk_dosyalar"].append((str(f.relative_to(PROJECT_ROOT)), f.stat().st_size))
                total_size += f.stat().st_size

    return categories, total_size

def main():
    print("="*70)
    print("ATLAS AI - TEMIZLIK ANALIZ ARACI")
    print("="*70)
    print("\nNe silebilecegini analiz ediyorum...\n")

    categories, total_size = analyze_for_cleanup()

    grand_total = 0

    for cat, items in sorted(categories.items(), key=lambda x: sum(i[1] for i in x[1]), reverse=True):
        cat_size = sum(i[1] for i in items)
        grand_total += cat_size

        print(f"\n[{cat.upper()}] - {len(items)} oge - Toplam: {cat_size/1024/1024:.2f} MB")
        print("-"*70)

        for item_path, item_size in items[:10]:  # Ilk 10
            size_str = f"{item_size/1024:.1f} KB" if item_size < 1024*1024 else f"{item_size/1024/1024:.2f} MB"
            print(f"  {item_path:50s} | {size_str:>10s}")

        if len(items) > 10:
            print(f"  ... ve {len(items)-10} oge daha")

    print("\n" + "="*70)
    print(f"TOPLAM SILINEBILECEK: {grand_total/1024/1024:.2f} MB")
    print(f"TOPLAM OGELER: {sum(len(v) for v in categories.values())}")
    print("="*70)

    print("\n[ONERILEN TEMIZLIK KOMUTLARI]")
    print("-"*70)

    if categories.get("__pycache__"):
        print("# __pycache__ temizle (GUVENLI)")
        print("Get-ChildItem -Recurse -Filter '__pycache__' | Remove-Item -Recurse -Force")
        print()

    if categories.get(".pyc"):
        print("# .pyc dosyalarini temizle (GUVENLI)")
        print("Get-ChildItem -Recurse -Filter '*.pyc' | Remove-Item -Force")
        print()

    if categories.get(".log"):
        print("# Log dosyalarini temizle (DIKKAT - kontrol et)")
        print("Get-ChildItem -Recurse -Filter '*.log' | Remove-Item -Force")
        print()

    print("# .git gc ile git objelerini temizle (GUVENLI)")
    print("git gc --aggressive --prune=now")
    print()

    print("[UYARI] Silmeden once yedek al!")
    print("Compress-Archive -Path '.' -DestinationPath 'yedek.zip'")

if __name__ == "__main__":
    main()

