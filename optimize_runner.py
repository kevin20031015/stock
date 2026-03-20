"""
optimize_runner.py — 批次 GA 參數優化腳本
用法：python optimize_runner.py

對 target_stocks 清單中每支股票跑遺傳演算法，
找出最佳參數後存入 optimized_params.json。
下次網頁查詢這支股票時會自動讀取優化後的參數（顯示 AI 標記）。
"""

import json
import os

from modules.data_fetcher import fetch_history
from modules.strategy import run_strategy_analysis, GeneticOptimizer, DEFAULT_PARAMS

# ── 設定 ──────────────────────────────────────────────────────────────
CAPITAL = 500_000

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
PARAMS_FILE = "optimized_params.json"
# ─────────────────────────────────────────────────────────────────────


def save_params(symbol, params):
    """將 GA 優化後的參數存入本地 JSON 檔案"""
    data = {}
    if os.path.exists(PARAMS_FILE):
        try:
            with open(PARAMS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            pass
    data[symbol] = params
    with open(PARAMS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def run_optimization():
    print("🧬 批次 GA 參數優化啟動")
    print("=" * 80)
    print(f"{'股號':<12} {'GA最佳分數':>12} {'預設分數':>12} {'提升':>10} {'狀態':>8}")
    print("-" * 80)

    for symbol in target_stocks:
        df, fundamentals = fetch_history(symbol, '2y')

        # 上市抓不到自動改上櫃
        if df.empty and symbol.endswith('.TW'):
            alt = symbol.replace('.TW', '.TWO')
            df_alt, fund_alt = fetch_history(alt, '2y')
            if not df_alt.empty:
                df, fundamentals, symbol = df_alt, fund_alt, alt

        if df.empty:
            print(f"{symbol:<12} 無法取得資料")
            continue

        try:
            # 先跑預設參數作為基準
            _, default_perf, _, _, _, _, _, _ = run_strategy_analysis(
                df, fundamentals, CAPITAL, DEFAULT_PARAMS
            )
            default_return = default_perf['total_return']

            # GA 優化
            optimizer = GeneticOptimizer(df, fundamentals, CAPITAL)
            best_params, best_score = optimizer.run()
            optimizer.cleanup()

            improvement = round(best_score - default_return, 2)

            # ✅ score=-9999 代表 GA 找不到任何交易訊號，參數無意義，不存檔
            if best_score <= -9000:
                print(
                    f"{symbol:<12} {best_score:>+11.1f}% {default_return:>+11.1f}% "
                    f"{improvement:>+9.1f}%  ⚠️ 無訊號跳過"
                )
            else:
                save_params(symbol, best_params)
                print(
                    f"{symbol:<12} {best_score:>+11.1f}% {default_return:>+11.1f}% "
                    f"{improvement:>+9.1f}%  已存檔"
                )

        except Exception as e:
            print(f"{symbol:<12} 優化失敗: {e}")

    print("=" * 80)
    print(f"完成！參數已存入 {PARAMS_FILE}")
    print("網頁查詢這些股票時會自動套用優化參數（顯示 AI 標記）。")


if __name__ == "__main__":
    run_optimization()