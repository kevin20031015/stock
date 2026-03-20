import pandas as pd
import numpy as np

def calculate_all_indicators(df):
    data = df.copy()
    if data.index.tz is not None:
        data.index = data.index.tz_localize(None)

    data['MA5'] = data['Close'].rolling(window=5).mean()
    data['MA20'] = data['Close'].rolling(window=20).mean()
    data['MA60'] = data['Close'].rolling(window=60).mean()
    
    data['VolMA5'] = data['Volume'].rolling(window=5).mean()
    data['VolMA20'] = data['Volume'].rolling(window=20).mean()
    data['Vol_Ratio'] = data['VolMA5'] / (data['VolMA20'].replace(0, 1))
    
    period_kd = 9
    low_min = data['Low'].rolling(window=period_kd).min()
    high_max = data['High'].rolling(window=period_kd).max()
    rsv = 100 * (data['Close'] - low_min) / (high_max - low_min).replace(0, 1)
    rsv = rsv.fillna(50)
    
    k_list, d_list = [], []
    k, d = 50, 50
    for r in rsv:
        k = (2/3)*k + (1/3)*r
        d = (2/3)*d + (1/3)*k
        k_list.append(k)
        d_list.append(d)
    data['K'] = k_list
    data['D'] = d_list

    exp1 = data['Close'].ewm(span=12, adjust=False).mean()
    exp2 = data['Close'].ewm(span=26, adjust=False).mean()
    data['MACD_DIF'] = exp1 - exp2
    data['MACD_DEA'] = data['MACD_DIF'].ewm(span=9, adjust=False).mean()
    data['MACD_OSC'] = data['MACD_DIF'] - data['MACD_DEA']

    delta = data['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / (loss + 1e-10)
    data['RSI'] = 100 - (100 / (1 + rs))

    data['up'] = data['High'] - data['High'].shift(1)
    data['down'] = data['Low'].shift(1) - data['Low']
    data['+DM'] = np.where((data['up'] > data['down']) & (data['up'] > 0), data['up'], 0)
    data['-DM'] = np.where((data['down'] > data['up']) & (data['down'] > 0), data['down'], 0)
    
    data['TR'] = pd.concat([
        data['High']-data['Low'], 
        (data['High']-data['Close'].shift(1)).abs(), 
        (data['Low']-data['Close'].shift(1)).abs()
    ], axis=1).max(axis=1)
    
    data['TR14'] = data['TR'].ewm(alpha=1/14, adjust=False).mean()
    data['+DM14'] = data['+DM'].ewm(alpha=1/14, adjust=False).mean()
    data['-DM14'] = data['-DM'].ewm(alpha=1/14, adjust=False).mean()
    
    data['+DI'] = 100 * (data['+DM14'] / data['TR14'].replace(0, 1))
    data['-DI'] = 100 * (data['-DM14'] / data['TR14'].replace(0, 1))
    data['DX'] = 100 * abs(data['+DI'] - data['-DI']) / (data['+DI'] + data['-DI'] + 1e-10)
    data['ADX'] = data['DX'].ewm(alpha=1/14, adjust=False).mean()

    data['BB_Mid'] = data['MA20']
    std = data['Close'].rolling(window=20).std()
    data['BB_Up'] = data['BB_Mid'] + 2*std
    data['BB_Low'] = data['BB_Mid'] - 2*std
    data['BB_Width'] = (data['BB_Up'] - data['BB_Low']) / data['BB_Mid']

    data['Volatility'] = data['Close'].pct_change().rolling(window=20).std()
    data['ATR'] = data['TR'].rolling(window=14).mean()
    
    return data

def calculate_indicators_simple(df):
    """專為掃描器設計的輕量級計算"""
    if len(df) < 25: return None
    data = df.copy()
    data['MA20'] = data['Close'].rolling(window=20).mean()
    
    # RSI
    delta = data['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / (loss + 1e-10)
    data['RSI'] = 100 - (100 / (1 + rs))
    
    # Volume Ratio
    vol_ma20 = data['Volume'].rolling(window=20).mean()
    data['Vol_Ratio'] = data['Volume'] / (vol_ma20.replace(0, 1))
    
    # Volatility for mode classification
    data['Volatility'] = data['Close'].pct_change().rolling(window=20).std()
    
    # KD
    period_kd = 9
    low_min = data['Low'].rolling(window=period_kd).min()
    high_max = data['High'].rolling(window=period_kd).max()
    rsv = 100 * (data['Close'] - low_min) / (high_max - low_min).replace(0, 1)
    k = rsv.ewm(com=2).mean()
    data['K'] = k

    return data.iloc[-1]

def calculate_sharpe(df):
    returns = df['Close'].pct_change().dropna()
    if len(returns) == 0: return 0
    mean_ret = np.mean(returns)
    std_ret = np.std(returns)
    return mean_ret / std_ret * np.sqrt(252) if std_ret > 0 else 0

def calculate_fundamental_score(fundamentals):
    score = 0
    if fundamentals.get('revenue_yoy', 0) > 0.15: score += 2
    elif fundamentals.get('revenue_yoy', 0) > 0.05: score += 1
    if fundamentals.get('eps_growth', False): score += 1
    if fundamentals.get('roe', 0) > 0.15: score += 1
    return score

def calculate_win_rate(trade_log):
    if len(trade_log) < 2: return 0
    wins = 0
    total_trades = 0
    for log in trade_log:
        if log['type'] == 'SELL':
            total_trades += 1
            if '(' in log['desc']:
                try:
                    pct = float(log['desc'].split('(')[1].split('%')[0])
                    if pct > 0: wins += 1
                except: pass
    if total_trades == 0: return 0
    return round(wins / total_trades * 100, 1)

# ✅ 新增：中央大腦篩選邏輯 (DRY 原則)
def check_strong_trend(last_row):
    """
    共用的掃描器強勢股判斷邏輯。
    只要在這裡修改條件，Telegram 機器人與網頁版都會同步生效！
    條件加嚴：RSI > 55, 量比 > 2.0, 加上 KD 確認，降低訊噪比。
    """
    is_bullish = (
        last_row['RSI'] > 55 and                # ✅ 從 50 提高到 55，避免弱勢股混入
        last_row['Close'] > last_row['MA20'] and
        last_row['Vol_Ratio'] > 2.0 and          # ✅ 從 1.5 提高到 2.0，確保真正爆量
        last_row.get('K', 50) > 50               # ✅ 加上 KD 確認，K > 50 代表短線偏多
    )

    mode = "⚡ 波段" if last_row.get('Volatility', 0) > 0.02 else "🌊 趨勢"

    return is_bullish, mode