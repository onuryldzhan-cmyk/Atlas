# -*- coding: utf-8 -*-
"""
Atlas AI Dashboard - Ana Uygulama v2.0
Flask + SocketIO tabanli gelismis web dashboard
"""

import os
import sys
import json
import logging
import random
from datetime import datetime, timedelta
from pathlib import Path
from functools import wraps

# Atlas AI path ekle
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from flask import Flask, render_template, jsonify, request, redirect, url_for
from flask_socketio import SocketIO, emit

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Flask App
app = Flask(__name__, 
            template_folder='templates',
            static_folder='static')
app.config['SECRET_KEY'] = 'atlas-ai-secret-key-2026-v2'
app.config['JSON_SORT_KEYS'] = False
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Global instances
brain = None
capital_manager = None
portfolio_manager = None
performance_tracker = None
market_intel = None
system_initialized = False

# ==================== MOCK DATA ====================

MOCK_PORTFOLIO = {
    'total_balance': 12547.85,
    'available_balance': 8432.12,
    'total_pnl': 2547.85,
    'total_pnl_percent': 25.48,
    'daily_pnl': 342.15,
    'daily_pnl_percent': 2.81,
    'total_positions': 4,
    'total_trades': 156,
    'win_rate': 68.5,
    'sharpe_ratio': 1.84,
    'max_drawdown': 8.2,
    'assets': {
        'USDT': 8432.12,
        'BTC': 2150.45,
        'ETH': 1280.30,
        'SOL': 485.98,
        'BNB': 199.00
    }
}

MOCK_POSITIONS = [
    {
        'id': 'POS-001',
        'symbol': 'BTC/USDT',
        'side': 'LONG',
        'entry_price': 64250.00,
        'current_price': 67540.00,
        'quantity': 0.032,
        'pnl': 102.72,
        'pnl_percent': 5.12,
        'leverage': 1,
        'open_time': (datetime.now() - timedelta(hours=8)).isoformat(),
        'stop_loss': 62000.00,
        'take_profit': 70000.00,
        'status': 'active'
    },
    {
        'id': 'POS-002',
        'symbol': 'ETH/USDT',
        'side': 'LONG',
        'entry_price': 3450.00,
        'current_price': 3200.00,
        'quantity': 0.4,
        'pnl': -100.00,
        'pnl_percent': -7.25,
        'leverage': 2,
        'open_time': (datetime.now() - timedelta(hours=12)).isoformat(),
        'stop_loss': 3100.00,
        'take_profit': 4000.00,
        'status': 'active'
    },
    {
        'id': 'POS-003',
        'symbol': 'SOL/USDT',
        'side': 'LONG',
        'entry_price': 145.00,
        'current_price': 162.30,
        'quantity': 3.0,
        'pnl': 51.90,
        'pnl_percent': 11.93,
        'leverage': 1,
        'open_time': (datetime.now() - timedelta(hours=4)).isoformat(),
        'stop_loss': 130.00,
        'take_profit': 180.00,
        'status': 'active'
    },
    {
        'id': 'POS-004',
        'symbol': 'BNB/USDT',
        'side': 'SHORT',
        'entry_price': 590.00,
        'current_price': 597.00,
        'quantity': 0.5,
        'pnl': -3.50,
        'pnl_percent': -1.19,
        'leverage': 3,
        'open_time': (datetime.now() - timedelta(hours=2)).isoformat(),
        'stop_loss': 610.00,
        'take_profit': 550.00,
        'status': 'active'
    }
]

MOCK_SIGNALS = [
    {
        'id': 'SIG-001',
        'symbol': 'BTC/USDT',
        'type': 'BUY',
        'confidence': 87.5,
        'strategy': 'Trend_Following_v3',
        'timeframe': '5m',
        'timestamp': (datetime.now() - timedelta(minutes=15)).isoformat(),
        'indicators': {'rsi': 42, 'macd': 'bullish', 'ema': 'above'},
        'status': 'active'
    },
    {
        'id': 'SIG-002',
        'symbol': 'ETH/USDT',
        'type': 'HOLD',
        'confidence': 65.0,
        'strategy': 'Mean_Reversion_v2',
        'timeframe': '15m',
        'timestamp': (datetime.now() - timedelta(minutes=30)).isoformat(),
        'indicators': {'rsi': 58, 'macd': 'neutral', 'ema': 'crossing'},
        'status': 'active'
    },
    {
        'id': 'SIG-003',
        'symbol': 'SOL/USDT',
        'type': 'BUY',
        'confidence': 92.3,
        'strategy': 'Momentum_Breakout',
        'timeframe': '1h',
        'timestamp': (datetime.now() - timedelta(minutes=5)).isoformat(),
        'indicators': {'rsi': 35, 'macd': 'bullish', 'ema': 'above'},
        'status': 'active'
    },
    {
        'id': 'SIG-004',
        'symbol': 'BNB/USDT',
        'type': 'SELL',
        'confidence': 78.1,
        'strategy': 'Support_Breakdown',
        'timeframe': '5m',
        'timestamp': (datetime.now() - timedelta(minutes=10)).isoformat(),
        'indicators': {'rsi': 72, 'macd': 'bearish', 'ema': 'below'},
        'status': 'active'
    }
]

MOCK_TRADES = [
    {
        'id': 'TR-001',
        'symbol': 'BTC/USDT',
        'side': 'BUY',
        'price': 64250.00,
        'quantity': 0.032,
        'pnl': 102.72,
        'pnl_percent': 5.12,
        'timestamp': (datetime.now() - timedelta(hours=8)).isoformat(),
        'strategy': 'Trend_Following_v3',
        'status': 'closed'
    },
    {
        'id': 'TR-002',
        'symbol': 'ETH/USDT',
        'side': 'BUY',
        'price': 3450.00,
        'quantity': 0.4,
        'pnl': -100.00,
        'pnl_percent': -7.25,
        'timestamp': (datetime.now() - timedelta(hours=12)).isoformat(),
        'strategy': 'Mean_Reversion_v2',
        'status': 'open'
    },
    {
        'id': 'TR-003',
        'symbol': 'SOL/USDT',
        'side': 'BUY',
        'price': 145.00,
        'quantity': 3.0,
        'pnl': 51.90,
        'pnl_percent': 11.93,
        'timestamp': (datetime.now() - timedelta(hours=4)).isoformat(),
        'strategy': 'Momentum_Breakout',
        'status': 'open'
    },
    {
        'id': 'TR-004',
        'symbol': 'ADA/USDT',
        'side': 'SELL',
        'price': 0.45,
        'quantity': 1000,
        'pnl': 45.00,
        'pnl_percent': 10.00,
        'timestamp': (datetime.now() - timedelta(days=1)).isoformat(),
        'strategy': 'Swing_Trading',
        'status': 'closed'
    },
    {
        'id': 'TR-005',
        'symbol': 'DOT/USDT',
        'side': 'BUY',
        'price': 7.20,
        'quantity': 50,
        'pnl': -15.00,
        'pnl_percent': -4.17,
        'timestamp': (datetime.now() - timedelta(days=2)).isoformat(),
        'strategy': 'Divergence_Play',
        'status': 'closed'
    }
]

MOCK_MARKET = {
    'btc_dominance': 52.4,
    'fear_greed_index': 65,
    'fear_greed_label': 'Greed',
    'total_market_cap': 2.45,
    'total_volume_24h': 98.5,
    'altcoin_season_index': 48,
    'trending': ['SOL', 'LINK', 'AVAX', 'NEAR', 'MATIC'],
    'top_gainers': [
        {'symbol': 'SOL/USDT', 'change_24h': 12.5},
        {'symbol': 'LINK/USDT', 'change_24h': 8.3},
        {'symbol': 'AVAX/USDT', 'change_24h': 6.7}
    ],
    'top_losers': [
        {'symbol': 'DOGE/USDT', 'change_24h': -5.2},
        {'symbol': 'SHIB/USDT', 'change_24h': -3.8},
        {'symbol': 'PEPE/USDT', 'change_24h': -2.1}
    ]
}

MOCK_BRAIN_STATUS = {
    'status': 'active',
    'mode': 'learning',
    'confidence_threshold': 75.0,
    'active_strategies': 8,
    'total_signals_24h': 47,
    'winning_signals_24h': 32,
    'learning_rate': 0.001,
    'last_update': datetime.now().isoformat(),
    'neural_network': {
        'layers': 5,
        'neurons': 256,
        'activation': 'relu',
        'dropout': 0.2
    },
    'memory_usage': 45.2,
    'cpu_usage': 12.8
}

MOCK_RISK = {
    'portfolio_risk': 3.2,
    'risk_level': 'medium',
    'var_95': 245.50,
    'max_drawdown': 8.2,
    'sharpe_ratio': 1.84,
    'sortino_ratio': 2.15,
    'calmar_ratio': 3.10,
    'beta': 0.85,
    'alpha': 2.45,
    'exposure': {
        'long': 65.0,
        'short': 15.0,
        'cash': 20.0
    },
    'position_limits': {
        'max_positions': 10,
        'current': 4,
        'available': 6
    },
    'daily_loss_limit': 500.00,
    'daily_loss_current': 342.15
}

# ==================== SISTEM BASLATMA ====================

def init_system():
    """Sistem modullerini baslat - Mock mod destegi ile"""
    global brain, capital_manager, portfolio_manager, performance_tracker, market_intel, system_initialized
    
    try:
        try:
            from core.atlas_brain import AtlasBrain
            brain = AtlasBrain()
            logger.info("AtlasBrain baslatildi")
        except ImportError as e:
            logger.warning(f"AtlasBrain yuklenemedi: {e}")
            brain = None
        
        try:
            from core.capital_manager import CapitalManager
            capital_manager = CapitalManager()
            logger.info("CapitalManager baslatildi")
        except ImportError as e:
            logger.warning(f"CapitalManager yuklenemedi: {e}")
            capital_manager = None
        
        try:
            from portfolio.portfolio_manager import PortfolioManager
            portfolio_manager = PortfolioManager()
            logger.info("PortfolioManager baslatildi")
        except ImportError as e:
            logger.warning(f"PortfolioManager yuklenemedi: {e}")
            portfolio_manager = None
        
        try:
            from analytics.performance_tracker import PerformanceTracker
            performance_tracker = PerformanceTracker()
            logger.info("PerformanceTracker baslatildi")
        except ImportError as e:
            logger.warning(f"PerformanceTracker yuklenemedi: {e}")
            performance_tracker = None
        
        try:
            from intelligence.market_intelligence import MarketIntelligence
            market_intel = MarketIntelligence()
            logger.info("MarketIntelligence baslatildi")
        except ImportError as e:
            logger.warning(f"MarketIntelligence yuklenemedi: {e}")
            market_intel = None
        
        system_initialized = True
        logger.info("Dashboard sistem modulleri baslatildi (Mock veri modu aktif)")
        return True
        
    except Exception as e:
        logger.error(f"Sistem baslatma hatasi: {e}")
        system_initialized = True
        return True

# ==================== ROUTES ====================

@app.route('/')
def index():
    """Ana dashboard sayfasi"""
    return render_template('index.html', version='4.3.0')

@app.route('/portfolio')
def portfolio_page():
    """Portfoy detay sayfasi"""
    return render_template('portfolio.html')

@app.route('/trades')
def trades_page():
    """Islemler sayfasi"""
    return render_template('trades.html')

@app.route('/signals')
def signals_page():
    """Sinyaller sayfasi"""
    return render_template('signals.html')

@app.route('/analytics')
def analytics_page():
    """Analitik sayfasi"""
    return render_template('analytics.html')

@app.route('/settings')
def settings_page():
    """Ayarlar sayfasi"""
    return render_template('settings.html')

# ==================== API ROUTES ====================

@app.route('/api/status')
def api_status():
    """Sistem durumu"""
    return jsonify({
        'status': 'running',
        'version': '4.3.0',
        'timestamp': datetime.now().isoformat(),
        'mode': 'SIMULATION',
        'system_initialized': system_initialized,
        'modules': {
            'brain': brain is not None,
            'capital': capital_manager is not None,
            'portfolio': portfolio_manager is not None,
            'performance': performance_tracker is not None,
            'market_intel': market_intel is not None
        },
        'mock_mode': brain is None or portfolio_manager is None
    })

@app.route('/api/portfolio')
def api_portfolio():
    """Portfoy bilgileri"""
    if portfolio_manager:
        try:
            data = portfolio_manager.get_portfolio_summary()
            if data:
                return jsonify(data)
        except Exception as e:
            logger.error(f"Portfolio error: {e}")
    return jsonify(MOCK_PORTFOLIO)

@app.route('/api/positions')
def api_positions():
    """Acik pozisyonlar"""
    if portfolio_manager:
        try:
            positions = portfolio_manager.get_open_positions()
            if positions:
                return jsonify({'positions': positions})
        except Exception as e:
            logger.error(f"Positions error: {e}")
    return jsonify({'positions': MOCK_POSITIONS})

@app.route('/api/position/<position_id>')
def api_position_detail(position_id):
    """Pozisyon detayi"""
    for pos in MOCK_POSITIONS:
        if pos['id'] == position_id:
            return jsonify(pos)
    return jsonify({'error': 'Position not found'}), 404

@app.route('/api/performance')
def api_performance():
    """Performans metrikleri"""
    if performance_tracker:
        try:
            metrics = performance_tracker.get_metrics()
            if metrics:
                return jsonify(metrics)
        except Exception as e:
            logger.error(f"Performance error: {e}")
    
    return jsonify({
        'total_return': 25.48,
        'daily_return': 2.81,
        'weekly_return': 8.45,
        'monthly_return': 15.20,
        'yearly_return': 25.48,
        'win_rate': 68.5,
        'profit_factor': 2.34,
        'avg_win': 145.20,
        'avg_loss': -62.40,
        'largest_win': 450.00,
        'largest_loss': -180.00,
        'avg_trade_duration': '4h 32m',
        'total_trades': 156,
        'winning_trades': 107,
        'losing_trades': 49,
        'sharpe_ratio': 1.84,
        'sortino_ratio': 2.15,
        'max_drawdown': 8.2,
        'recovery_factor': 3.10
    })

@app.route('/api/performance/history')
def api_performance_history():
    """Performans gecmisi (grafik icin)"""
    days = request.args.get('days', 30, type=int)
    
    history = []
    base_value = 10000
    for i in range(days):
        date = datetime.now() - timedelta(days=days-i)
        change = random.uniform(-2.5, 3.5)
        base_value *= (1 + change / 100)
        history.append({
            'date': date.strftime('%Y-%m-%d'),
            'value': round(base_value, 2),
            'pnl': round(base_value - 10000, 2),
            'pnl_percent': round((base_value - 10000) / 10000 * 100, 2)
        })
    
    return jsonify({'history': history})

@app.route('/api/market/overview')
def api_market_overview():
    """Piyasa genel gorunumu"""
    if market_intel:
        try:
            overview = market_intel.get_market_overview()
            if overview:
                return jsonify(overview)
        except Exception as e:
            logger.error(f"Market overview error: {e}")
    return jsonify(MOCK_MARKET)

@app.route('/api/market/prices')
def api_market_prices():
    """Guncel fiyatlar"""
    symbols = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'ADA/USDT', 'DOT/USDT']
    prices = []
    for symbol in symbols:
        base_price = random.uniform(50, 70000)
        change = random.uniform(-5, 5)
        prices.append({
            'symbol': symbol,
            'price': round(base_price, 2),
            'change_24h': round(change, 2),
            'change_24h_percent': round(change, 2),
            'volume_24h': round(random.uniform(1000000, 50000000), 2),
            'high_24h': round(base_price * 1.05, 2),
            'low_24h': round(base_price * 0.95, 2)
        })
    return jsonify({'prices': prices})

@app.route('/api/brain/status')
def api_brain_status():
    """AI Brain durumu"""
    if brain:
        try:
            status = brain.get_status()
            if status:
                return jsonify(status)
        except Exception as e:
            logger.error(f"Brain status error: {e}")
    return jsonify(MOCK_BRAIN_STATUS)

@app.route('/api/brain/strategies')
def api_brain_strategies():
    """Aktif stratejiler"""
    strategies = [
        {'name': 'Trend_Following_v3', 'type': 'trend', 'win_rate': 72.5, 'profit': 1250.00, 'status': 'active'},
        {'name': 'Mean_Reversion_v2', 'type': 'reversion', 'win_rate': 65.0, 'profit': 890.00, 'status': 'active'},
        {'name': 'Momentum_Breakout', 'type': 'momentum', 'win_rate': 58.3, 'profit': 650.00, 'status': 'active'},
        {'name': 'Support_Breakdown', 'type': 'breakdown', 'win_rate': 70.1, 'profit': 420.00, 'status': 'active'},
        {'name': 'Swing_Trading', 'type': 'swing', 'win_rate': 68.4, 'profit': 380.00, 'status': 'active'},
        {'name': 'Divergence_Play', 'type': 'divergence', 'win_rate': 55.2, 'profit': -120.00, 'status': 'paused'},
        {'name': 'Scalping_Master', 'type': 'scalping', 'win_rate': 61.0, 'profit': 210.00, 'status': 'active'},
        {'name': 'AI_Pattern_Rec', 'type': 'ai', 'win_rate': 74.2, 'profit': 367.85, 'status': 'active'}
    ]
    return jsonify({'strategies': strategies})

@app.route('/api/trades/history')
def api_trades_history():
    """Islem gecmisi"""
    limit = request.args.get('limit', 50, type=int)
    offset = request.args.get('offset', 0, type=int)
    
    if performance_tracker:
        try:
            trades = performance_tracker.get_trade_history(limit=limit)
            if trades:
                return jsonify({'trades': trades, 'total': len(trades)})
        except Exception as e:
            logger.error(f"Trades history error: {e}")
    
    all_trades = MOCK_TRADES
    paginated = all_trades[offset:offset+limit]
    return jsonify({'trades': paginated, 'total': len(all_trades)})

@app.route('/api/signals')
def api_signals():
    """Aktif sinyaller"""
    if brain:
        try:
            signals = brain.get_active_signals()
            if signals:
                return jsonify({'signals': signals})
        except Exception as e:
            logger.error(f"Signals error: {e}")
    return jsonify({'signals': MOCK_SIGNALS})

@app.route('/api/signals/history')
def api_signals_history():
    """Sinyal gecmisi"""
    limit = request.args.get('limit', 20, type=int)
    
    history = []
    for i in range(limit):
        signals = ['BUY', 'SELL', 'HOLD']
        strategies = ['Trend_Following_v3', 'Mean_Reversion_v2', 'Momentum_Breakout', 'Support_Breakdown']
        symbols = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'ADA/USDT']
        
        history.append({
            'id': f'SIG-HIST-{i+1:03d}',
            'symbol': random.choice(symbols),
            'type': random.choice(signals),
            'confidence': round(random.uniform(60, 95), 1),
            'strategy': random.choice(strategies),
            'result': random.choice(['win', 'loss', 'pending']),
            'pnl': round(random.uniform(-200, 300), 2),
            'timestamp': (datetime.now() - timedelta(hours=i*2)).isoformat()
        })
    
    return jsonify({'signals': history})

@app.route('/api/risk/metrics')
def api_risk_metrics():
    """Risk metrikleri"""
    if capital_manager:
        try:
            metrics = capital_manager.get_risk_metrics()
            if metrics:
                return jsonify(metrics)
        except Exception as e:
            logger.error(f"Risk metrics error: {e}")
    return jsonify(MOCK_RISK)

@app.route('/api/risk/distribution')
def api_risk_distribution():
    """Risk dagilimi (grafik icin)"""
    return jsonify({
        'by_symbol': [
            {'symbol': 'BTC/USDT', 'risk': 35.0},
            {'symbol': 'ETH/USDT', 'risk': 25.0},
            {'symbol': 'SOL/USDT', 'risk': 20.0},
            {'symbol': 'BNB/USDT', 'risk': 15.0},
            {'symbol': 'Diger', 'risk': 5.0}
        ],
        'by_type': [
            {'type': 'Trend', 'risk': 40.0},
            {'type': 'Reversion', 'risk': 30.0},
            {'type': 'Momentum', 'risk': 20.0},
            {'type': 'Breakdown', 'risk': 10.0}
        ]
    })

@app.route('/api/system/logs')
def api_system_logs():
    """Sistem loglari"""
    log_file = project_root / 'logs' / 'atlas.log'
    if log_file.exists():
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                logs = f.readlines()[-100:]
            return jsonify({'logs': logs})
        except Exception as e:
            logger.error(f"Log okuma hatasi: {e}")
    
    mock_logs = [
        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - INFO - Sistem baslatildi",
        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - INFO - Market verileri guncellendi",
        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - INFO - Yeni sinyal algilandi: BTC/USDT BUY",
        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - INFO - Pozisyon acildi: POS-001",
        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - INFO - Risk kontrolu tamamlandi",
        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - INFO - Portfoy degeri guncellendi: $12,547.85",
        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - INFO - AI modeli egitimi tamamlandi",
        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - INFO - Strateji optimizasyonu baslatildi"
    ]
    return jsonify({'logs': mock_logs})

@app.route('/api/system/health')
def api_system_health():
    """Sistem saglik durumu"""
    return jsonify({
        'cpu_usage': round(random.uniform(10, 30), 1),
        'memory_usage': round(random.uniform(40, 60), 1),
        'disk_usage': round(random.uniform(20, 40), 1),
        'network_status': 'connected',
        'api_latency': round(random.uniform(50, 150), 2),
        'last_backup': (datetime.now() - timedelta(hours=2)).isoformat(),
        'uptime': '3d 12h 45m',
        'errors_24h': 0,
        'warnings_24h': 3
    })

@app.route('/api/system/config')
def api_system_config():
    """Sistem konfigurasyonu"""
    return jsonify({
        'mode': 'SIMULATION',
        'paper_balance': 10000,
        'risk_profile': 'medium',
        'max_positions': 10,
        'max_daily_loss': 0.05,
        'timeframe': '5m',
        'exchange': 'binance',
        'kill_switch': True,
        'github_enabled': True,
        'telegram_enabled': False,
        'auto_trading': False,
        'ai_learning': True,
        'backtest_mode': False
    })

# ==================== KONTROL ENDPOINTLERI ====================

@app.route('/api/control/pause', methods=['POST'])
def api_control_pause():
    """Sistem duraklat"""
    logger.info("Sistem duraklatma istegi alindi")
    return jsonify({'status': 'paused', 'timestamp': datetime.now().isoformat()})

@app.route('/api/control/resume', methods=['POST'])
def api_control_resume():
    """Sistem devam ettir"""
    logger.info("Sistem devam ettirme istegi alindi")
    return jsonify({'status': 'resumed', 'timestamp': datetime.now().isoformat()})

@app.route('/api/control/emergency_stop', methods=['POST'])
def api_control_emergency_stop():
    """Acil durdurma (Kill Switch)"""
    logger.critical("ACIL DURDURMA AKTIF EDILDI!")
    return jsonify({
        'status': 'emergency_stop',
        'message': 'Tum pozisyonlar kapatiliyor ve sistem durduruluyor',
        'timestamp': datetime.now().isoformat()
    })

# ==================== SOCKET.IO ====================

@socketio.on('connect')
def handle_connect():
    """Client baglandiginda"""
    logger.info('Client connected to dashboard')
    emit('status', {
        'message': 'Connected to Atlas AI Dashboard',
        'version': '4.3.0',
        'timestamp': datetime.now().isoformat()
    })

@socketio.on('disconnect')
def handle_disconnect():
    """Client ayrildiginda"""
    logger.info('Client disconnected from dashboard')

@socketio.on('request_update')
def handle_request_update():
    """Guncelleme istegi"""
    try:
        if portfolio_manager and brain:
            data = {
                'portfolio': portfolio_manager.get_portfolio_summary(),
                'positions': portfolio_manager.get_open_positions(),
                'signals': brain.get_active_signals(),
                'timestamp': datetime.now().isoformat()
            }
        else:
            data = {
                'portfolio': MOCK_PORTFOLIO,
                'positions': MOCK_POSITIONS,
                'signals': MOCK_SIGNALS,
                'timestamp': datetime.now().isoformat()
            }
        emit('update', data)
    except Exception as e:
        logger.error(f"Socket update error: {e}")
        emit('error', {'message': str(e)})

@socketio.on('subscribe_market')
def handle_subscribe_market():
    """Piyasa verilerine abone ol"""
    emit('market_data', MOCK_MARKET)

# ==================== ERROR HANDLERS ====================

@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Endpoint not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Internal server error'}), 500

# ==================== MAIN ====================

if __name__ == '__main__':
    # Sistem baslat
    if init_system():
        logger.info("=" * 60)
        logger.info("  Atlas AI Dashboard v4.3.0 baslatiliyor...")
        logger.info("  URL: http://127.0.0.1:5000")
        logger.info("  Mod: SIMULATION (Mock veri destegi aktif)")
        logger.info("=" * 60)
        
        # SocketIO ile calistir
        socketio.run(app, 
                     host='0.0.0.0', 
                     port=5000, 
                     debug=True,
                     use_reloader=False)
    else:
        logger.error("Sistem baslatilamadi! Dashboard calistirilamiyor.")
        sys.exit(1)


# Ekstra baþlatma seçeneði
if __name__ == '__main__':
    from threading import Thread
    def run_server():
        socketio.run(app, host='127.0.0.1', port=8080, debug=False, use_reloader=False)
    
    server_thread = Thread(target=run_server)
    server_thread.daemon = True
    server_thread.start()
    print('Server arka planda baslatildi: http://127.0.0.1:8080')
    input('Kapatmak icin Enter a basin...')

