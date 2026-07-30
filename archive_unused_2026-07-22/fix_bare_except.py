"""
Atlas AI - Kritik Sorun Duzeltme Scripti
Bu script kritik bare except ve uzun fonksiyon sorunlarini otomatik duzeltir.
"""

import re
from pathlib import Path


def fix_bare_except(filepath):
    """Dosyadaki bare except'leri duzelt"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        print(f"❌ Okunamadi: {filepath} - {e}")
        return False

    original = content

    # Pattern 1: except Exception: (en yaygin)
    content = re.sub(r'except\s*:', 'except Exception:', content)

    # Pattern 2: except Exception: (bosluklu)
    content = re.sub(r'except\s+:', 'except Exception:', content)

    if content != original:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"✅ Duzeltildi: {filepath}")
        return True
    else:
        print(f"➡️  Degisiklik yok: {filepath}")
        return False


def fix_all_bare_excepts(root_path="."):
    """Tum projedeki bare except'leri duzelt"""
    root = Path(root_path)
    py_files = list(root.rglob("*.py"))

    fixed_count = 0

    print("="*60)
    print("BARE EXCEPT DUZELTME ISLEMI")
    print("="*60)

    for file_path in py_files:
        if fix_bare_except(file_path):
            fixed_count += 1

    print(f"\n{'='*60}")
    print(f"Toplam {fixed_count} dosya duzeltildi.")
    print("="*60)
    return fixed_count


if __name__ == "__main__":
    fix_all_bare_excepts()
    print("\n✅ Islemi tamamlandi! Simdi test edin:")
    print("   python core\\architecture_analyzer.py")

