# INVARIANCE_SPEC.md

**バージョン**: 1.0  
**更新日**: 2025-10-22  
**責任者**: core-team

---

## 📋 目的

スケール不変性検証とオンライン監視の仕様を定義する。

---

## 不変性パラメータ調整

### λ_inv自動調整

**目的**: 固定λ_invは市場regime変化で不適切

**解決策**: retention指標ベース自動調整

```python
class InvarianceLambdaOptimizer:
    """λ_inv自動調整"""
    
    def __init__(self, config: dict):
        self.target_retention = config.get("target_retention", 0.95)
        self.adjustment_rate = config.get("adjustment_rate", 0.1)
        self.min_lambda = config.get("min_lambda", 0.01)
        self.max_lambda = config.get("max_lambda", 1.0)
        
        self.current_lambda = config.get("initial_lambda", 0.1)
    
    def update_lambda(self, retention_ratio: float) -> float:
        """
        λ_inv更新
        
        Args:
            retention_ratio: 不変性テスト保持率（0-1）
        
        Returns:
            new_lambda: 更新後のλ_inv
        """
        # retention低い → λ増加（不変性ペナルティ強化）
        if retention_ratio < self.target_retention:
            delta = self.adjustment_rate * (self.target_retention - retention_ratio)
            new_lambda = self.current_lambda + delta
        else:
            # retention高すぎ → λ減少（過剰制約緩和）
            delta = self.adjustment_rate * (retention_ratio - self.target_retention) * 0.5
            new_lambda = self.current_lambda - delta
        
        new_lambda = np.clip(new_lambda, self.min_lambda, self.max_lambda)
        
        if abs(new_lambda - self.current_lambda) > 0.01:
            logger.info(f"λ_inv調整: {self.current_lambda:.3f} → {new_lambda:.3f}")
        
        self.current_lambda = new_lambda
        return new_lambda


# 使用例
optimizer = InvarianceLambdaOptimizer({
    "target_retention": 0.95,
    "adjustment_rate": 0.1,
    "initial_lambda": 0.1
})

# 学習ループ内
for epoch in range(num_epochs):
    # 不変性テスト実行
    retention = test_invariance(model, test_data)
    
    # λ更新
    new_lambda = optimizer.update_lambda(retention)
    
    # 損失関数へ反映
    loss = task_loss + new_lambda * invariance_loss
```

**調整ロジック**:
- retention < 0.95 → λ増加（不変性強化）
- retention > 0.95 → λ減少（制約緩和）

**KPI（項目33）**: retention維持率95±2%、λ調整による精度改善+1%

---

## スケール不変性評価閾値集約定義

**目的**: 文書間で散在している不変性評価閾値を一元管理し、検証基準を統一する。

### 1. 保持率（Retention）閾値

| 指標 | 閾値 | 意味 | 参照元 |
|-----|------|------|--------|
| **target_retention** | `0.95` (95%) | λ_inv自動調整の目標保持率 | INVARIANCE_SPEC.md L28 |
| **retention_tolerance** | `±2%` | 許容範囲（93%-97%） | INVARIANCE_SPEC.md L86 |
| **λ_inv調整トリガー** | `±1%` | 保持率が94%未満 or 96%超でλ調整 | INVARIANCE_SPEC.md L83-84 |

**計算方法**:
```python
retention_ratio = (
    len(samples_passing_invariance_test) /
    len(total_samples)
)
```

**判定ロジック**:
- `retention < 0.94` → λ_inv増加（不変性ペナルティ強化）
- `0.94 ≤ retention ≤ 0.96` → λ_inv維持
- `retention > 0.96` → λ_inv減少（過剰制約緩和）

### 2. 相関係数閾値

| 指標 | 閾値 | 意味 | 参照元 |
|-----|------|------|--------|
| **Spearman ρ (順位相関)** | `> 0.90` | 期待値decile vs 実測順位の単調性検証 | DRIFT_CALIBRATION_MONITORING_SPEC.md L36 |
| **特徴量相関除外** | `abs(ρ) > 0.95` | 高相関ペア除外（冗長性削減） | PREPROCESSOR_SPEC.md L40, L94 |

**Spearman ρ判定ロジック**:
```python
if spearman_rho < 0.90:
    logger.warning(f"単調性低下検出: ρ={spearman_rho:.3f} < 0.90")
    # キャリブレーション再実施を推奨
```

### 3. パフォーマンス劣化閾値

| 指標 | 閾値 | 意味 | 参照元 |
|-----|------|------|--------|
| **NetExpectancy変化率** | `< 5%` | スケール変換後の期待値変動許容範囲 | *(暗黙的基準、本文書で定義)* |
| **ONNX精度劣化** | `< 1.5%` | PyTorch→ONNX変換時の精度低下許容 | ONNX_CONVERTER_SPEC.md L1268, L1380 |
| **NaN比率** | `< 5%` | 特徴量計算時の欠損値許容上限 | README.md L510 |

**NetExpectancy変化率計算**:
```python
def compute_expectancy_degradation(
    net_expectancy_original: float,
    net_expectancy_scaled: float
) -> float:
    """
    スケール変換前後のNetExpectancy変化率

    Args:
        net_expectancy_original: 元の期待値（例: USDJPY 100倍スケール）
        net_expectancy_scaled: スケール変換後の期待値（例: EURUSD 10000倍スケール）

    Returns:
        degradation_pct: 変化率（%）

    許容範囲:
        < 5% → 合格（スケール不変性保持）
        >= 5% → 不合格（スケール依存性検出）
    """
    if net_expectancy_original == 0:
        return 100.0  # 元が0なら比較不可

    degradation_pct = abs(
        (net_expectancy_scaled - net_expectancy_original) /
        net_expectancy_original
    ) * 100

    return degradation_pct

# 使用例
degradation = compute_expectancy_degradation(
    net_expectancy_original=1.2,  # USDJPY (×100)
    net_expectancy_scaled=1.15    # EURUSD (×10000) 換算後
)

if degradation >= 5.0:
    logger.error(f"NetExpectancy劣化検出: {degradation:.2f}% >= 5%")
    raise ValueError("スケール不変性違反")
```

### 4. λ_inv（不変性ペナルティ重み）範囲

| パラメータ | デフォルト値 | 範囲 | 意味 | 参照元 |
|-----------|------------|------|------|--------|
| **initial_lambda** | `0.1` | - | 初期λ_inv値 | INVARIANCE_SPEC.md L66 |
| **min_lambda** | `0.01` | 下限 | 過度な緩和防止 | INVARIANCE_SPEC.md L30 |
| **max_lambda** | `1.0` | 上限 | タスク損失無視防止 | INVARIANCE_SPEC.md L31 |
| **adjustment_rate** | `0.1` | 調整速度 | 1エポックあたりの変化量上限 | INVARIANCE_SPEC.md L29 |
| **adjustment_threshold** | `0.01` | ログ出力閾値 | λ変化がこれ以上でログ記録 | INVARIANCE_SPEC.md L56 |

### 5. 統合評価フローチャート

```
スケール不変性検証フロー:

1. Retention Test
   ├─ retention < 0.94 → ❌ 不変性不足
   ├─ 0.94 ≤ retention ≤ 0.96 → ✅ 合格
   └─ retention > 0.96 → ⚠️  過剰制約（λ減少推奨）

2. NetExpectancy Degradation Test
   ├─ degradation < 5% → ✅ 合格
   └─ degradation >= 5% → ❌ スケール依存性検出

3. Spearman Monotonicity Test
   ├─ ρ > 0.90 → ✅ 合格
   └─ ρ ≤ 0.90 → ⚠️  キャリブレーション推奨

4. ONNX Conversion Test
   ├─ accuracy_degradation < 1.5% → ✅ 合格
   └─ accuracy_degradation >= 1.5% → ❌ 変換精度不足

総合判定:
  全て✅ → スケール不変性確認
  ❌が1つ以上 → 設計見直し必要
```

### 6. 実装例

```python
class InvarianceValidator:
    """スケール不変性検証の統合クラス"""

    # 閾値定数（本セクションで定義）
    RETENTION_TARGET = 0.95
    RETENTION_TOLERANCE = 0.02
    NETEXPECTANCY_DEGRADATION_THRESHOLD = 5.0  # %
    SPEARMAN_THRESHOLD = 0.90
    ONNX_DEGRADATION_THRESHOLD = 1.5  # %
    NAN_RATIO_THRESHOLD = 0.05

    def validate_all(
        self,
        retention: float,
        net_exp_degradation: float,
        spearman_rho: float,
        onnx_degradation: float,
        nan_ratio: float
    ) -> Dict[str, bool]:
        """
        全閾値を統合検証

        Returns:
            {
                'retention_ok': bool,
                'netexp_ok': bool,
                'spearman_ok': bool,
                'onnx_ok': bool,
                'nan_ok': bool,
                'all_passed': bool
            }
        """
        results = {
            'retention_ok': (
                self.RETENTION_TARGET - self.RETENTION_TOLERANCE <= retention <=
                self.RETENTION_TARGET + self.RETENTION_TOLERANCE
            ),
            'netexp_ok': net_exp_degradation < self.NETEXPECTANCY_DEGRADATION_THRESHOLD,
            'spearman_ok': spearman_rho > self.SPEARMAN_THRESHOLD,
            'onnx_ok': onnx_degradation < self.ONNX_DEGRADATION_THRESHOLD,
            'nan_ok': nan_ratio < self.NAN_RATIO_THRESHOLD
        }

        results['all_passed'] = all(results.values())

        return results
```

---

## 🔗 参照

- **親仕様書**: `docs/VALIDATOR_SPEC.md`
- **学習**: `docs/TRAINER_SPEC.md`
