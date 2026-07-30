"""Atlas AI - Live Data Feed"""
import asyncio, aiohttp, json
from datetime import datetime
from dataclasses import dataclass
from typing import Dict, List, Optional, Callable
from collections import deque

@dataclass
class Candle:
    timestamp: datetime; open: float; high: float; low: float
    close: float; volume: float; symbol: str; timeframe: str

@dataclass
class TickerData:
    symbol: str; price: float; bid: float; ask: float
    volume_24h: float; change_24h: float; timestamp: datetime

class LiveDataFeed:
    BINANCE_BASE = "https://api.binance.com"
    BINANCE_WS = "wss://stream.binance.com:9443/ws"
    TIMEFRAME_MAP = {'1m':'1m','5m':'5m','15m':'15m','1h':'1h','4h':'4h','1d':'1d'}

    def __init__(self, api_key=None, api_secret=None):
        self.api_key = api_key; self.api_secret = api_secret
        self.session = None
        self.candle_cache: Dict[str, deque] = {}
        self.ticker_cache: Dict[str, TickerData] = {}
        self.price_history: Dict[str, deque] = {}
        self.ws_connections = {}; self.ws_tasks = []
        self._running = False
        self.price_callbacks: List[Callable] = []
        self.candle_callbacks: List[Callable] = []
        self.stats = {'rest_requests': 0, 'ws_messages': 0, 'errors': 0, 'last_update': None}

    async def start(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(headers={'X-MBX-APIKEY': self.api_key} if self.api_key else {})
        self._running = True
        print("[LiveDataFeed] Baslatildi")

    async def stop(self):
        self._running = False
        for t in self.ws_tasks: t.cancel()
        self.ws_tasks.clear()
        for ws in self.ws_connections.values(): await ws.close()
        self.ws_connections.clear()
        if self.session and not self.session.closed: await self.session.close()

    async def _rest_request(self, endpoint, params=None):
        url = f"{self.BINANCE_BASE}{endpoint}"
        async with self.session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            self.stats['rest_requests'] += 1
            if resp.status == 200: return await resp.json()
            else: self.stats['errors'] += 1; raise Exception(f"API Error {resp.status}")

    async def get_klines(self, symbol, timeframe='5m', limit=100):
        tf = self.TIMEFRAME_MAP.get(timeframe, timeframe)
        data = await self._rest_request('/api/v3/klines', {'symbol': symbol.upper(), 'interval': tf, 'limit': min(limit, 1000)})
        candles = []
        for item in data:
            candles.append(Candle(timestamp=datetime.fromtimestamp(item[0]/1000), open=float(item[1]), high=float(item[2]), low=float(item[3]), close=float(item[4]), volume=float(item[5]), symbol=symbol.upper(), timeframe=timeframe))
        ck = f"{symbol.upper()}_{timeframe}"
        if ck not in self.candle_cache: self.candle_cache[ck] = deque(maxlen=2000)
        self.candle_cache[ck].extend(candles)
        return candles

    async def get_ticker(self, symbol):
        data = await self._rest_request('/api/v3/ticker/24hr', {'symbol': symbol.upper()})
        ticker = TickerData(symbol=symbol.upper(), price=float(data['lastPrice']), bid=float(data['bidPrice']), ask=float(data['askPrice']), volume_24h=float(data['volume']), change_24h=float(data['priceChangePercent']), timestamp=datetime.now())
        self.ticker_cache[symbol.upper()] = ticker
        return ticker

    def on_price_update(self, cb): self.price_callbacks.append(cb)
    def on_candle_close(self, cb): self.candle_callbacks.append(cb)

    def get_current_price(self, symbol):
        t = self.ticker_cache.get(symbol.upper())
        return t.price if t else None
