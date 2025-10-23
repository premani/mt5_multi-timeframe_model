# EXECUTION_LATENCY_SPEC.md

**バージョン**: 1.0  
**更新日**: 2025-10-21  
**責任者**: core-team

---

## 📋 目的

M1スキャルピング環境でのリアルタイム推論における**レイテンシ要件**と**最適化戦略**を定義し、デュアルモード（scalp/swing）トレード戦略において期待値劣化を防ぐ実行パフォーマンスを確保する。

---

## 🎯 レイテンシ要件（SLO: Service Level Objectives）

### 全体目標

```yaml
inference_latency_slo:
  # End-to-End レイテンシ（データ受信→予測出力）
  total:
    p50: < 5.0 ms     # 中央値
    p95: < 10.0 ms    # 95パーセンタイル
    p99: < 20.0 ms    # 99パーセンタイル
    max: < 50.0 ms    # 最大値（異常時）
  
  # Fast Path（通常実行パス）
  fast_path:
    p50: < 3.0 ms
    p95: < 8.0 ms
    max: < 15.0 ms
  
  # Slow Path（フル再計算が必要な場合）
  slow_path:
    p95: < 30.0 ms
    max: < 100.0 ms
```

### デュアルモード別要件

```yaml
mode_specific_requirements:
  # Scalp Mode（70-80%のトレード）
  scalp:
    critical: true
    target_duration: < 1 hour
    entry_timing_sensitivity: high
    max_acceptable_latency: 10 ms  # p95基準
    reason: "M1/M5/M15の短期エントリーでは数秒の遅延が致命的"
  
  # Swing Extension Mode（20-30%のトレード）
  swing:
    critical: false
    target_duration: < 6 hours
    entry_timing_sensitivity: medium
    max_acceptable_latency: 50 ms  # p95基準
    reason: "H1/H4参照のトレール戦略では数十msの遅延は許容可能"
```

---

## 🏗️ 実行パイプライン分解

### パイプラインステージ

```
┌─────────────────────────────────────────────────────────────┐
│ 1. Input Bind        (データ受信・バインド)                 │ ~0.5ms
├─────────────────────────────────────────────────────────────┤
│ 2. Diff Update       (差分前処理・特徴量更新)               │ ~1.5ms
├─────────────────────────────────────────────────────────────┤
│ 3. Model Forward     (LSTM推論 5TF + Attention Fusion)      │ ~4.0ms
├─────────────────────────────────────────────────────────────┤
│ 4. Postprocess       (確率正規化・期待値計算)               │ ~0.5ms
├─────────────────────────────────────────────────────────────┤
│ 5. Publish           (結果出力・ログ記録)                   │ ~0.5ms
└─────────────────────────────────────────────────────────────┘
Total Target: ~7.0ms (p50)
```

### ステージ別SLO

```python
stage_latency_targets = {
    "input_bind": {
        "p50": 0.3,  # ms
        "p95": 0.6,
        "description": "HDF5読込 or リングバッファ取得"
    },
    "diff_update": {
        "p50": 1.0,
        "p95": 2.0,
        "description": "増分特徴量計算（EMA/Welford更新）"
    },
    "model_forward_fast": {
        "p50": 3.0,
        "p95": 5.0,
        "description": "ONNX FP16推論（5TF LSTM + Fusion）"
    },
    "model_forward_lazy": {
        "p95": 15.0,
        "description": "フル再計算（キャッシュミス時）"
    },
    "postprocess": {
        "p50": 0.4,
        "p95": 0.8,
        "description": "Softmax + 期待値計算 + モード判定"
    },
    "publish": {
        "p50": 0.3,
        "p95": 0.6,
        "description": "非同期ログキュー + 結果返却"
    }
}
```

---

## ⚡ 最適化戦略

### 1. 差分前処理（Incremental Feature Update）

```python
# リングバッファによる効率化
class IncrementalFeatureUpdater:
    """
    新しいバーが1本追加されるたびに、O(1)で特徴量を更新
    """
    def __init__(self, window_size: int = 360):
        self.ring_buffer = RingBuffer(window_size)
        self.ema_state = {}  # EMA状態保持
        self.welford_state = {}  # 分散計算用
    
    def update(self, new_bar: dict) -> np.ndarray:
        """
        Target: p95 < 2.0ms
        
        差分更新対象:
        - EMA系（exponential moving average）
        - Rolling統計（mean, std via Welford）
        - ATR（Average True Range）
        - Tick activity率
        """
        self.ring_buffer.append(new_bar)
        
        # O(1)更新
        self._update_ema()
        self._update_welford_variance()
        self._update_atr()
        
        return self.get_features()  # 最新360本分
```

**効果**: 全特徴量再計算（~10ms） → 差分更新（~1.5ms）

### 2. モデル推論最適化

#### ONNX Runtime + FP16

```yaml
model_optimization:
  format: ONNX
  precision: FP16  # Mixed precision
  execution_provider: CUDAExecutionProvider
  graph_optimization_level: ORT_ENABLE_ALL
  
  quantization:
    phase1: FP16  # 初期
    phase2: INT8  # 検証後（精度確認必須）
```

#### Attention最適化

```python
# QK射影次元削減
attention_config = {
    "d_model": 128,
    "d_k_projection": 32,  # 通常64→32へ削減
    "num_heads": 4,
    "description": "Query/Key射影を低次元化してQK^T計算量削減"
}

# Age-based Weight テーブル化
# 動的計算（~0.5ms） → テーブル参照（~0.01ms）
age_weight_table = np.exp(-np.arange(360) * 0.01)  # 事前計算
```

#### バッチ処理の回避

```python
# ❌ NG: バッチ推論（待機時間増加）
# predictions = model.predict(batch_samples)

# ✅ OK: 単一サンプル即時推論
prediction = model.predict(single_sample)  # latency最小化
```

### 3. Fast Path / Slow Path 分岐

```python
class AdaptiveInferenceEngine:
    def predict(self, new_bar: dict) -> dict:
        # キャッシュヒット判定
        if self._is_incremental_update_valid():
            # Fast Path（差分更新のみ）
            features = self.feature_updater.update(new_bar)
            return self._fast_predict(features)  # ~5ms
        else:
            # Slow Path（フル再計算）
            features = self._full_recompute(new_bar)
            return self._full_predict(features)  # ~30ms
    
    def _is_incremental_update_valid(self) -> bool:
        """
        キャッシュ無効化条件:
        - データギャップ検出（時刻飛び）
        - スプレッド異常値（10σ超）
        - モデル再ロード直後
        """
        return (
            self._no_data_gap() and
            self._spread_within_normal_range() and
            self._cache_fresh()
        )
```

---

## 📊 計測・監視

### 計測実装

```python
import time

class LatencyTracker:
    """項目62, 108対応: GPU/ONNXウォームアップ測定開始基準明確化"""
    
    def __init__(self):
        self.stage_times = defaultdict(list)
        self.warmup_count = 32  # 最初32回は除外（GPUカーネル初期化対応）
        self.call_count = 0
        self.warmup_completed = False
    
    @contextmanager
    def measure(self, stage_name: str):
        """
        Monotonic time による高精度計測
        
        ウォームアップ基準（項目62, 108）:
        - GPU: 最初32回のforward呼び出しでカーネルコンパイル・キャッシュロード
        - ONNX: 最初32回でORT最適化グラフ生成・メモリアロケーション
        - 初期遅延（初回100ms超）を統計から除外してSLA誤判定防止
        """
        start = time.perf_counter_ns()  # ナノ秒精度
        try:
            yield
        finally:
            elapsed_ms = (time.perf_counter_ns() - start) / 1e6
            self.call_count += 1
            
            # ウォームアップ完了後のみ統計に含める
            if self.call_count > self.warmup_count:
                if not self.warmup_completed:
                    self.warmup_completed = True
                    logger.info(f"ウォームアップ完了: {self.warmup_count}回, 統計計測開始")
                self.stage_times[stage_name].append(elapsed_ms)
            else:
                # ウォームアップ中は統計外（ログのみ）
                if self.call_count <= 3:  # 初回3回のみログ
                    logger.debug(f"ウォームアップ中[{self.call_count}/{self.warmup_count}]: "
                               f"{stage_name}={elapsed_ms:.2f}ms")
    
    def get_percentiles(self, stage_name: str) -> dict:
        """p50, p95, p99, max を算出"""
        times = self.stage_times[stage_name]
        if len(times) == 0:
            logger.warning(f"統計データなし: {stage_name}（ウォームアップ中？）")
            return {"p50": 0, "p95": 0, "p99": 0, "max": 0}
        
        return {
            "p50": np.percentile(times, 50),
            "p95": np.percentile(times, 95),
            "p99": np.percentile(times, 99),
            "max": np.max(times),
            "sample_count": len(times)
        }
    
    def validate_slo(self, stage_name: str, slo_p95_ms: float) -> bool:
        """SLA検証（ウォームアップ完了後のみ）"""
        if not self.warmup_completed:
            return True  # ウォームアップ中は検証スキップ
        
        stats = self.get_percentiles(stage_name)
        return stats["p95"] <= slo_p95_ms


# デプロイwarmup手順
def deployment_warmup(model, device: str, warmup_calls: int = 32):
    """
    デプロイ時のwarmup手順明確化
    
    目的:
    - cold start時のp95悪化防止
    - 初期5分SLA達成保証
    - GPUカーネル・ONNXグラフ事前最適化
    """
    logger.info(f"デプロイwarmup開始: {warmup_calls}回")
    
    # ダミー入力生成（実データ形状と同じ）
    dummy_input = {
        "M1": torch.randn(1, 480, 128).to(device),
        "M5": torch.randn(1, 288, 128).to(device),
        "M15": torch.randn(1, 192, 128).to(device),
        "H1": torch.randn(1, 96, 128).to(device),
        "H4": torch.randn(1, 48, 128).to(device),
    }
    
    model.eval()
    with torch.no_grad():
        for i in range(warmup_calls):
            _ = model(**dummy_input)
            
            if i in [0, 1, 2, warmup_calls//2, warmup_calls-1]:
                logger.debug(f"warmup進行: {i+1}/{warmup_calls}")
    
    # キャッシュプライミング完了
    if device.startswith("cuda"):
        torch.cuda.synchronize()
    
    logger.info("デプロイwarmup完了: 本番統計計測開始")


**ウォームアップ基準仕様（項目62, 108）**:
- **warmup_calls**: 32回（GPU/ONNXカーネル最適化完了に十分）
- **統計除外**: 最初32回のレイテンシは p50/p95/p99 計算から除外
- **SLA検証**: warmup完了後からのみSLO判定開始
- **デプロイ手順**: サービス開始前に必ず `deployment_warmup()` 実行
- **成功指標**: 初期5分（warmup後）のp95 SLA達成率 >= 95%
```

### ログ出力

**注記**: timestampはUTC、ログ表示は日本時間(JST)で出力されます。詳細: [docs/utils/TIMEZONE_UTILS_SPEC.md](../../utils/TIMEZONE_UTILS_SPEC.md)

```python
# 1秒ごとまたは256呼び出しごとにスナップショット
log_snapshot = {
    "timestamp": "2025-10-21T10:30:00Z",
    "timestamp_jst": "2025-10-21 19:30:00 JST",
    "category": "latency",
    "interval_seconds": 1.0,
    "call_count": 256,
    
    "total_latency_ms": {
        "p50": 6.2,
        "p95": 9.8,
        "p99": 15.3,
        "max": 23.1,
        "slo_violations": 2  # p95>10ms の回数
    },
    
    "stage_breakdown_ms": {
        "input_bind": {"p50": 0.4, "p95": 0.7},
        "diff_update": {"p50": 1.3, "p95": 2.1},
        "model_forward": {"p50": 3.8, "p95": 5.5},
        "postprocess": {"p50": 0.5, "p95": 0.9},
        "publish": {"p50": 0.2, "p95": 0.6}
    },
    
    "path_distribution": {
        "fast_path_ratio": 0.94,  # 94%がFast Path
        "slow_path_ratio": 0.06,
        "slow_path_avg_ms": 28.5
    }
}
```

---

## 🚨 アラート・異常検知

### 閾値定義

```yaml
alerts:
  # WARNING: 注意が必要
  warning:
    total_p95_ms: > 12.0
    fast_path_p95_ms: > 10.0
    diff_update_p95_ms: > 3.0
    slow_path_ratio: > 0.15
  
  # CRITICAL: 緊急対応必要
  critical:
    total_p95_ms: > 20.0
    fast_path_p95_ms: > 15.0
    slo_violation_rate: > 0.05  # 5%超がSLO違反
    consecutive_slow_path: > 10  # 連続10回Slow Path
```

### 異常時の対応

```python
class LatencyAnomalyHandler:
    def handle_slo_violation(self, stage: str, actual_ms: float):
        """
        SLO違反時の対応フロー
        """
        if stage == "model_forward" and actual_ms > 15.0:
            # モデル推論が遅い
            self._check_gpu_utilization()
            self._check_model_cache()
            self._log_heavy_sample()
        
        elif stage == "diff_update" and actual_ms > 3.0:
            # 特徴量計算が遅い
            self._profile_feature_calculators()
            self._check_data_anomaly()
        
        # 連続違反でアラート
        if self._consecutive_violations(stage) >= 5:
            self._send_alert(severity="CRITICAL", stage=stage)
```

---

## 🔄 昇格・ロールバック基準

### 新モデル昇格条件（Elevation）

```yaml
elevation_criteria:
  # レイテンシ基準
  latency:
    fast_path_p95_delta: <= +2.0 ms  # 旧モデル比
    total_p95_absolute: < 10.0 ms
    slow_path_ratio_increase: <= +0.05
  
  # 性能基準（併用）
  performance:
    net_expectancy_delta: >= -0.02
    direction_accuracy_delta: >= -0.03
  
  # 連続違反なし
  stability:
    consecutive_slo_violations: < 5
```

### ロールバック条件

```yaml
rollback_triggers:
  # 即座にロールバック
  immediate:
    - total_p95_ms > 25.0 (連続3分)
    - fast_path_p95_ms > 15.0 (連続5分)
    - net_expectancy < baseline - 0.05 (連続3時間)
  
  # 段階的警告
  gradual:
    - total_p95_ms > 15.0 (連続10分) → 警告
    - slo_violation_rate > 0.1 (1時間) → 警告
```

---

## 🎯 Phase別実装計画

### 実装フェーズ1: 基盤構築
- ✅ ステージ別計測実装
- ✅ Fast/Slow Path 分岐
- ✅ 差分前処理（EMA/Welford）
- ✅ ONNX FP16推論
- ✅ ログスナップショット出力

### 実装フェーズ2: 最適化
- ⏳ Attention QK射影削減（d_k=32）
- ⏳ Age-weight テーブル化
- ⏳ GPU warmup最適化
- ⏳ モデル量子化検証（INT8）

### 実装フェーズ3: 監視強化
- ⏳ リアルタイムアラート統合
- ⏳ 自動ロールバック機構
- ⏳ Latency-aware position sizing
- ⏳ デュアルモード別latency分析

---

## 📝 設定例

```yaml
# config/execution_latency_config.yaml

execution:
  latency_tracking:
    enabled: true
    warmup_calls: 32
    snapshot_interval_seconds: 1.0
    snapshot_interval_calls: 256
    log_rotation_hours: 24
  
  slo:
    total_p95_ms: 10.0
    fast_path_p95_ms: 8.0
    slow_path_max_ms: 100.0
  
  optimization:
    use_onnx: true
    precision: fp16
    enable_diff_update: true
    attention_d_k: 32
    cache_validation_interval: 100
  
  alerts:
    warning_threshold_ms: 12.0
    critical_threshold_ms: 20.0
    consecutive_violation_limit: 5
```

---

## 推論最適化

### 差分更新API統一

**目的**: 特徴量計算器ごとにAPI形式が異なり統合困難

**解決策**: 標準インターフェース定義

```python
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional

class DifferentialUpdatable(ABC):
    """差分更新可能な特徴量計算器の基底クラス"""
    
    @abstractmethod
    def initialize_state(self, initial_window: np.ndarray) -> Dict[str, Any]:
        """
        初期状態の構築
        
        Args:
            initial_window: 初期窓データ (window_size, n_features)
        
        Returns:
            state: 状態辞書（次回update_incrementalで使用）
        """
        pass
    
    @abstractmethod
    def update_incremental(
        self,
        state: Dict[str, Any],
        new_tick: np.ndarray
    ) -> tuple[np.ndarray, Dict[str, Any]]:
        """
        差分更新（新着1本のみ処理）
        
        Args:
            state: 前回の状態
            new_tick: 新着データ (n_features,)
        
        Returns:
            (updated_feature, new_state)
        """
        pass
    
    @abstractmethod
    def supports_diff_update(self) -> bool:
        """差分更新対応フラグ"""
        pass


class EMACalculatorDiff(DifferentialUpdatable):
    """EMA差分更新実装例"""
    
    def __init__(self, period: int = 9):
        self.period = period
        self.alpha = 2.0 / (period + 1)
    
    def initialize_state(self, initial_window: np.ndarray) -> Dict[str, Any]:
        """初期EMA計算"""
        ema = initial_window[:, 0].mean()  # 単純平均で初期化
        
        for price in initial_window[:, 0]:
            ema = self.alpha * price + (1 - self.alpha) * ema
        
        return {"ema": ema}
    
    def update_incremental(
        self,
        state: Dict[str, Any],
        new_tick: np.ndarray
    ) -> tuple[np.ndarray, Dict[str, Any]]:
        """差分更新"""
        prev_ema = state["ema"]
        new_price = new_tick[0]
        
        # EMA更新式
        new_ema = self.alpha * new_price + (1 - self.alpha) * prev_ema
        
        return np.array([new_ema]), {"ema": new_ema}
    
    def supports_diff_update(self) -> bool:
        return True


class ATRCalculatorDiff(DifferentialUpdatable):
    """ATR差分更新実装例"""
    
    def __init__(self, period: int = 14):
        self.period = period
        self.alpha = 1.0 / period
    
    def initialize_state(self, initial_window: np.ndarray) -> Dict[str, Any]:
        """初期ATR計算"""
        # True Range計算
        trs = []
        for i in range(1, len(initial_window)):
            high = initial_window[i, 1]
            low = initial_window[i, 2]
            prev_close = initial_window[i-1, 0]
            
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close)
            )
            trs.append(tr)
        
        atr = np.mean(trs[-self.period:])
        
        return {"atr": atr, "prev_close": initial_window[-1, 0]}
    
    def update_incremental(
        self,
        state: Dict[str, Any],
        new_tick: np.ndarray  # [close, high, low]
    ) -> tuple[np.ndarray, Dict[str, Any]]:
        """差分更新"""
        prev_atr = state["atr"]
        prev_close = state["prev_close"]
        
        close, high, low = new_tick[0], new_tick[1], new_tick[2]
        
        # True Range
        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close)
        )
        
        # ATR更新（Wilder's Smoothing）
        new_atr = self.alpha * tr + (1 - self.alpha) * prev_atr
        
        return np.array([new_atr]), {"atr": new_atr, "prev_close": close}
    
    def supports_diff_update(self) -> bool:
        return True


# 統一マネージャー
class DifferentialUpdateManager:
    """差分更新統一管理"""
    
    def __init__(self):
        self.calculators: Dict[str, DifferentialUpdatable] = {}
        self.states: Dict[str, Dict[str, Any]] = {}
    
    def register_calculator(self, name: str, calculator: DifferentialUpdatable):
        """計算器登録"""
        if not calculator.supports_diff_update():
            raise ValueError(f"{name} は差分更新非対応")
        
        self.calculators[name] = calculator
        logger.info(f"差分更新計算器登録: {name}")
    
    def initialize_all(self, initial_data: Dict[str, np.ndarray]):
        """全計算器の初期化"""
        for name, calculator in self.calculators.items():
            if name in initial_data:
                self.states[name] = calculator.initialize_state(initial_data[name])
                logger.info(f"{name} 初期化完了")
    
    def update_all(self, new_data: Dict[str, np.ndarray]) -> Dict[str, np.ndarray]:
        """全計算器の差分更新"""
        results = {}
        
        for name, calculator in self.calculators.items():
            if name in new_data and name in self.states:
                feature, new_state = calculator.update_incremental(
                    self.states[name],
                    new_data[name]
                )
                results[name] = feature
                self.states[name] = new_state
        
        return results


# 使用例
manager = DifferentialUpdateManager()
manager.register_calculator("ema9", EMACalculatorDiff(period=9))
manager.register_calculator("atr14", ATRCalculatorDiff(period=14))

# 初期化
initial_data = {
    "ema9": historical_close[:480],  # M1: 480本
    "atr14": historical_hlc[:480]
}
manager.initialize_all(initial_data)

# 新着tick処理
while True:
    new_tick = get_new_tick()
    new_data = {
        "ema9": new_tick["close"],
        "atr14": np.array([new_tick["close"], new_tick["high"], new_tick["low"]])
    }
    
    features = manager.update_all(new_data)
    # features: {"ema9": [value], "atr14": [value]}
```

**API仕様**:

| メソッド | 引数 | 戻り値 | 計算量 |
|---------|------|--------|--------|
| `initialize_state` | 初期窓データ | 状態辞書 | O(N) |
| `update_incremental` | 状態+新着1本 | (特徴量, 新状態) | O(1) |
| `supports_diff_update` | なし | bool | O(1) |

**KPI（項目23）**:
- API準拠率: ≥80%の差分対応計算器
- 呼び出し成功率: >99.9%
- 統一化によるコード削減: ≥30%

---

### 遅延フォールバック

**目的**: レイテンシ超過時に全量再計算で更に遅延悪化

**解決策**: 軽量モード自動切替

```python
class LatencyFallbackController:
    """レイテンシフォールバック制御"""
    
    def __init__(self, config: dict):
        self.warning_threshold_ms = config.get("warning_threshold_ms", 12.0)
        self.critical_threshold_ms = config.get("critical_threshold_ms", 20.0)
        self.fallback_mode = "normal"  # normal | degraded | emergency
        
        self.latency_history = deque(maxlen=100)
    
    def record_latency(self, latency_ms: float):
        """レイテンシ記録"""
        self.latency_history.append(latency_ms)
        
        # 直近10回の平均
        if len(self.latency_history) >= 10:
            recent_avg = np.mean(list(self.latency_history)[-10:])
            
            if recent_avg > self.critical_threshold_ms:
                self._switch_mode("emergency")
            elif recent_avg > self.warning_threshold_ms:
                self._switch_mode("degraded")
            else:
                self._switch_mode("normal")
    
    def _switch_mode(self, new_mode: str):
        """モード切替"""
        if self.fallback_mode != new_mode:
            logger.warning(f"フォールバックモード切替: {self.fallback_mode} → {new_mode}")
            self.fallback_mode = new_mode
    
    def get_execution_strategy(self) -> Dict[str, Any]:
        """実行戦略取得"""
        if self.fallback_mode == "normal":
            return {
                "use_full_features": True,
                "attention_heads": 4,
                "precision": "fp16",
                "diff_update": True
            }
        elif self.fallback_mode == "degraded":
            return {
                "use_full_features": True,
                "attention_heads": 2,  # 削減
                "precision": "fp16",
                "diff_update": True
            }
        else:  # emergency
            return {
                "use_full_features": False,  # 特徴量削減
                "attention_heads": 1,
                "precision": "fp16",
                "diff_update": False  # 全量再計算も停止
            }


# 使用例
fallback_ctrl = LatencyFallbackController({
    "warning_threshold_ms": 12.0,
    "critical_threshold_ms": 20.0
})

# 推論ループ
while True:
    start = time.perf_counter()
    
    # 実行戦略取得
    strategy = fallback_ctrl.get_execution_strategy()
    
    # 戦略に基づいて推論
    if strategy["use_full_features"]:
        features = compute_all_features(new_tick)
    else:
        features = compute_minimal_features(new_tick)  # 10列のみ
    
    prediction = model.predict(features, **strategy)
    
    # レイテンシ記録
    latency_ms = (time.perf_counter() - start) * 1000
    fallback_ctrl.record_latency(latency_ms)
    
    logger.info(f"レイテンシ={latency_ms:.2f}ms, モード={fallback_ctrl.fallback_mode}")
```

**フォールバックレベル**:

| Mode | 特徴量 | Attention Heads | 期待レイテンシ | 精度劣化 |
|------|--------|----------------|---------------|---------|
| normal | 全列（50-80） | 4 | <10ms | 0% |
| degraded | 全列 | 2 | <15ms | <2% |
| emergency | 10列のみ | 1 | <5ms | <5% |

**KPI（項目24）**:
- degraded移行頻度: <5%
- emergency移行頻度: <1%
- フォールバック中の精度: >92%（normal=95%基準）

---

### 異常時軽量パス

**目的**: エラー時に推論停止はトレード機会損失

**解決策**: Degraded Mode設計

```python
class DegradedModeExecutor:
    """縮退モード実行"""
    
    def __init__(self, config: dict):
        self.minimal_features = config.get(
            "minimal_features",
            ["m1_close_return", "m5_close_return", "atr_14",
             "ema_9", "ema_21", "rsi_14", "m1_m5_close_diff",
             "spread_ema5", "volume_zscore", "direction_flip_rate"]
        )
        self.fallback_model_path = config.get("fallback_model_path", None)
    
    def detect_anomaly(self, error: Exception) -> str:
        """異常検出"""
        if isinstance(error, MemoryError):
            return "memory_exhausted"
        elif isinstance(error, TimeoutError):
            return "latency_exceeded"
        elif "NaN" in str(error):
            return "feature_corruption"
        else:
            return "unknown_error"
    
    def execute_degraded(
        self,
        anomaly_type: str,
        available_features: Dict[str, float]
    ) -> Dict[str, Any]:
        """縮退実行"""
        logger.warning(f"縮退モード実行: {anomaly_type}")
        
        # 最小特徴量抽出
        minimal_vector = []
        for feat in self.minimal_features:
            if feat in available_features:
                minimal_vector.append(available_features[feat])
            else:
                minimal_vector.append(0.0)  # 欠損は0埋め
        
        minimal_vector = np.array(minimal_vector).reshape(1, -1)
        
        # シンプルルールベース判定（モデル不使用）
        if anomaly_type == "memory_exhausted":
            # ルールベース: EMA クロスオーバー
            if len(minimal_vector[0]) >= 5:
                ema9, ema21 = minimal_vector[0][3], minimal_vector[0][4]
                direction = "UP" if ema9 > ema21 else "DOWN"
            else:
                direction = "NEUTRAL"
            
            return {
                "direction": direction,
                "confidence": 0.5,  # 低信頼度
                "mode": "degraded_rule_based"
            }
        
        elif anomaly_type == "latency_exceeded":
            # 前回予測を返す（キャッシュ）
            return {
                "direction": getattr(self, "last_prediction", "NEUTRAL"),
                "confidence": 0.3,
                "mode": "degraded_cached"
            }
        
        else:
            # デフォルト: NEUTRAL
            return {
                "direction": "NEUTRAL",
                "confidence": 0.0,
                "mode": "degraded_safe"
            }


# 使用例
degraded_executor = DegradedModeExecutor({
    "minimal_features": ["m1_close_return", "ema_9", "ema_21", "rsi_14"],
    "fallback_model_path": None
})

# 推論ループ
try:
    features = compute_full_features(new_tick)
    prediction = model.predict(features)
except Exception as e:
    # 異常検出
    anomaly_type = degraded_executor.detect_anomaly(e)
    
    # 縮退実行
    available_features = compute_available_features(new_tick)
    prediction = degraded_executor.execute_degraded(anomaly_type, available_features)
    
    logger.error(f"異常発生: {anomaly_type}, 縮退モードで継続")
```

**Degraded Mode戦略**:

| 異常タイプ | 対応 | 信頼度 | SLA |
|-----------|------|--------|-----|
| memory_exhausted | ルールベース判定 | 0.5 | <3ms |
| latency_exceeded | 前回予測キャッシュ | 0.3 | <1ms |
| feature_corruption | NEUTRAL返却 | 0.0 | <1ms |

**KPI（項目31）**:
- 縮退発動頻度: <1%
- 縮退中の信頼度: ≥0.3（トレード続行可能）
- 縮退レイテンシ: <5ms

---

### Fast/Slow Path理由分類

**目的**: 遅延発生理由が不明で改善困難

**解決策**: パス選択理由のログ記録

```python
class PathReasonLogger:
    """パス選択理由ロギング"""
    
    # 理由コード定義
    REASON_CODES = {
        # Fast Path理由
        "FAST_DIFF_UPDATE": "差分更新成功",
        "FAST_CACHE_HIT": "キャッシュヒット",
        "FAST_MINIMAL_FEATURES": "最小特徴量モード",
        
        # Slow Path理由
        "SLOW_CACHE_MISS": "キャッシュミス（初回・リセット）",
        "SLOW_FULL_RECOMPUTE": "全量再計算必須",
        "SLOW_FEATURE_CORRUPTION": "特徴量破損検出",
        "SLOW_STATE_INCONSISTENT": "状態不整合",
        "SLOW_DRIFT_DETECTED": "ドリフト検出",
        
        # Emergency理由
        "EMERGENCY_LATENCY": "レイテンシ超過",
        "EMERGENCY_MEMORY": "メモリ不足",
        "EMERGENCY_ERROR": "予期せぬエラー"
    }
    
    def __init__(self):
        self.path_stats = {code: 0 for code in self.REASON_CODES.keys()}
    
    def log_path(self, reason_code: str, latency_ms: float, details: str = ""):
        """パス記録"""
        if reason_code not in self.REASON_CODES:
            logger.warning(f"不明な理由コード: {reason_code}")
            return
        
        self.path_stats[reason_code] += 1
        
        logger.debug(
            f"Path={reason_code}, "
            f"理由={self.REASON_CODES[reason_code]}, "
            f"レイテンシ={latency_ms:.2f}ms, "
            f"詳細={details}"
        )
    
    def get_summary(self) -> Dict[str, Any]:
        """統計サマリ"""
        total = sum(self.path_stats.values())
        
        summary = {
            "total_calls": total,
            "fast_path_ratio": sum(
                self.path_stats[k] for k in self.path_stats if k.startswith("FAST")
            ) / total * 100 if total > 0 else 0,
            "slow_path_ratio": sum(
                self.path_stats[k] for k in self.path_stats if k.startswith("SLOW")
            ) / total * 100 if total > 0 else 0,
            "emergency_ratio": sum(
                self.path_stats[k] for k in self.path_stats if k.startswith("EMERGENCY")
            ) / total * 100 if total > 0 else 0,
            "breakdown": self.path_stats
        }
        
        return summary


# 使用例
path_logger = PathReasonLogger()

# 推論ループ
while True:
    start = time.perf_counter()
    
    try:
        if can_use_diff_update():
            prediction = predict_with_diff_update(new_tick)
            reason = "FAST_DIFF_UPDATE"
        else:
            prediction = predict_full_recompute(new_tick)
            reason = "SLOW_FULL_RECOMPUTE"
    except MemoryError:
        prediction = fallback_predict()
        reason = "EMERGENCY_MEMORY"
    
    latency_ms = (time.perf_counter() - start) * 1000
    path_logger.log_path(reason, latency_ms)

# 定期サマリ
summary = path_logger.get_summary()
logger.info(f"Fast Path率: {summary['fast_path_ratio']:.1f}%")
logger.info(f"Slow Path率: {summary['slow_path_ratio']:.1f}%")
logger.info(f"Emergency率: {summary['emergency_ratio']:.1f}%")
```

**理由コード分類**:

| カテゴリ | コード数 | 期待比率 |
|---------|---------|---------|
| FAST_* | 3 | >90% |
| SLOW_* | 5 | <10% |
| EMERGENCY_* | 3 | <1% |

**KPI（項目60）**:
- Fast Path率: ≥90%
- ログ粒度: デバッグレベルで全記録
- サマリ出力: 1時間毎

---

## 🔗 関連仕様

- `README.md` - デュアルモード戦略概要
- `TRAINER_SPEC.md` - モデルアーキテクチャ詳細
- `PREPROCESSOR_SPEC.md` - 特徴量計算仕様
- `LOGGING_OPERATIONS_SPEC.md` - ログ統合仕様
- `LIFECYCLE_ROLLING_RETRAIN_SPEC.md` - モデル昇格・ロールバック

---

## 📚 参考資料

### レイテンシ最適化
- ONNX Runtime Performance Tuning: https://onnxruntime.ai/docs/performance/
- PyTorch JIT Script: https://pytorch.org/docs/stable/jit.html
- CUDA Graph Optimization: https://developer.nvidia.com/blog/cuda-graphs/

### リアルタイム推論
- Welford's Online Algorithm: https://en.wikipedia.org/wiki/Algorithms_for_calculating_variance
- Ring Buffer Implementation: https://en.wikipedia.org/wiki/Circular_buffer
- Low-Latency Trading Systems: "Trading and Exchanges" by Larry Harris

---

**更新履歴**:
- 2025-10-21: 初版作成（デュアルモード戦略対応、Phase 1仕様確定）
