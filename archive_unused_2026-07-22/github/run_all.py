"""
Atlas AI - Toplu Refactoring & GitHub Sync
Hepsini bir arada calistir
"""
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent

def run_command(cmd, description):
    """Komut calistir ve sonucu yazdir"""
    print(f"\n{'='*60}")
    print(f"🚀 {description}")
    print(f"{'='*60}")
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=PROJECT_ROOT)
        print(result.stdout)
        if result.stderr:
            print(f"⚠️  Uyari: {result.stderr}")
        return result.returncode == 0
    except Exception as e:
        print(f"❌ Hata: {e}")
        return False

def main():
    print("="*60)
    print("ATLAS AI - TOPLU REFACTORING & GITHUB SYNC")
    print("="*60)

    # 1. Background Service calistir
    run_command("python github/background_service.py", "Background Service - Dosya Analizi")

    # 2. GitHub Integration calistir
    run_command("python github/github_integration.py", "GitHub Integration - Sync & README")

    # 3. Git durumunu kontrol et
    run_command("git status", "Git Durum Kontrolu")

    print("\n" + "="*60)
    print("✅ Tum islemler tamamlandi!")
    print("="*60)

if __name__ == "__main__":
    main()

