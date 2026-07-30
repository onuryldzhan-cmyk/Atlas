"""
Atlas AI - Dependency Graph
Kendi kod yapısını analiz eden, modüller arası bağımlılıkları haritalayan sistem.
"""

import os
import ast
import json
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional
from dataclasses import dataclass, field, asdict
from collections import defaultdict


@dataclass
class ModuleInfo:
    """Bir modülün tüm bilgileri"""
    name: str
    file_path: str
    imports: List[str] = field(default_factory=list)
    imported_by: List[str] = field(default_factory=list)
    classes: List[str] = field(default_factory=list)
    functions: List[str] = field(default_factory=list)
    lines_of_code: int = 0
    docstring: str = ""
    has_main: bool = False
    complexity_score: float = 0.0
    
    def to_dict(self) -> dict:
        return asdict(self)


class DependencyGraph:
    """
    Atlas AI'nin tüm Python dosyalarını tarar ve:
    - Hangi modül hangi modülü import ediyor?
    - Kim kimden bağımlı?
    - Döngüsel bağımlılık var mı?
    - Hangi modül en kritik? (en çok import edilen)
    """
    
    def __init__(self, root_path: str = "."):
        self.root_path = Path(root_path).resolve()
        self.modules: Dict[str, ModuleInfo] = {}
        self.dependency_matrix: Dict[str, List[str]] = defaultdict(list)
        self.reverse_dependencies: Dict[str, List[str]] = defaultdict(list)
        self.circular_deps: List[List[str]] = []
        self.critical_modules: List[str] = []
        
    def scan_all_modules(self) -> None:
        """Tüm Python dosyalarını tara"""
        print("🔍 Atlas AI kod yapısı taranıyor...")
        
        # Tüm .py dosyalarını bul
        py_files = list(self.root_path.rglob("*.py"))
        total = len(py_files)
        
        for i, file_path in enumerate(py_files, 1):
            rel_path = str(file_path.relative_to(self.root_path))
            print(f"  [{i}/{total}] Analiz: {rel_path}")
            self._analyze_file(file_path)
            
        # Reverse dependencies oluştur
        self._build_reverse_dependencies()
        
        # Döngüsel bağımlılıkları bul
        self._detect_circular_dependencies()
        
        # Kritik modülleri belirle
        self._identify_critical_modules()
        
        print(f"\n✅ {total} modül tarandı.")
        print(f"🔗 {len(self.dependency_matrix)} bağımlılık ilişkisi bulundu.")
        print(f"⚠️  {len(self.circular_deps)} döngüsel bağımlılık tespit edildi.")
        print(f"⭐ {len(self.critical_modules)} kritik modül belirlendi.")
        
    def _analyze_file(self, file_path: Path) -> None:
        """Tek bir Python dosyasını analiz et"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                lines = content.split('\n')
        except Exception as e:
            print(f"    ⚠️ Okunamadı: {file_path} - {e}")
            return
            
        # AST parse et
        try:
            tree = ast.parse(content)
        except SyntaxError:
            print(f"    ⚠️ Syntax hatası: {file_path}")
            return
            
        # Modül adını oluştur (örn: core.dependency_graph)
        rel_path = file_path.relative_to(self.root_path)
        module_name = str(rel_path.with_suffix('')).replace(os.sep, '.')
        
        # Modül bilgisi oluştur
        module = ModuleInfo(
            name=module_name,
            file_path=str(rel_path),
            lines_of_code=len(lines)
        )
        
        # AST üzerinde gez
        for node in ast.walk(tree):
            # Import'ları bul
            if isinstance(node, ast.Import):
                for alias in node.names:
                    module.imports.append(alias.name)
                    
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    # Göreceli import'ları çözümle
                    if node.level > 0:
                        # from .module import x
                        base = '.'.join(module_name.split('.')[:-node.level])
                        if node.module:
                            full_import = f"{base}.{node.module}" if base else node.module
                        else:
                            full_import = base
                        module.imports.append(full_import)
                    else:
                        module.imports.append(node.module)
                        
            # Sınıfları bul
            elif isinstance(node, ast.ClassDef):
                module.classes.append(node.name)
                
            # Fonksiyonları bul
            elif isinstance(node, ast.FunctionDef):
                module.functions.append(node.name)
                if node.name == 'main':
                    module.has_main = True
                    
            # Docstring'i bul
            elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
                if isinstance(node.value.value, str) and not module.docstring:
                    module.docstring = node.value.value[:200]
                    
        # Karmaşıklık skoru
        module.complexity_score = (
            module.lines_of_code * 0.1 + 
            len(module.functions) * 2 + 
            len(module.classes) * 3
        )
        
        self.modules[module_name] = module
        self.dependency_matrix[module_name] = module.imports
        
    def _build_reverse_dependencies(self) -> None:
        """Kim kimin tarafından import ediliyor?"""
        for module_name, imports in self.dependency_matrix.items():
            for imp in imports:
                for mod_name in self.modules:
                    if imp == mod_name or mod_name.startswith(imp + '.'):
                        self.reverse_dependencies[mod_name].append(module_name)
                        self.modules[mod_name].imported_by.append(module_name)
                        
    def _detect_circular_dependencies(self) -> None:
        """Döngüsel bağımlılıkları bul (A -> B -> C -> A)"""
        visited = set()
        rec_stack = set()
        path = []
        
        def dfs(node: str):
            visited.add(node)
            rec_stack.add(node)
            path.append(node)
            
            for neighbor in self.dependency_matrix.get(node, []):
                matching_modules = [m for m in self.modules if m == neighbor or m.startswith(neighbor + '.')]
                
                for mod in matching_modules:
                    if mod not in visited:
                        dfs(mod)
                    elif mod in rec_stack:
                        cycle_start = path.index(mod)
                        cycle = path[cycle_start:] + [mod]
                        if cycle not in self.circular_deps:
                            self.circular_deps.append(cycle)
                            
            path.pop()
            rec_stack.remove(node)
            
        for module in self.modules:
            if module not in visited:
                dfs(module)
                
    def _identify_critical_modules(self) -> None:
        """En çok import edilen modülleri bul"""
        sorted_modules = sorted(
            self.modules.items(),
            key=lambda x: len(x[1].imported_by),
            reverse=True
        )
        
        self.critical_modules = [
            name for name, info in sorted_modules 
            if len(info.imported_by) >= 2
        ]
        
    def get_module_info(self, module_name: str) -> Optional[ModuleInfo]:
        return self.modules.get(module_name)
        
    def get_dependencies_of(self, module_name: str) -> List[str]:
        return self.dependency_matrix.get(module_name, [])
        
    def get_dependents_of(self, module_name: str) -> List[str]:
        return self.reverse_dependencies.get(module_name, [])
        
    def get_orphan_modules(self) -> List[str]:
        return [
            name for name, info in self.modules.items()
            if len(info.imported_by) == 0 and name != '__init__'
        ]
        
    def get_health_report(self) -> Dict:
        """Sistem sağlık raporu"""
        total_modules = len(self.modules)
        total_imports = sum(len(v) for v in self.dependency_matrix.values())
        avg_complexity = sum(m.complexity_score for m in self.modules.values()) / total_modules if total_modules > 0 else 0
        
        return {
            "total_modules": total_modules,
            "total_imports": total_imports,
            "circular_dependencies": len(self.circular_deps),
            "critical_modules_count": len(self.critical_modules),
            "orphan_modules": len(self.get_orphan_modules()),
            "average_complexity": round(avg_complexity, 2),
            "critical_modules": self.critical_modules[:10],
            "circular_dependency_details": self.circular_deps,
            "orphan_module_names": self.get_orphan_modules()
        }
        
    def export_to_json(self, filepath: str = "dependency_graph.json") -> None:
        """Tüm grafiği JSON olarak kaydet"""
        data = {
            "modules": {name: mod.to_dict() for name, mod in self.modules.items()},
            "dependency_matrix": dict(self.dependency_matrix),
            "reverse_dependencies": dict(self.reverse_dependencies),
            "circular_dependencies": self.circular_deps,
            "critical_modules": self.critical_modules,
            "health_report": self.get_health_report()
        }
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            
        print(f"\n💾 Bağımlılık grafiği kaydedildi: {filepath}")
        
    def print_summary(self) -> None:
        """Özet bilgiyi ekrana yazdır"""
        report = self.get_health_report()
        
        print("\n" + "="*60)
        print("📊 ATLAS AI - ARCHITECTURE INTELLIGENCE RAPORU")
        print("="*60)
        print(f"📦 Toplam Modül:        {report['total_modules']}")
        print(f"🔗 Toplam Bağımlılık:   {report['total_imports']}")
        print(f"⚠️  Döngüsel Bağımlılık: {report['circular_dependencies']}")
        print(f"⭐ Kritik Modül:         {report['critical_modules_count']}")
        print(f"🗑️  Yetim Modül:         {report['orphan_modules']}")
        print(f"📈 Ort. Karmaşıklık:    {report['average_complexity']}")
        print("="*60)
        
        if self.critical_modules:
            print("\n🏆 EN KRİTİK MODÜLLER:")
            for i, mod in enumerate(self.critical_modules[:5], 1):
                count = len(self.modules[mod].imported_by)
                print(f"   {i}. {mod} ({count} modül tarafından kullanılıyor)")
                
        if self.circular_deps:
            print("\n🔄 DÖNGÜSEL BAĞIMLILIKLAR:")
            for cycle in self.circular_deps:
                print(f"   {' -> '.join(cycle)}")
                
        if report['orphan_module_names']:
            print("\n🗑️ YETİM MODÜLLER:")
            for mod in report['orphan_module_names'][:5]:
                print(f"   • {mod}")


if __name__ == "__main__":
    print("🚀 Atlas AI Dependency Graph - Test Modu")
    print("-" * 50)
    
    graph = DependencyGraph()
    graph.scan_all_modules()
    graph.print_summary()
    graph.export_to_json()
    
    print("\n✅ Test tamamlandı!")
