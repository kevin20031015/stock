"""
train_model.py  —  離線訓練腳本

使用方式：
  # 訓練 VIP 觀測清單（8 檔，最快）
  python train_model.py --vip

  # 訓練單一或少數幾檔（臨時補訓用）
  python train_model.py --symbol 2330.TW 2317.TW

  # 訓練全台股（1800+ 檔，耗時，建議週末跑）
  python train_model.py --all

  # 只訓練「還沒有模型」的股票（--all 中斷後補跑很好用）
  python train_model.py --all --new-only

  # 限制並行數（預設 4，CPU 核心少的機器可降低）
  python train_model.py --all --workers 2

Cron 排程範例：
  # 每週日 18:00 重訓 VIP
  0 18 * * 0 cd /your/project && python train_model.py --vip >> logs/train.log 2>&1

  # 每月第一個週日 02:00 重訓全台股（注意 % 要跳脫）
  # 0 2 * * 0 [ $(date +%d) -le 7 ] && cd /your/project && python train_model.py --all --new-only >> logs/train_all.log 2>&1
"""

import argparse
import os
import copy
import math
import random
import numpy as np
import gc
import time
import concurrent.futures
import threading

MODEL_DIR = "models"

# VIP 預設清單，與 auto_scanner.py 的 POPULAR_STOCKS 同步
VIP_SYMBOLS = [
    "2330.TW", "2317.TW", "2408.TW", "2344.TW",
    "2337.TW", "3260.TWO", "8299.TWO", "0050.TW",
]

FEATURE_COLS = [
    'Open', 'High', 'Low', 'Close', 'Volume',
    'MA5', 'MA20', 'RSI', 'Log_Ret',
    'MACD', 'BB_Pct', 'High_Low_Pct', 'Gap'
]
LOOKBACK     = 60
PREDICT_DAYS = 3
BATCH_SIZE   = 32
EPOCHS       = 150

# print 鎖，避免多執行緒輸出亂掉
_print_lock = threading.Lock()

def safe_print(*args, **kwargs):
    with _print_lock:
        print(*args, **kwargs)


# === GPU 偵測 ===
try:
    import torch
    import torch.nn as nn
    from torch.utils.data import DataLoader
    from sklearn.preprocessing import MinMaxScaler
    import joblib
    TORCH_AVAILABLE = True
    DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"🖥️  使用裝置: {DEVICE}")
except ImportError as e:
    TORCH_AVAILABLE = False
    print(f"❌ 缺少套件：{e}，無法訓練")
    exit(1)


def set_seed(seed=42):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False


class PositionalEncoding(nn.Module):
    def __init__(self, d_model, max_len=5000, dropout=0.2):
        super().__init__()
        self.dropout = nn.Dropout(p=dropout)
        pe = torch.zeros(max_len, d_model)
        position = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
        div_term = torch.exp(
            torch.arange(0, d_model, 2).float() * (-math.log(10000.0) / d_model)
        )
        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term)
        self.register_buffer('pe', pe.unsqueeze(0))

    def forward(self, x):
        x = x + self.pe[:, :x.size(1), :]
        return self.dropout(x)


class TransformerPredictor(nn.Module):
    def __init__(self, input_dim, d_model=64, nhead=4, num_layers=3,
                 output_dim=3, dropout=0.3):
        super().__init__()
        self.input_linear = nn.Linear(input_dim, d_model)
        self.pos_encoder  = PositionalEncoding(d_model, dropout=dropout)
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model, nhead=nhead,
            dim_feedforward=128, dropout=dropout, batch_first=True
        )
        self.transformer_encoder = nn.TransformerEncoder(encoder_layer, num_layers=num_layers)
        self.decoder = nn.Sequential(
            nn.Linear(d_model, 32),
            nn.LeakyReLU(0.1),
            nn.Linear(32, output_dim)
        )
        self.d_model = d_model

    def forward(self, src):
        src = self.input_linear(src) * math.sqrt(self.d_model)
        src = self.pos_encoder(src)
        out = self.transformer_encoder(src)
        return self.decoder(out[:, -1, :])


def build_features(df):
    """特徵工程，與 ai_predictor.py 的 _build_features 完全一致"""
    data = df.copy()
    data['MA5']     = data['Close'].rolling(5).mean()
    data['MA20']    = data['Close'].rolling(20).mean()
    data['Log_Ret'] = np.log(data['Close'] / data['Close'].shift(1))

    delta = data['Close'].diff()
    gain  = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss  = (-delta.where(delta < 0, 0)).rolling(14).mean()
    data['RSI'] = 100 - (100 / (1 + gain / (loss + 1e-10)))

    exp1 = data['Close'].ewm(span=12, adjust=False).mean()
    exp2 = data['Close'].ewm(span=26, adjust=False).mean()
    data['MACD'] = exp1 - exp2

    bb_std = data['Close'].rolling(20).std()
    data['BB_Pct']       = (data['Close'] - data['MA20']) / (2 * bb_std + 1e-10)
    data['High_Low_Pct'] = (data['High'] - data['Low']) / (data['Close'] + 1e-10)
    data['Gap']          = (data['Open'] - data['Close'].shift(1)) / (data['Close'].shift(1) + 1e-10)

    return data.dropna()


def model_exists(symbol):
    """檢查該股票是否已有訓練好的模型（.pth 和 .scaler 都要存在）"""
    safe        = symbol.replace('/', '_')
    pth         = os.path.join(MODEL_DIR, f"{safe}.pth")
    scaler_path = os.path.join(MODEL_DIR, f"{safe}.scaler")
    return os.path.exists(pth) and os.path.exists(scaler_path)


def train_one_symbol(symbol, worker_id=0):
    """
    訓練單一股票並儲存模型權重與 scaler。

    Args:
        symbol:    股票代號，例如 '2330.TW'
        worker_id: 執行緒編號，僅用於 log 顯示

    Returns:
        'ok' | 'skip' | 'fail'
    """
    tag = f"[Worker {worker_id}]"

    try:
        from modules.data_fetcher import fetch_history
        df, _ = fetch_history(symbol, period='5y')

        if df.empty or len(df) < 200:
            safe_print(f"{tag} ⏭️  {symbol}：資料不足（{len(df)} 筆），跳過")
            return 'skip'

        set_seed(42)
        data          = build_features(df)
        aligned_close = data['Close'].values
        TOTAL_LEN     = len(data)
        split_idx     = int(TOTAL_LEN * 0.85)

        # ✅ 用前 85% 資料 fit scaler，並同步存檔
        scaler = MinMaxScaler(feature_range=(0, 1))
        scaler.fit(data[FEATURE_COLS].values[:split_idx])
        scaled = scaler.transform(data[FEATURE_COLS].values)

        # 建 dataset
        X_all, Y_all = [], []
        for i in range(LOOKBACK, TOTAL_LEN - PREDICT_DAYS + 1):
            X_all.append(scaled[i - LOOKBACK:i])
            curr  = aligned_close[i - 1]
            fut   = aligned_close[i:i + PREDICT_DAYS]
            Y_all.append((fut - curr) / curr * 100)

        X = torch.FloatTensor(np.array(X_all))
        Y = torch.FloatTensor(np.array(Y_all))

        ds_split = max(split_idx - LOOKBACK, int(len(X) * 0.8))
        train_dl = DataLoader(
            torch.utils.data.TensorDataset(X[:ds_split], Y[:ds_split]),
            batch_size=BATCH_SIZE, shuffle=True, pin_memory=False
        )
        val_dl = DataLoader(
            torch.utils.data.TensorDataset(X[ds_split:], Y[ds_split:]),
            batch_size=BATCH_SIZE, shuffle=False, pin_memory=False
        )

        model     = TransformerPredictor(input_dim=len(FEATURE_COLS)).to(DEVICE)
        criterion = nn.HuberLoss()
        optimizer = torch.optim.AdamW(model.parameters(), lr=0.001, weight_decay=1e-4)
        scheduler = torch.optim.lr_scheduler.OneCycleLR(
            optimizer, max_lr=0.005,
            steps_per_epoch=len(train_dl), epochs=EPOCHS
        )

        best_val_loss = float('inf')
        best_state    = None
        patience      = 10
        stale         = 0

        for epoch in range(EPOCHS):
            model.train()
            for bx, by in train_dl:
                bx, by = bx.to(DEVICE), by.to(DEVICE)
                optimizer.zero_grad()
                loss = criterion(model(bx), by)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), 0.5)
                optimizer.step()
                scheduler.step()

            model.eval()
            val_loss = 0.0
            with torch.no_grad():
                for bx, by in val_dl:
                    val_loss += criterion(model(bx.to(DEVICE)), by.to(DEVICE)).item()
            avg_val = val_loss / len(val_dl)

            if avg_val < best_val_loss:
                best_val_loss = avg_val
                best_state    = copy.deepcopy(model.state_dict())
                stale         = 0
            else:
                stale += 1
                if stale >= patience:
                    break

        if best_state:
            model.load_state_dict(best_state)

        # ✅ 模型和 scaler 成對儲存，缺一不可
        os.makedirs(MODEL_DIR, exist_ok=True)
        safe        = symbol.replace('/', '_')
        pth         = os.path.join(MODEL_DIR, f"{safe}.pth")
        scaler_path = os.path.join(MODEL_DIR, f"{safe}.scaler")

        torch.save({
            'model_state':  best_state,
            'val_loss':     best_val_loss,
            'symbol':       symbol,
            'feature_cols': FEATURE_COLS,
            'split_idx':    split_idx,
        }, pth)
        joblib.dump(scaler, scaler_path)

        safe_print(f"{tag} ✅ {symbol}  val_loss={best_val_loss:.4f}")
        return 'ok'

    except Exception as e:
        safe_print(f"{tag} ❌ {symbol}：訓練失敗 — {e}")
        return 'fail'

    finally:
        # 每次訓練完都清記憶體，避免多執行緒下累積
        try:
            del X, Y, model, best_state, train_dl, val_dl
        except Exception:
            pass
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        gc.collect()


def run_training(symbols, new_only=False, max_workers=4):
    """
    批次訓練多檔股票。

    Args:
        symbols:     股票代號列表
        new_only:    True = 只訓練還沒有模型的股票（中斷補跑很好用）
        max_workers: 最大並行執行緒數
    """
    if new_only:
        before = len(symbols)
        symbols = [s for s in symbols if not model_exists(s)]
        safe_print(f"📋 --new-only 模式：{before} 檔 → 跳過已有模型，剩 {len(symbols)} 檔待訓練")
    else:
        safe_print(f"📋 共 {len(symbols)} 檔待訓練")

    if not symbols:
        safe_print("✅ 所有股票都已有模型，無需訓練。")
        return

    # GPU 環境下不要多執行緒（PyTorch CUDA context 不能跨 thread 共用）
    # CPU 環境下可以開多個 worker 並行
    if torch.cuda.is_available():
        safe_print("🚀 GPU 模式：單執行緒順序訓練（CUDA 不支援多執行緒共用）")
        actual_workers = 1
    else:
        actual_workers = min(max_workers, os.cpu_count() or 1, len(symbols))
        safe_print(f"🖥️  CPU 模式：{actual_workers} 個並行 worker")

    counts = {'ok': 0, 'skip': 0, 'fail': 0}
    t_start = time.time()

    if actual_workers == 1:
        for i, sym in enumerate(symbols, 1):
            safe_print(f"\n[{i}/{len(symbols)}] 訓練中：{sym}")
            result = train_one_symbol(sym, worker_id=0)
            counts[result] += 1
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=actual_workers) as executor:
            futures = {
                executor.submit(train_one_symbol, sym, i % actual_workers): sym
                for i, sym in enumerate(symbols)
            }
            done = 0
            for future in concurrent.futures.as_completed(futures):
                sym    = futures[future]
                result = future.result()
                counts[result] += 1
                done += 1
                safe_print(f"進度：{done}/{len(symbols)} 完成")

    elapsed = time.time() - t_start
    safe_print(f"\n{'='*40}")
    safe_print(f"🏁 訓練完成！耗時 {elapsed/60:.1f} 分鐘")
    safe_print(f"   成功 {counts['ok']} 檔 | 跳過 {counts['skip']} 檔 | 失敗 {counts['fail']} 檔")
    safe_print(f"📁 模型存放於 ./{MODEL_DIR}/")


def main():
    parser = argparse.ArgumentParser(
        description="台股 Transformer 模型離線訓練",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
範例：
  python train_model.py --vip                     # 訓練 VIP 8 檔
  python train_model.py --symbol 2330.TW 2317.TW  # 指定幾檔
  python train_model.py --all                     # 全台股 1800+ 檔
  python train_model.py --all --new-only          # 只補訓還沒有模型的
  python train_model.py --all --workers 2         # 限制並行數
        """
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--vip',    action='store_true', help='訓練 VIP 預設清單（8 檔）')
    group.add_argument('--all',    action='store_true', help='訓練全台股（1800+ 檔，耗時）')
    group.add_argument('--symbol', nargs='+', metavar='SYMBOL', help='指定股票代號')

    parser.add_argument('--new-only', action='store_true',
                        help='只訓練尚無模型的股票（搭配 --all 使用）')
    parser.add_argument('--workers', type=int, default=4,
                        help='CPU 並行 worker 數（預設 4，GPU 模式下此設定無效）')

    args = parser.parse_args()

    if args.vip:
        symbols = VIP_SYMBOLS
    elif args.all:
        from modules.data_fetcher import get_all_tw_stocks
        symbols = get_all_tw_stocks()
        safe_print(f"📊 從 twstock 取得 {len(symbols)} 檔台股代號")
    else:
        symbols = args.symbol

    run_training(symbols, new_only=args.new_only, max_workers=args.workers)


if __name__ == "__main__":
    main()