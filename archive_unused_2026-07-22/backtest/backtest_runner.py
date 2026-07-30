"""
Atlas AI - Backtest Runner
Hazir kullanim ornegi
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from portfolio_backtest import (
    BacktestEngine, BacktestReport, RiskProfile,
    MultiCoinScanner, PortfolioAllocator, RISK_PROFILES
)
from datetime import datetime, timedelta
import json


def run_all_profiles():
    results = {}
    for profile in RiskProfile:
        print(f"\n{'='*60}")
        print(f"?? PROFIL: {profile.value.upper()}")
        print(f"{'='*60}")
        engine = BacktestEngine(
            risk_profile=profile,
            start_date=datetime.now() - timedelta(days=30),
            end_date=datetime.now()
        )
        result = engine.run_backtest()
        BacktestReport.print_report(result)
        results[profile.value] = result
    return results


def compare_profiles(results):
    print("\n" + "=" * 70)
    print("?? RISK PROFILI KARSILASTIRMASI")
    print("=" * 70)
    print(f"{'Profil':<12} {'Getiri':>10} {'Win Rate':>10} {'Trades':>8} {'Sharpe':>8} {'Max DD':>8}")
    print("-" * 70)
    for name, r in results.items():
        print(f"{r['profile']:<12} {r['total_return_pct']:>+9.2f}% {r['win_rate']:>9.1f}% "
              f"{r['total_trades']:>8d} {r['sharpe_ratio']:>8.2f} {r['max_drawdown_pct']:>7.2f}%")
    print("=" * 70)


def run_single_profile(profile_name="medium"):
    profile_map = {
        "low": RiskProfile.LOW,
        "medium": RiskProfile.MEDIUM,
        "high": RiskProfile.HIGH,
    }
    profile = profile_map.get(profile_name.lower(), RiskProfile.MEDIUM)
    engine = BacktestEngine(
        risk_profile=profile,
        start_date=datetime.now() - timedelta(days=30),
        end_date=datetime.now()
    )
    result = engine.run_backtest()
    BacktestReport.print_report(result)
    BacktestReport.to_json(result, f"backtest_result_{profile_name}.json")
    return result


def show_portfolio_allocation():
    print("\n" + "=" * 60)
    print("?? PORTFOY DAGILIMLARI")
    print("=" * 60)
    for profile in RiskProfile:
        config = RISK_PROFILES[profile]
        allocator = PortfolioAllocator(config)
        print(f"\n?? {config.name} Profili (${config.total_balance:,.0f})")
        print(f"   Max Pozisyon: {config.max_positions} | Gunluk Max Kayip: {config.max_daily_loss_pct*100:.0f}%")
        print("   " + "-" * 50)
        print(f"   {'Coin':<12} {'Tahsis':>10} {'Pozisyon':>12} {'Stop Loss':>10} {'Take Profit':>12}")
        print("   " + "-" * 50)
        for coin in config.coins:
            pos_size = allocator.get_position_size(coin.symbol)
            print(f"   {coin.symbol:<12} {coin.allocation_pct*100:>9.1f}% ${pos_size:>10.2f} "
                  f"{coin.stop_loss_pct*100:>9.1f}% {coin.take_profit_pct*100:>11.1f}%")
    print("=" * 60)


def show_scanner_example():
    print("\n" + "=" * 60)
    print("?? COKLU COIN TARAMA ORNEGI")
    print("=" * 60)
    scanner = MultiCoinScanner()
    results = scanner.scan_all()
    print(f"\n{'Coin':<12} {'Sinyal':<8} {'Fiyat':>12} {'Degisim':>10} {'RSI':>8} {'Hacim':>15}")
    print("-" * 70)
    for symbol, data in results.items():
        if "error" in data:
            print(f"{symbol:<12} HATA: {data['error']}")
        else:
            signal_emoji = {"BUY": "??", "SELL": "??", "HOLD": "??"}.get(data['signal'], "?")
            print(f"{symbol:<12} {signal_emoji} {data['signal']:<6} ${data['price']:>10.4f} "
                  f"{data['change_24h']*100:>+8.2f}% {data['rsi']:>7.1f} {data['volume']:>15,.0f}")
    print("=" * 60)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Atlas AI Backtest Runner")
    parser.add_argument("--profile", choices=["low", "medium", "high"], help="Tek bir profil kos")
    parser.add_argument("--all", action="store_true", help="Tum profilleri kos")
    parser.add_argument("--allocation", action="store_true", help="Portfoy dagilimlarini goster")
    parser.add_argument("--scan", action="store_true", help="Coin tarama ornegi goster")
    args = parser.parse_args()
    
    if args.allocation:
        show_portfolio_allocation()
    elif args.scan:
        show_scanner_example()
    elif args.all:
        results = run_all_profiles()
        compare_profiles(results)
    elif args.profile:
        run_single_profile(args.profile)
    else:
        print("\n?? Kullanim:")
        print("  python backtest_runner.py --profile medium")
        print("  python backtest_runner.py --all")
        print("  python backtest_runner.py --allocation")
        print("  python backtest_runner.py --scan")
        print("\n?? Varsayilan: Medium profil backtest\n")
        run_single_profile("medium")
