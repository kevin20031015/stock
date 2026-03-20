import pandas as pd
import numpy as np
import random
import threading
import concurrent.futures
import gc
from collections import OrderedDict
from .data_fetcher import get_market_sentiment
from .technical_analysis import calculate_all_indicators, calculate_fundamental_score, calculate_win_rate, calculate_sharpe


class _LRUCache:
    """有上限的 LRU Cache，避免 GA 迭代時 fitness_cache 無限膨脹。"""
    def __init__(self, maxsize=500):
        self.cache = OrderedDict()
        self.maxsize = maxsize
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            if key not in self.cache:
                return None
            self.cache.move_to_end(key)
            return self.cache[key]

    def set(self, key, value):
        with self._lock:
            if key in self.cache:
                self.cache.move_to_end(key)
            self.cache[key] = value
            if len(self.cache) > self.maxsize:
                self.cache.popitem(last=False)  # 淘汰最舊

    def clear(self):
        with self._lock:
            self.cache.clear()

DEFAULT_PARAMS = {
    "strategy_type": "swing",
    "adx_threshold": 20,
    "rsi_upper": 85,
    "rsi_lower": 40,
    "vol_ratio": 1.75,
    "bb_width_min": 0.03,
    "stop_loss": 0.08,
    "trailing_start": 0.05,
    "take_profit": 0.20,
    "atr_multiplier": 2.0
}

def run_strategy_analysis(df, fundamentals, initial_capital, params=DEFAULT_PARAMS, pre_calculated_data=None):
    if pre_calculated_data is not None:
        # ✅ GA 路徑：用 assign 建立臨時欄位，不對 cached_data 做完整 copy
        data = pre_calculated_data.assign(
            Next_Open=pre_calculated_data['Open'].shift(-1),
            past_20_days_high=pre_calculated_data['High'].rolling(window=20, min_periods=1).max().shift(1),
            Signal=0
        )
    else:
        if df.empty: return df, {}, "無資料", "gray", [], {}, {}, []
        data = calculate_all_indicators(df)
        data['Next_Open'] = data['Open'].shift(-1)
        data['past_20_days_high'] = data['High'].rolling(window=20, min_periods=1).max().shift(1)

    
    p = {**DEFAULT_PARAMS, **params}
    strategy_type = p.get('strategy_type', 'swing')
    
    capital = initial_capital
    position = 0          
    entry_price = 0       
    highest_price = 0     
    days_held = 0         
    trailing_stop = 0     
    
    last_sell_index = -999
    cooldown_days = 3
    fee_rate = 0.001425 * 0.6
    tax_rate = 0.003
    trade_log = []
    
    start_idx = 60 
    data['Signal'] = 0

    fund_score = calculate_fundamental_score(fundamentals)
    market_sentiment = get_market_sentiment()

    # ✅ 預先把所有迴圈需要的欄位轉成 numpy array，避免逐行 iloc 的 pandas overhead
    arr_close        = data['Close'].values
    arr_next_open    = data['Next_Open'].values
    arr_atr          = data['ATR'].values
    arr_rsi          = data['RSI'].values
    arr_k            = data['K'].values
    arr_d            = data['D'].values
    arr_ma5          = data['MA5'].values
    arr_ma20         = data['MA20'].values
    arr_ma60         = data['MA60'].values
    arr_macd_osc     = data['MACD_OSC'].values
    arr_vol_ratio    = data['Vol_Ratio'].values
    arr_volatility   = data['Volatility'].values
    arr_bb_up        = data['BB_Up'].values
    arr_inst_buy     = data['Institutional_Buy'].values
    arr_p20high      = data['past_20_days_high'].values
    arr_signal       = np.zeros(len(data), dtype=int)
    # ✅ 融資指標陣列（抓不到資料時欄位為全 0，不影響原有邏輯）
    arr_margin_diff  = data['Margin_Diff'].values           # 每日融資增減（負=散戶退場）
    arr_margin_bal   = data['MarginPurchaseBalance'].values  # 融資餘額絕對值

    equity_curve = []
    current_equity = initial_capital
    initial_close_price = arr_close[start_idx] if len(data) > start_idx else 0

    if len(data) > start_idx:
        for i in range(start_idx, len(data)-1):
            # ✅ 全改用預先抽取的 numpy array，避免每次 iloc 的 pandas overhead
            current_close    = arr_close[i]
            execution_price  = arr_next_open[i]
            atr              = arr_atr[i]
            date             = data.index[i]

            if pd.isna(execution_price): continue

            if position > 0:
                current_equity = capital + position * current_close
            else:
                current_equity = capital
            equity_curve.append(current_equity)
            
            # 1. 賣出檢查
            if position > 0:
                days_held += 1
                if current_close > highest_price:
                    highest_price = current_close
                    if strategy_type == 'trend':
                        trailing_stop = max(trailing_stop, arr_ma20[i])
                    else:
                        trailing_stop = highest_price - (atr * p['atr_multiplier'])

                unrealized_profit_pct = (current_close - entry_price) / entry_price
                do_sell = False
                desc = ""

                if not do_sell and current_close < entry_price * (1 - p['stop_loss']):
                    do_sell, desc = True, "🛡️ 硬停損觸發"

                if not do_sell and current_close <= trailing_stop:
                    if strategy_type == 'trend':
                        do_sell, desc = True, "📉 跌破趨勢線"
                    else:
                        do_sell, desc = True, "🛡️ ATR 停損"

                profit_pct_from_high = (highest_price - current_close) / highest_price
                if strategy_type == 'swing' and not do_sell:
                    if unrealized_profit_pct > 0.3 and profit_pct_from_high > 0.05:
                        do_sell, desc = True, "🍖 獲利回吐出場"
                    elif unrealized_profit_pct > 0.05 and profit_pct_from_high > 0.08:
                        do_sell, desc = True, "🍖 保本出場"

                if strategy_type == 'swing' and not do_sell:
                    is_profit_target = unrealized_profit_pct > p['take_profit']
                    is_rsi_hot = arr_rsi[i] > 80
                    bias_ma20 = (current_close - arr_ma20[i]) / arr_ma20[i]
                    is_bias_high = bias_ma20 > 0.20
                    if is_profit_target and (is_rsi_hot or is_bias_high):
                        do_sell, desc = True, "🔥 過熱止盈 (RSI/乖離)"
                    elif unrealized_profit_pct > 0.40:
                        do_sell, desc = True, "💰 超額獲利止盈"

                if do_sell:
                    sell_price = execution_price
                    revenue = position * sell_price * (1 - fee_rate - tax_rate)
                    capital += revenue
                    real_pct = (sell_price - entry_price) / entry_price * 100
                    trade_log.append({
                        "date": data.index[i+1],
                        "type": "SELL",
                        "price": sell_price,
                        "desc": f"{desc} ({real_pct:.1f}%)",
                        "balance": int(capital)
                    })
                    position = 0
                    days_held = 0
                    last_sell_index = i
                    arr_signal[i+1] = -1
                    continue

            # 2. 買進檢查
            if position == 0:
                if (i - last_sell_index) < cooldown_days: continue

                if arr_close[i] < arr_ma60[i]: continue
                if arr_ma60[i] < arr_ma60[i-1]: continue

                is_gap_huge = execution_price > current_close * 1.05
                past_20_days_high = arr_p20high[i]
                if np.isnan(past_20_days_high):
                    past_20_days_high = 99999

                is_breakout = execution_price > past_20_days_high
                bias_ma5 = (execution_price - arr_ma5[i]) / arr_ma5[i]
                is_bias_huge = bias_ma5 > 0.15

                should_skip = False
                skip_reason = ""
                if is_gap_huge and not is_breakout:
                    should_skip = True
                    skip_reason = "🚫 開盤偷漲且未突破，放棄"
                elif is_bias_huge:
                    should_skip = True
                    skip_reason = "🚫 乖離過大(>15%)，危險"

                if should_skip:
                    trade_log.append({
                        "date": data.index[i+1],
                        "type": "SKIP",
                        "price": execution_price,
                        "desc": skip_reason,
                        "balance": int(capital)
                    })
                    continue

                adx_val = data['ADX'].iat[i]  # ADX 不常用，保持原樣避免多一個 array
                if adx_val < 25: continue
                vol_i = arr_volatility[i]
                if not np.isnan(vol_i) and (vol_i > 0.08 or vol_i < 0.005): continue

                cond_buy = False
                reason = ""
                signal_type = 0

                macd_bull = arr_macd_osc[i] > 0
                is_k_up   = arr_k[i] > arr_d[i]
                kd_gold   = (arr_k[i] > arr_d[i]) and (arr_k[i-1] <= arr_d[i-1])

                # ── 融資指標：判斷散戶動向 ─────────────────────────────
                # retail_panic：近 3 日融資連續減少 → 散戶正在被洗下車
                # 條件：有實際融資資料（餘額 > 0）才啟用，全 0 代表抓不到資料時跳過
                has_margin_data = arr_margin_bal[i] > 0
                retail_panic = (
                    has_margin_data and
                    i >= 2 and
                    arr_margin_diff[i]   < 0 and
                    arr_margin_diff[i-1] < 0 and
                    arr_margin_diff[i-2] < 0
                )
                # margin_shrinking：近 5 日融資持續萎縮（籌碼更乾淨，趨勢型用）
                margin_shrinking = (
                    has_margin_data and
                    i >= 4 and
                    arr_margin_diff[i-4:i+1].sum() < 0
                )

                if strategy_type == 'trend':
                    on_ma20 = arr_close[i] > arr_ma20[i]
                    if on_ma20 and macd_bull and arr_vol_ratio[i] > 1.0:
                        cond_buy, reason, signal_type = True, "🌊 趨勢確認", 1
                        # ✅ 趨勢策略：融資同步萎縮 → 升級為更強訊號
                        if margin_shrinking and arr_inst_buy[i] > 0:
                            reason = "🌊💎 趨勢+籌碼集中（融資萎縮+法人買）"
                else:
                    bias = (current_close - arr_ma20[i]) / arr_ma20[i]
                    if bias > 0.12: continue

                    if arr_rsi[i] < p['rsi_upper'] and arr_rsi[i] > p['rsi_lower']:
                        if fund_score >= 1 and bias < 0.03 and arr_ma20[i] > arr_ma20[i-1] and kd_gold:
                            if arr_inst_buy[i] > 0 and retail_panic:
                                # ✅ S 級買點：法人吃貨 + 散戶踩踏出場（籌碼最乾淨）
                                cond_buy, reason, signal_type = True, "💎 S級拉回 (主力吃貨+散戶踩踏)", 2
                            else:
                                cond_buy, reason, signal_type = True, "🎣 優質拉回", 2
                        elif arr_vol_ratio[i] > p['vol_ratio'] and macd_bull and is_k_up:
                            cond_buy, reason, signal_type = True, "🚀 帶量突破", 1

                if cond_buy:
                    buy_price = execution_price
                    risk_percent = 0.05
                    if signal_type == 1: risk_percent = 0.08

                    if strategy_type == 'trend':
                        stop_price = arr_ma20[i]
                    else:
                        stop_price = buy_price * (1 - p['stop_loss'])

                    risk_per_share = buy_price - stop_price
                    if risk_per_share <= 0: risk_per_share = buy_price * 0.05

                    risk_capital = current_equity * risk_percent
                    suggested_shares = int(risk_capital / risk_per_share)
                    max_shares = int((capital * 0.98) / (buy_price * (1 + fee_rate)))
                    shares = min(suggested_shares, max_shares)

                    if shares > 10:
                        cost = shares * buy_price * (1 + fee_rate)
                        capital -= cost
                        position = shares
                        entry_price = buy_price
                        highest_price = buy_price
                        trailing_stop = stop_price
                        arr_signal[i+1] = signal_type

                        trade_log.append({
                            "date": data.index[i+1],
                            "type": "BUY",
                            "price": buy_price,
                            "desc": reason,
                            "balance": int(capital)
                        })

    # ✅ 迴圈結束，把 numpy signal array 寫回 DataFrame（避免迴圈內逐行 data.at）
    data['Signal'] = arr_signal

    last_price = arr_close[-1]
    if position > 0:
        final_asset = capital + (position * last_price)
    else:
        final_asset = capital

    is_k_up     = arr_k[-1] > arr_d[-1]
    is_macd_bull = arr_macd_osc[-1] > 0
    chip_buy    = arr_inst_buy[-1] > 0

    # ── 籌碼細項指標 ────────────────────────────────────────────────
    arr_foreign = data['Foreign'].values
    arr_trust   = data['Trust'].values

    # 外資近5日累計買賣超（正=買超，負=賣超）
    foreign_5d  = int(arr_foreign[-5:].sum()) if len(arr_foreign) >= 5 else 0
    trust_5d    = int(arr_trust[-5:].sum())   if len(arr_trust)   >= 5 else 0
    inst_5d     = int(arr_inst_buy[-5:].sum()) if len(arr_inst_buy) >= 5 else 0

    # 外資連續買超天數（從最新往前數）
    foreign_streak = 0
    for v in reversed(arr_foreign[-20:]):
        if v > 0: foreign_streak += 1
        else: break

    # 投信連續買超天數
    trust_streak = 0
    for v in reversed(arr_trust[-20:]):
        if v > 0: trust_streak += 1
        else: break

    # 外資今日單日買賣超
    foreign_today = int(arr_foreign[-1]) if len(arr_foreign) > 0 else 0
    trust_today   = int(arr_trust[-1])   if len(arr_trust)   > 0 else 0

    # ── 融資指標統計 ────────────────────────────────────────────────
    margin_bal_latest = int(arr_margin_bal[-1]) if len(arr_margin_bal) > 0 else 0
    # 近 5 日融資增減合計（負=散戶持續退場）
    margin_diff_5d = int(arr_margin_diff[-5:].sum()) if len(arr_margin_diff) >= 5 else 0
    # 近 5 日連續融資減少天數（從最新往前數）
    margin_shrink_days = 0
    for v in reversed(arr_margin_diff[-10:]):
        if v < 0: margin_shrink_days += 1
        else: break
    # 融資水位：餘額佔近 60 日最高點的比例（越低代表籌碼越乾淨）
    margin_60d_max = arr_margin_bal[-60:].max() if len(arr_margin_bal) >= 60 else margin_bal_latest
    margin_level_pct = round(margin_bal_latest / margin_60d_max * 100, 1) if margin_60d_max > 0 else 0

    suggestion = "觀望 (WAIT)"
    suggestion_color = "gray"

    if position > 0:
        suggestion, suggestion_color = "持股中 (HOLD)", "red"
    elif arr_signal[-2] > 0:
        suggestion, suggestion_color = "建議買進 (BUY)", "red"
    elif is_macd_bull and is_k_up:
        suggestion, suggestion_color = "趨勢偏多 (WATCH)", "orange"

    checklist = {
        "adx_ok": bool(data['ADX'].iat[-1] > p['adx_threshold']),
        "vol_ok": bool(arr_vol_ratio[-1] > p['vol_ratio']),
        "macd": bool(is_macd_bull),
        "kd": bool(is_k_up),
        "fund_ok": bool(fund_score >= 1),
        "chip_ok": bool(chip_buy),
                "chip_detail": {
                    "foreign_today": foreign_today,
                    "trust_today":   trust_today,
                    "foreign_5d":    foreign_5d,
                    "trust_5d":      trust_5d,
                    "inst_5d":       inst_5d,
                    "foreign_streak": foreign_streak,
                    "trust_streak":   trust_streak,
                    # ✅ 融資面（有資料才有意義，前端根據 margin_bal_latest > 0 決定是否顯示）
                    "margin_bal":         margin_bal_latest,
                    "margin_diff_5d":     margin_diff_5d,
                    "margin_shrink_days": margin_shrink_days,
                    "margin_level_pct":   margin_level_pct,
                }
    }

    forecast = {
        "trend": "多頭" if arr_ma20[-1] > arr_ma60[-1] else "空頭",
        "action_title": "觀望",
        "action_desc": "大盤或個股訊號不明確，建議空手。",
        "support": round(float(arr_ma20[-1]), 2),
        "pressure": round(float(arr_bb_up[-1]), 2),
        "stop_loss": 0,
        "chip_status": "法人買超" if chip_buy else "無"
    }

    if position > 0:
        forecast['action_title'] = "續抱監控"
        forecast['action_desc'] = f"持股中。停損設於 {round(trailing_stop, 2)}。"
        forecast['stop_loss'] = round(trailing_stop, 2)
    elif suggestion == "建議買進 (BUY)":
        forecast['action_title'] = "準備進場"
        forecast['action_desc'] = "訊號浮現，建議明日開盤進場，並嚴設停損。"
        forecast['stop_loss'] = round(last_price * (1-p['stop_loss']), 2)

    data = data.where(pd.notnull(data), None)
    total_return = (final_asset - initial_capital) / initial_capital * 100
    
    buy_hold_return = 0
    if initial_close_price > 0:
        buy_hold_return = ((last_price - initial_close_price) / initial_close_price) * 100

    sharpe = calculate_sharpe(data)

    # ✅ 只保留最近 250 個交易日的 equity_curve，避免無限累積
    equity_curve = equity_curve[-250:]

    # Vectorized chart data creation
    equity_df = pd.DataFrame(equity_curve, columns=['equity'])
    equity_df.index = data.index[start_idx:start_idx + len(equity_curve)]
    data['equity'] = equity_df['equity']
    data['equity'] = data['equity'].ffill()
    data['equity'] = data['equity'].bfill()
    if not equity_curve:
        data['equity'] = initial_capital
    
    if initial_close_price > 0:
        data['bh_equity'] = initial_capital * (data['Close'] / initial_close_price)
    else:
        data['bh_equity'] = initial_capital

    chart_df = data.reset_index()
    # ✅ 不在這裡手動建 time 欄位，讓下方 rename_map 的 'Date'->'time' 統一處理
    # 避免 Date rename 後與手動建立的 time 衝突，產生重複欄位 Warning

    rename_map = {
        'Date':     'time',
        'Close':    'close',
        'Open':     'open',
        'High':     'high',
        'Low':      'low',
        'MA5':      'ma5',
        'MA20':     'ma20',
        'Vol_Ratio':'vol_ratio',
        'Signal':   'signal',
        'RSI':      'rsi',
        'K':        'k',
        'D':        'd',
        'MACD_OSC': 'macd_osc',
        'MACD_DIF': 'macd_dif',
        'MACD_DEA': 'macd_dea',
        'BB_Up':    'bb_up',
        'BB_Low':   'bb_low',
        'Foreign':          'foreign',
        'Trust':            'trust',
        'Institutional_Buy':'inst_buy',
    }

    chart_df = chart_df.rename(columns=rename_map)

    # ✅ time 欄位格式化為字串（rename 後 Date 變成 time，需轉成前端可讀的字串）
    chart_df['time'] = chart_df['time'].dt.strftime('%Y-%m-%d')

    # ✅ signal 欄位確保是整數且 NaN 填 0（rename 後才處理，不會重複）
    chart_df['signal'] = chart_df['signal'].fillna(0).astype(int)

    # ✅ required_cols 用 dict.fromkeys 去重，避免 rename_map 有重複 value 時再次炸掉
    required_cols = list(dict.fromkeys(list(rename_map.values()) + ['equity', 'bh_equity']))
    chart_data_with_equity = chart_df[required_cols].to_dict('records')

    return data, {
        "total_return": round(total_return, 2), 
        "buy_hold_return": round(buy_hold_return, 2),
        "trade_count": len(trade_log), 
        "final_asset": int(final_asset),
        "win_rate": calculate_win_rate(trade_log),
        "sharpe": round(sharpe, 2)
    }, suggestion, suggestion_color, trade_log, checklist, forecast, chart_data_with_equity

class GeneticOptimizer:
    def __init__(self, df, fundamentals, capital=500000, seed=42):
        self.cached_data = calculate_all_indicators(df).iloc[-300:]
        self.fundamentals = fundamentals
        self.capital = capital
        self.seed = seed
        random.seed(self.seed)
        np.random.seed(self.seed)
        
        self.population_size = 50   
        self.generations = 25       
        self.base_mutation_rate = 0.2
        self.mutation_rate = self.base_mutation_rate
        self.elitism_count = 8
        self.early_stop_patience = 10
        self.crossover_rate = 0.7
        
        self.hall_of_fame = [] 
        self.hof_size = 10
        
        self.gene_space = {
            "adx_threshold": (15, 40), 
            "rsi_upper": (75, 95),      
            "rsi_lower": (20, 45), 
            "vol_ratio": (1.1, 2.5), 
            "bb_width_min": (0.02, 0.08),
            "stop_loss": (0.05, 0.15), 
            "trailing_start": (0.03, 0.12),
            "atr_multiplier": (1.5, 4.0)
        }
        
        self.cache_lock = threading.Lock()
        self.fitness_cache = _LRUCache(maxsize=500)  # ✅ LRU 有上限，取代無限 dict

    def get_params_signature(self, params):
        items = []
        for k in sorted(params.keys()):
            v = params[k]
            if isinstance(v, float): v = round(v, 6)
            items.append((k, v))
        return tuple(items)

    def validate_individual(self, ind):
        ind['rsi_lower'] = min(ind['rsi_lower'], ind['rsi_upper'] - 15)
        ind['rsi_lower'] = max(10, ind['rsi_lower'])
        
        for k, (min_v, max_v) in self.gene_space.items():
            if ind[k] < min_v: ind[k] = min_v
            if ind[k] > max_v: ind[k] = max_v
            if isinstance(min_v, int): ind[k] = int(ind[k])
            else: ind[k] = round(ind[k], 3)
        return ind

    def create_individual(self):
        ind = {}
        for k, (min_v, max_v) in self.gene_space.items():
            if isinstance(min_v, int):
                ind[k] = random.randint(min_v, max_v)
            else:
                ind[k] = round(random.uniform(min_v, max_v), 3)
        return self.validate_individual(ind)

    def fitness(self, params):
        sig = self.get_params_signature(params)
        cached = self.fitness_cache.get(sig)
        if cached is not None:
            return cached

        try:
            _, perf, _, _, _, _, _, _ = run_strategy_analysis(
                pd.DataFrame(), self.fundamentals, self.capital, params, pre_calculated_data=self.cached_data 
            )
            
            raw_return = perf.get('total_return', 0)
            sharpe = perf.get('sharpe', 0)
            trade_count = perf.get('trade_count', 0)
            
            score = raw_return
            score += sharpe * 25  # ✅ 修正：原本 *20 + *5 重複計算，統一為 *25
            
            if trade_count == 0:
                score = -9999
            elif trade_count < 4:
                score -= 50
            elif trade_count < 8:
                score -= 15

            self.fitness_cache.set(sig, score)
            return score
        except:
            return -999

    def local_search(self, individual):
        optimized_ind = individual.copy()
        target_keys = random.sample(list(self.gene_space.keys()), 3)
        current_score = self.fitness(optimized_ind)

        for _ in range(10):
            key = random.choice(target_keys)
            original_val = optimized_ind[key]
            min_v, max_v = self.gene_space[key]
            step = 1 if isinstance(min_v, int) else (max_v - min_v) * 0.05
            
            # 嘗試增加
            optimized_ind[key] = original_val + step
            optimized_ind = self.validate_individual(optimized_ind)
            if optimized_ind[key] != original_val:
                fit_plus = self.fitness(optimized_ind)
                if fit_plus > current_score:
                    current_score = fit_plus
                    continue 
            
            # 嘗試減少
            optimized_ind[key] = original_val - step
            optimized_ind = self.validate_individual(optimized_ind)
            if optimized_ind[key] != original_val:
                fit_minus = self.fitness(optimized_ind)
                if fit_minus > current_score:
                    current_score = fit_minus
                    continue
            
            # 都沒有更好，恢復原狀
            optimized_ind[key] = original_val
            
        return optimized_ind

    def update_hall_of_fame(self, population, scores):
        for ind, score in zip(population, scores):
            sig = self.get_params_signature(ind)
            if any(self.get_params_signature(h['params']) == sig for h in self.hall_of_fame):
                continue
            self.hall_of_fame.append({'params': ind.copy(), 'score': score})
        
        self.hall_of_fame.sort(key=lambda x: x['score'], reverse=True)
        self.hall_of_fame = self.hall_of_fame[:self.hof_size]

    def run(self):
        population = [self.create_individual() for _ in range(self.population_size)]
        
        best_params = DEFAULT_PARAMS
        best_score = -float('inf')
        no_improve_count = 0
        
        print(f"🔥 GA v2.5.1 Hybrid 啟動 (Pop: {self.population_size}, Gen: {self.generations})")
        import os
        executor_cls = concurrent.futures.ThreadPoolExecutor 
        _max_workers = min(os.cpu_count() or 4, 4)  # ✅ 限制在 CPU 核心數，避免 GIL 競爭
        
        for gen in range(self.generations):
            scores = []
            with executor_cls(max_workers=_max_workers) as executor:
                scores = list(executor.map(self.fitness, population))

            pop_scores = sorted(zip(population, scores), key=lambda x: x[1], reverse=True)
            population = [p for p, s in pop_scores]
            scores = [s for p, s in pop_scores]

            gen_best_score = scores[0]
            if gen_best_score > best_score:
                best_score = gen_best_score
                best_params = population[0]
                no_improve_count = 0
                print(f"Gen {gen+1}: ⭐ New Best! Score={best_score:.1f}")
                
                improved_elite = self.local_search(best_params)
                improved_score = self.fitness(improved_elite)
                if improved_score > best_score:
                    best_score = improved_score
                    best_params = improved_elite
                    population[0] = improved_elite
                    scores[0] = improved_score
            else:
                no_improve_count += 1
                if no_improve_count >= 3:
                    self.mutation_rate = min(0.4, self.base_mutation_rate * 1.5)
                else:
                    self.mutation_rate = self.base_mutation_rate

            self.update_hall_of_fame(population, scores)

            if no_improve_count >= self.early_stop_patience:
                print("🛑 早停：策略已收斂")
                break

            next_gen = []
            next_gen.extend(population[:self.elitism_count])
            
            if self.hall_of_fame:
                hof_inject = [h['params'] for h in self.hall_of_fame[:2]]
                next_gen.extend(hof_inject)
            
            while len(next_gen) < self.population_size:
                candidates_idx = random.sample(range(len(population)), 3)
                winner_idx = max(candidates_idx, key=lambda i: scores[i])
                parent1 = population[winner_idx]
                
                candidates_idx = random.sample(range(len(population)), 3)
                winner_idx = max(candidates_idx, key=lambda i: scores[i])
                parent2 = population[winner_idx]
                
                child = parent1.copy()
                if random.random() < self.crossover_rate:
                    for k in parent1:
                        if random.random() > 0.5: child[k] = parent2[k]
                
                for k in self.gene_space:
                    if random.random() < self.mutation_rate:
                        min_v, max_v = self.gene_space[k]
                        if isinstance(min_v, int):
                            child[k] += random.choice([-1, 1, 0])
                        else:
                            sigma = (max_v - min_v) * 0.05
                            child[k] += random.gauss(0, sigma)
                
                next_gen.append(self.validate_individual(child))
                
            population = next_gen[:self.population_size]

        return best_params, best_score

    def cleanup(self):
        """✅ 明確釋放 GA 佔用的記憶體"""
        self.fitness_cache.clear()
        del self.cached_data
        gc.collect()