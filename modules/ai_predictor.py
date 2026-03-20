"""
modules/ai_predictor.py  —  純推論模組

職責：載入已訓練好的模型權重 (.pth)，對最新資料做 MC Dropout 推論。
訓練邏輯已移至 train_model.py，API 呼叫時不再跑 150 epochs。

使用流程：
  1. 定期（如每週日收盤後）執行 train_model.py 產生 models/<symbol>.pth
  2. API 呼叫 /api/predict_ai/<symbol> 時，這裡只負責載入 + 推論（< 1 秒）
"""

import os
import numpy as np
import math
import gc
import threading
MODEL_DIR = "models"

# 記錄正在背景訓練中的 symbol，避免重複觸發
_training_in_progress = set()
_training_lock = threading.Lock()




def _schedule_background_training(symbol):
    """
    若該 symbol 尚未在訓練中，啟動一個背景執行緒進行訓練。
    重複呼叫同一 symbol 時直接 return，不會重複訓練。
    """
    with _training_lock:
        if symbol in _training_in_progress:
            print(f"[AI] {symbol} 已在訓練佇列中，略過重複觸發")
            return
        _training_in_progress.add(symbol)

    def _train_worker():
        try:
            print(f"[AI 背景訓練] 開始訓練 {symbol}...")
            # 動態 import 避免循環依賴
            import subprocess, sys
            subprocess.run(
                [sys.executable, "train_model.py", "--symbol", symbol],
                check=False
            )
            print(f"[AI 背景訓練] {symbol} 訓練完成")
        except Exception as e:
            print(f"[AI 背景訓練] {symbol} 失敗：{e}")
        finally:
            with _training_lock:
                _training_in_progress.discard(symbol)

    t = threading.Thread(target=_train_worker, daemon=True, name=f"train-{symbol}")
    t.start()

# === GPU 偵測 ===
try:
    import torch
    import torch.nn as nn
    TORCH_AVAILABLE = True
    if torch.cuda.is_available():
        DEVICE   = torch.device("cuda")
        GPU_NAME = torch.cuda.get_device_name(0)
        print(f"🚀 [AI 推論引擎] GPU: {GPU_NAME}")
    else:
        DEVICE   = torch.device("cpu")
        GPU_NAME = "CPU"
except ImportError:
    TORCH_AVAILABLE = False
    DEVICE   = "cpu"
    GPU_NAME = "None"

FEATURE_COLS = [
    'Open', 'High', 'Low', 'Close', 'Volume',
    'MA5', 'MA20', 'RSI', 'Log_Ret',
    'MACD', 'BB_Pct', 'High_Low_Pct', 'Gap'
]
LOOKBACK     = 60
PREDICT_DAYS = 3
MC_RUNS      = 30


if TORCH_AVAILABLE:
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


def _build_features(df):
    """共用特徵工程，與 train_model.py 保持一致"""
    data = df.copy()
    data['MA5']  = data['Close'].rolling(5).mean()
    data['MA20'] = data['Close'].rolling(20).mean()
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


def _model_path(symbol):
    """回傳模型權重和 scaler 的路徑"""
    os.makedirs(MODEL_DIR, exist_ok=True)
    safe = symbol.replace('/', '_')
    return (
        os.path.join(MODEL_DIR, f"{safe}.pth"),
        os.path.join(MODEL_DIR, f"{safe}.scaler"),
    )


def run_ai_prediction(df, symbol=None):
    """
    純推論：載入已訓練好的模型權重，對最新資料做 MC Dropout 推論。

    若找不到對應的 .pth 檔，回傳 valid=False 並提示先執行 train_model.py。
    symbol 參數用於找到對應的模型檔案。
    """
    if not TORCH_AVAILABLE:
        return {"valid": False, "msg": "未安裝 PyTorch"}
    if len(df) < 200:
        return {"valid": False, "msg": "資料不足（需至少 200 筆）"}

    # 找模型檔和 scaler 檔
    if not symbol:
        return {"valid": False, "msg": "未提供 symbol，無法找到對應模型"}

    pth, scaler_path = _model_path(symbol)

    if not os.path.exists(pth):
        # ✅ 按需訓練：模型不存在時，在背景執行緒啟動訓練，本次請求先回傳提示
        _schedule_background_training(symbol)
        return {
            "valid":    False,
            "training": True,
            "msg":      f"模型訓練中，通常需要 3~10 分鐘，請稍後再試。（{pth}）"
        }
    if not os.path.exists(scaler_path):
        return {
            "valid": False,
            "msg": f"找不到 Scaler（{scaler_path}）。模型和 Scaler 必須成對，請重新執行訓練：python train_model.py --symbol {symbol}"
        }

    try:
        import joblib
        data          = _build_features(df)
        aligned_close = data['Close'].values
        current_price = float(aligned_close[-1])

        # ✅ 載入訓練時存下的 scaler，絕對不重新 fit
        # 重新 fit 會讓數值映射範圍跑掉，模型輸入分布偏移，預測結果錯誤
        scaler      = joblib.load(scaler_path)
        scaled_data = scaler.transform(data[FEATURE_COLS].values)

        # 載入模型
        model = TransformerPredictor(
            input_dim=len(FEATURE_COLS),
            d_model=64, nhead=4, num_layers=3,
            output_dim=PREDICT_DAYS, dropout=0.3
        ).to(DEVICE)
        checkpoint = torch.load(pth, map_location=DEVICE)
        model.load_state_dict(checkpoint['model_state'])
        val_loss_saved = checkpoint.get('val_loss', 0.0)

        # MC Dropout 推論（in-place 累積，不存整個 list）
        last_seq        = torch.FloatTensor(scaled_data[-LOOKBACK:]).unsqueeze(0).to(DEVICE)
        mc_sum          = np.zeros(PREDICT_DAYS)
        mc_sq_sum       = np.zeros(PREDICT_DAYS)
        bull_votes      = 0

        model.train()  # 保持 dropout 啟用
        with torch.no_grad():
            for _ in range(MC_RUNS):
                pred = model(last_seq).cpu().numpy()[0]
                mc_sum    += pred
                mc_sq_sum += pred ** 2
                if np.mean(pred) > 0:
                    bull_votes += 1
        model.eval()

        del last_seq, model
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        gc.collect()

        avg_returns       = mc_sum / MC_RUNS
        std_returns       = np.sqrt(np.maximum(mc_sq_sum / MC_RUNS - avg_returns ** 2, 0))
        consistency_ratio = max(bull_votes, MC_RUNS - bull_votes) / MC_RUNS
        avg_change_pct    = float(np.mean(avg_returns))
        uncertainty       = float(np.mean(std_returns))

        predictions = [round(current_price * (1 + r / 100), 2) for r in avg_returns]

        base_score  = max(0, 100 - val_loss_saved * 25)
        bonus       = 20 if consistency_ratio > 0.9 else (10 if consistency_ratio > 0.7 else 0)
        confidence  = base_score - uncertainty * 15 + bonus
        if abs(avg_change_pct) > 20:
            confidence = 0
        else:
            confidence = round(min(98, max(10, confidence)), 1)

        return {
            "valid":      True,
            "gpu":        GPU_NAME,
            "current":    round(current_price, 2),
            "predicted":  predictions,
            "change_pct": round(avg_change_pct, 2),
            "confidence": confidence,
            "trend":      "BULL" if avg_change_pct > 0 else "BEAR",
            "model_type": "Transformer (Pretrained)",
            "notes": {
                "val_loss":    round(val_loss_saved, 4),
                "consistency": f"{int(consistency_ratio * 100)}%",
                "model_file":  pth,
            }
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"valid": False, "msg": f"AI Error: {str(e)}"}