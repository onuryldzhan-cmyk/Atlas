# -*- coding: utf-8 -*-
"""
ATLAS EXECUTION OPTIMIZER
Emir yurutme optimizasyonu - Slippage, timing, parcali emir, TWAP/VWAP
"""
import random
import time
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field


@dataclass
class ExecutionOrder:
    """Yurutme emri"""
    id: str
    symbol: str
    side: str  # BUY, SELL
    quantity: float
    price: float
    order_type: str  # MARKET, LIMIT, TWAP, VWAP, ICEBERG
    urgency: str  # low, medium, high
    max_slippage: float  # Maksimum kabul edilebilir slippage
    time_limit: int  # Saniye cinsinden zaman limiti
    status: str = "pending"
    filled_qty: float = 0.0
    avg_fill_price: float = 0.0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    executed_at: Optional[str] = None


@dataclass
class ExecutionResult:
    """Yurutme sonucu"""
    order_id: str
    success: bool
    filled_qty: float
    avg_price: float
    slippage: float
    fees: float
    execution_time: float
    child_orders: int
    strategy_used: str
    savings_vs_market: float


class AtlasExecutionOptimizer:
    """
    Atlas AI Emir Yurutme Optimizasyon Motoru
    
    Stratejiler:
    1. Market Order - Hizli ama slippage riski yuksek
    2. Limit Order - Slippage kontrolu ama doldurulma riski
    3. TWAP - Zaman agirlikli ortalama fiyat (buyuk emirler)
    4. VWAP - Hacim agirlikli ortalama fiyat
    5. Iceberg - Emiri parcalara bol (piyasa etkisini azalt)
    6. Smart Router - En iyi fiyat/derinlik kombinasyonu
    """
    
    # Borsa simulasyonu (gercek baglanti sonraki asama)
    EXCHANGE_FEES = {
        "maker": 0.0008,   # %0.08
        "taker": 0.0010,   # %0.10
    }
    
    # Slippage tahmini (emir buyuklugune gore)
    SLIPPAGE_TABLE = {
        (0, 1000): 0.0005,      # %0.05
        (1000, 5000): 0.0010,   # %0.10
        (5000, 20000): 0.0020,  # %0.20
        (20000, 50000): 0.0030, # %0.30
        (50000, float('inf')): 0.0050, # %0.50
    }
    
    def __init__(self):
        self.orders: List[ExecutionOrder] = []
        self.results: List[ExecutionResult] = []
        self.market_depth: Dict[str, List[Dict]] = {}  # Simule edilmis derinlik
        self.execution_history: List[Dict] = []
        
    def _estimate_slippage(self, symbol: str, quantity: float, side: str) -> float:
        """Slippage tahmini"""
        notional = quantity * random.uniform(30000, 70000)  # BTC fiyati varsayimi
        
        for (min_val, max_val), slippage in self.SLIPPAGE_TABLE.items():
            if min_val <= notional < max_val:
                # Volatilite etkisi
                volatility_factor = random.uniform(0.8, 1.5)
                return slippage * volatility_factor
                
        return 0.0050  # Varsayilan
    
    def _simulate_market_depth(self, symbol: str) -> List[Dict]:
        """Piyasa derinligi simulasyonu"""
        base_price = random.uniform(30000, 70000) if "BTC" in symbol else random.uniform(1500, 5000)
        
        bids = []
        asks = []
        
        for i in range(10):
            bid_price = base_price * (1 - i * 0.001)
            ask_price = base_price * (1 + i * 0.001)
            bid_qty = random.uniform(0.1, 5.0) * (1 / (i + 1))
            ask_qty = random.uniform(0.1, 5.0) * (1 / (i + 1))
            
            bids.append({"price": bid_price, "quantity": bid_qty})
            asks.append({"price": ask_price, "quantity": ask_qty})
            
        return {"bids": bids, "asks": asks, "base_price": base_price}
    
    def _select_strategy(self, order: ExecutionOrder) -> str:
        """En iyi yurutme stratejisini sec"""
        notional = order.quantity * order.price
        
        # Hizli ve kucuk emirler -> Market
        if order.urgency == "high" and notional < 5000:
            return "MARKET"
            
        # Buyuk emirler -> Iceberg veya TWAP
        if notional > 20000:
            if order.urgency == "low":
                return "TWAP"
            else:
                return "ICEBERG"
                
        # Orta buyukluk -> Limit veya VWAP
        if order.urgency == "medium":
            return "VWAP"
            
        # Dusuk aciliyet -> Limit
        if order.urgency == "low":
            return "LIMIT"
            
        return "MARKET"
    
    def execute_market(self, order: ExecutionOrder) -> ExecutionResult:
        """Market emri yurut"""
        start_time = time.time()
        
        depth = self._simulate_market_depth(order.symbol)
        slippage = self._estimate_slippage(order.symbol, order.quantity, order.side)
        
        if order.side == "BUY":
            fill_price = depth["base_price"] * (1 + slippage)
            fee_rate = self.EXCHANGE_FEES["taker"]
        else:
            fill_price = depth["base_price"] * (1 - slippage)
            fee_rate = self.EXCHANGE_FEES["taker"]
            
        fees = order.quantity * fill_price * fee_rate
        
        execution_time = time.time() - start_time
        
        # Market emri karsilastirmasi icin "tasarruf" (negatif = daha kotu)
        market_price = depth["base_price"]
        savings = (market_price - fill_price) * order.quantity if order.side == "BUY" else (fill_price - market_price) * order.quantity
        
        return ExecutionResult(
            order_id=order.id,
            success=True,
            filled_qty=order.quantity,
            avg_price=fill_price,
            slippage=slippage,
            fees=fees,
            execution_time=execution_time,
            child_orders=1,
            strategy_used="MARKET",
            savings_vs_market=savings,
        )
    
    def execute_limit(self, order: ExecutionOrder) -> ExecutionResult:
        """Limit emri yurut"""
        start_time = time.time()
        
        depth = self._simulate_market_depth(order.symbol)
        
        # Limit fiyati belirle (emir tarafina gore)
        if order.side == "BUY":
            limit_price = depth["base_price"] * 0.9995  # Hafif altinda
        else:
            limit_price = depth["base_price"] * 1.0005  # Hafif ustunde
            
        # Doldurulma olasiligi (limit fiyatina gore)
        fill_probability = random.uniform(0.7, 0.95)
        
        if random.random() < fill_probability:
            filled_qty = order.quantity
            fill_price = limit_price
            success = True
        else:
            # Kismi doldurulma
            filled_qty = order.quantity * random.uniform(0.5, 0.9)
            fill_price = limit_price
            success = True
            
        fee_rate = self.EXCHANGE_FEES["maker"]  # Limit emri = maker
        
        fees = filled_qty * fill_price * fee_rate
        execution_time = time.time() - start_time
        
        # Tasarruf (limit emri daha iyi fiyat)
        market_price = depth["base_price"]
        savings = (market_price - fill_price) * filled_qty if order.side == "BUY" else (fill_price - market_price) * filled_qty
        savings += (self.EXCHANGE_FEES["taker"] - fee_rate) * filled_qty * fill_price  # Fee tasarrufu
        
        return ExecutionResult(
            order_id=order.id,
            success=success,
            filled_qty=filled_qty,
            avg_price=fill_price,
            slippage=abs((fill_price - market_price) / market_price),
            fees=fees,
            execution_time=execution_time,
            child_orders=1,
            strategy_used="LIMIT",
            savings_vs_market=savings,
        )
    
    def execute_twap(self, order: ExecutionOrder) -> ExecutionResult:
        """TWAP (Time Weighted Average Price) yurut"""
        start_time = time.time()
        
        # Emiri zaman dilimlerine bol
        slices = 5
        slice_qty = order.quantity / slices
        slice_interval = order.time_limit / slices
        
        total_filled = 0.0
        total_cost = 0.0
        child_orders = 0
        
        for i in range(slices):
            depth = self._simulate_market_depth(order.symbol)
            
            # Her dilimde hafif fiyat hareketi
            price_move = random.uniform(-0.002, 0.002)
            fill_price = depth["base_price"] * (1 + price_move)
            
            if order.side == "BUY":
                fill_price *= (1 + 0.0005)  # Hafif slippage
            else:
                fill_price *= (1 - 0.0005)
                
            total_filled += slice_qty
            total_cost += slice_qty * fill_price
            child_orders += 1
            
            time.sleep(0.01)  # Simulasyon gecikmesi
            
        avg_price = total_cost / total_filled if total_filled > 0 else 0
        fees = total_filled * avg_price * self.EXCHANGE_FEES["taker"]
        
        execution_time = time.time() - start_time
        market_price = self._simulate_market_depth(order.symbol)["base_price"]
        savings = (market_price - avg_price) * total_filled if order.side == "BUY" else (avg_price - market_price) * total_filled
        
        return ExecutionResult(
            order_id=order.id,
            success=True,
            filled_qty=total_filled,
            avg_price=avg_price,
            slippage=abs((avg_price - market_price) / market_price),
            fees=fees,
            execution_time=execution_time,
            child_orders=child_orders,
            strategy_used="TWAP",
            savings_vs_market=savings,
        )
    
    def execute_iceberg(self, order: ExecutionOrder) -> ExecutionResult:
        """Iceberg emri yurut (gorunur kismi kucuk)"""
        start_time = time.time()
        
        # Gosterilen miktar (toplamin %10-20'si)
        visible_pct = random.uniform(0.10, 0.20)
        visible_qty = order.quantity * visible_pct
        
        # Emiri parcalara bol
        total_slices = int(order.quantity / visible_qty)
        total_filled = 0.0
        total_cost = 0.0
        child_orders = 0
        
        for i in range(total_slices):
            depth = self._simulate_market_depth(order.symbol)
            
            # Daha dusuk slippage (kucuk emirler)
            slippage = self._estimate_slippage(order.symbol, visible_qty, order.side) * 0.5
            
            if order.side == "BUY":
                fill_price = depth["base_price"] * (1 + slippage)
            else:
                fill_price = depth["base_price"] * (1 - slippage)
                
            total_filled += visible_qty
            total_cost += visible_qty * fill_price
            child_orders += 1
            
            # Her parca arasinda bekle (piyasa etkisini azalt)
            time.sleep(0.02)
            
        avg_price = total_cost / total_filled if total_filled > 0 else 0
        fees = total_filled * avg_price * self.EXCHANGE_FEES["taker"]
        
        execution_time = time.time() - start_time
        market_price = self._simulate_market_depth(order.symbol)["base_price"]
        savings = (market_price - avg_price) * total_filled if order.side == "BUY" else (avg_price - market_price) * total_filled
        
        return ExecutionResult(
            order_id=order.id,
            success=True,
            filled_qty=total_filled,
            avg_price=avg_price,
            slippage=abs((avg_price - market_price) / market_price),
            fees=fees,
            execution_time=execution_time,
            child_orders=child_orders,
            strategy_used="ICEBERG",
            savings_vs_market=savings,
        )
    
    def execute_vwap(self, order: ExecutionOrder) -> ExecutionResult:
        """VWAP (Volume Weighted Average Price) yurut"""
        start_time = time.time()
        
        # Hacim profiline gore dagilim
        volume_profile = [0.15, 0.20, 0.25, 0.20, 0.15, 0.05]  # Gun icinde hacim dagilimi
        
        total_filled = 0.0
        total_cost = 0.0
        child_orders = 0
        
        for pct in volume_profile:
            if total_filled >= order.quantity:
                break
                
            slice_qty = order.quantity * pct
            depth = self._simulate_market_depth(order.symbol)
            
            # Hacim profiline gore fiyat
            price_adjustment = random.uniform(-0.001, 0.001)
            fill_price = depth["base_price"] * (1 + price_adjustment)
            
            if order.side == "BUY":
                fill_price *= (1 + 0.0003)
            else:
                fill_price *= (1 - 0.0003)
                
            total_filled += slice_qty
            total_cost += slice_qty * fill_price
            child_orders += 1
            
        avg_price = total_cost / total_filled if total_filled > 0 else 0
        fees = total_filled * avg_price * self.EXCHANGE_FEES["taker"]
        
        execution_time = time.time() - start_time
        market_price = self._simulate_market_depth(order.symbol)["base_price"]
        savings = (market_price - avg_price) * total_filled if order.side == "BUY" else (avg_price - market_price) * total_filled
        
        return ExecutionResult(
            order_id=order.id,
            success=True,
            filled_qty=total_filled,
            avg_price=avg_price,
            slippage=abs((avg_price - market_price) / market_price),
            fees=fees,
            execution_time=execution_time,
            child_orders=child_orders,
            strategy_used="VWAP",
            savings_vs_market=savings,
        )
    
    def optimize_and_execute(self, symbol: str, side: str, quantity: float,
                              price: float, urgency: str = "medium",
                              max_slippage: float = 0.005) -> ExecutionResult:
        """En iyi stratejiyi sec ve yurut"""
        order = ExecutionOrder(
            id=f"EXEC_{int(time.time())}_{random.randint(1000, 9999)}",
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=price,
            order_type="AUTO",
            urgency=urgency,
            max_slippage=max_slippage,
            time_limit=300,  # 5 dakika
        )
        
        self.orders.append(order)
        
        # Strateji sec
        strategy = self._select_strategy(order)
        order.order_type = strategy
        
        # Yurut
        if strategy == "MARKET":
            result = self.execute_market(order)
        elif strategy == "LIMIT":
            result = self.execute_limit(order)
        elif strategy == "TWAP":
            result = self.execute_twap(order)
        elif strategy == "ICEBERG":
            result = self.execute_iceberg(order)
        elif strategy == "VWAP":
            result = self.execute_vwap(order)
        else:
            result = self.execute_market(order)
            
        self.results.append(result)
        order.status = "filled"
        order.executed_at = datetime.now().isoformat()
        
        return result
    
    def compare_strategies(self, symbol: str, side: str, quantity: float, price: float) -> Dict:
        """Tum stratejileri karsilastir"""
        results = {}
        
        for strategy in ["MARKET", "LIMIT", "TWAP", "ICEBERG", "VWAP"]:
            order = ExecutionOrder(
                id=f"COMP_{strategy}_{random.randint(1000, 9999)}",
                symbol=symbol,
                side=side,
                quantity=quantity,
                price=price,
                order_type=strategy,
                urgency="medium",
                max_slippage=0.005,
                time_limit=300,
            )
            
            if strategy == "MARKET":
                result = self.execute_market(order)
            elif strategy == "LIMIT":
                result = self.execute_limit(order)
            elif strategy == "TWAP":
                result = self.execute_twap(order)
            elif strategy == "ICEBERG":
                result = self.execute_iceberg(order)
            elif strategy == "VWAP":
                result = self.execute_vwap(order)
                
            results[strategy] = {
                "avg_price": result.avg_price,
                "slippage": result.slippage,
                "fees": result.fees,
                "execution_time": result.execution_time,
                "child_orders": result.child_orders,
                "savings": result.savings_vs_market,
            }
            
        return results
    
    def generate_report(self) -> str:
        """Yurutme raporu olustur"""
        if not self.results:
            return "Heniz yurutme yapilmadi."
            
        total_savings = sum(r.savings_vs_market for r in self.results)
        avg_slippage = sum(r.slippage for r in self.results) / len(self.results)
        avg_time = sum(r.execution_time for r in self.results) / len(self.results)
        
        report = f"""
==============================================================
     ATLAS EXECUTION OPTIMIZER - YURUTME RAPORU             
==============================================================
  Toplam Emir: {len(self.orders)}
  Basarili: {len([r for r in self.results if r.success])}
  Basarisiz: {len([r for r in self.results if not r.success])}
  
  PERFORMANS METRIKLERI:
    Ortalama Slippage: {avg_slippage:.4f} ({avg_slippage:.2%})
    Ortalama Sure: {avg_time:.3f}s
    Toplam Tasarruf: ${total_savings:,.2f}
    
  STRATEJI DAGILIMI:
"""
        strategies = {}
        for r in self.results:
            strategies[r.strategy_used] = strategies.get(r.strategy_used, 0) + 1
            
        for strat, count in sorted(strategies.items(), key=lambda x: x[1], reverse=True):
            report += f"    {strat:12s}: {count} emir\n"
            
        report += f"\n  SON YURUTMELER:\n"
        for r in self.results[-5:]:
            report += f"    {r.strategy_used:8s} | Fiyat: ${r.avg_price:,.2f} | Slippage: {r.slippage:.2%} | Sure: {r.execution_time:.3f}s\n"
            
        report += f"""
==============================================================
"""
        return report


# ==============================================================
# TEST
# ==============================================================

def test_execution_optimizer():
    """Yurutme optimizasyonu testi"""
    print("=" * 60)
    print("ATLAS EXECUTION OPTIMIZER - EMIR YURUTME TESTI")
    print("=" * 60)
    
    optimizer = AtlasExecutionOptimizer()
    
    # 1. Strateji karsilastirmasi
    print("\n[1] Strateji Karsilastirmasi")
    print("-" * 50)
    print("  Sembol: BTC, Side: BUY, Miktar: 1.0, Fiyat: $50,000")
    print()
    
    comparison = optimizer.compare_strategies("BTC", "BUY", 1.0, 50000)
    
    print(f"  {'Strateji':<12} {'Ort.Fiyat':>12} {'Slippage':>10} {'Ucret':>10} {'Sure':>8} {'Parca':>6} {'Tasarruf':>12}")
    print(f"  {'-'*12} {'-'*12} {'-'*10} {'-'*10} {'-'*8} {'-'*6} {'-'*12}")
    
    for strat, data in comparison.items():
        print(f"  {strat:<12} ${data['avg_price']:>10,.2f} {data['slippage']:>9.2%} ${data['fees']:>9,.2f} {data['execution_time']:>7.3f}s {data['child_orders']:>5d} ${data['savings']:>10,.2f}")
    
    # 2. Farkli aciliyet seviyeleri
    print("\n[2] Aciliyet Seviyeleri")
    print("-" * 50)
    
    for urgency in ["low", "medium", "high"]:
        result = optimizer.optimize_and_execute(
            "BTC", "BUY", 2.0, 50000,
            urgency=urgency, max_slippage=0.003
        )
        print(f"  Aciliyet: {urgency.upper():6s} | Strateji: {result.strategy_used:8s} | "
              f"Fiyat: ${result.avg_price:,.2f} | Slippage: {result.slippage:.2%} | "
              f"Sure: {result.execution_time:.3f}s")
    
    # 3. Buyuk emir testi
    print("\n[3] Buyuk Emir Testi (10 BTC)")
    print("-" * 50)
    
    big_order = optimizer.optimize_and_execute(
        "BTC", "SELL", 10.0, 50000,
        urgency="low", max_slippage=0.002
    )
    print(f"  Strateji: {big_order.strategy_used}")
    print(f"  Doldurulan: {big_order.filled_qty:.4f} BTC")
    print(f"  Ortalama Fiyat: ${big_order.avg_price:,.2f}")
    print(f"  Slippage: {big_order.slippage:.2%}")
    print(f"  Ucret: ${big_order.fees:,.2f}")
    print(f"  Parca Sayisi: {big_order.child_orders}")
    print(f"  Tasarruf: ${big_order.savings_vs_market:,.2f}")
    print(f"  Sure: {big_order.execution_time:.3f}s")
    
    # 4. Rapor
    print("\n" + "=" * 60)
    print(optimizer.generate_report())
    
    print("\n" + "=" * 60)
    print("[OK] YURUTME OPTIMIZASYONU TEST TAMAMLANDI")
    print("=" * 60)


if __name__ == "__main__":
    test_execution_optimizer()