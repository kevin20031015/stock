from flask import Flask, jsonify, request
from flask_cors import CORS
import concurrent.futures
import time
import json
import random
import yfinance as yf
import os
import gc
import math # ✅ 記得加上這行

# ✅ 新增這個清洗函數（放在 app = Flask(__name__) 下方即可）
def clean_nan(obj):
    """遞迴檢查並將資料中的 NaN 轉換為合法的 None"""
    if isinstance(obj, dict):
        return {k: clean_nan(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [clean_nan(v) for v in obj]
    elif isinstance(obj, float) and math.isnan(obj):
        return None  # 將 NaN 轉為 None (JSON 序列化後會變成 null)
    return obj
def save_params(symbol, params):
    """將 GA 優化後的參數存入本地 JSON 檔案"""
    file_path = "optimized_params.json"
    data = {}
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except:
            pass
    data[symbol] = params
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

# 匯入我們的模組
from modules.data_fetcher import (
    get_all_tw_stocks, fetch_news_sentiment, get_market_sentiment, 
    get_stock_info, fetch_history, SCAN_CACHE
)
# ✅ 引入共用大腦 check_strong_trend
from modules.technical_analysis import calculate_indicators_simple, check_strong_trend
from modules.scanner import run_full_market_scan
from modules.ai_predictor import run_ai_prediction, TORCH_AVAILABLE
from modules.strategy import run_strategy_analysis, GeneticOptimizer, DEFAULT_PARAMS

import threading
import uuid

app = Flask(__name__)
CORS(app)

# scan lock：防止多次同時觸發全市場掃描
_scan_lock = threading.Lock()

# ── 非同步掃描任務狀態表 ─────────────────────────────────────────────────
# task_id -> { status: 'running'|'done'|'error', progress: int, total: int,
#              results: list, error: str }
_scan_tasks: dict = {}
_scan_tasks_lock = threading.Lock()

# indicator cache：同一 symbol 短時間內重複查詢不重算指標
_indicator_cache = {}
_indicator_cache_lock = threading.Lock()
_INDICATOR_TTL = 300  # 5 分鐘

# 嘗試匯入 twstock 以供掃描器名稱查詢
try:
    import twstock
except ImportError:
    twstock = None

@app.route('/api/stock/<symbol>')
def get_stock_data(symbol):
    try:
        capital = float(request.args.get('capital', 500000))
        period = request.args.get('period', '1y')
        custom_params = request.args.get('params')
        strategy_params = DEFAULT_PARAMS
        if custom_params:
            try: strategy_params = json.loads(custom_params)
            except: pass

        df, fundamentals = fetch_history(symbol, period)
        if df.empty: return jsonify({"error": "No data"}), 404
        
        # ✅ indicator cache：同一 symbol 5 分鐘內不重算指標
        cache_key = f"{symbol}_{period}"
        with _indicator_cache_lock:
            cached = _indicator_cache.get(cache_key)
            if cached and (time.time() - cached['ts'] < _INDICATOR_TTL):
                pre_calc = cached['data']
            else:
                pre_calc = None

        market_sentiment = get_market_sentiment()
        news_sentiment = fetch_news_sentiment(symbol)

        analyzed_df, perf, sugg, sugg_color, logs, checklist, forecast, chart_data_with_equity = run_strategy_analysis(
            df, fundamentals, capital, strategy_params,
            pre_calculated_data=pre_calc
        )

        # ✅ 若沒有 cache，存入 cache 供下次使用
        if pre_calc is None:
            with _indicator_cache_lock:
                _indicator_cache[cache_key] = {'data': analyzed_df, 'ts': time.time()}
        
        chart_data = chart_data_with_equity
        if period == '1mo': chart_data = chart_data[-30:]
        elif period == '3mo': chart_data = chart_data[-90:]
        elif period == '6mo': chart_data = chart_data[-120:]
        elif period == '1y': chart_data = chart_data[-250:]
        
        # 將原本要回傳的資料先打包
        response_payload = {
            "chart_data": chart_data,
            "strategy": {
                "performance": perf, "suggestion": sugg, "suggestion_color": sugg_color,
                "logs": logs[-10:], "checklist": checklist, "fundamentals": fundamentals,
                "current_params": strategy_params,
                "forecast": forecast
            },
            "market_sentiment": market_sentiment,
            "news_sentiment": news_sentiment
        }
        
        # 經過 clean_nan 處理後再轉為 JSON
        return jsonify(clean_nan(response_payload))
    except Exception as e:
        print(f"API Error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/search/<symbol>')
def search_stock(symbol):
    res = get_stock_info(symbol)
    if res['success']: return jsonify(res)
    return jsonify({"error": "查無代號", "success": False}), 404

@app.route('/api/optimize/<symbol>')
def optimize_strategy(symbol):
    try:
        capital = float(request.args.get('capital', 500000))
        df, fundamentals = fetch_history(symbol, '1y')
        if df.empty: return jsonify({"error": "No data"}), 404
        optimizer = GeneticOptimizer(df, fundamentals, capital)
        best_params, best_score = optimizer.run()
        _, default_perf, _, _, _, _, _, _ = run_strategy_analysis(df, fundamentals, capital, DEFAULT_PARAMS)
        result = jsonify({
            "best_params": best_params,
            "best_return": best_score,
            "default_return": default_perf['total_return'],
            "improvement": round(best_score - default_perf['total_return'], 2)
        })
        optimizer.cleanup()  # ✅ 釋放 GA 記憶體
        return result
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/scan', methods=['POST', 'GET'])
def scan_market():
    """
    POST → 啟動背景掃描，立刻回傳 task_id
    GET  → 相容舊呼叫：若已有進行中的任務回傳其 id，否則新建一個
    """
    # 若已有任務正在跑，回傳該任務 id（不重複啟動）
    with _scan_tasks_lock:
        for tid, task in _scan_tasks.items():
            if task['status'] == 'running':
                return jsonify({"task_id": tid, "already_running": True})

    task_id = str(uuid.uuid4())
    with _scan_tasks_lock:
        _scan_tasks[task_id] = {
            "status":   "running",
            "progress": 0,
            "total":    0,
            "results":  [],
            "error":    None,
        }

    def _bg_scan():
        try:
            targets = get_all_tw_stocks()
            if len(targets) > 1819:
                targets = random.sample(targets, 1819)

            with _scan_tasks_lock:
                _scan_tasks[task_id]['total'] = len(targets)

            print(f"[Task {task_id[:8]}] 開始掃描 {len(targets)} 檔股票...")

            # ── 進度回呼：每掃完一個 chunk 更新 progress ──────────────────
            completed_ref = [0]
            original_scan = run_full_market_scan

            def scan_with_progress(tgts, tw, **kw):
                chunk_size = kw.get('chunk_size', 10)   # ✅ 20→10，每批記憶體減半
                results_acc = []
                chunks = [tgts[i:i+chunk_size] for i in range(0, len(tgts), chunk_size)]
                import concurrent.futures, gc
                from modules.scanner import _process_chunk
                batch_size  = kw.get('batch_size', 3)   # ✅ 5→3，並發壓力降低
                max_workers = kw.get('max_workers', 2)  # ✅ 3→2，降低同時下載數
                with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
                    for bs in range(0, len(chunks), batch_size):
                        batch = chunks[bs:bs+batch_size]
                        futures = [ex.submit(_process_chunk, c, tw) for c in batch]
                        for fut in concurrent.futures.as_completed(futures):
                            res = fut.result()
                            if res:
                                results_acc.extend(res)
                            completed_ref[0] += chunk_size
                            with _scan_tasks_lock:
                                _scan_tasks[task_id]['progress'] = min(completed_ref[0], len(tgts))
                        try:
                            import yfinance.shared as yfs
                            if hasattr(yfs, '_ERRORS'): yfs._ERRORS.clear()
                            if hasattr(yfs, '_DFS'):   yfs._DFS.clear()
                        except Exception:
                            pass
                        gc.collect()
                results_acc.sort(key=lambda x: (x['rsi'] - (5 if x['is_otc'] else 0)), reverse=True)
                return results_acc[:200]  # ✅ 只保留前200筆，足夠用且大幅減少傳輸量

            results = scan_with_progress(targets, twstock)

            n_results = len(results)
            SCAN_CACHE['results']        = results
            SCAN_CACHE['last_scan_time'] = time.time()
            del results          # ✅ 釋放局部變數，SCAN_CACHE 已是唯一一份

            with _scan_tasks_lock:
                _scan_tasks[task_id]['status']   = 'done'
                _scan_tasks[task_id]['progress'] = len(targets)
                # ✅ 不在 task 裡存 results，結果統一從 SCAN_CACHE 讀

            import gc as _gc; _gc.collect()
            print(f"[Task {task_id[:8]}] 掃描完成，{n_results} 檔通過")

        except Exception as e:
            with _scan_tasks_lock:
                _scan_tasks[task_id]['status'] = 'error'
                _scan_tasks[task_id]['error']  = str(e)
            print(f"[Task {task_id[:8]}] 掃描失敗：{e}")

    t = threading.Thread(target=_bg_scan, daemon=True, name=f"scan-{task_id[:8]}")
    t.start()

    return jsonify({"task_id": task_id, "already_running": False})


@app.route('/api/scan/status/<task_id>')
def scan_status(task_id):
    """輪詢掃描進度"""
    with _scan_tasks_lock:
        task = _scan_tasks.get(task_id)

    if task is None:
        # 找不到任務時，回傳快取（相容舊版前端）
        return jsonify({
            "status":   "done",
            "progress": len(SCAN_CACHE['results']),
            "total":    len(SCAN_CACHE['results']),
            "results":  SCAN_CACHE['results'],
        })

    if task['status'] == 'done':
        # ✅ 結果從 SCAN_CACHE 讀，task dict 讀完即清，釋放記憶體
        results_to_send = SCAN_CACHE.get('results', [])
        with _scan_tasks_lock:
            _scan_tasks.pop(task_id, None)
        return jsonify({
            "status":   "done",
            "progress": task['progress'],
            "total":    task['total'],
            "results":  results_to_send,
            "error":    None,
        })

    return jsonify({
        "status":   task['status'],
        "progress": task['progress'],
        "total":    task['total'],
        "results":  [],
        "error":    task['error'],
    })


@app.route('/api/predict_ai/<symbol>')
def predict_ai(symbol):
    if not TORCH_AVAILABLE:
        return jsonify({"valid": False, "msg": "Server 無 GPU/PyTorch 支援"})

    df, _ = fetch_history(symbol, period='5y')
    if df.empty:
        return jsonify({"valid": False, "msg": "無資料"})

    # ✅ 傳入 symbol，讓推論模組找到對應的 models/<symbol>.pth
    result = run_ai_prediction(df, symbol=symbol)
    return jsonify(result)

if __name__ == '__main__':
    app.run(debug=True, port=5000)