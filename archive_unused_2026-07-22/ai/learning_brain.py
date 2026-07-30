"""
Atlas AI - Learning Brain v2.0
Öğrenme ve hafıza yönetimi — güvenli path ve hata yönetimi ile.
"""

import os
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime

logger = logging.getLogger("AtlasAI.LearningBrain")


class LearningBrain:
    """
    Atlas AI Öğrenme Beyni v2.0

    Özellikler:
    - Güvenli dosya yolu yönetimi (absolute path)
    - JSON tabanlı kalıcı öğrenme hafızası
    - Model performans takibi
    - Hata koruması ve otomatik kurtarma
    """

    def __init__(self, project_root: str = None, memory_file: str = "database/model_memory.json"):
        """
        Learning Brain başlat.

        Args:
            project_root: Proje kök dizini (None = otomatik tespit)
            memory_file: Hafıza dosyası yolu (relative to project_root)
        """
        # Proje kökünü bul
        if project_root is None:
            # Bu dosyanın konumundan çıkar
            current_file = Path(__file__).resolve()
            # ai/learning_brain.py → project root
            self.project_root = current_file.parent.parent
        else:
            self.project_root = Path(project_root)

        # Absolute path kullan — relative path sorunlarını önle
        self.memory_file = self.project_root / memory_file
        self.memory_file.parent.mkdir(parents=True, exist_ok=True)

        # Öğrenme istatistikleri
        self.stats = {
            'total_learned': 0,
            'successful_predictions': 0,
            'failed_predictions': 0,
            'last_update': None
        }

        logger.info(f"Learning Brain v2.0 başlatıldı. Hafıza: {self.memory_file}")

    def _load_memory(self) -> Dict[str, Any]:
        """
        Öğrenme hafızasını güvenli şekilde yükle.

        Returns:
            Dict: Hafıza verileri
        """
        try:
            if not self.memory_file.exists():
                logger.info("Hafıza dosyası bulunamadı. Yeni oluşturuluyor.")
                return self._create_default_memory()

            with open(self.memory_file, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if not content:
                    return self._create_default_memory()

                memory = json.loads(content)
                logger.debug(f"Hafıza yüklendi: {len(memory)} kayıt")
                return memory

        except json.JSONDecodeError as e:
            logger.error(f"Hafıza dosyası bozuk: {e}. Yeniden oluşturuluyor.")
            return self._create_default_memory()
        except Exception as e:
            logger.error(f"Hafıza yükleme hatası: {e}")
            return self._create_default_memory()

    def _create_default_memory(self) -> Dict[str, Any]:
        """Varsayılan hafıza yapısı oluştur"""
        default = {
            "version": "2.0.0",
            "created_at": datetime.now().isoformat(),
            "models": {},
            "patterns": {},
            "performance_history": [],
            "learning_rate": 0.001,
            "confidence_threshold": 0.6
        }
        self._save_memory(default)
        return default

    def _save_memory(self, memory: Dict[str, Any]) -> bool:
        """
        Öğrenme hafızasını güvenli şekilde kaydet.

        Args:
            memory: Kaydedilecek hafıza verileri

        Returns:
            bool: Başarılı ise True
        """
        try:
            self.memory_file.parent.mkdir(parents=True, exist_ok=True)

            with open(self.memory_file, "w", encoding="utf-8") as f:
                json.dump(memory, f, indent=4, ensure_ascii=False)

            logger.debug("Hafıza kaydedildi.")
            return True

        except Exception as e:
            logger.error(f"Hafıza kaydetme hatası: {e}")
            return False

    def learn(self, model_name: str, data: Dict[str, Any]) -> bool:
        """
        Yeni bir öğrenme kaydı ekle.

        Args:
            model_name: Model adı (örn: "trend_predictor")
            data: Öğrenme verileri

        Returns:
            bool: Başarılı ise True
        """
        try:
            memory = self._load_memory()

            if "models" not in memory:
                memory["models"] = {}

            if model_name not in memory["models"]:
                memory["models"][model_name] = {
                    "created_at": datetime.now().isoformat(),
                    "updates": [],
                    "performance": {}
                }

            # Yeni öğrenme kaydı
            learning_record = {
                "timestamp": datetime.now().isoformat(),
                "data": data,
                "version": memory.get("version", "2.0.0")
            }

            memory["models"][model_name]["updates"].append(learning_record)

            # İstatistikleri güncelle
            self.stats['total_learned'] += 1
            self.stats['last_update'] = datetime.now().isoformat()

            success = self._save_memory(memory)

            if success:
                logger.info(f"[{model_name}] Yeni öğrenme kaydı eklendi.")

            return success

        except Exception as e:
            logger.error(f"Öğrenme hatası [{model_name}]: {e}")
            return False

    def predict(self, model_name: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Bir modelden tahmin al.

        Args:
            model_name: Model adı
            input_data: Girdi verileri

        Returns:
            Dict: Tahmin sonucu
        """
        try:
            memory = self._load_memory()

            if model_name not in memory.get("models", {}):
                logger.warning(f"[{model_name}] Model bulunamadı.")
                return {
                    "success": False,
                    "confidence": 0.0,
                    "prediction": None,
                    "reason": "Model not found"
                }

            model = memory["models"][model_name]
            updates = model.get("updates", [])

            if not updates:
                return {
                    "success": False,
                    "confidence": 0.0,
                    "prediction": None,
                    "reason": "No training data"
                }

            # Basit tahmin — son kayıtlara dayalı
            recent = updates[-10:]  # Son 10 kayıt

            # Basit çoğunluk oylaması veya ortalama
            predictions = [u["data"].get("outcome", 0) for u in recent if "outcome" in u["data"]]

            if not predictions:
                return {
                    "success": False,
                    "confidence": 0.0,
                    "prediction": None,
                    "reason": "No outcome data"
                }

            avg_prediction = sum(predictions) / len(predictions)
            confidence = min(0.95, len(predictions) / 100)  # Daha fazla veri = daha yüksek güven

            self.stats['successful_predictions'] += 1

            return {
                "success": True,
                "confidence": round(confidence, 2),
                "prediction": round(avg_prediction, 4),
                "based_on_records": len(predictions),
                "model": model_name
            }

        except Exception as e:
            self.stats['failed_predictions'] += 1
            logger.error(f"Tahmin hatası [{model_name}]: {e}")
            return {
                "success": False,
                "confidence": 0.0,
                "prediction": None,
                "reason": f"Error: {str(e)}"
            }

    def get_model_stats(self, model_name: str = None) -> Dict[str, Any]:
        """
        Model istatistiklerini döndür.

        Args:
            model_name: Belirli bir model (None = tümü)

        Returns:
            Dict: İstatistikler
        """
        try:
            memory = self._load_memory()
            models = memory.get("models", {})

            if model_name:
                if model_name in models:
                    model = models[model_name]
                    return {
                        "model": model_name,
                        "created_at": model.get("created_at"),
                        "update_count": len(model.get("updates", [])),
                        "performance": model.get("performance", {})
                    }
                return {"error": f"Model '{model_name}' bulunamadı"}

            # Tüm modeller
            return {
                "total_models": len(models),
                "models": {name: len(m.get("updates", [])) for name, m in models.items()},
                "brain_stats": self.stats
            }

        except Exception as e:
            logger.error(f"İstatistik hatası: {e}")
            return {"error": str(e)}

    def get_health(self) -> Dict[str, Any]:
        """Öğrenme beyni sağlık durumunu döndür"""
        total_predictions = self.stats['successful_predictions'] + self.stats['failed_predictions']
        success_rate = (self.stats['successful_predictions'] / total_predictions * 100) if total_predictions > 0 else 100.0

        return {
            "status": "healthy" if success_rate > 90 else "warning" if success_rate > 70 else "critical",
            "memory_file": str(self.memory_file),
            "memory_exists": self.memory_file.exists(),
            "total_learned": self.stats['total_learned'],
            "success_rate": round(success_rate, 1),
            "last_update": self.stats['last_update']
        }


# ═══════════════════════════════════════════════════════════════════════════════
# TEST
# ═══════════════════════════════════════════════════════════════════════════════

def test_learning_brain():
    """Learning Brain test fonksiyonu"""
    print("🧠 Atlas AI Learning Brain v2.0 - Test Mode")
    print("=" * 50)

    # Test için geçici hafıza kullan
    brain = LearningBrain(
        project_root=Path(__file__).parent.parent,
        memory_file="database/test_model_memory.json"
    )

    print("\n📚 Öğrenme kayıtları ekleniyor...")

    # Trend tahmini modeli eğit
    for i in range(5):
        brain.learn("trend_predictor", {
            "features": {"rsi": 65 + i, "ema": 100 + i},
            "outcome": 1 if i % 2 == 0 else -1,
            "accuracy": 0.8 + i * 0.02
        })
        print(f"   ✅ Kayıt {i+1} eklendi.")

    print("\n🔮 Tahmin yapılıyor...")
    prediction = brain.predict("trend_predictor", {
        "rsi": 70,
        "ema": 105
    })
    print(f"   Tahmin: {prediction}")

    print("\n📊 Model İstatistikleri:")
    stats = brain.get_model_stats("trend_predictor")
    for k, v in stats.items():
        print(f"   {k}: {v}")

    print("\n🏥 Sağlık Durumu:")
    health = brain.get_health()
    for k, v in health.items():
        print(f"   {k}: {v}")

    # Temizlik
    test_file = brain.memory_file
    if test_file.exists():
        test_file.unlink()
        print("\n🗑️  Test dosyası temizlendi.")

    print("\n✅ Learning Brain v2.0 test completed!")
    return brain


if __name__ == "__main__":
    test_learning_brain()
