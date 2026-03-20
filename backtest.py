"""
backtest.py — 批次回測腳本
用法：python backtest.py
"""

import re
import time

from modules.data_fetcher import fetch_history
from modules.strategy import run_strategy_analysis, DEFAULT_PARAMS

# ── 設定 ──────────────────────────────────────────────────────────────
INITIAL_CAPITAL = 500_000
TEST_PERIOD     = '2y'

target_stocks = [
    "2377.TW",  # 微星
    "2886.TW",  # 兆豐金
    "4958.TW",  # 臻鼎
    "3017.TW",  # 奇鋐（散熱）
    "3035.TW",  # 智原（IP）
    "2330.TW",  # 台積電
    "2603.TW",  # 長榮（航運）
    "3231.TW",  # 緯創（AI伺服器）
    "2382.TW",  # 廣達
    "1519.TW",  # 華城（重電）
]


def parse_profit_pct(desc):
    """從交易 log desc 字串中提取百分比，例如 '🛡️ 硬停損 (-8.5%)' -> -8.5"""
    try:
        match = re.search(r'\(([-+]?\d*\.?\d+)%\)', desc)
        return float(match.group(1)) if match else 0.0
    except Exception:
        return 0.0


def run_batch_backtest():
    print("🚀 批量回測啟動")
    print(f"💰 初始本金: ${INITIAL_CAPITAL:,} | 📅 期間: {TEST_PERIOD}")
    print("=" * 95)
    print(f"{'股號':<12} {'最終資產':>12} {'報酬率':>9} {'交易次數':>8} {'勝率':>7} {'Sharpe':>8} {'W/L':>8}")
    print("-" * 95)

    results         = []
    total_start_cap = 0
    total_end_cap   = 0

    for symbol in target_stocks:
        df, fundamentals = fetch_history(symbol, TEST_PERIOD)

        # 上市抓不到自動改上櫃
        if df.empty and symbol.endswith('.TW'):
            alt = symbol.replace('.TW', '.TWO')
            df_alt, fund_alt = fetch_history(alt, TEST_PERIOD)
            if not df_alt.empty:
                df, fundamentals, symbol = df_alt, fund_alt, alt

        if df.empty:
            print(f"{symbol:<12} 無法取得資料")
            continue

        try:
            # run_strategy_analysis 回傳 8 個值
            _, perf, _, _, logs, checklist, forecast, _ = run_strategy_analysis(
                df, fundamentals, INITIAL_CAPITAL, DEFAULT_PARAMS
            )

            sell_logs    = [l for l in logs if l['type'] == 'SELL']
            wins         = sum(1 for l in sell_logs if parse_profit_pct(l['desc']) > 0)
            losses       = sum(1 for l in sell_logs if parse_profit_pct(l['desc']) < 0)
            total_trades = wins + losses
            win_rate     = wins / total_trades * 100 if total_trades > 0 else 0.0
            sharpe       = perf.get('sharpe', 0.0)

            results.append({
                "symbol":   symbol,
                "final":    perf['final_asset'],
                "return":   perf['total_return'],
                "trades":   total_trades,
                "win_rate": win_rate,
                "sharpe":   sharpe,
                "wins":     wins,
                "losses":   losses,
            })

            total_start_cap += INITIAL_CAPITAL
            total_end_cap   += perf['final_asset']

            ret_str = f"{perf['total_return']:+.1f}%"
            print(
                f"{symbol:<12} ${perf['final_asset']:>11,.0f} "
                f"{ret_str:>9} {total_trades:>8} {win_rate:>6.0f}% "
                f"{sharpe:>8.2f} {wins}W/{losses}L"
            )

        except Exception as e:
            print(f"{symbol:<12} 策略執行錯誤: {e}")

        time.sleep(0.5)

    # ── 總結 ──────────────────────────────────────────────────────────
    print("=" * 95)
    if not results:
        print("沒有產生任何回測結果。")
        return

    total_profit = total_end_cap - total_start_cap
    avg_return   = total_profit / total_start_cap * 100 if total_start_cap > 0 else 0

    print(f"\n📊 總結報告")
    print(f"  投資組合總本金: ${total_start_cap:>12,.0f}")
    print(f"  投資組合總市值: ${total_end_cap:>12,.0f}")
    print(f"  總體損益:       ${total_profit:>+12,.0f}  ({'獲利' if total_profit >= 0 else '虧損'})")
    print(f"  總體報酬率:     {avg_return:>+8.2f}%")

    best  = max(results, key=lambda x: x['return'])
    worst = min(results, key=lambda x: x['return'])
    print(f"\n  MVP:  {best['symbol']}  ({best['return']:+.1f}%)")
    print(f"  殿尾: {worst['symbol']} ({worst['return']:+.1f}%)")

    avg_win_rate = sum(r['win_rate'] for r in results) / len(results)
    avg_sharpe   = sum(r['sharpe']   for r in results) / len(results)
    print(f"\n  平均勝率:   {avg_win_rate:.1f}%")
    print(f"  平均Sharpe: {avg_sharpe:.2f}")


if __name__ == "__main__":
    run_batch_backtest()