import json
import os

from dotenv import load_dotenv
import requests

load_dotenv()

TELEGRAM_BOT_TOKEN = ""
TELEGRAM_CHAT_ID = ""

if not TELEGRAM_BOT_TOKEN:
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def send_telegram_message(msg):
    """發送 Telegram 通知（超過 4096 字自動分段）"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("❌ 找不到 Telegram API 設定，請檢查參數")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    MAX_LEN = 4000
    chunks = [msg[i:i + MAX_LEN] for i in range(0, len(msg), MAX_LEN)]
    for chunk in chunks:
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": chunk}
        try:
            res = requests.post(url, data=payload, timeout=10)
            if res.status_code != 200:
                print(f"❌ Telegram 發送失敗: {res.text}")
        except Exception as e:
            print(f"⚠️ Telegram 網路錯誤: {e}")


try:
    import twstock
except ImportError:
    twstock = None

from modules.data_fetcher import get_all_tw_stocks, fetch_history, get_market_sentiment
from modules.scanner import run_full_market_scan
from modules.strategy import run_strategy_analysis, DEFAULT_PARAMS

POPULAR_STOCKS = [
    "2330.TW",   # 台積電
    "2317.TW",   # 鴻海
    "2408.TW",   # 南亞科
    "2344.TW",   # 華邦電
    "2337.TW",   # 旺宏
    "3260.TWO",  # 威剛
    "8299.TWO",  # 群聯
    "0050.TW",   # 台灣50
]


def load_ai_params(symbol):
    """讀取 AI 優化過的專屬參數"""
    file_path = "optimized_params.json"
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if symbol in data:
                    return data[symbol]
        except Exception:
            pass
    return DEFAULT_PARAMS


def get_stock_name(symbol):
    """根據代號取得中文名稱"""
    code = symbol.split('.')[0]
    if twstock and code in twstock.codes:
        return twstock.codes[code].name
    return ""


def fmt_chip(v):
    """把大數字格式化成 +1.2K / -300 這種易讀格式"""
    if v == 0:
        return "0"
    sign = "+" if v > 0 else "-"
    abs_v = abs(v)
    if abs_v >= 1_000_000:
        return f"{sign}{abs_v/1_000_000:.1f}M"
    if abs_v >= 1_000:
        return f"{sign}{abs_v/1_000:.0f}K"
    return f"{sign}{abs_v}"


def build_chip_line(checklist):
    """
    從 checklist 組出籌碼摘要文字，例如：
    🏦 外資+1.2K｜投信+300｜融資水位42%↓3天
    """
    cd = checklist.get("chip_detail", {})
    if not cd:
        return ""

    parts = []

    # 外資近5日
    f5 = cd.get("foreign_5d", 0)
    fstreak = cd.get("foreign_streak", 0)
    f_str = fmt_chip(f5)
    if fstreak >= 3:
        f_str += f" 連買{fstreak}天🔥"
    parts.append(f"外資{f_str}")

    # 投信近5日
    t5 = cd.get("trust_5d", 0)
    tstreak = cd.get("trust_streak", 0)
    t_str = fmt_chip(t5)
    if tstreak >= 3:
        t_str += f" 連買{tstreak}天🔥"
    parts.append(f"投信{t_str}")

    # 融資水位（有資料才顯示）
    margin_bal = cd.get("margin_bal", 0)
    if margin_bal > 0:
        level = cd.get("margin_level_pct", 0)
        shrink_days = cd.get("margin_shrink_days", 0)
        margin_str = f"融資水位{level}%"
        if shrink_days >= 3:
            margin_str += f" ↓{shrink_days}天✨"
        parts.append(margin_str)

    line = "🏦 " + "｜".join(parts)

    # S 級訊號獨立一行
    if cd.get("margin_shrink_days", 0) >= 3 and cd.get("inst_5d", 0) > 0:
        line += "\n   💎 S級：法人吃貨＋散戶踩踏"

    return line


def run_auto_scan():
    print("🚀 啟動全自動雷達：全台強勢股掃描 + AI記憶 + VIP觀測...")

    # ── 大盤哨兵 ──────────────────────────────────────────────────────
    market        = get_market_sentiment()
    market_status = market.get("status", "NEUTRAL")
    market_desc   = market.get("desc", "")
    indicators    = market.get("indicators", {})
    sp_arrow      = "↑" if indicators.get("sp500_bull") else "↓"
    tw_mood       = "多頭" if indicators.get("twii_bull") else "空頭"

    if market_status == "BEAR":
        market_header = (
            f"⛔ 【大盤空頭警戒】⛔\n"
            f"{market_desc}\n"
            f"VIX {indicators.get('vix','?')} | S&P {sp_arrow} | 台股{tw_mood}\n"
            f"⚠️ 空頭期間訊號可靠度下降，建議輕倉或觀望\n"
        )
    elif market_status == "BULL":
        market_header = (
            f"✅ 【大盤多頭助攻】\n"
            f"{market_desc}\n"
            f"VIX {indicators.get('vix','?')} | S&P {sp_arrow} | 台股{tw_mood}\n"
        )
    else:
        market_header = (
            f"⚠️ 【大盤震盪觀望】\n"
            f"{market_desc}\n"
            f"VIX {indicators.get('vix','?')} | 台股{tw_mood}\n"
        )

    # ── 全市場掃描 ────────────────────────────────────────────────────
    targets = get_all_tw_stocks()
    print(f"📊 總共抓取到 {len(targets)} 檔標的，開始運算...")

    strong_stocks = run_full_market_scan(targets, twstock)
    top_stocks    = strong_stocks[:10]
    otc_count     = sum(1 for s in strong_stocks if s['is_otc'])
    listed_count  = len(strong_stocks) - otc_count

    msg = market_header + "\n"

    if top_stocks:
        msg += "🔥【今日前10大爆量強勢股】🔥\n"
        msg += f"通過過濾：上市{listed_count}檔 / 上櫃{otc_count}檔\n"
        msg += "=" * 20 + "\n"

        for s in top_stocks:
            symbol     = s['id']
            market_tag = "【櫃】" if s['is_otc'] else "【市】"
            stock_name = get_stock_name(symbol)

            df, fundamentals = fetch_history(symbol, period='6mo')
            if not df.empty:
                best_params = load_ai_params(symbol)
                _, _, _, _, _, checklist, forecast, _ = run_strategy_analysis(
                    df, fundamentals, 500000, best_params
                )
                ai_mark = "🤖" if best_params != DEFAULT_PARAMS else ""

                msg += f"🎯 {market_tag} {symbol.split('.')[0]} {stock_name} {ai_mark}\n"
                msg += f"現價: ${s['price']:.1f} | 量比:{s['vol_ratio']:.1f}x | RSI:{s['rsi']:.0f}\n"
                msg += f"💡 戰略: {forecast['action_title']} ({forecast['trend']})\n"
                if forecast['stop_loss'] > 0:
                    msg += f"🛡️ 防守: ${forecast['stop_loss']}\n"

                chip_line = build_chip_line(checklist)
                if chip_line:
                    msg += chip_line + "\n"

            msg += "-" * 15 + "\n"

    # ── VIP 觀測清單 ──────────────────────────────────────────────────
    print("🌟 正在分析 VIP 熱門觀測股...")
    msg += "\n🌟【VIP 記憶體與熱門股觀測】🌟\n" + "=" * 20 + "\n"

    for symbol in POPULAR_STOCKS:
        stock_name = get_stock_name(symbol)
        df, fundamentals = fetch_history(symbol, period='6mo')
        if not df.empty:
            best_params = load_ai_params(symbol)
            _, _, suggestion, _, _, checklist, forecast, _ = run_strategy_analysis(
                df, fundamentals, 500000, best_params
            )
            ai_mark = "🤖" if best_params != DEFAULT_PARAMS else ""
            price   = df.iloc[-1]['Close']

            # 大盤空頭時，買進訊號加警示
            signal_note = ""
            if market_status == "BEAR" and "BUY" in suggestion:
                signal_note = " ⚠️空頭慎入"

            msg += f"📌 {symbol.split('.')[0]} {stock_name} {ai_mark} (${price:.1f})\n"
            msg += f"💡 {suggestion}{signal_note}\n"
            msg += f"📉 支撐: ${forecast['support']} | 📈 壓力: ${forecast['pressure']}\n"

            chip_line = build_chip_line(checklist)
            if chip_line:
                msg += chip_line + "\n"

            msg += "-" * 15 + "\n"

    if msg:
        send_telegram_message(msg)
        print("✅ 掃描與分析完成，已發送 Telegram 通知！")
    else:
        print("今日無資料可發送。")


if __name__ == "__main__":
    run_auto_scan()