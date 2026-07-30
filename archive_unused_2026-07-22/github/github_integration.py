"""
Atlas AI - GitHub Integration Module
Profesyonel GitHub yonetimi
"""
import json
import os
import sys
import subprocess
from datetime import datetime
from pathlib import Path
from typing import List, Dict

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

class GitCommand:
    @staticmethod
    def run(cmd: List[str], cwd=None):
        try:
            result = subprocess.run(["git"] + cmd, cwd=cwd or PROJECT_ROOT,
                capture_output=True, text=True, encoding="utf-8", timeout=30)
            return result.returncode == 0, result.stdout, result.stderr
        except Exception as e:
            return False, "", str(e)

    @staticmethod
    def is_repo():
        ok, _, _ = GitCommand.run(["rev-parse", "--git-dir"])
        return ok

    @staticmethod
    def get_status():
        ok, out, _ = GitCommand.run(["status", "--porcelain"])
        if not ok: return {"error": out}
        modified, untracked, deleted = [], [], []
        for line in out.strip().split("\n"):
            if not line: continue
            st, fn = line[:2], line[3:].strip()
            if "M" in st: modified.append(fn)
            elif "??" in st: untracked.append(fn)
            elif "D" in st: deleted.append(fn)
        return {"modified": modified, "untracked": untracked, "deleted": deleted,
                "has_changes": len(modified)+len(untracked)+len(deleted) > 0}

    @staticmethod
    def get_last_commit():
        ok, out, _ = GitCommand.run(["log", "-1", "--format=%H|%an|%ad|%s", "--date=iso"])
        if ok and out.strip():
            p = out.strip().split("|", 3)
            return {"hash": p[0][:8], "author": p[1], "date": p[2], "message": p[3]} if len(p)>=4 else {}
        return {}

    @staticmethod
    def get_commit_count():
        ok, out, _ = GitCommand.run(["rev-list", "--count", "HEAD"])
        return int(out.strip()) if ok else 0

    @staticmethod
    def get_branch():
        ok, out, _ = GitCommand.run(["branch", "--show-current"])
        return out.strip() if ok else "unknown"

    @staticmethod
    def get_remote_url():
        ok, out, _ = GitCommand.run(["remote", "get-url", "origin"])
        return out.strip() if ok else ""

class AtlasGitHubManager:
    def __init__(self):
        self.git = GitCommand()
        self.state_file = PROJECT_ROOT / "data" / "github_state.json"
        self.state = self._load_state()

    def _load_state(self):
        if self.state_file.exists():
            with open(self.state_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"last_commit_time": None, "commit_count": 0, "version": "0.0.0"}

    def _save_state(self):
        os.makedirs(self.state_file.parent, exist_ok=True)
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=2, ensure_ascii=False)

    def check_repo_health(self):
        if not self.git.is_repo():
            return {"status": "ERROR", "message": "Git repo yok!"}
        status = self.git.get_status()
        last = self.git.get_last_commit()
        return {
            "status": "OK", "branch": self.git.get_branch(),
            "remote": self.git.get_remote_url() or "Tanimli degil",
            "last_commit": last, "commit_count": self.git.get_commit_count(),
            "uncommitted": len(status.get("modified",[]))+len(status.get("untracked",[])),
            "needs_commit": status.get("has_changes", False)
        }

    def auto_commit(self, action="UPDATE", desc=""):
        if not self.git.is_repo(): return {"status": "ERROR"}
        status = self.git.get_status()
        if not status.get("has_changes"): return {"status": "NO_CHANGES"}
        self.git.run(["add", "."])
        msg = f"[Atlas AI] {action}: {desc or datetime.now().strftime('%Y-%m-%d %H:%M')}" 
        ok, _, err = self.git.run(["commit", "-m", msg])
        if ok:
            h = self.git.get_last_commit().get("hash", "?")
            self.state["last_commit_time"] = datetime.now().isoformat()
            self.state["commit_count"] = self.git.get_commit_count()
            self._save_state()
            self.git.run(["push", "origin", self.git.get_branch()])
            return {"status": "SUCCESS", "hash": h, "message": msg}
        return {"status": "FAILED", "error": err}

    def get_file_stats(self):
        stats = {"total_files": 0, "total_lines": 0, "modules": {}, "largest": []}
        for f in PROJECT_ROOT.rglob("*.py"):
            if "__pycache__" in str(f): continue
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    lines = len(fh.readlines())
                mod = f.parent.name
                if mod not in stats["modules"]:
                    stats["modules"][mod] = {"files": 0, "lines": 0}
                stats["modules"][mod]["files"] += 1
                stats["modules"][mod]["lines"] += lines
                stats["total_files"] += 1
                stats["total_lines"] += lines
                stats["largest"].append((str(f.relative_to(PROJECT_ROOT)), lines))
            except: pass
        stats["largest"].sort(key=lambda x: x[1], reverse=True)
        return stats

    def update_readme(self):
        readme = PROJECT_ROOT / "README.md"
        health = self.check_repo_health()
        stats = self.get_file_stats()
        content = f"""# Atlas AI
> Kendi kendini gelistiren otonom finansal yapay zeka

## Durum
| Metrik | Deger |
|--------|-------|
| Versiyon | {self.state.get('version','0.0.0')} |
| Commit | {health.get('commit_count',0)} |
| Branch | {health.get('branch','N/A')} |
| Guncelleme | {datetime.now().strftime('%Y-%m-%d %H:%M')} |

## Moduller ({stats['total_files']} dosya, {stats['total_lines']:,} satir)
"""
        for mod, info in sorted(stats["modules"].items(), key=lambda x: x[1]["lines"], reverse=True)[:10]:
            content += f"- **{mod}**: {info['files']} dosya, {info['lines']:,} satir\n"
        content += "\n## Uyari\nEgitim ve arastirma amaclidir.\n"
        with open(readme, "w", encoding="utf-8") as f:
            f.write(content)
        return {"status": "SUCCESS"}

def main():
    print("="*60)
    print("ATLAS AI - GITHUB INTEGRATION")
    print("="*60)
    m = AtlasGitHubManager()
    h = m.check_repo_health()
    if h.get("status") == "ERROR":
        print(f"Hata: {h['message']}")
        return
    print(f"Branch: {h['branch']} | Remote: {h['remote']}")
    print(f"Commit: {h['commit_count']} | Son: {h.get('last_commit',{}).get('hash','?')}")
    if h.get("needs_commit"):
        print(f"Commit bekleyen: {h['uncommitted']} dosya")
        r = m.auto_commit("AUTO_SYNC", "Otomatik senkronizasyon")
        print(f"Sonuc: {r['status']}")
    stats = m.get_file_stats()
    print(f"\n{stats['total_files']} dosya | {stats['total_lines']:,} satir")
    print("\nEn buyuk dosyalar:")
    for fn, ln in stats["largest"][:5]:
        print(f"  {fn:45s} | {ln:,} satir")
    m.update_readme()
    print("\nTamamlandi!")

if __name__ == "__main__":
    main()

