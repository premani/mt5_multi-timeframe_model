# DRIFT_CALIBRATION_MONITORING_SPEC

**バージョン**: 1.0  
**更新日**: 2025-10-21

## 1. 目的

市場状態分布の変化 (ドリフト) とモデル出力の校正ズレを高精度に検知し、再学習・重み調整・λ_inv 適応の判断材料を提供する。過剰再学習を避けつつ期待値と不変性品質を維持する運用監視レイヤを定義。

... (内容省略なし: 元全文復元) ...

---


## 📋 目的

市場状態分布の変化（ドリフト）とモデル出力の校正ズレを高精度に検知し、再学習・重み調整の判断材料を提供する。

---

## 📊 監視指標

### 1. ドリフト検出

| 指標 | 説明 | 閾値例 |
|------|------|--------|
| **PSI** | Population Stability Index（分布安定性） | >0.25 で再学習検討 |
| **feature_drift_score** | PSI正規化加重平均 | >0.25 で警告 |

### 2. 校正検証

| 指標 | 説明 | 閾値例 |
|------|------|--------|
| **ECE** | Expected Calibration Error | >0.04 で警告 |
| **expectancy_bias** | 期待値予測 vs 実測差分（相対%） | abs(bias) >5% で警告 |
| **monotonicity_spearman** | 期待値decile vs 実測順位相関 | <0.9 で警告 |

---

## 🔄 監視フロー

### 1. データ収集
定期的（例: 1000サンプル毎）に特徴量分布とモデル出力を記録

### 2. PSI計算（項目56対応: ゼロビン平滑化）
```python
# 10分位でビン分割
for feature in features:
    bins = quantile(reference_data[feature], q=[0, 0.1, ..., 1.0])
    expected = histogram(reference_data[feature], bins)
    actual = histogram(current_data[feature], bins)
    
    # ゼロビン平滑化（Laplace平滑化）
    eps = 1e-6  # 平滑化パラメータ
    expected_smoothed = expected + eps
    actual_smoothed = actual + eps
    
    # 正規化
    expected_smoothed = expected_smoothed / expected_smoothed.sum()
    actual_smoothed = actual_smoothed / actual_smoothed.sum()
    
    # PSI計算（log(0)防止）
    psi = sum((actual_smoothed - expected_smoothed) * log(actual_smoothed / expected_smoothed))
    
    # 最小サンプル閾値チェック
    if min(actual.sum(), expected.sum()) < 100:
        log_warning(f"PSI計算でサンプル数不足: {feature}")
```

**ゼロビン平滑化仕様**:
- eps = 1e-6（デフォルト）
- 最小サンプル閾値 = 100件
- 閾値未満の場合は警告ログ出力のみ（PSIは計算）

### 3. 校正誤差計算（項目57対応: ECE動的閾値）
```python
# ECE: 10 decile（サンプルサイズ適応型）
min_bin_count = max(50, len(predictions) // 100)  # 最小ビン件数
adaptive_bins = min(10, len(predictions) // min_bin_count)  # 動的ビン数

for decile in range(adaptive_bins):
    predicted_prob = mean(predictions[decile])
    actual_freq = mean(actuals[decile])
    ece += abs(predicted_prob - actual_freq) / adaptive_bins

# 動的閾値（サンプルサイズ依存）
sample_size = len(predictions)
if sample_size < 1000:
    ece_threshold = 0.06  # 小サンプル時は緩和
elif sample_size < 5000:
    ece_threshold = 0.05
else:
    ece_threshold = 0.04  # デフォルト
```

**ECE動的閾値仕様**:
- 最小ビン件数: max(50, N // 100)
- 動的ビン数: min(10, N // min_bin_count)
- 閾値: N < 1000: 0.06, N < 5000: 0.05, N >= 5000: 0.04
- KPI: false positive率 < 5%

### 4. トリガ判定
```python
if (psi > 0.25) or (ece > 0.04 and abs(expectancy_bias) > 0.05):
    trigger_retrain = True
```

---

## 📝 ログ出力

**注記**: timestampはUTC、ログ表示は日本時間(JST)で出力されます。詳細: [docs/utils/TIMEZONE_UTILS_SPEC.md](../utils/TIMEZONE_UTILS_SPEC.md)

```json
{
  "event": "drift_calibration",
  "timestamp": "2025-10-21T10:30:00Z",
  "timestamp_jst": "2025-10-21 19:30:00 JST",
  "psi": 0.27,
  "ece": 0.045,
  "expectancy_bias": 0.06,
  "monotonicity_spearman": 0.88,
  "trigger": "retrain"
}
```

---

## 🚨 アラート条件

| 条件 | 重要度 | アクション |
|------|--------|------------|
| PSI > 0.25 | WARNING | 再学習検討 |
| PSI > 0.35 | CRITICAL | 再学習必須 |
| ECE > 0.04 | WARNING | 校正チェック |
| expectancy_bias > 5% | WARNING | バイアス補正検討 |

---

## 🔗 参照

- **親仕様書**: `docs/VALIDATOR_SPEC.md`
- **再学習**: `docs/TRAINER_SPEC.md` §ローリング再学習

---

## 🔮 将来拡張

- レジーム別ドリフト検出
- 動的閾値調整（市場状況に応じて）
- マルチモデルアンサンブル時のドリフト検出

---

## オンライン校正・再学習制御

### オンライン校正（rolling_bias調整）

**目的**: モデルdrift下でバイアス蓄積

**解決策**: rolling window bias補正

```python
class OnlineCalibrator:
    """オンライン校正"""
    
    def __init__(self, window_size: int = 1000):
        self.window_size = window_size
        self.error_history = deque(maxlen=window_size)
    
    def update(self, pred: float, actual: float):
        """誤差履歴更新"""
        self.error_history.append(actual - pred)
    
    def get_bias_correction(self) -> float:
        """バイアス補正値取得"""
        if len(self.error_history) < 100:
            return 0.0
        return np.median(list(self.error_history))
    
    def calibrate_prediction(self, pred: float) -> float:
        """予測値補正"""
        bias = self.get_bias_correction()
        return pred + bias
```

**KPI（項目27）**: バイアス<2 pips、calibration適用で精度+3%

---

### 再学習トリガクールダウン

**目的**: ドリフト誤検出で頻繁再学習

**解決策**: クールダウン期間設定

```python
class RetrainCooldownManager:
    """再学習クールダウン管理"""
    
    def __init__(self, cooldown_hours: int = 24):
        self.cooldown_hours = cooldown_hours
        self.last_retrain_time = None
    
    def can_retrain(self) -> bool:
        """再学習可能判定"""
        if self.last_retrain_time is None:
            return True
        
        elapsed = time.time() - self.last_retrain_time
        return elapsed > self.cooldown_hours * 3600
    
    def mark_retrained(self):
        """再学習実行記録"""
        self.last_retrain_time = time.time()
```

**KPI（項目58）**: 再学習頻度<1回/日、誤トリガ<5%
