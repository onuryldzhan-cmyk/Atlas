"""Atlas AI - Paper Trading Engine"""
import uuid, random
from datetime import datetime
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from enum import Enum

class OrderSide(Enum): BUY = "BUY"; SELL = "SELL"
class OrderType(Enum): MARKET = "MARKET"; LIMIT = "LIMIT"
class OrderStatus(Enum): PENDING = "PENDING"; FILLED = "FILLED"; CANCELLED = "CANCELLED"; REJECTED = "REJECTED"
class PositionSide(Enum): LONG = "LONG"; SHORT = "SHORT"

@dataclass
class Order:
    id: str; symbol: str; side: OrderSide; order_type: OrderType
    quantity: float; price: Optional[float] = None
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: float = 0.0; avg_fill_price: float = 0.0
    commission: float = 0.0; slippage: float = 0.0
    created_at: datetime = field(default_factory=datetime.now)
    def to_dict(self): return {'id': self.id, 'symbol': self.symbol, 'side': self.side.value, 'type': self.order_type.value, 'quantity': self.quantity, 'price': self.price, 'status': self.status.value, 'avg_fill_price': self.avg_fill_price, 'commission': self.commission}

@dataclass
class Trade:
    id: str; order_id: str; symbol: str; side: OrderSide
    quantity: float; price: float; commission: float
    realized_pnl: float = 0.0; timestamp: datetime = field(default_factory=datetime.now)
    def to_dict(self): return {'id': self.id, 'symbol': self.symbol, 'side': self.side.value, 'quantity': self.quantity, 'price': self.price, 'commission': self.commission, 'realized_pnl': self.realized_pnl}

@dataclass
class Position:
    id: str; symbol: str; side: PositionSide
    entry_price: float; quantity: float; margin: float
    unrealized_pnl: float = 0.0; realized_pnl: float = 0.0
    commission_paid: float = 0.0; status: str = "OPEN"
    opened_at: datetime = field(default_factory=datetime.now)
    stop_loss: Optional[float] = None; take_profit: Optional[float] = None
    def to_dict(self): return {'id': self.id, 'symbol': self.symbol, 'side': self.side.value, 'entry_price': self.entry_price, 'quantity': self.quantity, 'margin': self.margin, 'unrealized_pnl': self.unrealized_pnl, 'realized_pnl': self.realized_pnl, 'status': self.status}

@dataclass
class Account:
    balance: float = 10000.0; initial_balance: float = 10000.0
    available_balance: float = 10000.0; margin_used: float = 0.0
    total_pnl: float = 0.0; total_commission: float = 0.0

class PaperTradingEngine:
    def __init__(self, initial_balance=10000.0, base_commission_rate=0.001, slippage_model="adaptive", base_slippage=0.0005):
        self.initial_balance = initial_balance
        self.base_commission_rate = base_commission_rate
        self.taker_commission_rate = base_commission_rate
        self.maker_commission_rate = base_commission_rate * 0.75
        self.slippage_model = slippage_model
        self.base_slippage = base_slippage
        self.account = Account(balance=initial_balance, initial_balance=initial_balance, available_balance=initial_balance)
        self.orders: Dict[str, Order] = {}
        self.trades: List[Trade] = []
        self.positions: Dict[str, Position] = {}
        self.closed_positions: List[Position] = []
        self.current_prices: Dict[str, float] = {}
        self.stats = {'total_orders': 0, 'filled_orders': 0, 'cancelled_orders': 0, 'rejected_orders': 0, 'total_trades': 0, 'winning_trades': 0, 'losing_trades': 0, 'largest_win': 0.0, 'largest_loss': 0.0, 'max_drawdown': 0.0, 'peak_equity': initial_balance}
        self.order_callbacks = []; self.trade_callbacks = []; self.position_callbacks = []

    def _calculate_slippage(self, symbol, quantity, side):
        if self.slippage_model == "none": return 0.0
        if self.slippage_model == "fixed": return self.base_slippage
        current_price = self.current_prices.get(symbol, 1)
        notional = quantity * current_price
        volume_factor = min(notional / 10000, 5.0)
        return min(self.base_slippage * volume_factor * random.uniform(0.8, 1.2), 0.01)

    def place_market_order(self, symbol, side, quantity):
        order_id = str(uuid.uuid4())[:8]
        order = Order(id=order_id, symbol=symbol.upper(), side=side, order_type=OrderType.MARKET, quantity=quantity)
        self.stats['total_orders'] += 1
        current_price = self.current_prices.get(symbol.upper())
        if current_price is None:
            order.status = OrderStatus.REJECTED; self.stats['rejected_orders'] += 1
            print(f"[ENGINE] Emir reddedildi: {symbol} icin fiyat bilgisi yok"); return order
        slippage = self._calculate_slippage(symbol, quantity, side)
        order.slippage = slippage
        fill_price = current_price * (1 + slippage) if side == OrderSide.BUY else current_price * (1 - slippage)
        order.avg_fill_price = fill_price; order.filled_quantity = quantity
        order.status = OrderStatus.FILLED; order.filled_at = datetime.now()
        notional = quantity * fill_price
        commission = notional * self.taker_commission_rate
        order.commission = commission
        self.orders[order_id] = order; self.stats['filled_orders'] += 1
        trade = Trade(id=str(uuid.uuid4())[:8], order_id=order_id, symbol=symbol.upper(), side=side, quantity=quantity, price=fill_price, commission=commission)
        self.trades.append(trade); self.stats['total_trades'] += 1
        self._update_position(symbol, side, quantity, fill_price, commission)
        self._update_account(commission)
        for cb in self.order_callbacks: cb(order)
        for cb in self.trade_callbacks: cb(trade)
        print(f"[ENGINE] Market {side.value} | {symbol} | Qty: {quantity:.6f} | Price: ${fill_price:,.2f} | Slippage: {slippage*100:.3f}% | Commission: ${commission:.4f}")
        return order

    def _update_position(self, symbol, side, quantity, price, commission):
        symbol = symbol.upper()
        if symbol not in self.positions:
            position = Position(id=str(uuid.uuid4())[:8], symbol=symbol, side=PositionSide.LONG if side == OrderSide.BUY else PositionSide.SHORT, entry_price=price, quantity=quantity, margin=quantity * price, commission_paid=commission)
            self.positions[symbol] = position
            for cb in self.position_callbacks: cb(position, "OPENED")
            print(f"[POSITION] Yeni pozisyon acildi: {symbol} {position.side.value} | Entry: ${price:,.2f} | Qty: {quantity:.6f}")
        else:
            position = self.positions[symbol]
            if (side == OrderSide.BUY and position.side == PositionSide.LONG) or (side == OrderSide.SELL and position.side == PositionSide.SHORT):
                total_qty = position.quantity + quantity
                position.entry_price = ((position.entry_price * position.quantity) + (price * quantity)) / total_qty
                position.quantity = total_qty; position.margin = position.quantity * position.entry_price
                position.commission_paid += commission
                for cb in self.position_callbacks: cb(position, "INCREASED")
            else:
                if quantity >= position.quantity:
                    self._close_position(symbol, price, commission)
                else:
                    closed_qty = quantity
                    pnl = self._calculate_realized_pnl(position.side, position.entry_price, price, closed_qty)
                    position.quantity -= closed_qty; position.realized_pnl += pnl; position.commission_paid += commission
                    if self.trades: self.trades[-1].realized_pnl = pnl
                    print(f"[POSITION] Kismi kapatma: {symbol} | Kapatilan: {closed_qty:.6f} | Kalan: {position.quantity:.6f} | Realized PnL: ${pnl:,.2f}")

    def _close_position(self, symbol, exit_price, commission):
        symbol = symbol.upper(); position = self.positions.get(symbol)
        if not position: return
        pnl = self._calculate_realized_pnl(position.side, position.entry_price, exit_price, position.quantity)
        position.realized_pnl = pnl; position.commission_paid += commission
        position.status = "CLOSED"; position.closed_at = datetime.now()
        if self.trades: self.trades[-1].realized_pnl = pnl
        if pnl > 0: self.stats['winning_trades'] += 1; self.stats['largest_win'] = max(self.stats['largest_win'], pnl)
        else: self.stats['losing_trades'] += 1; self.stats['largest_loss'] = min(self.stats['largest_loss'], pnl)
        self.account.total_pnl += pnl
        self.closed_positions.append(position); del self.positions[symbol]
        for cb in self.position_callbacks: cb(position, "CLOSED")
        print(f"[POSITION] Pozisyon kapandi: {symbol} | Entry: ${position.entry_price:,.2f} -> Exit: ${exit_price:,.2f} | Realized PnL: ${pnl:,.2f}")

    def _calculate_realized_pnl(self, side, entry_price, exit_price, quantity):
        return (exit_price - entry_price) * quantity if side == PositionSide.LONG else (entry_price - exit_price) * quantity

    def _update_account(self, commission):
        self.account.total_commission += commission; self.account.available_balance -= commission
        equity = self.account.balance + self.account.total_pnl
        if equity > self.stats['peak_equity']: self.stats['peak_equity'] = equity
        drawdown = (self.stats['peak_equity'] - equity) / self.stats['peak_equity']
        self.stats['max_drawdown'] = max(self.stats['max_drawdown'], drawdown)

    def update_price(self, symbol, price):
        self.current_prices[symbol.upper()] = price
        for pos_symbol, position in self.positions.items():
            if pos_symbol == symbol.upper():
                position.unrealized_pnl = (price - position.entry_price) * position.quantity if position.side == PositionSide.LONG else (position.entry_price - price) * position.quantity

    def get_position(self, symbol): return self.positions.get(symbol.upper())
    def get_all_positions(self): return list(self.positions.values())

    def get_account_summary(self):
        unrealized_pnl = sum(p.unrealized_pnl for p in self.positions.values())
        equity = self.account.balance + self.account.total_pnl + unrealized_pnl
        total_closed = self.stats['winning_trades'] + self.stats['losing_trades']
        return {'balance': self.account.balance, 'available_balance': self.account.available_balance, 'margin_used': self.account.margin_used, 'total_pnl': self.account.total_pnl, 'unrealized_pnl': unrealized_pnl, 'equity': equity, 'total_commission': self.account.total_commission, 'return_pct': ((equity - self.initial_balance) / self.initial_balance) * 100, 'open_positions': len(self.positions), 'total_trades': self.stats['total_trades'], 'win_rate': (self.stats['winning_trades'] / max(total_closed, 1)) * 100}

    def get_stats(self):
        total_closed = self.stats['winning_trades'] + self.stats['losing_trades']
        total_wins = sum(t.realized_pnl for t in self.trades if t.realized_pnl > 0)
        total_losses = abs(sum(t.realized_pnl for t in self.trades if t.realized_pnl < 0))
        wins = [t.realized_pnl for t in self.trades if t.realized_pnl > 0]
        losses = [t.realized_pnl for t in self.trades if t.realized_pnl < 0]
        return {**self.stats, 'win_rate': (self.stats['winning_trades'] / max(total_closed, 1)) * 100, 'profit_factor': total_wins / max(total_losses, 0.01), 'avg_win': sum(wins) / max(len(wins), 1), 'avg_loss': sum(losses) / max(len(losses), 1), 'current_equity': self.get_account_summary()['equity']}

    def on_order_filled(self, cb): self.order_callbacks.append(cb)
    def on_trade_executed(self, cb): self.trade_callbacks.append(cb)
    def on_position_update(self, cb): self.position_callbacks.append(cb)
