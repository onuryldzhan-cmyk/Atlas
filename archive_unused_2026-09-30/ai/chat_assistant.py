import json
import os
import re
from datetime import datetime


class AtlasChatAssistant:
    """
    Atlas AI - Smart Chat Assistant
    Understands context, learns from conversations
    """
    
    def __init__(self, data_dir="data/chat_memory"):
        self.data_dir = data_dir
        self.memory_file = os.path.join(data_dir, "conversations.json")
        self.stats_file = os.path.join(data_dir, "daily_stats.json")
        self.context = []  # Conversation history
        self.conversations = []
        self.daily_stats = {
            "trades_opened": 0,
            "trades_closed": 0,
            "win_count": 0,
            "loss_count": 0,
            "total_pnl": 0.0,
            "win_rate": 0.0,
        }
        self._load_memory()
        self._load_stats()
    
    def _load_memory(self):
        if os.path.exists(self.memory_file):
            with open(self.memory_file, "r") as f:
                self.conversations = json.load(f)
    
    def _save_memory(self):
        os.makedirs(self.data_dir, exist_ok=True)
        with open(self.memory_file, "w") as f:
            json.dump(self.conversations, f, indent=2, default=str)
    
    def _load_stats(self):
        if os.path.exists(self.stats_file):
            with open(self.stats_file, "r") as f:
                self.daily_stats = json.load(f)
    
    def save_stats(self, stats):
        self.daily_stats = stats
        os.makedirs(self.data_dir, exist_ok=True)
        with open(self.stats_file, "w") as f:
            json.dump(stats, f, indent=2, default=str)
    
    def ask(self, question):
        question = question.lower().strip()
        
        # Add to context
        self.context.append({"role": "user", "text": question})
        if len(self.context) > 10:
            self.context.pop(0)
        
        # Smart intent detection
        answer = self._detect_intent(question)
        
        # Add to memory
        self.conversations.append({
            "timestamp": datetime.now().isoformat(),
            "question": question,
            "answer": answer,
        })
        self._save_memory()
        
        # Add to context
        self.context.append({"role": "assistant", "text": answer})
        
        return answer
    
    def _detect_intent(self, question):
        """Smart intent detection with multiple patterns"""
        
        # TRADE COUNT - many variations
        if any(w in question for w in ["kac islem", "how many trade", "kac trade", "islem sayisi", "trade count", "kac pozisyon", "how many position"]):
            return self._answer_trade_count()
        
        # WIN RATE - many variations
        elif any(w in question for w in ["kazanma orani", "win rate", "basari orani", "ne kadar kazaniyorum", "kac tane kazandi", "success rate"]):
            return self._answer_win_rate()
        
        # PNL / PROFIT
        elif any(w in question for w in ["pnl", "kar", "profit", "kazanc", "ne kadar para", "balance", "bakiye", "portfoy degeri"]):
            return self._answer_pnl()
        
        # STATUS
        elif any(w in question for w in ["durum", "status", "nasıl", "nasil", "sistem", "ne yapıyor", "ne yapıyorsun"]):
            return self._answer_status()
        
        # IMPROVEMENTS
        elif any(w in question for w in ["gelistir", "improve", "neler yapabilirim", "oneri", "tavsiye", "nasil daha iyi", "arttir", "yükselt"]):
            return self._answer_improvements()
        
        # BACKTEST
        elif any(w in question for w in ["backtest", "test", "gecmis", "simulasyon"]):
            return "Backtest calistirmak icin: python main.py -> Menu 1"
        
        # RISK / PORTFOLIO
        elif any(w in question for w in ["risk", "profil", "portfoy", "portfolio", "dagilim", "allocation"]):
            return "Risk profilleri: LOW, MEDIUM, HIGH. Portfoy dagilimi icin: python main.py -> Menu 3"
        
        # SCANNER
        elif any(w in question for w in ["scan", "tara", "coin", "fiyat", "price", "piyasa", "market"]):
            return "Coin taramak icin: python main.py -> Menu 2"
        
        # GREETING
        elif any(w in question for w in ["merhaba", "hello", "hi", "selam", "hey"]):
            return "Merhaba! Ben Atlas AI. Bugun size nasil yardimci olabilirim? Islem sayisi, kazanma orani, sistem durumu veya gelistirme onerileri hakkinda soru sorabilirsiniz."
        
        # THANKS
        elif any(w in question for w in ["tesekkur", "thanks", "sagol", "tesekkurler", "thank you"]):
            return "Rica ederim! Baska bir sorunuz varsa bekliyorum."
        
        # GOODBYE
        elif any(w in question for w in ["gule gule", "bye", "cik", "exit", "kapat", "görüşürüz"]):
            return "Gorusmek uzere! Basarili islemler dilerim."
        
        # CONTEXT-AWARE: if previous was about trades
        elif self._context_check("trade"):
            return "Baska bir islem bilgisi mi istiyorsunuz? Ornegin: kazanma orani, PnL veya sistem durumu?"
        
        # CONTEXT-AWARE: if previous was about PnL
        elif self._context_check("pnl"):
            return "Daha fazla finansal bilgi mi istiyorsunuz? Portfoy dagilimi veya risk profili hakkinda soru sorabilirsiniz."
        
        # DEFAULT with suggestions
        else:
            return "Anladim. Size yardimci olabilmem icin su konularda soru sorabilirsiniz:\n" \
                   "  - Bugun kac islem acildi?\n" \
                   "  - Kazanma oranim ne?\n" \
                   "  - Sistem durumu nedir?\n" \
                   "  - Neleri gelistirebiliriz?\n" \
                   "  - Toplam PnL nedir?"
    
    def _context_check(self, topic):
        """Check if recent context is about a topic"""
        if not self.context:
            return False
        recent = self.context[-2:] if len(self.context) >= 2 else self.context
        texts = " ".join([c["text"] for c in recent])
        return topic in texts
    
    def _answer_trade_count(self):
        o = self.daily_stats["trades_opened"]
        c = self.daily_stats["trades_closed"]
        if o == 0:
            return "Bugun henuz islem acilmadi. Sistem aktif olarak piyasayi izliyor."
        return "Bugun " + str(o) + " islem acildi ve " + str(c) + " islem kapandi. Su an " + str(o - c) + " acik pozisyon var."
    
    def _answer_win_rate(self):
        w = self.daily_stats["win_count"]
        l = self.daily_stats["loss_count"]
        wr = self.daily_stats["win_rate"]
        total = w + l
        if total == 0:
            return "Henuz islem yapilmadi. Ilk islem acildiginde kazanma orani hesaplanacak."
        return "Kazanma oraniniz " + str(round(wr, 1)) + "%. Toplam " + str(total) + " islemden " + str(w) + " kazanan, " + str(l) + " kaybeden."
    
    def _answer_pnl(self):
        pnl = self.daily_stats["total_pnl"]
        sign = "+" if pnl >= 0 else ""
        if pnl == 0:
            return "Henuz realise edilmis bir kar/zarar yok. Sistem aktif olarak calisiyor."
        return "Bugunku toplam PnL: " + sign + "$" + str(round(pnl, 2)) + ". Portfoy degeriniz guncelleniyor."
    
    def _answer_status(self):
        o = self.daily_stats["trades_opened"]
        c = self.daily_stats["trades_closed"]
        status = "aktif ve calisiyor"
        if o > 0:
            status += ". " + str(o) + " islem acildi, " + str(c) + " islem kapandi"
        return "Atlas AI sistemi " + status + ". Tum moduller yuklu ve piyasa izleniyor."
    
    def _answer_improvements(self):
        return "Atlas'i gelistirmek icin onerilerim:\n" \
               "1. Gercek AI modeli ekle (LSTM/Transformer ile fiyat tahmini)\n" \
               "2. Pattern recognition sistemi (teknik formasyonlari tanima)\n" \
               "3. Reinforcement Learning (stratejiyi kendi kendine ogrenme)\n" \
               "4. Multi-Agent debate sistemi (birden fazla AI'nin tartismasi)\n" \
               "5. Gercek Binance verisi ile backtest\n" \
               "6. Sentiment analysis (Twitter/News analizi)\n" \
               "7. Market regime detection (piyasa durumunu algilama)\n" \
               "8. Dynamic position sizing (risk'e gore pozisyon ayarlama)"


if __name__ == "__main__":
    assistant = AtlasChatAssistant()
    print("=" * 60)
    print("ATLAS AI SMART CHAT TEST")
    print("=" * 60)
    
    tests = [
        "merhaba",
        "bugun kac islem acildi",
        "kazanma oranim ne kadar",
        "toplam kar ne durumda",
        "sistem nasil calisiyor",
        "neleri gelistirebiliriz",
        "tesekkurler",
        "gule gule",
    ]
    
    for q in tests:
        print("")
        print("You: " + q)
        print("Atlas: " + assistant.ask(q))
    
    print("")
    print("=" * 60)