"""
Atlas AI - Module Health Monitor
Modul sagligini surekli izleyen, sorunlari erken tespit eden,
ve sistem sagligi hakkinda rapor ureten monitor sistemi.
Dependency Graph ve Architecture Analyzer ile entegre calisir.
"""

import json
import time
from pathlib import Path
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, field, asdict
from datetime import datetime
from collections import defaultdict
import threading


@dataclass
class HealthCheck:
    """Tek bir saglik kontrolunun sonucu"""
    module_name: str
    check_name: str
    status: str  # healthy, warning, critical, error
    message: str
    timestamp: float = field(default_factory=time.time)
    details: Dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        data = asdict(self)
        data['timestamp'] = datetime.fromtimestamp(self.timestamp).isoformat()
        return data


@dataclass
class ModuleHealth:
    """Bir modulun genel saglik durumu"""
    module_name: str
    overall_status: str = "unknown"  # healthy, warning, critical, error
    last_check: float = 0.0
    check_count: int = 0
    error_count: int = 0
    warning_count: int = 0
    consecutive_errors: int = 0
    consecutive_warnings: int = 0
    average_response_time: float = 0.0
    checks: List[HealthCheck] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "module_name": self.module_name,
            "overall_status": self.overall_status,
            "last_check": datetime.fromtimestamp(self.last_check).isoformat() if self.last_check else None,
            "check_count": self.check_count,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "consecutive_errors": self.consecutive_errors,
            "consecutive_warnings": self.consecutive_warnings,
            "average_response_time": round(self.average_response_time, 3),
            "recent_checks": [c.to_dict() for c in self.checks[-5:]]
        }


class ModuleHealthMonitor:
    """
    Atlas AI modullerinin sagligini surekli izler.

    Ozellikler:
    - Modul basina saglik skoru
    - Otomatik saglik kontrolleri
    - Kritik modul tespiti
    - Trend analizi (iyilesme/kotulesme)
    - Uyari sistemi
    """

    STATUS_WEIGHTS = {
        "healthy": 0,
        "warning": 1,
        "critical": 2,
        "error": 3
    }

    def __init__(self, root_path: str = "."):
        self.root_path = Path(root_path).resolve()
        self.module_healths: Dict[str, ModuleHealth] = {}
        self.check_history: List[Dict] = []
        self._running = False
        self._monitor_thread = None
        self._callbacks: List[Callable] = []

    def register_module(self, module_name: str) -> ModuleHealth:
        """Yeni bir modulu izlemeye al"""
        if module_name not in self.module_healths:
            self.module_healths[module_name] = ModuleHealth(module_name=module_name)
        return self.module_healths[module_name]

    def run_health_check(self, module_name: str, check_func: Callable, check_name: str = "general") -> HealthCheck:
        """Bir modul icin saglik kontrolu calistir"""
        health = self.register_module(module_name)

        start_time = time.time()
        try:
            result = check_func()
            response_time = time.time() - start_time

            if isinstance(result, tuple):
                status, message = result
                details = {}
            elif isinstance(result, dict):
                status = result.get("status", "healthy")
                message = result.get("message", "OK")
                details = result.get("details", {})
            else:
                status = "healthy" if result else "error"
                message = "Check passed" if result else "Check failed"
                details = {}

        except Exception as e:
            response_time = time.time() - start_time
            status = "error"
            message = f"Exception: {str(e)}"
            details = {"exception": str(e)}

        check = HealthCheck(
            module_name=module_name,
            check_name=check_name,
            status=status,
            message=message,
            details=details
        )

        # Modul sagligini guncelle
        health.checks.append(check)
        health.last_check = time.time()
        health.check_count += 1

        # Yanit suresi ortalamasi
        health.average_response_time = (
            (health.average_response_time * (health.check_count - 1) + response_time)
            / health.check_count
        )

        # Durum sayaclarini guncelle
        if status == "error":
            health.error_count += 1
            health.consecutive_errors += 1
            health.consecutive_warnings = 0
        elif status == "warning":
            health.warning_count += 1
            health.consecutive_warnings += 1
            health.consecutive_errors = 0
        else:
            health.consecutive_errors = 0
            health.consecutive_warnings = 0

        # Genel durumu belirle
        health.overall_status = self._determine_overall_status(health)

        # Kritik durum kontrolu
        if status in ("critical", "error"):
            self._trigger_alert(module_name, check)

        return check

    def _determine_overall_status(self, health: ModuleHealth) -> str:
        """Modulun genel durumunu belirle"""
        if health.consecutive_errors >= 3:
            return "critical"
        if health.consecutive_errors >= 1:
            return "error"
        if health.consecutive_warnings >= 3:
            return "warning"
        if health.warning_count > health.check_count * 0.3:
            return "warning"
        if health.check_count == 0:
            return "unknown"
        return "healthy"

    def _trigger_alert(self, module_name: str, check: HealthCheck) -> None:
        """Kritik durumda uyari tetikle"""
        alert = {
            "type": "health_alert",
            "module": module_name,
            "severity": check.status,
            "message": check.message,
            "timestamp": datetime.now().isoformat()
        }

        self.check_history.append(alert)

        # Kayitli callbackleri cagir
        for callback in self._callbacks:
            try:
                callback(alert)
            except Exception:
                pass

    def add_alert_callback(self, callback: Callable) -> None:
        """Uyari callbacki ekle"""
        self._callbacks.append(callback)

    def get_module_health(self, module_name: str) -> Optional[ModuleHealth]:
        """Bir modulun saglik durumunu getir"""
        return self.module_healths.get(module_name)

    def get_unhealthy_modules(self) -> List[ModuleHealth]:
        """Sagliksiz modulleri getir"""
        return [
            health for health in self.module_healths.values()
            if health.overall_status in ("warning", "critical", "error")
        ]

    def get_critical_modules(self) -> List[ModuleHealth]:
        """Kritik durumdaki modulleri getir"""
        return [
            health for health in self.module_healths.values()
            if health.overall_status == "critical"
        ]

    def get_health_trend(self, module_name: str, window: int = 10) -> str:
        """Bir modulun saglik trendini analiz et"""
        health = self.module_healths.get(module_name)
        if not health or len(health.checks) < 2:
            return "insufficient_data"

        recent = health.checks[-window:]
        statuses = [self.STATUS_WEIGHTS.get(c.status, 0) for c in recent]

        # Trend hesapla
        if len(statuses) >= 3:
            first_half = sum(statuses[:len(statuses)//2]) / max(len(statuses)//2, 1)
            second_half = sum(statuses[len(statuses)//2:]) / max(len(statuses) - len(statuses)//2, 1)

            if second_half < first_half:
                return "improving"
            elif second_half > first_half:
                return "degrading"

        return "stable"

    def get_system_health_score(self) -> float:
        """Tum sistemin saglik skorunu hesapla (0-100)"""
        if not self.module_healths:
            return 0.0

        total_score = 0
        for health in self.module_healths.values():
            if health.overall_status == "healthy":
                total_score += 100
            elif health.overall_status == "warning":
                total_score += 60
            elif health.overall_status == "error":
                total_score += 30
            elif health.overall_status == "critical":
                total_score += 0
            else:
                total_score += 50

        return total_score / len(self.module_healths)

    def run_batch_checks(self, checks: Dict[str, Callable]) -> Dict[str, HealthCheck]:
        """Birden fazla modul icin toplu saglik kontrolu"""
        results = {}
        for module_name, check_func in checks.items():
            results[module_name] = self.run_health_check(module_name, check_func)
        return results

    def start_monitoring(self, interval: int = 60) -> None:
        """Arka planda surekli izlemeyi baslat"""
        if self._running:
            return

        self._running = True

        def monitor_loop():
            while self._running:
                # Tum modulleri kontrol et
                for module_name in self.module_healths:
                    # Varsayilan kontrol: dosya var mi?
                    def default_check():
                        module_path = self.root_path / f"{module_name.replace('.', '/')}.py"
                        if module_path.exists():
                            return ("healthy", f"Modul dosyasi mevcut: {module_path}")
                        return ("error", f"Modul dosyasi bulunamadi: {module_path}")

                    self.run_health_check(module_name, default_check, "file_exists")

                time.sleep(interval)

        self._monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
        self._monitor_thread.start()
        print(f"Module Health Monitor basladi (interval: {interval}s)")

    def stop_monitoring(self) -> None:
        """Izlemeyi durdur"""
        self._running = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5)
        print("Module Health Monitor durduruldu.")

    def get_full_report(self) -> Dict:
        """Tam saglik raporu"""
        unhealthy = self.get_unhealthy_modules()
        critical = self.get_critical_modules()

        return {
            "timestamp": datetime.now().isoformat(),
            "system_health_score": round(self.get_system_health_score(), 2),
            "total_modules": len(self.module_healths),
            "healthy_modules": len(self.module_healths) - len(unhealthy),
            "warning_modules": len([h for h in unhealthy if h.overall_status == "warning"]),
            "error_modules": len([h for h in unhealthy if h.overall_status == "error"]),
            "critical_modules": len(critical),
            "modules": {name: health.to_dict() for name, health in self.module_healths.items()},
            "alerts": self.check_history[-20:]  # Son 20 uyari
        }

    def print_dashboard(self) -> None:
        """Saglik dashboardunu ekrana yazdir"""
        report = self.get_full_report()

        print("\n" + "="*70)
        print("ATLAS AI - MODULE HEALTH MONITOR DASHBOARD")
        print("="*70)
        print(f"Zaman:                {report['timestamp']}")
        print(f"Sistem Saglik Skoru:  {report['system_health_score']}/100")
        print(f"Toplam Modul:         {report['total_modules']}")
        print(f"  Saglikli:           {report['healthy_modules']}")
        print(f"  Uyari:              {report['warning_modules']}")
        print(f"  Hata:               {report['error_modules']}")
        print(f"  Kritik:             {report['critical_modules']}")
        print("="*70)

        # Sagliksiz modulleri goster
        if report['warning_modules'] > 0 or report['error_modules'] > 0 or report['critical_modules'] > 0:
            print("\nSAGLIKSIZ MODULLER:")
            for name, health in self.module_healths.items():
                if health.overall_status != "healthy":
                    status_icon = {
                        "warning": "!",
                        "error": "X",
                        "critical": "!!!"
                    }.get(health.overall_status, "?")
                    print(f"   [{status_icon}] {name}: {health.overall_status.upper()}")
                    print(f"       Son kontrol: {datetime.fromtimestamp(health.last_check).strftime('%H:%M:%S') if health.last_check else 'Hic'}")
                    if health.checks:
                        print(f"       Son mesaj: {health.checks[-1].message}")

        # Trend analizi
        print("\nTREND ANALIZI:")
        for name in list(self.module_healths.keys())[:5]:
            trend = self.get_health_trend(name)
            trend_icon = {
                "improving": "📈",
                "stable": "➡️",
                "degrading": "📉",
                "insufficient_data": "❓"
            }.get(trend, "?")
            print(f"   {trend_icon} {name}: {trend}")

        print("="*70)

    def export_report(self, filepath: str = "health_report.json") -> None:
        """Raporu JSON olarak kaydet"""
        report = self.get_full_report()

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        print(f"\nSaglik raporu kaydedildi: {filepath}")


# ═══════════════════════════════════════════════════════════════
# TEST / DEMO
# ═══════════════════════════════════════════════════════════════

def demo_checks():
    """Demo saglik kontrolleri"""

    def check_brain():
        import random
        status = random.choice(["healthy", "healthy", "healthy", "warning", "healthy"])
        return (status, f"Brain status: {status}")

    def check_database():
        return ("healthy", "Database connection OK")

    def check_trading():
        import random
        if random.random() < 0.2:
            return ("error", "Trading engine timeout")
        return ("healthy", "Trading engine running")

    def check_memory():
        return ("warning", "Memory usage at 85%")

    return {
        "core.atlas_brain": check_brain,
        "core.database": check_database,
        "core.trading_engine": check_trading,
        "core.memory": check_memory,
        "ai.learning_brain": check_brain,
    }


if __name__ == "__main__":
    print("Atlas AI Module Health Monitor - Test Modu")
    print("-" * 50)

    monitor = ModuleHealthMonitor()

    # Demo kontrolleri calistir
    checks = demo_checks()
    print("\nSaglik kontrolleri calistiriliyor...")
    results = monitor.run_batch_checks(checks)

    for module, check in results.items():
        icon = {"healthy": "✅", "warning": "⚠️", "error": "❌", "critical": "🔴"}.get(check.status, "❓")
        print(f"  {icon} {module}: {check.status} - {check.message}")

    # Dashboard goster
    monitor.print_dashboard()
    monitor.export_report()

    print("\nTest tamamlandi!")
