import yfinance as yf
import pandas as pd
import time
import random
from FinMind.data import DataLoader 
import requests
from bs4 import BeautifulSoup

# 嘗試匯入 twstock
try:
    import twstock
except ImportError:
    twstock = None
    print("⚠️ 警告：未安裝 twstock，將使用內建熱門股列表")

# 全局緩存 (搬移至此)
SCAN_CACHE = {
    "last_scan_time": 0,
    "results": []
}

MARKET_CACHE = {
    "last_update": 0,
    "data": None
}

# ✅ chip data TTL cache：FinMind API 慢且限流，同一股票 1 小時內不重複呼叫
_CHIP_CACHE = {}
_CHIP_TTL = 3600  # 秒

# ✅ 新增：已知下市或 Yahoo 抓不到的無效代號黑名單
BLACKLIST = {
    '1565.TWO', '6457.TWO', '6404.TWO', '5383.TWO', '6287.TWO', 
    '3202.TWO', '6747.TWO', '6589.TWO', '4945.TWO', '1701.TW', 
    '6514.TWO', '6288.TW', '8420.TWO', '2443.TW', '4712.TWO', 
    '2888.TW', '2809.TW', '2358.TW'
}

def get_all_tw_stocks():
    """取得全台股代碼列表"""
    if twstock:
        targets = []
        for code, info in twstock.codes.items():
            if info.type == '股票':
                target_id = ""
                if info.market == '上市':
                    target_id = f"{code}.TW"
                elif info.market == '上櫃':
                    target_id = f"{code}.TWO"
                
                # ✅ 關鍵修改：如果是有效的代號，且「不在黑名單內」，才加入掃描排程
                if target_id and target_id not in BLACKLIST:
                    targets.append(target_id)
                    
        random.shuffle(targets)
        return targets
    else:
        return [
            '2330.TW', '2454.TW', '2317.TW', '2308.TW', '2303.TW', '2379.TW', '3034.TW', '3035.TW',
            '3008.TW', '3231.TW', '2382.TW', '2357.TW', '2376.TW', '2345.TW', '2412.TW', '2301.TW',
            '2353.TW', '2356.TW', '3017.TW', '4938.TW', '2313.TW', '2409.TW', '3481.TW', '2324.TW',
            '0050.TW', '0056.TW', '00878.TW', '00929.TW', '00919.TW'
        ]

def fetch_chip_data(stock_id, days=120):
    # ✅ TTL cache：同一股票 1 小時內直接回傳快取
    cache_key = (stock_id, days)
    if cache_key in _CHIP_CACHE:
        cached_result, cached_ts = _CHIP_CACHE[cache_key]
        if time.time() - cached_ts < _CHIP_TTL:
            return cached_result

    try:
        api = DataLoader()
        start_date = (pd.Timestamp.now() - pd.Timedelta(days=days)).strftime('%Y-%m-%d')
        df = api.taiwan_stock_institutional_investors(
            stock_id=stock_id,
            start_date=start_date
        )
        if df.empty:
            _CHIP_CACHE[cache_key] = (None, time.time())
            return None
        
        df['net_buy'] = df['buy'] - df['sell']
        pivot = df.pivot_table(index='date', columns='name', values='net_buy', aggfunc='sum').fillna(0)
        
        pivot['Foreign'] = pivot.get('Foreign_Investor', 0)
        pivot['Trust'] = pivot.get('Investment_Trust', 0)
        pivot['Dealer'] = pivot.get('Dealer_Self', 0) + pivot.get('Dealer_Hedging', 0)
        pivot['Institutional_Buy'] = pivot['Foreign'] + pivot['Trust'] + pivot['Dealer']
        
        pivot.index = pd.to_datetime(pivot.index)
        result = pivot[['Foreign', 'Trust', 'Institutional_Buy']]
        _CHIP_CACHE[cache_key] = (result, time.time())  # ✅ 寫入 cache
        return result
    except Exception as e:
        _CHIP_CACHE[cache_key] = (None, time.time())  # ✅ 失敗也 cache，避免短時間重複打 API
        return None

def fetch_margin_data(stock_id, days=120):
    """
    抓取融資融券餘額與增減。
    
    注意事項：
    - 只在個股詳細頁面呼叫（period != 'scan'），掃描器路徑完全跳過
    - 使用與 fetch_chip_data 相同的 TTL cache，避免 FinMind 限流
    - 大戶持股比例（集保週報）是週頻數據，不納入此函式，避免回測資訊洩漏
    """
    cache_key = f"margin_{stock_id}_{days}"
    if cache_key in _CHIP_CACHE:
        cached_result, cached_ts = _CHIP_CACHE[cache_key]
        if time.time() - cached_ts < _CHIP_TTL:
            return cached_result

    try:
        api = DataLoader()
        start_date = (pd.Timestamp.now() - pd.Timedelta(days=days)).strftime('%Y-%m-%d')
        df = api.taiwan_stock_margin_purchase_short_sale(
            stock_id=stock_id,
            start_date=start_date
        )
        if df.empty:
            _CHIP_CACHE[cache_key] = (None, time.time())
            return None

        # ✅ FinMind 實際欄位是 MarginPurchaseTodayBalance，改名為內部統一用名
        df = df[['date', 'MarginPurchaseTodayBalance', 'ShortSaleTodayBalance']].copy()
        df = df.rename(columns={
            'MarginPurchaseTodayBalance': 'MarginPurchaseBalance',
            'ShortSaleTodayBalance':      'ShortSaleBalance',
        })
        df = df.set_index('date')
        df.index = pd.to_datetime(df.index)
        df = df.sort_index()

        # 每日融資增減（正=融資增加/散戶追買，負=融資減少/散戶退場）
        df['Margin_Diff'] = df['MarginPurchaseBalance'].diff()

        _CHIP_CACHE[cache_key] = (df, time.time())
        return df
    except Exception as e:
        print(f"Margin Fetch Error ({stock_id}): {e}")
        _CHIP_CACHE[cache_key] = (None, time.time())
        return None


def fetch_news_sentiment(stock_symbol, stock_name=None):
    try:
        pure_symbol = stock_symbol.split('.')[0]
        url = f"https://tw.stock.yahoo.com/quote/{pure_symbol}/news"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
        }
        res = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(res.text, "html.parser")

        # 建立相關性關鍵詞：股票代號 + 公司名稱（若有）
        relevance_tokens = [pure_symbol]
        if stock_name:
            # 公司名稱拆成 2 字元以上的片段（避免單字誤判）
            relevance_tokens.append(stock_name)
            # 去掉常見後綴，留核心名稱（例：台積電→台積）
            core = stock_name.replace('股份有限公司','').replace('有限公司','').replace('公司','').strip()
            if len(core) >= 2:
                relevance_tokens.append(core)

        news_items = []
        for a in soup.find_all('a'):
            href = a.get('href', '')
            title = a.text.strip()
            if '/news/' in href and len(title) > 8:
                if not any(item['title'] == title for item in news_items):
                    # ✅ 相關性過濾：標題必須包含代號或公司名，否則是版面上的其他新聞
                    is_relevant = any(token in title for token in relevance_tokens)
                    news_items.append({'title': title, 'link': href, 'relevant': is_relevant})

        if not news_items:
            return {"sentiment_score": 0, "news": [], "summary": "無近期重大新聞"}

        # 優先取相關新聞，不夠再補非相關（至少讓使用者看到有新聞）
        relevant   = [n for n in news_items if n['relevant']]
        irrelevant = [n for n in news_items if not n['relevant']]
        ordered = (relevant + irrelevant)[:8]  # 取前8篇再評分

        # 關鍵字庫保持不變
        positive_keywords = [
            '新高', '成長', '大增', '配息', '獲利', '上漲', '利多', '旺', '買超', '雙增', 
            '看好', '升評', '爆發', '優於預期', '強勁', '接單', '滿載', '漲停', '跳空', '創高', '回溫',
            '買進', '加碼', '進場', '看旺', '轉強', '反彈', '受惠', '利好', '飆漲', '噴出', '押寶'
        ]
        
        # 🔥 加強版負向關鍵字
        negative_keywords = [
            '衰退', '重挫', '大跌', '虧損', '不如預期', '違約', '利空', '砍單', '賣超', '降評', 
            '看壞', '探底', '跌停', '下修', '保守', '風暴', '崩盤', '外資提款', '走弱', '出脫', '疲軟', '拖累',
            '回檔', '恐慌', '下跌', '看淡', '轉弱', '利淡', '跳水', '套牢', '警戒', '拋售', '殺盤'
        ]
        
        analyzed_news = []
        total_score = 0

        for item in ordered:
            title = item['title']
            link = item['link']
            is_relevant = item['relevant']
            
            if link.startswith('/'):
                link = f"https://tw.stock.yahoo.com{link}"
                
            score = 0
            for kw in positive_keywords:
                if kw in title: score += 1
            for kw in negative_keywords:
                if kw in title: score -= 1
            
            score = max(-2, min(2, score)) 
            total_score += score
            
            sentiment_label = "neutral"
            if score > 0: sentiment_label = "positive"
            elif score < 0: sentiment_label = "negative"

            analyzed_news.append({
                "title": title,
                "link": link,
                "sentiment": sentiment_label,
                "score": score,
                "time": "近期",
                "relevant": is_relevant,  # ✅ 傳給前端，非相關新聞可淡化顯示
            })

        # 只用相關新聞計算總分，避免其他股票新聞干擾判斷
        relevant_scores = [n['score'] for n in analyzed_news if n['relevant']]
        total_score = sum(relevant_scores) if relevant_scores else sum(n['score'] for n in analyzed_news)

        final_summary = "消息面平淡"
        if total_score >= 2: final_summary = "🔥 利多消息頻傳"
        elif total_score <= -2: final_summary = "⚠️ 利空消息罩頂"

        return {
            "sentiment_score": total_score,
            "news": analyzed_news,
            "summary": final_summary
        }

    except Exception as e:
        print(f"News Fetch Error: {e}")
        return {"sentiment_score": 0, "news": [], "summary": "新聞抓取失敗"}

def get_market_sentiment():
    if time.time() - MARKET_CACHE['last_update'] < 1800 and MARKET_CACHE['data']:
        return MARKET_CACHE['data']

    try:
        tickers = ['^GSPC', '^VIX', '^TWII']
        data = yf.download(tickers, period='3mo', progress=False, auto_adjust=True)['Close']
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.droplevel(1)

        sentiment = {"status": "NEUTRAL", "score": 50, "desc": "多空不明", "indicators": {}}

        sp500 = data['^GSPC'].dropna()
        if len(sp500) > 20:
            current_sp = sp500.iloc[-1]
            ma20_sp = sp500.rolling(20).mean().iloc[-1]
            sp_bull = current_sp > ma20_sp
        else: current_sp, sp_bull = 0, False

        vix = data['^VIX'].dropna()
        if len(vix) > 0: current_vix = vix.iloc[-1]
        else: current_vix = 20

        twii = data['^TWII'].dropna()
        if len(twii) > 20:
            current_tw = twii.iloc[-1]
            ma20_tw = twii.rolling(20).mean().iloc[-1]
            tw_bull = current_tw > ma20_tw
        else: current_tw, tw_bull = 0, False

        score = 50
        if sp_bull: score += 20
        else: score -= 20
        if tw_bull: score += 20
        else: score -= 20
        
        if current_vix < 15: score += 10
        elif current_vix < 20: score += 5
        elif current_vix > 30: score -= 30
        elif current_vix > 25: score -= 15

        if score >= 70:
            sentiment = {"status": "BULL", "score": score, "color": "red", "desc": "全球多頭助攻 (Safe)", "action_suggestion": "積極操作"}
        elif score <= 30:
            sentiment = {"status": "BEAR", "score": score, "color": "green", "desc": "全球空頭警戒 (Danger)", "action_suggestion": "現金為王/空手"}
        else:
            sentiment = {"status": "NEUTRAL", "score": score, "color": "gray", "desc": "震盪盤整 (Neutral)", "action_suggestion": "選股不選市"}

        sentiment['indicators'] = {
            "sp500_price": round(float(current_sp), 0),
            "sp500_bull": bool(sp_bull),
            "vix": round(float(current_vix), 2),
            "twii_bull": bool(tw_bull)
        }

        MARKET_CACHE['data'] = sentiment
        MARKET_CACHE['last_update'] = time.time()
        return sentiment

    except Exception as e:
        print(f"Market Sentiment Error: {e}")
        return {"status": "NEUTRAL", "score": 50, "color": "gray", "desc": "無法取得數據", "action_suggestion": "保守操作", "indicators": {}}

def get_stock_info(symbol):
    symbol = symbol.strip().upper()
    if symbol.isdigit() and twstock and symbol in twstock.codes:
        info = twstock.codes[symbol]
        real_id = f"{symbol}.TWO" if info.market == '上櫃' else f"{symbol}.TW"
        return {"id": real_id, "name": info.name, "success": True}
            
    candidates = [f"{symbol}.TW", f"{symbol}.TWO", symbol] 
    for cid in candidates:
        try:
            ticker = yf.Ticker(cid)
            hist = ticker.history(period='1d')
            if not hist.empty:
                name = ticker.info.get('shortName', cid)
                return {"id": cid, "name": name, "success": True}
        except:
            continue
    return {"success": False}

def fetch_fundamentals(ticker_obj):
    default_res = {"revenue_yoy": 0, "eps_growth": False, "roe": 0, "valid": False}
    try:
        fin = ticker_obj.quarterly_financials
        if fin is None or fin.empty: return default_res

        eps_row = None
        if 'Basic EPS' in fin.index: eps_row = fin.loc['Basic EPS']
        elif 'Diluted EPS' in fin.index: eps_row = fin.loc['Diluted EPS']
        
        eps_growth = False
        if eps_row is not None and len(eps_row) >= 2:
            try:
                eps_growth = bool(float(eps_row.iloc[0]) > float(eps_row.iloc[1]))
            except: pass

        rev_yoy = 0
        if 'Total Revenue' in fin.index:
            rev_row = fin.loc['Total Revenue']
            if len(rev_row) >= 5:
                try:
                    now = float(rev_row.iloc[0])
                    last_year = float(rev_row.iloc[4])
                    if last_year > 0:
                        rev_yoy = float((now - last_year) / last_year)
                except: pass

        roe = ticker_obj.info.get('returnOnEquity', 0)

        return {"revenue_yoy": rev_yoy, "eps_growth": eps_growth, "roe": roe, "valid": True}
    except:
        return default_res

# 新增一個輔助函式，用來修正代號
def normalize_symbol(symbol):
    symbol = symbol.strip().upper()
    
    # 1. 如果已經有 .TW 或 .TWO，直接回傳
    if symbol.endswith('.TW') or symbol.endswith('.TWO'):
        return symbol
    
    # 2. 如果是純數字 (例如 "2330")，嘗試用 twstock 判斷
    if symbol.isdigit() and twstock:
        if symbol in twstock.codes:
            info = twstock.codes[symbol]
            if info.market == '上市':
                return f"{symbol}.TW"
            elif info.market == '上櫃':
                return f"{symbol}.TWO"
            elif info.market == '興櫃':
                return f"{symbol}.TWO" # 興櫃在 Yahoo Finance 通常也是用 .TWO，但資料可能不全
        # 如果 twstock 沒抓到，默認嘗試 .TW
        return f"{symbol}.TW"
        
    return symbol

# 修改原本的 fetch_history
def fetch_history(symbol, period='1y'):
    # === [新增] 自動修正代號 ===
    real_symbol = normalize_symbol(symbol)
    print(f"🔍 嘗試抓取: {symbol} -> 修正為: {real_symbol}")
    # ==========================

    try:
        stock = yf.Ticker(real_symbol) # 使用修正後的代號
        
        fundamentals = {"valid": False} 
        if period != 'scan': 
            fundamentals = fetch_fundamentals(stock)

        if period in ['1y', '6mo', '3mo', '1mo']:
            fetch_period = '2y'
        elif period == 'scan':
            fetch_period = '3mo'
        else:
            fetch_period = period 

        df = stock.history(period=fetch_period)
        if df.empty and fetch_period == '2y':
            df = stock.history(period='1y')

        if df.empty: 
            print(f"❌ {real_symbol} 抓無資料 (Yahoo Finance 可能未收錄)")
            return pd.DataFrame(), fundamentals
        
        df = df[['Open', 'High', 'Low', 'Close', 'Volume']]
        df.index = df.index.tz_localize(None)
        
        # 修正這裡：籌碼面也要用純數字代號
        stock_code = real_symbol.split('.')[0] 
        
        if period != 'scan':
            chip_df   = fetch_chip_data(stock_code)
            margin_df = fetch_margin_data(stock_code)   # ✅ 只在非掃描路徑呼叫

            if chip_df is not None:
                df = df.join(chip_df, how='left')
                df[['Foreign', 'Trust', 'Institutional_Buy']] = df[['Foreign', 'Trust', 'Institutional_Buy']].fillna(0)
            else:
                df['Institutional_Buy'] = 0.0
                df['Foreign'] = 0.0
                df['Trust'] = 0.0

            # ✅ 融資融券合併，並填補缺漏日（假日/無資料日 forward-fill）
            if margin_df is not None:
                df = df.join(margin_df[['MarginPurchaseBalance', 'Margin_Diff']], how='left')
                # 餘額用 ffill 補（假日延用前一日餘額），增減欄位缺漏填 0
                df['MarginPurchaseBalance'] = df['MarginPurchaseBalance'].ffill().fillna(0)
                df['Margin_Diff']           = df['Margin_Diff'].fillna(0)
            else:
                df['MarginPurchaseBalance'] = 0.0
                df['Margin_Diff']           = 0.0
        else:
            df['Institutional_Buy']      = 0.0
            df['Foreign']                = 0.0
            df['Trust']                  = 0.0
            df['MarginPurchaseBalance']  = 0.0
            df['Margin_Diff']            = 0.0

        df = df.ffill().bfill()
        return df, fundamentals
    except Exception as e:
        print(f"Fetch Error: {e}")
        return pd.DataFrame(), {"valid": False}