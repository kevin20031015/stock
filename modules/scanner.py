"""
modules/scanner.py

統一的全市場掃描邏輯。
auto_scanner.py（Telegram 推播）和 server.py（API）都呼叫這裡，
維護時只需改一個地方。
"""

import yfinance as yf
import time
import concurrent.futures
import gc

from .technical_analysis import calculate_indicators_simple, check_strong_trend

# ✅ 上市/上櫃絕對量能門檻（單位：張）
# 上櫃基期量小，相對量比容易虛高；加上絕對量門檻才能確保流動性
OTC_MIN_VOLUME    = 500   # 上櫃：近5日均量至少 500 張
LISTED_MIN_VOLUME = 1000  # 上市：近5日均量至少 1000 張


def is_volume_sufficient(df, ticker):
    """
    上市/上櫃分開驗證量能品質。

    問題根源：上櫃股票日均量可能只有 50 張，今天成交 100 張量比就達 2x，
    但這種「爆量」毫無意義，主力根本無法在此規模進出。

    解法：量比（相對量）之外，額外要求近5日均量達到最低門檻。

    Returns:
        (bool, float): (是否通過, 近5日均量)
    """
    is_otc = ticker.endswith('.TWO')
    min_vol = OTC_MIN_VOLUME if is_otc else LISTED_MIN_VOLUME
    recent_avg_vol = df['Volume'].tail(5).mean()
    return recent_avg_vol >= min_vol, recent_avg_vol


def _process_chunk(chunk_tickers, twstock_module=None):
    """
    處理一小批股票的抓取、量能驗證與技術指標篩選。
    內部函式，由 run_full_market_scan 呼叫。
    """
    chunk_res = []
    pending_tickers = chunk_tickers.copy()
    max_retries = 3

    for attempt in range(max_retries):
        if not pending_tickers:
            break

        data = None
        try:
            data = yf.download(
                pending_tickers, period="3mo",
                group_by='ticker', progress=False,
                threads=False, auto_adjust=False
            )

            if data is None or data.empty:
                raise ValueError("Yahoo 回傳全空資料")

            failed_this_round = []

            for ticker in pending_tickers:
                df = None
                try:
                    df = data[ticker].dropna() if len(pending_tickers) > 1 else data.dropna()

                    if df.empty:
                        failed_this_round.append(ticker)
                        continue

                    if len(df) < 30:
                        continue

                    # 第一關：絕對量能過濾
                    vol_ok, avg_vol = is_volume_sufficient(df, ticker)
                    if not vol_ok:
                        continue

                    # 第二關：技術指標篩選
                    last = calculate_indicators_simple(df)
                    if last is None:
                        continue

                    is_bullish, mode = check_strong_trend(last)
                    if is_bullish:
                        name = ticker
                        code = ticker.split('.')[0]
                        if twstock_module and code in twstock_module.codes:
                            name = twstock_module.codes[code].name

                        chunk_res.append({
                            "id":       ticker,
                            "name":     name,
                            "market":   "OTC" if ticker.endswith('.TWO') else "Listed",
                            "is_otc":   ticker.endswith('.TWO'),
                            "price":    round(float(last['Close']), 2),
                            "vol_ratio": round(float(last['Vol_Ratio']), 2),
                            "avg_vol":  int(avg_vol),
                            "suggestion": mode,
                            "rsi":      round(float(last['RSI']), 1),
                        })

                except Exception:
                    failed_this_round.append(ticker)
                finally:
                    if df is not None:
                        del df

            pending_tickers = failed_this_round
            if pending_tickers:
                time.sleep(1.5)

        except Exception:
            time.sleep(1.5)
        finally:
            if data is not None:
                del data

    return chunk_res


def run_full_market_scan(targets, twstock_module=None, chunk_size=20, batch_size=5, max_workers=3):
    """
    執行全市場多執行緒掃描並回傳排序結果。

    Args:
        targets:        股票代號列表（例如 ['2330.TW', '3008.TW', ...]）
        twstock_module: 傳入已匯入的 twstock 模組（供查中文名稱），沒有就傳 None
        chunk_size:     每批下載的股票數，預設 20
        batch_size:     每輪同時送出的 chunk 數，預設 5
        max_workers:    ThreadPoolExecutor 工人數，預設 3

    Returns:
        list[dict]: 通過篩選的股票清單，依 RSI 降序（上櫃扣 5 分流動性折扣）
    """
    chunks = [targets[i:i + chunk_size] for i in range(0, len(targets), chunk_size)]
    results = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        for batch_start in range(0, len(chunks), batch_size):
            batch = chunks[batch_start: batch_start + batch_size]
            futures = [
                executor.submit(_process_chunk, chunk, twstock_module)
                for chunk in batch
            ]
            for future in concurrent.futures.as_completed(futures):
                res = future.result()
                if res:
                    results.extend(res)

            # 清理 yfinance 內部快取，避免記憶體洩漏
            try:
                import yfinance.shared as yfs
                if hasattr(yfs, '_ERRORS'): yfs._ERRORS.clear()
                if hasattr(yfs, '_DFS'):   yfs._DFS.clear()
            except Exception:
                pass
            gc.collect()

    # 排序：RSI 降序，上櫃扣 5 分（流動性折扣）
    results.sort(
        key=lambda x: (x['rsi'] - (5 if x['is_otc'] else 0)),
        reverse=True
    )

    otc_count    = sum(1 for s in results if s['is_otc'])
    listed_count = len(results) - otc_count
    print(f"📈 掃描完成：上市 {listed_count} 檔 / 上櫃 {otc_count} 檔（共 {len(results)} 檔通過）")

    return results