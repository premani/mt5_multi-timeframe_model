# VALIDATOR_SPEC.md

**バージョン**: 1.3 (Phase 0実装)
**更新日**: 2025-10-25
**責任者**: core-team
**処理段階**: 第5段階: 検証・評価

---

## 📋 変更履歴

| バージョン | 日付 | 変更内容 |
|-----------|------|---------|
| 1.0 | 2025-10-21 | 初版作成（デュアルモード対応仕様） |
| 1.1 | 2025-10-25 | Phase 0実装（シンプルLSTM検証） |
| 1.2 | 2025-10-25 | 出力先models/に変更、JSON+MD両方出力 |
| 1.3 | 2025-10-25 | 命名規約修正（タイムスタンプなし基本、既存時バックアップ） |

---

## 🎯 Phase 0実装範囲

### ✅ 実装済み（v1.3）
- 基本的な方向予測評価（Accuracy, Precision, Recall, F1）
- 価格幅予測評価（MAE, RMSE, R²）
- JSON + Markdownレポート出力（models/ディレクトリ）
- 確認ツール（inspect_validation.py）
- 命名規約準拠（タイムスタンプなし基本、既存時自動バックアップ）
- マルチTFモデル対応（MultiTFModel読み込み）
- PyTorch 2.8対応（weights_only=False）

### 📋 未実装（Phase 1以降）
- デュアルモード対応（Scalp/Swing別評価）
- バックテスト機能
- コスト考慮期待値計算
- 性能劣化検出
- モデル比較機能

---

## 📋 目的

`src/validator.py` による学習済みモデルの性能評価。

---

## 📊 Phase 0 評価指標

### 1. 方向予測（3クラス分類）

#### Accuracy（正解率）
```
Accuracy = (正解数) / (全サンプル数)
```

#### Precision（適合率）
```
Precision = TP / (TP + FP)
```

#### Recall（再現率）
```
Recall = TP / (TP + FN)
```

#### F1-Score（調和平均）
```
F1 = 2 * (Precision * Recall) / (Precision + Recall)
```

#### 混同行列
```
              予測
          DOWN  NEUTRAL  UP
実DOWN     xxxx     xxxx  xxxx
  NEUTRAL  xxxx     xxxx  xxxx
  UP       xxxx     xxxx  xxxx
```

### 2. 価格幅予測（回帰）

#### MAE（平均絶対誤差）
```
MAE = (1/N) * Σ|y_true - y_pred|
```
- 単位: pips

#### RMSE（二乗平均平方根誤差）
```
RMSE = sqrt((1/N) * Σ(y_true - y_pred)²)
```
- 単位: pips

#### R² Score（決定係数）
```
R² = 1 - (SS_res / SS_tot)
```
- 範囲: -∞ ~ 1.0

---

## 📊 評価指標（デュアルモード対応）

**注意**: 以下はPhase 1以降の拡張仕様（未実装）

### 1. 分類精度（共通）
- **Direction Accuracy**: 方向予測精度（UP/DOWN/NEUTRAL別）
- **F1 Score**: クラス別F1スコア
- **Confusion Matrix**: 混同行列

### 2. 回帰精度（モード別）

#### Scalp Mode（70-80%のトレード）
- **MAE_Scalp**: スキャルピング価格幅予測誤差平均（0.5-2.0 pips）
- **RMSE_Scalp**: 二乗平均平方根誤差
- **R²_Scalp**: 決定係数

#### Swing Extension Mode（20-30%のトレード）
- **MAE_Swing**: スイング延長価格幅予測誤差平均（2.0-5.0 pips）
- **RMSE_Swing**: 二乗平均平方根誤差
- **R²_Swing**: 決定係数

#### Trend Strength（モード判定精度）
- **MAE_Trend**: トレンド強度予測誤差（0-1）
- **Mode_Classification_Accuracy**: 実際のモード（scalp/swing）と予測一致率

### 3. 実用指標（モード別）

#### 全体
- **Cost-Adjusted Expectancy**: コスト考慮期待値（単位: **net pips**）
  - 計算式: `raw_expectancy - spread - slippage - commission`
  - すべてのコスト要素を差し引いた実質的な期待値
  - 正値: 収益性あり、負値: コスト超過
- **Profit Factor**: 総利益/総損失
- **Max Drawdown**: 最大ドローダウン（pips）

#### Scalp Mode
- **Win Rate_Scalp**: スキャルピングトレード勝率
- **Avg Duration_Scalp**: 平均保有時間（<1時間）
- **Payoff Ratio_Scalp**: 平均利益/平均損失（固定TP/SL）

#### Swing Extension Mode
- **Win Rate_Swing**: スイング延長トレード勝率
- **Avg Duration_Swing**: 平均保有時間（トレール延長）
- **Trail Activation Rate**: トレール起動成功率
- **Payoff Ratio_Swing**: 平均利益/平均損失（トレール）

---

## 🧪 簡易バックテスト（デュアルモード対応）

### 手順

1. **エントリー条件（共通）**
   ```python
   if net_expectancy > 0 and direction_confidence > θ:
       entry = True
       
       # モード判定
       if trend_strength < 0.7:
           mode = "scalp"
       else:
           mode = "swing_trail"
   ```

2. **TP/SL設定（モード別）**
   
   ```python
   # Scalp Mode（固定TP/SL）
   if mode == "scalp":
       TP = ATR × 0.8  # 0.8 pips目標
       SL = ATR × 0.5  # 0.5 pips損切
       use_trailing = False
   
   # Swing Extension Mode（トレール）
   elif mode == "swing_trail":
       TP = None  # トレールのみ
       SL = ATR × 0.5  # 初期損切
       use_trailing = True
       trail_activation = entry_price + 0.8 * pip  # +0.8 pips起動
       trail_distance = 0.3 * pip  # 0.3 pips幅
   ```

3. **決済判定**
   
   ```python
   # Scalp Mode
   if mode == "scalp":
       if current_price >= entry + TP:
           exit = "TP"
       elif current_price <= entry - SL:
           exit = "SL"
       elif duration > 1_hour:
           exit = "Timeout"
   
   # Swing Extension Mode
   elif mode == "swing_trail":
       if use_trailing and current_price >= trail_activation:
           trailing_active = True
           trail_stop = max(trail_stop, current_price - trail_distance)
       
       if current_price <= trail_stop:
           exit = "TrailStop"
       elif current_price <= entry - SL:
           exit = "SL"
       elif duration > 6_hours:
           exit = "Timeout"
   ```

4. **統計計算（モード別）**
   - PnL記録（scalp/swing別）
   - MFE/MAE記録
   - Drawdown計算
   - モード分類精度
   - トレール起動成功率

### バックテスト設定例

```yaml
validation:
  backtest:
    enabled: true
    
    entry:
      min_expectancy: 0.0  # 単位: net pips（コスト差引後）
      min_confidence: 0.60
      trend_strength_threshold: 0.7  # モード判定閾値
    
    exit:
      scalp_mode:
        tp_atr_multiplier: 0.8
        sl_atr_multiplier: 0.5
        max_hold_hours: 1
      
      swing_mode:
        sl_atr_multiplier: 0.5
        trail_activation_pips: 0.8
        trail_distance_pips: 0.3
        max_hold_hours: 6
    
    cost_model:
      spread: 1.2
      slippage:
        scalp: 1.2
        swing: 0.8
      commission: 0.0
      rejection_rate: 0.04
    
    mode_reporting:
```

---

## 📈 JSON レポート

```json
{
  "direction_accuracy": {
    "overall": 0.68,
    "UP": 0.72,
    "DOWN": 0.70,
    "NEUTRAL": 0.62
  },
  "magnitude": {
    "mae": 0.8,
    "rmse": 1.2,
    "r2": 0.65
  },
  "backtest": {
    "cost_adjusted_expectancy": 0.12,
    "profit_factor": 1.45,
    "win_rate": 0.56,
    "payoff_ratio": 1.32,
    "max_drawdown": -2.4,
    "total_trades": 1250
  },
  "class_distribution": {
    "UP": 0.34,
    "DOWN": 0.33,
    "NEUTRAL": 0.33
  },
  "metadata": {
    "config_hash": "abc123...",
    "commit_hash": "def456...",
    "timestamp": "2025-10-21T10:30:00Z"
  }
}
```

---

## 🚨 性能劣化検出

### 警告条件

| 指標 | 閾値 | アクション |
|------|------|------------|
| profit_factor | < 1.0 | CRITICAL |
| cost_adjusted_expectancy | < 0 | WARNING |
| max_drawdown | < -ATR_avg × 3 | WARNING |
| direction_accuracy | 低下 > 5% | WARNING |

### ドリフト検出

```yaml
drift_detection:
  enabled: true
  
  metrics:
    PSI:                      # Population Stability Index
      threshold: 0.25
      window: 1000
    
    ECE:                      # Expected Calibration Error
      threshold: 0.04
```

---

## 💾 出力ファイル

| ファイル名 | 内容 | Git管理 |
|-----------|------|---------|
| `models/validator_report.json` | 評価メトリクス・バックテスト結果 | ❌ 除外 |
| `models/validator_report.md` | 人間可読レポート | ❌ 除外 |
| `models/validator_confusion_matrix.png` | 混同行列（オプション） | ❌ 除外 |
| `models/validator_calibration_curve.png` | キャリブレーション曲線 | ❌ 除外 |

**命名規約**:
- 基本ファイル名: `validator_report.json` / `validator_report.md`（タイムスタンプなし）
- 既存ファイルがある場合: 既存ファイルを `validator_YYYYMMDD_HHMMSS_report.*` にリネーム後、新ファイルを作成
- タイムスタンプは既存ファイルの変更時刻を使用（JST）

例:
```
# 初回実行
models/validator_report.json  ← 新規作成

# 2回目実行
models/validator_20251025_220556_report.json  ← 既存ファイルをリネーム
models/validator_report.json  ← 新規作成
```

**注**: 検証フェーズはモデルファイルを生成しないため、レポートのみ出力

---

## 📄 レポート生成

### JSONレポート (`models/validator_report.json`)

次処理（ONNX変換）が読み込むパラメータ情報:

```json
{
  "timestamp": "2025-10-24T16:00:35+09:00",
  "process": "validator",
  "version": "1.0",
  "input": {
    "model_file": "models/trainer.pt",
    "data_file": "data/preprocessor.h5",
    "source_report": "models/trainer_report.json"
  },
  "validation_period": {
    "start": "2024-11-01T00:00:00+09:00",
    "end": "2024-12-31T23:59:00+09:00",
    "total_samples": 44640
  },
  "metrics": {
    "direction": {
      "overall_accuracy": 0.68,
      "up_accuracy": 0.72,
      "down_accuracy": 0.70,
      "neutral_accuracy": 0.62,
      "confusion_matrix": {
        "true_up_pred_up": 9500,
        "true_up_pred_down": 1200,
        "true_up_pred_neutral": 2480,
        "true_down_pred_up": 1150,
        "true_down_pred_down": 9800,
        "true_down_pred_neutral": 2530,
        "true_neutral_pred_up": 2680,
        "true_neutral_pred_down": 2750,
        "true_neutral_pred_neutral": 8950
      }
    },
    "magnitude": {
      "mae_pips": 8.2,
      "rmse_pips": 12.5,
      "r2_score": 0.65,
      "median_error_pips": 6.8
    },
    "calibration": {
      "ece": 0.032,
      "mce": 0.058,
      "brier_score": 0.18
    }
  },
  "backtest": {
    "total_trades": 1250,
    "winning_trades": 700,
    "losing_trades": 550,
    "win_rate": 0.56,
    "profit_factor": 1.45,
    "expectancy_pips": 0.12,
    "max_drawdown_pips": -2.4,
    "sharpe_ratio": 1.23,
    "total_pnl_pips": 150.0,
    "avg_trade_duration_minutes": 360
  },
  "class_distribution": {
    "up": 0.34,
    "down": 0.33,
    "neutral": 0.33
  },
  "performance": {
    "inference_time_sec": 45,
    "avg_prediction_time_ms": 1.0,
    "memory_peak_mb": 6000
  }
}
```

### Markdownレポート (`models/validator_report.md`)

人間による検証用の可読レポート:

```markdown
# 検証 実行レポート

**実行日時**: 2025-10-24 16:00:35 JST  
**検証時間**: 22分13秒  
**バージョン**: 1.0

## 📊 入力

- **モデルファイル**: `models/trainer.pt`
- **データファイル**: `data/preprocessor.h5`
- **検証期間**: 2024-11-01 00:00 JST ～ 2024-12-31 23:59 JST
- **総サンプル数**: 44,640

## 🎯 方向予測精度

### 総合精度

| メトリクス | 値 |
|----------|-----|
| Overall Accuracy | 68.0% |
| UP Accuracy | 72.0% |
| DOWN Accuracy | 70.0% |
| NEUTRAL Accuracy | 62.0% |

### 混同行列

|          | Pred UP | Pred DOWN | Pred NEUTRAL | 合計 |
|----------|---------|-----------|--------------|------|
| **True UP** | 9,500 | 1,200 | 2,480 | 13,180 |
| **True DOWN** | 1,150 | 9,800 | 2,530 | 13,480 |
| **True NEUTRAL** | 2,680 | 2,750 | 8,950 | 14,380 |

### クラス分布

| クラス | 比率 |
|-------|------|
| UP | 34.0% |
| DOWN | 33.0% |
| NEUTRAL | 33.0% |

## 📏 価格幅予測精度

| メトリクス | 値 |
|----------|-----|
| MAE | 8.2 pips |
| RMSE | 12.5 pips |
| R² Score | 0.65 |
| Median Error | 6.8 pips |

## 🎲 確率キャリブレーション

| メトリクス | 値 | 閾値 | 判定 |
|----------|-----|------|------|
| ECE | 0.032 | <0.04 | ✅ 合格 |
| MCE | 0.058 | <0.10 | ✅ 合格 |
| Brier Score | 0.18 | <0.25 | ✅ 合格 |

## 💰 バックテスト結果

### 基本統計

| 項目 | 値 |
|-----|-----|
| 総トレード数 | 1,250 |
| 勝ちトレード | 700 (56.0%) |
| 負けトレード | 550 (44.0%) |
| 勝率 | 56.0% |

### パフォーマンス指標

| 指標 | 値 |
|-----|-----|
| Profit Factor | 1.45 |
| Expectancy | 0.12 pips |
| 総損益 | 150.0 pips |
| 最大DD | -2.4 pips |
| Sharpe Ratio | 1.23 |
| 平均保有時間 | 6時間00分 |

## ⚙️ パフォーマンス

- **推論時間**: 45秒
- **平均予測時間**: 1.0ms/サンプル
- **ピークメモリ**: 6,000 MB

## ⚠️ 警告・注意事項

- NEUTRAL精度が62%（他クラスより低い）
- 最大DDが-2.4 pips（許容範囲内）
- 推論速度は実トレードに十分

## ✅ 検証結果

- ✅ 方向精度68%達成
- ✅ 価格幅MAE 8.2 pips（目標10 pips以下）
- ✅ キャリブレーション良好（ECE <0.04）
- ✅ Profit Factor 1.45（1.0以上）
- ✅ 実運用可能レベル
```

---

## 📝 ログ出力

### 時刻表示ルール
- **全ログ**: 日本時間(JST)で表示
- **フォーマット**: `YYYY-MM-DD HH:MM:SS JST`
- **検証期間**: 日本時間で明記
- **詳細**: [TIMEZONE_UTILS_SPEC.md](./utils/TIMEZONE_UTILS_SPEC.md)

```
🔄 第5段階: 検証開始 [2025-10-24 03:50:22 JST]
📂 モデル: models/fx_mtf_20251022_100000_model.pth
📂 データ: models/fx_mtf_20251022_100000_preprocessed.h5
   検証期間: 2024-11-01 00:00:00 JST ～ 2024-12-31 23:59:00 JST

🎯 方向精度
   Overall=0.68, UP=0.72, DOWN=0.70, NEUTRAL=0.62

📊 価格幅精度
   MAE=0.8pips, RMSE=1.2pips, R²=0.65

💰 バックテスト結果
   期待値=0.12pips, PF=1.45, 勝率=56%
   最大DD=-2.4pips, トレード数=1250

📈 クラス分布
   UP=34%, DOWN=33%, NEUTRAL=33%

✅ 検証完了 [2025-10-24 04:12:35 JST]
   検証時間: 22分13秒
```

---

## ⚙️ 設定例

```yaml
validation:
  metrics:
    - direction_accuracy
    - magnitude_mae
    - cost_adjusted_expectancy
    - profit_factor
    - max_drawdown
  
  backtest:
    enabled: true
    entry:
      min_expectancy: 1.0      # 単位: net pips（コストモデル考慮後）
      min_confidence: 0.65     # 引き上げ（cost増加対応）
    exit:
      # 動的TP/SL戦略（DYNAMIC_EXIT_SPEC.md参照）
      strategy: "dynamic"      # dynamic | fixed（Phase 1ではfixed）
      scalp_base_tp: 0.8       # pips
      scalp_base_sl: 0.5       # pips
      swing_initial_tp: 2.0    # pips
      # 従来の固定倍率は廃止（ATR×2.0は非現実的）
    cost_model:
      spread: 1.2
      slippage: 0.3
      commission: 0.0
  
  drift_detection:
    enabled: true
    PSI_threshold: 0.25
    ECE_threshold: 0.04
  
  output:
    report_format: json
    save_confusion_matrix: true
    save_scatter_plots: true
```

---

## 🔗 関連仕様書

- **前段階**: 第4段階: [TRAINER_SPEC.md](./TRAINER_SPEC.md) - 学習
- **次工程**: 第6段階: [ONNX_CONVERTER_SPEC.md](./ONNX_CONVERTER_SPEC.md) - ONNX変換
- **詳細仕様**:
  - [validator/BACKTEST_EVALUATION_SPEC.md](./validator/BACKTEST_EVALUATION_SPEC.md) - バックテスト評価
  - [validator/DRIFT_CALIBRATION_MONITORING_SPEC.md](./validator/DRIFT_CALIBRATION_MONITORING_SPEC.md) - ドリフト較正監視
  - [validator/EXECUTION_LATENCY_SPEC.md](./validator/EXECUTION_LATENCY_SPEC.md) - 実行レイテンシ
  - [validator/COST_MODEL_SPEC.md](./validator/COST_MODEL_SPEC.md) - コストモデル
  - [validator/DYNAMIC_EXIT_SPEC.md](./validator/DYNAMIC_EXIT_SPEC.md) - 動的Exit戦略（固定倍率廃止、市場適応型TP/SL）
  - [validator/FUTURE_LEAK_PREVENTION_SPEC.md](./validator/FUTURE_LEAK_PREVENTION_SPEC.md) - 未来リーク防止

---

## 項目22対応: 低ボラ期エントリ抑制

**目的**: 低ボラティリティ時（spread/ATR > ratio_thr）は予測信頼度低下しコスト負け頻発。エントリ抑制でドローダウン防止。

**解決策**: spread/ATR_short比率閾値でconfidence減衰 + エントリスキップ

### 低ボラティリティ判定

```python
def check_low_volatility_suppression(
    spread_pips: float,
    atr_short: float,  # M5の20期間ATR（短期）
    ratio_threshold: float = 0.6
) -> Dict[str, Any]:
    """
    低ボラティリティ期のエントリ抑制判定
    
    Args:
        spread_pips: スプレッド（pips）
        atr_short: 短期ATR（M5_20期間、pips）
        ratio_threshold: 抑制閾値（デフォルト0.6）
    
    Returns:
        {
            "suppression_active": bool,
            "spread_atr_ratio": float,
            "confidence_multiplier": float,  # 0.5 or 1.0
            "reason": str
        }
    """
    # spread/ATR比率計算
    if atr_short < 1e-6:
        # ATRがほぼゼロの場合は強制抑制
        return {
            "suppression_active": True,
            "spread_atr_ratio": float('inf'),
            "confidence_multiplier": 0.0,
            "reason": "ATR異常低下（ゼロ近傍）→ 強制エントリ抑制"
        }
    
    ratio = spread_pips / atr_short
    
    # 閾値判定
    if ratio > ratio_threshold:
        return {
            "suppression_active": True,
            "spread_atr_ratio": ratio,
            "confidence_multiplier": 0.5,
            "reason": f"低ボラティリティ（ratio={ratio:.3f} > {ratio_threshold}）→ confidence×0.5"
        }
    else:
        return {
            "suppression_active": False,
            "spread_atr_ratio": ratio,
            "confidence_multiplier": 1.0,
            "reason": f"通常ボラティリティ（ratio={ratio:.3f} ≤ {ratio_threshold}）"
        }


# 使用例: エントリ判定時
suppression = check_low_volatility_suppression(
    spread_pips=1.2,
    atr_short=1.5,  # M5_ATR20=1.5 pips
    ratio_threshold=0.6
)

if suppression["suppression_active"]:
    # confidence減衰適用
    confidence_adjusted = original_confidence * suppression["confidence_multiplier"]
    
    logger.warning(
        f"⚠️ 低ボラ抑制発動: {suppression['reason']}, "
        f"confidence: {original_confidence:.3f} → {confidence_adjusted:.3f}"
    )
    
    # エントリ判定（調整後confidence）
    if confidence_adjusted < entry_threshold:
        logger.info(f"エントリスキップ: 調整後confidence不足")
        entry_decision = False
else:
    confidence_adjusted = original_confidence
    logger.debug(f"低ボラ抑制なし: {suppression['reason']}")
```

### バックテストへの統合

```python
def backtest_with_volatility_suppression(
    predictions: pd.DataFrame,
    price_data: pd.DataFrame,
    config: dict
) -> Dict[str, Any]:
    """
    低ボラ抑制付きバックテスト
    
    Args:
        predictions: 予測結果 DataFrame
            - direction_confidence: 方向予測信頼度
            - expectancy: 期待値
            - atr_m5_20: M5の20期間ATR
        price_data: 価格データ
            - spread_pips: スプレッド
        config:
            - entry_min_confidence: エントリ最低confidence（通常0.6）
            - volatility_suppression_ratio: 抑制比率閾値（デフォルト0.6）
    
    Returns:
        {
            "total_trades": int,
            "suppression_triggered_count": int,
            "suppression_rate": float,
            "trades_with_suppression": List[Dict],
            ...
        }
    """
    trades = []
    suppression_count = 0
    
    for idx, row in predictions.iterrows():
        original_confidence = row["direction_confidence"]
        spread = price_data.loc[idx, "spread_pips"]
        atr_short = row["atr_m5_20"]
        
        # 低ボラ判定
        suppression = check_low_volatility_suppression(
            spread_pips=spread,
            atr_short=atr_short,
            ratio_threshold=config["volatility_suppression_ratio"]
        )
        
        # confidence調整
        confidence_adjusted = original_confidence * suppression["confidence_multiplier"]
        
        # 抑制カウント
        if suppression["suppression_active"]:
            suppression_count += 1
        
        # エントリ判定
        if (
            row["expectancy"] > 0 and
            confidence_adjusted >= config["entry_min_confidence"]
        ):
            # トレード実行
            trade = execute_trade(
                entry_price=price_data.loc[idx, "close"],
                direction=row["predicted_direction"],
                tp=row["tp_pips"],
                sl=row["sl_pips"],
                confidence=confidence_adjusted,
                suppression_applied=suppression["suppression_active"]
            )
            trades.append(trade)
        else:
            # エントリスキップ記録
            if suppression["suppression_active"]:
                logger.debug(
                    f"[{idx}] 低ボラ抑制によりスキップ: "
                    f"ratio={suppression['spread_atr_ratio']:.3f}, "
                    f"confidence: {original_confidence:.3f} → {confidence_adjusted:.3f}"
                )
    
    # 統計集計
    total_signals = len(predictions)
    suppression_rate = suppression_count / total_signals if total_signals > 0 else 0
    
    return {
        "total_signals": total_signals,
        "total_trades": len(trades),
        "suppression_triggered_count": suppression_count,
        "suppression_rate": suppression_rate,
        "trades": trades,
        "suppression_impact": {
            "avg_ratio_when_suppressed": ...,  # 統計計算
            "avg_confidence_reduction": ...,
        }
    }
```

### KPI・評価基準

- **抑制発動率**: 5-15%（適切な閾値設定時）
- **抑制後勝率**: 通常期と比較して低下しない（または改善）
- **ドローダウン削減**: 低ボラ期のドローダウン ≤ 通常期の50%
- **誤抑制率**: <5%（通常ボラでエントリ阻害しない）

### 閾値調整ガイドライン

| ratio_threshold | 発動頻度 | 効果 | 推奨用途 |
|----------------|---------|------|---------|
| 0.4 | 高（20-30%） | 過剰抑制リスク | 超保守的運用 |
| 0.6 | 中（10-15%） | バランス | **標準推奨** |
| 0.8 | 低（5-10%） | 限定的 | 積極的運用 |
| 1.0 | 極低（<5%） | ほぼ無効 | 検証用 |

### 検証

```python
def test_low_volatility_suppression():
    """低ボラ抑制の動作確認"""
    # ケース1: 通常ボラ（ratio=0.5 < 0.6）
    result = check_low_volatility_suppression(1.2, 2.4, 0.6)
    assert result["suppression_active"] == False
    assert result["confidence_multiplier"] == 1.0
    
    # ケース2: 低ボラ（ratio=0.8 > 0.6）
    result = check_low_volatility_suppression(1.2, 1.5, 0.6)
    assert result["suppression_active"] == True
    assert result["confidence_multiplier"] == 0.5
    
    # ケース3: ATRゼロ（極端ケース）
    result = check_low_volatility_suppression(1.2, 1e-10, 0.6)
    assert result["suppression_active"] == True
    assert result["confidence_multiplier"] == 0.0
```

---

## コストモデル最適化

### コストモデル反映遅延対策（spread動的モデル）

**目的**: 固定spread（1.5pips）は市場時間帯・流動性で変動

**解決策**: 時間帯別spread動的モデル

```python
class DynamicSpreadModel:
    """動的spreadモデル"""
    
    def __init__(self, config: dict):
        self.default_spread = config.get("default_spread_pips", 1.5)
        self.time_profile = config.get("time_profile", {})
        self.liquidity_adjustment = config.get("liquidity_adjustment", True)
    
    def get_spread(
        self,
        timestamp: pd.Timestamp,
        volume_ratio: float = 1.0
    ) -> float:
        """
        動的spread取得
        
        Args:
            timestamp: 現在時刻（UTC）
            volume_ratio: 通常時比出来高比率
        
        Returns:
            spread_pips: 推定spread
        """
        hour_utc = timestamp.hour
        
        # 時間帯別ベースspread
        if 0 <= hour_utc < 7:  # アジア時間（低流動性）
            base_spread = self.default_spread * 1.5
        elif 7 <= hour_utc < 14:  # ロンドン時間（高流動性）
            base_spread = self.default_spread * 0.8
        elif 14 <= hour_utc < 21:  # NY時間（最高流動性）
            base_spread = self.default_spread * 0.7
        else:  # 21-24時（流動性低下）
            base_spread = self.default_spread * 1.2
        
        # 流動性調整
        if self.liquidity_adjustment:
            if volume_ratio < 0.5:  # 閑散
                base_spread *= 1.5
            elif volume_ratio < 0.8:
                base_spread *= 1.2
            elif volume_ratio > 2.0:  # 活況
                base_spread *= 0.9
        
        return base_spread


# 使用例（バックテスト統合）
spread_model = DynamicSpreadModel({
    "default_spread_pips": 1.5,
    "liquidity_adjustment": True
})

# バックテスト内
for timestamp, pred in backtest_predictions.items():
    volume_ratio = current_volume / historical_avg_volume
    spread = spread_model.get_spread(timestamp, volume_ratio)
    
    cost = spread + slippage
    net_pips = pred_magnitude - cost
    
    if net_pips > 0:
        # エントリー許可
        pass
```

**時間帯別spread係数**:

| 時間帯（UTC） | 市場 | 流動性 | spread係数 |
|-------------|------|--------|-----------|
| 00-07 | アジア | 低 | 1.5x |
| 07-14 | ロンドン | 高 | 0.8x |
| 14-21 | NY | 最高 | 0.7x |
| 21-24 | クローズ | 中 | 1.2x |

**KPI（項目25）**:
- spread推定誤差: <0.3 pips（実測比較）
- コスト考慮後の期待値改善: ≥+1 pip/trade
- 時間帯別モデル精度: R²>0.6

---

### spread_jump反映遅延対策

**目的**: 急激なspread拡大（指標発表時）の反映遅れでコスト誤算

**解決策**: spread jump検出・遅延補正

```python
class SpreadJumpDetector:
    """spread jump検出"""
    
    def __init__(self, config: dict):
        self.jump_threshold = config.get("jump_threshold_multiplier", 2.0)
        self.lookback_window = config.get("lookback_window", 30)
        
        self.spread_history = deque(maxlen=self.lookback_window)
    
    def detect_jump(self, current_spread: float) -> Dict[str, Any]:
        """
        spread jump検出
        
        Args:
            current_spread: 現在のspread (pips)
        
        Returns:
            {
                "is_jump": bool,
                "jump_ratio": float,
                "baseline_spread": float,
                "action": "block" | "adjust" | "normal"
            }
        """
        if len(self.spread_history) < 10:
            # 初期化中
            self.spread_history.append(current_spread)
            return {
                "is_jump": False,
                "jump_ratio": 1.0,
                "baseline_spread": current_spread,
                "action": "normal"
            }
        
        # ベースライン（中央値）
        baseline = np.median(list(self.spread_history))
        
        # jump比率
        jump_ratio = current_spread / baseline
        
        # 履歴更新
        self.spread_history.append(current_spread)
        
        # jump判定
        if jump_ratio > self.jump_threshold:
            return {
                "is_jump": True,
                "jump_ratio": jump_ratio,
                "baseline_spread": baseline,
                "action": "block"  # エントリー停止
            }
        elif jump_ratio > self.jump_threshold * 0.7:
            return {
                "is_jump": False,
                "jump_ratio": jump_ratio,
                "baseline_spread": baseline,
                "action": "adjust"  # コスト補正
            }
        else:
            return {
                "is_jump": False,
                "jump_ratio": jump_ratio,
                "baseline_spread": baseline,
                "action": "normal"
            }


# 使用例
jump_detector = SpreadJumpDetector({
    "jump_threshold_multiplier": 2.0,
    "lookback_window": 30
})

# リアルタイムチェック
while True:
    current_spread = get_current_spread()
    result = jump_detector.detect_jump(current_spread)
    
    if result["action"] == "block":
        logger.warning(
            f"spread jump検出: {result['jump_ratio']:.2f}x, "
            f"エントリー停止"
        )
        continue  # トレードスキップ
    
    elif result["action"] == "adjust":
        # コスト補正（jump分を上乗せ）
        adjusted_cost = result["baseline_spread"] + slippage + \
                       (current_spread - result["baseline_spread"]) * 0.5
        
        logger.info(f"spread調整: {adjusted_cost:.2f} pips")
    
    # 通常処理
    execute_trade(adjusted_cost if result["action"] == "adjust" else current_spread)
```

**jump検出基準**:

| 比率 | 判定 | アクション |
|------|------|-----------|
| >2.0x | jump | エントリー停止 |
| 1.4-2.0x | 警戒 | コスト補正 |
| <1.4x | 通常 | そのまま |

**KPI（項目36）**:
- jump検出精度: ≥90%（指標発表時を正確に捕捉）
- 誤検出率: <5%
- jump中のエントリー回避率: 100%

---

### trend_strength TTL

**目的**: 古いtrend_strength値を使い続けて誤判定

**解決策**: TTL（Time To Live）管理

```python
class TrendStrengthCache:
    """trend_strength TTL管理"""
    
    def __init__(self, config: dict):
        self.ttl_seconds = config.get("ttl_seconds", 300)  # 5分
        
        self.cache = {}  # {tf: {"value": float, "timestamp": float}}
    
    def set(self, tf: str, value: float):
        """trend_strength設定"""
        self.cache[tf] = {
            "value": value,
            "timestamp": time.time()
        }
    
    def get(self, tf: str) -> Optional[float]:
        """
        trend_strength取得（TTLチェック）
        
        Returns:
            trend_strength値（有効期限内） or None（期限切れ）
        """
        if tf not in self.cache:
            return None
        
        entry = self.cache[tf]
        age_seconds = time.time() - entry["timestamp"]
        
        if age_seconds > self.ttl_seconds:
            logger.debug(f"{tf} trend_strength期限切れ: {age_seconds:.0f}秒経過")
            del self.cache[tf]
            return None
        
        return entry["value"]
    
    def is_valid(self, tf: str) -> bool:
        """有効期限内チェック"""
        return self.get(tf) is not None
    
    def cleanup_expired(self):
        """期限切れエントリ削除"""
        expired_keys = []
        current_time = time.time()
        
        for tf, entry in self.cache.items():
            if current_time - entry["timestamp"] > self.ttl_seconds:
                expired_keys.append(tf)
        
        for key in expired_keys:
            del self.cache[key]
        
        if expired_keys:
            logger.debug(f"期限切れ削除: {expired_keys}")


# 使用例
trend_cache = TrendStrengthCache({
    "ttl_seconds": 300  # 5分
})

# trend_strength計算時
trend_strength_h4 = calculate_trend_strength("H4")
trend_cache.set("H4", trend_strength_h4)

# モード判定時
while True:
    trend_h4 = trend_cache.get("H4")
    
    if trend_h4 is None:
        logger.warning("H4 trend_strength期限切れ: 再計算")
        trend_h4 = calculate_trend_strength("H4")
        trend_cache.set("H4", trend_h4)
    
    # モード判定
    mode = "swing" if trend_h4 > 0.6 else "scalp"
    
    # 定期クリーンアップ
    trend_cache.cleanup_expired()
```

**TTL設定指針**:

| TF | データ更新頻度 | 推奨TTL |
|----|-------------|---------|
| M1 | 1分毎 | 2分 |
| M5 | 5分毎 | 10分 |
| H1 | 1時間毎 | 2時間 |
| H4 | 4時間毎 | **5分** |

**注**: H4のTTLが短い理由は、M1エントリーのモード判定で頻繁に参照するため。

**KPI（項目39）**:
- キャッシュヒット率: >95%
- 期限切れ検出率: 100%
- 再計算トリガ頻度: <5%

---

## 📌 注意事項

1. **バックテストは簡易版**: 実際の運用とは乖離の可能性
2. **スリッページモデル簡略**: 実市場では変動大
3. **コスト保守的に**: 過度な楽観禁止
4. **ドリフト監視必須**: 定期的な再学習トリガ
5. **低ボラ抑制**: 閾値調整は検証データで最適化必須

---

## 🔮 将来拡張

- スリッページ動的モデル
- マルチペア評価
- Walk-forward最適化
- リアルタイム監視ダッシュボード
- A/Bテストフレームワーク
- 適応的ボラティリティ閾値（市場環境で自動調整）
