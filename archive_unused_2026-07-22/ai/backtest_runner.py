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
        print("")
        print("=" * 60)
        print("PROFILE: " + profile.value.upper())
        print("=" * 60)
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
    print("")
    print("=" * 70)
    print("RISK PROFILE COMPARISON")
    print("=" * 70)
    header = "Profile".ljust(12) + "Return".rjust(10) + "Win Rate".rjust(10) + "Trades".rjust(8) + "Sharpe".rjust(8) + "Max DD".rjust(8)
    print(header)
    print("-" * 70)
    for name, r in results.items():
        ret = str(round(r["total_return_pct"], 2)) + "%"
        wr = str(round(r["win_rate"], 1)) + "%"
        line = r["profile"].ljust(12) + ret.rjust(10) + wr.rjust(10) + str(r["total_trades"]).rjust(8) + str(round(r["sharpe_ratio"], 2)).rjust(8) + str(round(r["max_drawdown_pct"], 2)).rjust(6) + "%"
        print(line)
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
    BacktestReport.to_json(result, "backtest_result_" + profile_name + ".json")
    return result


def show_portfolio_allocation():
    print("")
    print("=" * 60)
    print("PORTFOLIO ALLOCATIONS")
    print("=" * 60)
    for profile in RiskProfile:
        config = RISK_PROFILES[profile]
        allocator = PortfolioAllocator(config)
        print("")
        print(config.name + " Profile ($" + str(int(config.total_balance)) + ")")
        print("   Max Positions: " + str(config.max_positions) + " | Daily Max Loss: " + str(int(config.max_daily_loss_pct * 100)) + "%")
        print("   " + "-" * 50)
        print("   " + "Coin".ljust(12) + "Alloc".rjust(10) + "Position".rjust(12) + "Stop Loss".rjust(10) + "Take Profit".rjust(12))
        print("   " + "-" * 50)
        for coin in config.coins:
            pos_size = allocator.get_position_size(coin.symbol)
            line = "   " + coin.symbol.ljust(12) + str(round(coin.allocation_pct * 100, 1)).rjust(9) + "%" + " $" + str(round(pos_size, 2)).rjust(10) + " " + str(round(coin.stop_loss_pct * 100, 1)).rjust(9) + "%" + " " + str(round(coin.take_profit_pct * 100, 1)).rjust(11) + "%"
            print(line)
    print("=" * 60)


def show_scanner_example():
    print("")
    print("=" * 60)
    print("MULTI-COIN SCANNER EXAMPLE")
    print("=" * 60)
    scanner = MultiCoinScanner()
    results = scanner.scan_all()
    print("")
    print("Coin".ljust(12) + "Signal".ljust(8) + "Price".rjust(12) + "Change".rjust(10) + "RSI".rjust(8) + "Volume".rjust(15))
    print("-" * 70)
    for symbol, data in results.items():
        if "error" in data:
            print(symbol.ljust(12) + "ERROR: " + data["error"])
        else:
            sig = data["signal"]
            line = symbol.ljust(12) + sig.ljust(8) + "$" + str(round(data["price"], 4)).rjust(10) + " " + str(round(data["change_24h"] * 100, 2)).rjust(7) + "%" + " " + str(round(data["rsi"], 1)).rjust(7) + " " + str(int(data["volume"])).rjust(15)
            print(line)
    print("=" * 60)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Atlas AI Backtest Runner")
    parser.add_argument("--profile", choices=["low", "medium", "high"], help="Run single profile")
    parser.add_argument("--all", action="store_true", help="Run all profiles")
    parser.add_argument("--allocation", action="store_true", help="Show portfolio allocations")
    parser.add_argument("--scan", action="store_true", help="Show coin scanner example")
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
        print("")
        print("Usage:")
        print("  python backtest_runner.py --profile medium")
        print("  python backtest_runner.py --all")
        print("  python backtest_runner.py --allocation")
        print("  python backtest_runner.py --scan")
        print("")
        print("Default: Medium profile backtest")
        print("")
        run_single_profile("medium")