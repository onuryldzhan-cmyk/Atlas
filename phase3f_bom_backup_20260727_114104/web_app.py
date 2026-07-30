"""
web_app.py

FastAPI ile Atlas Brain Web Dashboard.
AtlasBrain motorunu kullanır, gerçek zamanlı analiz ve portföy durumunu gösterir.
"""

import os
import sys
import logging
import requests
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
import uvicorn

# NOT (konsolidasyon): gercek AtlasBrain sinifi core/ altinda degil, ai/core/ altinda.
# core/atlas_brain.py icinde sadece AtlasBrainV2 var, AtlasBrain adinda bir sinif yok --
# bu yuzden bu dosya daha once ImportError ile hic acilamiyordu.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE_DIR, "ai", "core"))  # atlas_brain.py'nin ic importlari icin

from ai.core.atlas_brain import AtlasBrain
from core.database import DatabaseManager
from core.paper_trader import PaperTrader

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("AtlasAI")

app = FastAPI(title="Project Atlas AI", description="Hedge Fund Level AI Trading Platform")
templates = Jinja2Templates(directory="templates")

# Çekirdek motoru başlat
db = DatabaseManager()
trader = PaperTrader(db)
brain = AtlasBrain(trader)

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return templates.TemplateResponse(request=request, name="login.html")

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    try:
        price = float(requests.get("https://api.binance.com/api/v3/ticker/price?symbol=BTCTRY", timeout=5).json()["price"])
    except Exception:
        price = 0.0
    return templates.TemplateResponse(request=request, name="dashboard.html", context={"price": price})

@app.get("/api/analysis")
async def api_analysis(symbol: str = "ALL"):
    """
    Canlı analiz endpoint'i.
    ALL yazılırsa portföydeki tüm coinleri (BTC, ETH, SOL) analiz eder.
    """
    try:
        if symbol.upper() == "ALL":
            results = brain.run(["BTCUSDT", "ETHUSDT", "SOLUSDT"])
            return JSONResponse(content={"status": "success", "data": results})
        else:
            results = brain.run([symbol.upper()])
            report = results.get(symbol.upper(), {})
            if report.get("error"):
                return JSONResponse(content={"status": "error", "message": "Veri alınamadı"})
            return JSONResponse(content={"status": "success", "data": report})
    except Exception as e:
        logger.error(f"API hatası: {e}")
        return JSONResponse(content={"status": "error", "message": str(e)})

@app.get("/api/backtest")
async def api_backtest(symbol: str = "BTCUSDT", interval: str = "1h", days: int = 30):
    """
    Backtest motorunu çalıştırır. (Adım 3'te doldurulacak)
    """
    from core.backtest_engine import BacktestEngine
    from datetime import datetime, timedelta
    
    engine = BacktestEngine()
    result = engine.run(
        symbol=symbol,
        interval=interval,
        start_date=datetime.now() - timedelta(days=days)
    )
    return JSONResponse(content=result)

@app.post("/login")
async def login(username: str = Form(...)):
    # Basit login simülasyonu (ileride JWT veya 2FA eklenecek)
    return RedirectResponse(url="/dashboard", status_code=303)

if __name__ == "__main__":
    logger.info("Atlas AI Web Panel başlatılıyor...")
    uvicorn.run(app, host="127.0.0.1", port=8000)
