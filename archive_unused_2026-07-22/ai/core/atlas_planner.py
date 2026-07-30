# -*- coding: utf-8 -*-
"""
ATLAS PLANNER
Stratejik planlama motoru - Hedef, roadmap, kaynak yonetimi
"""
import random
import time
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field


@dataclass
class Goal:
    """Hedef"""
    id: str
    name: str
    description: str
    priority: str  # critical, high, medium, low
    deadline: Optional[datetime]
    progress: float  # 0-100
    status: str  # pending, active, completed, failed
    dependencies: List[str]  # Bagli oldugu hedef ID'leri
    resources: Dict  # Gerekli kaynaklar
    estimated_hours: int
    actual_hours: int = 0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class Milestone:
    """Kilometre tasi"""
    id: str
    name: str
    target_date: datetime
    goals: List[str]
    completed: bool = False
    completion_date: Optional[str] = None


@dataclass
class ResourceAllocation:
    """Kaynak tahsisi"""
    resource_type: str  # compute, memory, time, capital
    allocated: float
    used: float
    available: float
    unit: str


class AtlasPlanner:
    """
    Atlas AI Stratejik Planlama Motoru
    
    Planlama yetenekleri:
    1. Hedef Yonetimi - SMART hedefler olustur
    2. Roadmap Olusturma - Zamansal planlama
    3. Kaynak Optimizasyonu - Kaynaklari en verimli kullan
    4. Bagimlilik Yonetimi - Hedefler arasi iliskiler
    5. Risk Planlamasi - Plan B olustur
    6. Ilerleme Takibi - Gercek zamanli monitoring
    """
    
    # Atlas AI gelisim asamalari
    DEVELOPMENT_PHASES = {
        "phase_0": {"name": "Temel Sistem", "duration_days": 30, "modules": 15},
        "phase_1": {"name": "Mimari Zeka", "duration_days": 45, "modules": 20},
        "phase_2": {"name": "Cok Ajanli Sistem", "duration_days": 60, "modules": 25},
        "phase_3": {"name": "Uretim ve Ogrenme", "duration_days": 90, "modules": 30},
        "phase_4": {"name": "Ileri Seviye", "duration_days": 120, "modules": 20},
        "phase_5": {"name": "Otonom Ticaret", "duration_days": 180, "modules": 15},
    }
    
    # Kaynak tipleri
    RESOURCE_TYPES = {
        "compute": {"unit": "CPU saat", "daily_limit": 24},
        "memory": {"unit": "GB", "daily_limit": 64},
        "time": {"unit": "saat", "daily_limit": 16},
        "capital": {"unit": "USDT", "daily_limit": 1000},
    }
    
    def __init__(self):
        self.goals: List[Goal] = []
        self.milestones: List[Milestone] = []
        self.resources: Dict[str, ResourceAllocation] = {}
        self.roadmap: List[Dict] = []
        self.risk_plans: List[Dict] = []
        self.progress_history: List[Dict] = []
        
        # Baslangic kaynaklari
        for rtype, config in self.RESOURCE_TYPES.items():
            self.resources[rtype] = ResourceAllocation(
                resource_type=rtype,
                allocated=0,
                used=0,
                available=config["daily_limit"],
                unit=config["unit"],
            )
            
    def _generate_id(self) -> str:
        """Benzersiz ID olustur"""
        return f"PLAN_{int(time.time())}_{random.randint(1000, 9999)}"
    
    def create_goal(self, name: str, description: str, priority: str,
                    deadline_days: Optional[int] = None,
                    dependencies: List[str] = None,
                    estimated_hours: int = 40) -> Goal:
        """Yeni hedef olustur"""
        goal_id = self._generate_id()
        
        deadline = None
        if deadline_days:
            deadline = datetime.now() + timedelta(days=deadline_days)
            
        goal = Goal(
            id=goal_id,
            name=name,
            description=description,
            priority=priority,
            deadline=deadline,
            progress=0.0,
            status="pending",
            dependencies=dependencies or [],
            resources={},
            estimated_hours=estimated_hours,
        )
        
        self.goals.append(goal)
        return goal
    
    def create_roadmap(self, phase_name: str) -> List[Milestone]:
        """Gelisim asamasi icin roadmap olustur"""
        phase = self.DEVELOPMENT_PHASES.get(phase_name)
        if not phase:
            return []
            
        milestones = []
        num_milestones = 4  # Her asama 4 kilometre tasi
        
        for i in range(num_milestones):
            milestone_date = datetime.now() + timedelta(
                days=(phase["duration_days"] // num_milestones) * (i + 1)
            )
            
            # Bu asamaya ait hedefleri sec
            phase_goals = [g.id for g in self.goals 
                          if g.created_at > (datetime.now() - timedelta(days=30)).isoformat()]
            
            milestone = Milestone(
                id=self._generate_id(),
                name=f"{phase['name']} - Asama {i+1}",
                target_date=milestone_date,
                goals=random.sample(phase_goals, min(3, len(phase_goals))) if phase_goals else [],
            )
            
            milestones.append(milestone)
            
        self.milestones.extend(milestones)
        return milestones
    
    def allocate_resources(self, goal_id: str, requirements: Dict[str, float]) -> bool:
        """Kaynak tahsis et"""
        goal = next((g for g in self.goals if g.id == goal_id), None)
        if not goal:
            return False
            
        # Mevcut kaynaklari kontrol et
        for rtype, amount in requirements.items():
            if rtype not in self.resources:
                return False
                
            resource = self.resources[rtype]
            if resource.available < amount:
                return False
                
        # Tahsis et
        for rtype, amount in requirements.items():
            resource = self.resources[rtype]
            resource.allocated += amount
            resource.available -= amount
            goal.resources[rtype] = amount
            
        return True
    
    def optimize_schedule(self) -> List[Goal]:
        """Hedefleri optimize et ve sirala"""
        # Oncelige gore sirala
        priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        
        # Bagimliliklari coz
        resolved = []
        pending = list(self.goals)
        
        while pending:
            # Bagimliligi cozulmus hedefleri bul
            ready = [g for g in pending 
                    if all(dep in [r.id for r in resolved] for dep in g.dependencies)]
            
            if not ready:
                # Deadlock - kalanlari rastgele ekle
                ready = pending[:1]
                
            # Sirala
            ready.sort(key=lambda x: (
                priority_order.get(x.priority, 99),
                x.deadline or datetime.max,
                -x.progress
            ))
            
            for goal in ready:
                resolved.append(goal)
                pending.remove(goal)
                
        return resolved
    
    def calculate_progress(self) -> Dict:
        """Genel ilerlemeyi hesapla"""
        if not self.goals:
            return {"overall": 0, "by_priority": {}, "by_status": {}}
            
        total_progress = sum(g.progress for g in self.goals) / len(self.goals)
        
        by_priority = {}
        for p in ["critical", "high", "medium", "low"]:
            p_goals = [g for g in self.goals if g.priority == p]
            if p_goals:
                by_priority[p] = sum(g.progress for g in p_goals) / len(p_goals)
                
        by_status = {}
        for s in ["pending", "active", "completed", "failed"]:
            s_goals = [g for g in self.goals if g.status == s]
            by_status[s] = len(s_goals)
            
        return {
            "overall": total_progress,
            "by_priority": by_priority,
            "by_status": by_status,
            "completed_goals": len([g for g in self.goals if g.status == "completed"]),
            "total_goals": len(self.goals),
        }
    
    def create_risk_plan(self, goal_id: str) -> Dict:
        """Risk plani olustur"""
        goal = next((g for g in self.goals if g.id == goal_id), None)
        if not goal:
            return {}
            
        risks = [
            {
                "risk": "Teknik zorluk",
                "probability": random.uniform(0.2, 0.5),
                "impact": "high",
                "mitigation": "Alternatif teknolojileri arastir",
                "contingency": "Daha basit cozume gec",
            },
            {
                "risk": "Kaynak yetersizligi",
                "probability": random.uniform(0.1, 0.3),
                "impact": "medium",
                "mitigation": "Kaynaklari onceden rezerve et",
                "contingency": "Kapsami daralt",
            },
            {
                "risk": "Bagimli modul gecikmesi",
                "probability": random.uniform(0.3, 0.6),
                "impact": "medium",
                "mitigation": "Erken basla ve paralel calis",
                "contingency": "Mock implementasyon kullan",
            },
            {
                "risk": "Piyasa kosullari degisimi",
                "probability": random.uniform(0.1, 0.4),
                "impact": "low",
                "mitigation": "Esnek strateji tasarla",
                "contingency": "Parametreleri dinamik ayarla",
            },
        ]
        
        risk_plan = {
            "goal_id": goal_id,
            "goal_name": goal.name,
            "risks": risks,
            "overall_risk": sum(r["probability"] for r in risks) / len(risks),
            "created_at": datetime.now().isoformat(),
        }
        
        self.risk_plans.append(risk_plan)
        return risk_plan
    
    def simulate_execution(self, days: int = 30) -> List[Dict]:
        """Plan yurutmesini simule et"""
        timeline = []
        current_date = datetime.now()
        
        for day in range(days):
            # Her gun rastgele ilerleme
            for goal in self.goals:
                if goal.status == "completed":
                    continue
                    
                # Bagimliliklari kontrol et
                deps_completed = all(
                    next((g for g in self.goals if g.id == dep), None).status == "completed"
                    if any(g.id == dep for g in self.goals) else True
                    for dep in goal.dependencies
                )
                
                if deps_completed and goal.status == "pending":
                    goal.status = "active"
                    
                if goal.status == "active":
                    # Gunluk ilerleme
                    daily_progress = random.uniform(2, 8)
                    goal.progress = min(100, goal.progress + daily_progress)
                    goal.actual_hours += random.randint(2, 6)
                    
                    if goal.progress >= 100:
                        goal.status = "completed"
                        goal.progress = 100.0
                        
            # Kaynak tuketimi
            for rtype, resource in self.resources.items():
                daily_usage = random.uniform(0.3, 0.7) * resource.allocated
                resource.used += daily_usage
                resource.available = max(0, resource.available - daily_usage)
                
            timeline.append({
                "day": day + 1,
                "date": (current_date + timedelta(days=day)).strftime('%Y-%m-%d'),
                "active_goals": len([g for g in self.goals if g.status == "active"]),
                "completed_goals": len([g for g in self.goals if g.status == "completed"]),
                "overall_progress": self.calculate_progress()["overall"],
            })
            
        return timeline
    
    def generate_report(self) -> str:
        """Planlama raporu olustur"""
        progress = self.calculate_progress()
        
        report = f"""
==============================================================
         ATLAS PLANNER - STRATEJIK PLANLAMA RAPORU          
==============================================================
  Tarih: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
  
  HEDEF OZETI:
    Toplam: {progress['total_goals']}
    Tamamlanan: {progress['completed_goals']}
    Genel Ilerleme: {progress['overall']:.1f}%
    
  ONCELIGE GORE ILERLEME:
"""
        for priority, prog in progress['by_priority'].items():
            bar = "+" * int(prog / 5)
            report += f"    {priority:10s}: {bar} {prog:.1f}%\n"
            
        report += f"\n  DURUM DAGILIMI:\n"
        for status, count in progress['by_status'].items():
            report += f"    {status:12s}: {count}\n"
            
        report += f"\n  KAYNAK KULLANIMI:\n"
        for rtype, resource in self.resources.items():
            usage_pct = (resource.used / (resource.used + resource.available)) * 100 if (resource.used + resource.available) > 0 else 0
            report += f"    {rtype:10s}: {resource.used:.1f}/{resource.used + resource.available:.1f} {resource.unit} ({usage_pct:.0f}%)\n"
            
        report += f"\n  YAKLASAN KILOMETRE TASLARI:\n"
        upcoming = [m for m in self.milestones if not m.completed]
        upcoming.sort(key=lambda x: x.target_date)
        for m in upcoming[:3]:
            days_left = (m.target_date - datetime.now()).days
            report += f"    - {m.name} ({days_left} gun kaldi)\n"
            
        report += f"\n  RISK PLANLARI: {len(self.risk_plans)}\n"
            
        report += f"""
==============================================================
"""
        return report


# ==============================================================
# TEST
# ==============================================================

def test_planner():
    """Planlama motoru testi"""
    print("=" * 60)
    print("ATLAS PLANNER - STRATEJIK PLANLAMA TESTI")
    print("=" * 60)
    
    planner = AtlasPlanner()
    
    # 1. Hedef olusturma
    print("\n[1] Hedef Olusturma")
    print("-" * 50)
    
    goals = [
        planner.create_goal("Executive Brain", "Karar sentezi motoru", "critical", 30, [], 80),
        planner.create_goal("Alpha Factory", "Strateji uretim sistemi", "high", 45, [], 60),
        planner.create_goal("Backtesting Engine", "Gecmis test motoru", "high", 60, [], 100),
        planner.create_goal("Risk Manager AI", "AI tabanli risk yonetimi", "medium", 45, [], 50),
        planner.create_goal("Portfolio Optimizer", "Portfoy optimizasyonu", "medium", 60, [], 70),
    ]
    
    # Bagimliliklar ekle
    goals[2].dependencies = [goals[0].id]  # Backtesting -> Executive Brain
    goals[3].dependencies = [goals[0].id]  # Risk Manager -> Executive Brain
    goals[4].dependencies = [goals[1].id, goals[3].id]  # Portfolio -> Alpha + Risk
    
    for g in goals:
        print(f"  [{g.priority:8s}] {g.name} - {g.estimated_hours} saat")
        if g.dependencies:
            print(f"    Bagimli: {g.dependencies}")
    
    # 2. Roadmap olusturma
    print("\n[2] Roadmap Olusturma")
    print("-" * 50)
    milestones = planner.create_roadmap("phase_4")
    for m in milestones:
        print(f"  - {m.name}")
        print(f"    Hedef: {m.target_date.strftime('%Y-%m-%d')}")
        print(f"    Iliskili hedefler: {len(m.goals)}")
    
    # 3. Kaynak tahsisi
    print("\n[3] Kaynak Tahsisi")
    print("-" * 50)
    for goal in goals[:3]:
        requirements = {
            "compute": random.uniform(4, 12),
            "time": random.uniform(4, 8),
        }
        success = planner.allocate_resources(goal.id, requirements)
        print(f"  {goal.name}: {'Tahsis edildi' if success else 'Yetersiz kaynak'}")
        print(f"    Ihtiyac: {requirements}")
    
    # 4. Optimizasyon
    print("\n[4] Hedef Optimizasyonu")
    print("-" * 50)
    optimized = planner.optimize_schedule()
    print("  Siralama:")
    for i, g in enumerate(optimized, 1):
        deps = " (bagimli: " + ", ".join(g.dependencies[:2]) + ")" if g.dependencies else ""
        print(f"    {i}. [{g.priority}] {g.name}{deps}")
    
    # 5. Risk plani
    print("\n[5] Risk Plani")
    print("-" * 50)
    risk = planner.create_risk_plan(goals[0].id)
    print(f"  Hedef: {risk['goal_name']}")
    print(f"  Genel Risk: {risk['overall_risk']:.1%}")
    print(f"  Riskler:")
    for r in risk['risks']:
        print(f"    - {r['risk']} (Olasilik: {r['probability']:.0%}, Etki: {r['impact']})")
        print(f"      Onlem: {r['mitigation']}")
    
    # 6. Simulasyon
    print("\n[6] 30 Gun Simulasyonu")
    print("-" * 50)
    timeline = planner.simulate_execution(days=15)
    
    # Her 5 gunde bir ozet
    for entry in timeline[::5]:
        print(f"  Gun {entry['day']:2d}: Aktif: {entry['active_goals']} | "
              f"Tamamlanan: {entry['completed_goals']} | Ilerleme: {entry['overall_progress']:.1f}%")
    
    # 7. Ilerleme
    print("\n[7] Ilerleme Ozeti")
    print("-" * 50)
    progress = planner.calculate_progress()
    print(f"  Genel: {progress['overall']:.1f}%")
    print(f"  Tamamlanan: {progress['completed_goals']}/{progress['total_goals']}")
    print(f"  Oncelige gore:")
    for p, val in progress['by_priority'].items():
        print(f"    {p}: {val:.1f}%")
    
    # 8. Rapor
    print("\n" + "=" * 60)
    print(planner.generate_report())
    
    print("\n" + "=" * 60)
    print("[OK] PLANLAMA TEST TAMAMLANDI")
    print("=" * 60)


if __name__ == "__main__":
    test_planner()