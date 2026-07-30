"""
Atlas AI - BOM Fix
JSON dosyalarindaki UTF-8 BOM problemini cozer.
"""

import json
from pathlib import Path


def fix_json_bom(filepath):
    """JSON dosyasindaki BOM'u temizle"""
    path = Path(filepath)

    if not path.exists():
        print(f"❌ Dosya bulunamadi: {filepath}")
        return False

    # Dosyayi binary modda oku
    with open(path, 'rb') as f:
        raw = f.read()

    # BOM kontrol et ve kaldir
    if raw.startswith(b'\xef\xbb\xbf'):
        raw = raw[3:]
        print(f"🧹 BOM kaldirildi: {filepath}")

    # JSON olarak parse et
    try:
        data = json.loads(raw.decode('utf-8'))
    except Exception as e:
        print(f"❌ JSON hatasi: {e}")
        return False

    # Temiz olarak kaydet
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"✅ Duzeltildi: {filepath}")
    return True


def fix_all_json_in_data():
    """data klasorundeki tum JSON dosyalarini duzelt"""
    data_dir = Path("data")

    if not data_dir.exists():
        print("❌ data klasoru bulunamadi!")
        return

    json_files = list(data_dir.glob("*.json"))

    if not json_files:
        print("⚠️  data klasorunde JSON dosyasi yok")
        return

    print(f"🔍 {len(json_files)} JSON dosyasi kontrol ediliyor...")
    print("-" * 40)

    fixed = 0
    for file in json_files:
        if fix_json_bom(file):
            fixed += 1

    print("-" * 40)
    print(f"✅ {fixed} dosya duzeltildi")


if __name__ == "__main__":
    fix_all_json_in_data()

