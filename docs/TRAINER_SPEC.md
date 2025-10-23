# TRAINER_SPEC.md

**バージョン**: 1.0
**更新日**: 2025-10-21
**責任者**: core-team
**処理段階**: 第4段階: 学習

---

## 📋 目的

`src/trainer.py` によるマルチタイムフレーム・マルチタスク学習の実装仕様を定義する。

---

## 🎯 入力契約

```
features: Tensor[batch, time, channels]  # マルチTF統合済み
time: 正規化後の固定長（例: N=64）
aux_tf_streams: {M1, M5, M15, H1, H4} (オプション)
```

---

## 🏗️ モデルアーキテクチャ

### 基本構造（デュアルモード対応）

```
入力: マルチTF特徴量（M1/M5/M15/H1/H4）

    ┌──────────┐
    │ M1 LSTM  │────┐  weight: 0.35 (エントリータイミング)
    ├──────────┤    │
    │ M5 LSTM  │────┤  weight: 0.30 (短期トレンド)
    ├──────────┤    │
    │ M15 LSTM │────┤──→ Fusion (Attention) ──┬→ Direction Head
    ├──────────┤    │                          ├→ Magnitude_Scalp Head
    │ H1 LSTM  │────┤  weight: 0.10 (大局)     ├→ Magnitude_Swing Head
    ├──────────┤    │                          └→ Trend_Strength Head
    │ H4 LSTM  │────┘  weight: 0.05 (レジーム)
    └──────────┘

出力（マルチヘッド）:
- Direction: [UP, DOWN, NEUTRAL] 確率分布
- Magnitude_Scalp: 短期価格幅 (0.5-2.0pips未満, 1時間以内)
- Magnitude_Swing: 延長価格幅 (2.0pips以上-5.0pips, トレール時)
- Trend_Strength: トレンド強度 (0-1, H1/H4ベース)

**ラベル境界条件**:
```python
# 価格幅実測値から適切なラベル割り当て
def assign_magnitude_label(actual_magnitude_pips: float, trend_strength: float) -> Dict[str, float]:
    """
    Scalp/Swing境界での一貫したラベル割り当て

    境界条件:
    - actual_magnitude < 2.0 pips: Scalpラベルのみ生成、Swingラベルは None
    - actual_magnitude >= 2.0 pips: Swingラベルのみ生成、Scalpラベルは None
    - trend_strength は参照しない（実測値のみで判定）

    Returns:
        {
            'magnitude_scalp': float or None,
            'magnitude_swing': float or None
        }
    """
    if actual_magnitude_pips < 2.0:
        return {
            'magnitude_scalp': actual_magnitude_pips,
            'magnitude_swing': None  # 学習時にマスク
        }
    else:  # >= 2.0 pips
        return {
            'magnitude_scalp': None,  # 学習時にマスク
            'magnitude_swing': actual_magnitude_pips
        }
```

**学習時のマスク処理**:
```python
# None ラベルは損失計算から除外
def compute_masked_loss(pred, target, mask):
    """
    有効なラベルのみで損失計算

    Args:
        pred: 予測値 [batch_size]
        target: 正解値 [batch_size]（Noneは0.0に変換済み）
        mask: 有効フラグ [batch_size]（False=除外）
    """
    valid_pred = pred[mask]
    valid_target = target[mask]

    if len(valid_target) == 0:
        return torch.tensor(0.0)  # 有効サンプルなし

    return F.huber_loss(valid_pred, valid_target, delta=0.3)

# 使用例
loss_scalp = compute_masked_loss(
    pred_magnitude_scalp,
    target_magnitude_scalp,
    mask_scalp  # actual_magnitude < 2.0 のサンプル
)

loss_swing = compute_masked_loss(
    pred_magnitude_swing,
    target_magnitude_swing,
    mask_swing  # actual_magnitude >= 2.0 のサンプル
)
```

**注記**:
- 境界値 `2.0 pips` はSwing側に含める（`>=` 判定）
- 両ヘッドは常に予測を出力するが、学習時は該当範囲のみで損失計算
- 推論時は `trend_strength` でどちらの予測を使うか判定（学習は実測値ベース）
```

### モード切替ロジック

```python
# 基本モード判定（70-80%のトレード）
if trend_strength < 0.7:
    mode = "scalp"
    primary_tf_weight = [0.35, 0.30, 0.20, 0.10, 0.05]  # M1優先
    target_magnitude = magnitude_scalp
    exit_strategy = "fixed_tp_sl"
    # 動的TP/SL（DYNAMIC_EXIT_SPEC.md参照）
    tp_base = 0.8 pips  # 固定倍率（ATR×0.8）は廃止
    sl_base = 0.5 pips

# 拡張モード判定（20-30%のトレード）
else:  # trend_strength >= 0.7
    mode = "swing_trail"
    primary_tf_weight = [0.20, 0.20, 0.25, 0.20, 0.15]  # H1/H4重視
    target_magnitude = magnitude_swing
    exit_strategy = "trailing_stop"
    trail_activation = +0.8 pips
    trail_distance = 0.3 pips
```

#### モード切替ヒステリシス

**目的**: 閾値（0.7）付近での頻繁なモード切替による性能劣化（churn）を抑制する。

```python
class ModeStateMachine:
    """
    モード切替のヒステリシス実装

    ヒステリシス幅により、頻繁な切替を抑制
    """

    def __init__(
        self,
        enter_swing_threshold: float = 0.7,
        exit_swing_threshold: float = 0.6
    ):
        """
        Args:
            enter_swing_threshold: Swing モード進入閾値
            exit_swing_threshold: Swing モード退出閾値
        """
        self.enter_swing_thr = enter_swing_threshold
        self.exit_swing_thr = exit_swing_threshold
        self.current_mode = "scalp"  # 初期モード

    def update(self, trend_strength: float) -> str:
        """
        モード更新（ヒステリシス適用）

        Args:
            trend_strength: 現在のトレンド強度 [0, 1]

        Returns:
            str: 'scalp' または 'swing_trail'
        """
        if self.current_mode == "scalp":
            # Scalp → Swing 遷移: 高い閾値
            if trend_strength >= self.enter_swing_thr:
                self.current_mode = "swing_trail"
                logger.info(f"Mode switch: scalp → swing (strength={trend_strength:.3f})")

        elif self.current_mode == "swing_trail":
            # Swing → Scalp 遷移: 低い閾値
            if trend_strength < self.exit_swing_thr:
                self.current_mode = "scalp"
                logger.info(f"Mode switch: swing → scalp (strength={trend_strength:.3f})")

        return self.current_mode

    def get_mode_config(self) -> Dict[str, Any]:
        """現在のモード設定を取得"""
        if self.current_mode == "scalp":
            return {
                'mode': 'scalp',
                'tf_weights': [0.35, 0.30, 0.20, 0.10, 0.05],
                'magnitude_head': 'magnitude_scalp',
                'exit_strategy': 'fixed_tp_sl'
            }
        else:  # swing_trail
            return {
                'mode': 'swing_trail',
                'tf_weights': [0.20, 0.20, 0.25, 0.20, 0.15],
                'magnitude_head': 'magnitude_swing',
                'exit_strategy': 'trailing_stop'
            }


# 使用例
mode_fsm = ModeStateMachine(
    enter_swing_threshold=0.7,
    exit_swing_threshold=0.6
)

# 推論時
for signal in signals:
    trend_strength = model.predict(signal)['trend_strength']

    # モード更新（ヒステリシス適用）
    current_mode = mode_fsm.update(trend_strength)
    config = mode_fsm.get_mode_config()

    # モード別処理
    if current_mode == "scalp":
        magnitude = model.predict(signal)['magnitude_scalp']
    else:
        magnitude = model.predict(signal)['magnitude_swing']
```

**ヒステリシス幅の選択**:
```python
# 推奨設定
default_config = {
    'enter_swing_threshold': 0.7,   # Swing進入
    'exit_swing_threshold': 0.6,    # Swing退出
    'hysteresis_width': 0.1         # 幅 = 0.7 - 0.6
}

# 調整指針
# - 幅が大きい（例: 0.15）: 切替頻度↓、モード固定傾向↑
# - 幅が小さい（例: 0.05）: 切替頻度↑、市場追従性↑
```

**成功指標**:
- モード切替頻度: ベースライン比で30%減少
- 切替時の期待値劣化 < 5%
- 不要な切替（10バー以内の往復）< 3%

**検証**:
```python
def test_mode_hysteresis():
    """ヒステリシスの動作検証"""
    fsm = ModeStateMachine(enter_swing_thr=0.7, exit_swing_thr=0.6)

    # Scalp → Swing 遷移
    assert fsm.update(0.65) == "scalp"  # まだScalp
    assert fsm.update(0.69) == "scalp"  # まだScalp
    assert fsm.update(0.71) == "swing_trail"  # 遷移

    # Swing → Scalp 遷移（低い閾値）
    assert fsm.update(0.65) == "swing_trail"  # まだSwing
    assert fsm.update(0.61) == "swing_trail"  # まだSwing
    assert fsm.update(0.59) == "scalp"  # 遷移

    # チャタリング防止確認
    # 0.65付近の往復でも切替しない
    fsm = ModeStateMachine(enter_swing_thr=0.7, exit_swing_thr=0.6)
    modes = [fsm.update(s) for s in [0.65, 0.66, 0.65, 0.64, 0.65]]
    assert all(m == "scalp" for m in modes), "不要な切替発生"
```

### コンポーネント詳細

#### 1. TFエンコーダ
- 各TF用LSTM（hidden=128）
- 最終隠れ状態を時系列拡張（長さN揃え）

#### 2. Fusion層
- Attention機構でTF間を統合
- Query: 最新K本の平均ベクトル
- Keys/Values: 全タイムステップ

**詳細**: [MULTI_TF_FUSION_SPEC.md](trainer/MULTI_TF_FUSION_SPEC.md) を参照
- 各TFのシーケンス長定義（最大公約数的固定窓）
- LSTM + Self-Attention設計（動的パターン抽出）
- Cross-TF Attention実装詳細

#### 3. 出力ヘッド（デュアルモード対応）
- **Direction Head**: 3クラス分類（UP/DOWN/NEUTRAL）
- **Magnitude_Scalp Head**: 回帰（0.5-2.0 pips、固定TP/SL用）
- **Magnitude_Swing Head**: 回帰（2.0-5.0 pips、トレール延長用）
- **Trend_Strength Head**: 回帰（0-1、H1/H4トレンド持続性）

---

## 📊 マルチタスク損失関数（デュアルモード対応）

```python
L_total = α × L_direction + β × L_magnitude_scalp + γ × L_magnitude_swing + δ × L_trend_strength

# Direction: CrossEntropy
L_direction = CE(pred_direction, true_direction)

# Magnitude_Scalp: Huber Loss（外れ値耐性、0.5-2.0 pips）
L_magnitude_scalp = HuberLoss(pred_scalp, true_scalp, delta=0.3)

# Magnitude_Swing: Huber Loss（2.0-5.0 pips）
L_magnitude_swing = HuberLoss(pred_swing, true_swing, delta=0.5)

# Trend_Strength: MSE（0-1）
L_trend_strength = MSE(pred_trend, true_trend)

# 重み（初期値）
α = 0.40  # 方向（最重要）
β = 0.35  # スキャルピング価格幅
γ = 0.15  # スイング延長価格幅
δ = 0.10  # トレンド強度
```

### 動的重み調整

```python
# バッチ内のtrend_strengthに応じて動的調整
def compute_loss_weights(trend_strength_batch):
    scalp_ratio = (trend_strength_batch < 0.7).float().mean()
    swing_ratio = 1.0 - scalp_ratio

    # β, γを動的調整（α, δは固定）
    β_dynamic = 0.35 * (scalp_ratio / 0.75)  # 基準75%で正規化
    γ_dynamic = 0.15 * (swing_ratio / 0.25)  # 基準25%で正規化

    return {
        'alpha': 0.40,
        'beta': β_dynamic,
        'gamma': γ_dynamic,
        'delta': 0.10
    }
```

#### 動的損失重みの正規化

**目的**: 重み合計の膨張によるoptimizer実効学習率の変調と収束震え（oscillation）を防止する。

**実装**: Σw=1 正規化 + 個別clamp [0.02, 3.0] + drift検出

```python
def normalize_loss_weights(weights: Dict[str, float]) -> Dict[str, float]:
    """
    損失重みの正規化と制約

    Args:
        weights: {'alpha': 0.4, 'beta': 0.35, 'gamma': 0.15, 'delta': 0.1}

    Returns:
        正規化された重み（合計=1.0、個別clamp適用済み）
    """
    # 個別clamp [0.02, 3.0]
    clamped = {
        key: np.clip(val, 0.02, 3.0)
        for key, val in weights.items()
    }

    # 総和正規化（Σw = 1.0）
    total = sum(clamped.values())
    normalized = {
        key: val / total
        for key, val in clamped.items()
    }

    return normalized


class LossWeightDriftDetector:
    """重み変動の監視"""

    def __init__(self, window_size: int = 100):
        self.window_size = window_size
        self.history = {
            'alpha': [],
            'beta': [],
            'gamma': [],
            'delta': []
        }

    def update(self, weights: Dict[str, float]):
        """重み履歴を更新"""
        for key, val in weights.items():
            self.history[key].append(val)
            if len(self.history[key]) > self.window_size:
                self.history[key].pop(0)

    def check_drift(self, cv_threshold: float = 0.25) -> Dict[str, bool]:
        """
        変動係数（CV）による drift 検出

        Args:
            cv_threshold: CV閾値（デフォルト: 0.25）

        Returns:
            各重みのdrift有無（True=警告）
        """
        drift_flags = {}

        for key, values in self.history.items():
            if len(values) < 10:  # 最小サンプル数
                drift_flags[key] = False
                continue

            mean = np.mean(values)
            std = np.std(values)
            cv = std / mean if mean > 0 else 0

            drift_flags[key] = cv > cv_threshold

        return drift_flags


# トレーニングループ内での使用
drift_detector = LossWeightDriftDetector(window_size=100)

for epoch in range(num_epochs):
    for batch in dataloader:
        # 動的重み計算
        raw_weights = compute_loss_weights(batch['trend_strength'])

        # 正規化 + clamp
        weights = normalize_loss_weights(raw_weights)

        # 損失計算
        loss_total = (
            weights['alpha'] * loss_direction +
            weights['beta'] * loss_magnitude_scalp +
            weights['gamma'] * loss_magnitude_swing +
            weights['delta'] * loss_trend_strength
        )

        # Drift監視
        drift_detector.update(weights)
        drift_flags = drift_detector.check_drift(cv_threshold=0.25)

        if any(drift_flags.values()):
            logger.warning(f"Loss weight drift detected: {drift_flags}")

        # 逆伝播
        optimizer.zero_grad()
        loss_total.backward()
        optimizer.step()
```

**成功指標**:
- 主要head勾配ノルム安定性: CV < 0.2
- 重み総和不変: Σw = 1.0 ± 1e-6
- Drift警告頻度 < 5% of batches

**検証**:
```python
def test_weight_normalization():
    """重み正規化の検証"""
    raw_weights = {'alpha': 0.5, 'beta': 4.0, 'gamma': 0.01, 'delta': 0.2}

    normalized = normalize_loss_weights(raw_weights)

    # 合計=1.0
    assert abs(sum(normalized.values()) - 1.0) < 1e-6

    # 個別clamp確認
    assert all(0.02 <= v <= 3.0 for v in normalized.values())
```

---

## 📊 データ分割戦略

時系列データの特性を考慮した分割方法を定義。

### 基本方針

**時系列順序を厳守**: 未来データのリークを防ぐため、Train/Val/Testは時系列順に分割。

```
時系列順序:
├─ Train   (60%): 2024-01-01 ~ 2024-07-10
├─ Val     (20%): 2024-07-11 ~ 2024-09-05
└─ Test    (20%): 2024-09-06 ~ 2024-10-31
```

### 分割比率

| データセット | 比率 | 期間（例） | 用途 |
|-------------|-----|-----------|------|
| Train | 60% | 約6ヶ月 | モデル学習・パラメータ更新 |
| Validation | 20% | 約2ヶ月 | ハイパーパラメータ調整・早期停止判定 |
| Test | 20% | 約2ヶ月 | 最終性能評価・バックテスト |

### 実装詳細

```python
def split_timeseries_data(data_h5_path: str) -> Dict[str, np.ndarray]:
    """
    時系列順序を保持したデータ分割

    Args:
        data_h5_path: 前処理済みHDF5ファイルパス

    Returns:
        {'train': (N_train, seq, feat),
         'val': (N_val, seq, feat),
         'test': (N_test, seq, feat)}
    """
    with h5py.File(data_h5_path, 'r') as f:
        sequences = f['sequences'][:]
        timestamps = f['timestamps'][:]

    # 時系列順にソート済み想定（前処理段階で保証）
    assert np.all(timestamps[:-1] <= timestamps[1:]), "時系列順序違反"

    N = len(sequences)
    train_end = int(N * 0.60)
    val_end = int(N * 0.80)

    return {
        'train': sequences[:train_end],
        'val': sequences[train_end:val_end],
        'test': sequences[val_end:]
    }
```

### ローリングウィンドウ分割（Phase 3実装予定）

定期的な再学習のため、ローリングウィンドウ方式を採用：

```
ウィンドウ1: Train[1-6月] → Val[7-8月] → Test[9-10月]
ウィンドウ2: Train[2-7月] → Val[8-9月] → Test[10-11月]
ウィンドウ3: Train[3-8月] → Val[9-10月] → Test[11-12月]
```

#### Walk-forward評価と閾値最適化

**目的**: 単一期間最適化による運用期待値劣化と閾値過学習を防止する。

**実装**: Walk-forward Cross-Validation (k=6 folds, overlap=0.5) + Temporal CV

```python
def walk_forward_validation(
    data_h5_path: str,
    k_folds: int = 6,
    overlap: float = 0.5,
    optimize_thresholds: bool = True
) -> Dict[str, Any]:
    """
    Walk-forward評価とハイパーパラメータ最適化

    Args:
        data_h5_path: データファイルパス
        k_folds: 分割数（デフォルト: 6）
        overlap: オーバーラップ比率（デフォルト: 0.5 = 50%）
        optimize_thresholds: 閾値最適化を実施するか

    Returns:
        {'scores': [...], 'best_thresholds': {...}, 'frontiers': [...]}
    """
    with h5py.File(data_h5_path, 'r') as f:
        sequences = f['sequences'][:]
        timestamps = f['timestamps'][:]

    N = len(sequences)
    fold_size = N // k_folds
    overlap_size = int(fold_size * overlap)

    results = {
        'val_scores': [],
        'train_scores': [],
        'best_thresholds': [],
        'frontier_models': []
    }

    for i in range(k_folds):
        # ウィンドウ定義
        train_start = max(0, i * fold_size - overlap_size)
        train_end = (i + 1) * fold_size
        val_start = train_end
        val_end = min(N, val_start + fold_size // 2)

        # データ分割
        train_data = sequences[train_start:train_end]
        val_data = sequences[val_start:val_end]

        logger.info(f"Fold {i+1}/{k_folds}: Train[{train_start}:{train_end}], Val[{val_start}:{val_end}]")

        # モデル学習
        model = train_model(train_data)

        # Train性能評価
        train_score = evaluate_model(model, train_data)
        results['train_scores'].append(train_score)

        # 閾値最適化（Validation上で）
        if optimize_thresholds:
            best_thr = optimize_decision_thresholds(
                model,
                val_data,
                search_space={
                    'confidence_threshold': (0.5, 0.9),
                    'neutral_k_atr': (0.2, 0.5),
                    'mode_switch_threshold': (0.6, 0.8)
                },
                method='grid_search',  # or 'bayesian'
                cv_splits=3  # 内部temporal CV
            )
            results['best_thresholds'].append(best_thr)

        # Validation性能評価
        val_score = evaluate_model(model, val_data, thresholds=best_thr)
        results['val_scores'].append(val_score)

        # Frontierモデル保存（過学習検出用）
        results['frontier_models'].append({
            'fold': i,
            'timestamp_range': (timestamps[train_start], timestamps[val_end]),
            'model_path': f'models/wf_fold{i}.pt',
            'train_score': train_score,
            'val_score': val_score,
            'thresholds': best_thr
        })

    # KPI計算
    mean_val_score = np.mean(results['val_scores'])
    mean_train_score = np.mean(results['train_scores'])
    val_train_ratio = mean_val_score / mean_train_score

    # 過学習チェック
    if val_train_ratio < 0.8:
        logger.warning(f"過学習検出: val/train = {val_train_ratio:.3f} < 0.8")

    results['summary'] = {
        'mean_val_score': mean_val_score,
        'mean_train_score': mean_train_score,
        'val_train_ratio': val_train_ratio,
        'fold_consistency': np.std(results['val_scores']) / mean_val_score  # CV
    }

    return results


def optimize_decision_thresholds(
    model,
    val_data,
    search_space: Dict[str, Tuple[float, float]],
    method: str = 'grid_search',
    cv_splits: int = 3
) -> Dict[str, float]:
    """
    閾値パラメータの最適化（過学習対策付き）

    Args:
        model: 学習済みモデル
        val_data: Validationデータ
        search_space: 探索空間 {'param_name': (min, max)}
        method: 'grid_search' | 'bayesian' | 'random'
        cv_splits: Temporal CV分割数

    Returns:
        最適閾値セット
    """
    # Validation を更にcv_splits分割（temporal）
    N = len(val_data)
    fold_size = N // cv_splits

    best_score = -np.inf
    best_thresholds = None

    # 探索空間のグリッド生成
    if method == 'grid_search':
        grid = generate_threshold_grid(search_space, n_points=10)
    elif method == 'bayesian':
        # Bayesian Optimization
        from skopt import gp_minimize
        # ...省略...
        return {}
    else:
        # Random search
        grid = generate_random_threshold_samples(search_space, n_samples=50)

    for threshold_set in grid:
        # Temporal CV評価
        cv_scores = []

        for split_i in range(cv_splits):
            split_start = split_i * fold_size
            split_end = (split_i + 1) * fold_size
            split_data = val_data[split_start:split_end]

            # 閾値適用して評価
            score = evaluate_with_thresholds(model, split_data, threshold_set)
            cv_scores.append(score)

        # 平均スコア
        mean_score = np.mean(cv_scores)
        score_std = np.std(cv_scores)

        # 安定性ペナルティ（CV大きすぎる場合）
        if score_std / mean_score > 0.3:  # 変動係数 > 30%
            mean_score *= 0.9  # ペナルティ

        if mean_score > best_score:
            best_score = mean_score
            best_thresholds = threshold_set

    logger.info(f"最適閾値: {best_thresholds}, スコア: {best_score:.4f}")

    return best_thresholds


def generate_threshold_grid(search_space, n_points=10):
    """閾値グリッド生成"""
    from itertools import product

    param_ranges = {}
    for param, (min_val, max_val) in search_space.items():
        param_ranges[param] = np.linspace(min_val, max_val, n_points)

    # 全組み合わせ
    keys = list(param_ranges.keys())
    values = list(param_ranges.values())

    grid = []
    for combo in product(*values):
        grid.append(dict(zip(keys, combo)))

    return grid
```

**成功指標**:
- **Val/Train比 ≥ 0.8**: 過学習防止
- **Fold一貫性**: CV(val_scores) < 0.2（安定性）
- **閾値再現性**: 連続fold間での閾値変動 < 20%

**検証**:
```python
def test_walk_forward():
    """Walk-forward評価の検証"""
    results = walk_forward_validation(
        'data/preprocessed.h5',
        k_folds=6,
        overlap=0.5
    )

    # 1. Val/Train比チェック
    assert results['summary']['val_train_ratio'] >= 0.8, "過学習検出"

    # 2. Fold一貫性
    cv = results['summary']['fold_consistency']
    assert cv < 0.2, f"Fold間ばらつき大: CV={cv:.3f}"

    # 3. 閾値安定性
    thresholds = results['best_thresholds']
    for param in thresholds[0].keys():
        values = [t[param] for t in thresholds]
        relative_std = np.std(values) / np.mean(values)
        assert relative_std < 0.2, f"{param}の閾値が不安定"
```

### 注意事項

- **シャッフル禁止**: 時系列データのため`shuffle=False`を厳守
- **リーク防止**: Validation/Testデータは学習時に一切参照しない
- **統計量計算**: 正規化パラメータ（mean/std）はTrainデータのみから算出
- **クロスバリデーション**: 時系列データでは使用しない（Time Series Splitのみ許可）

---

## 🏷️ ラベリング戦略（デュアルモード対応）

### 方向ラベル

#### NEUTRAL閾値の定義（Phase別実装）

```python
# 実装フェーズ1: 基本実装（spread + ATRベース）
θ_neutral = max(
    spread × k_spread,      # 1.0（コスト考慮）
    ATR_short × k_atr       # 0.3（短期ボラティリティ）
)

# 実装フェーズ2: ボラティリティレジーム追加（将来拡張）
θ_neutral = max(
    spread × k_spread,
    ATR_short × k_atr,
    ATR_ratio × k_ratio     # ATR_short / ATR_long（レジーム判定）
)

# 分類
if ΔP > θ_neutral: label = UP
elif ΔP < -θ_neutral: label = DOWN
else: label = NEUTRAL
```

#### パラメータ詳細

```python
# Phase 1パラメータ（即実装可能）
params = {
    "k_spread": 1.0,        # スプレッド倍率（コスト回収必須）
    "k_atr": 0.3,           # ATR倍率（ノイズ除外）
    "atr_period": 14,       # ATR計算期間（M5基準）
    "spread_default": 1.2   # pips（動的取得失敗時）
}

# 計算例（EURUSD、通常時）
spread = 1.2 pips
ATR_short = 8.0 pips (M5, 14期間)

θ_neutral = max(
    1.2 × 1.0 = 1.2 pips,
    8.0 × 0.3 = 2.4 pips
) = 2.4 pips

# 結果: ±2.4 pips以内の変動はNEUTRAL
```

#### デュアルモード対応

```python
# モード別にNEUTRAL閾値を調整

# Scalp Mode（短期・高頻度）
θ_neutral_scalp = max(
    spread × 1.2,           # コストマージン増加
    ATR_M1 × 0.25           # M1ベースの短期ボラ
)

# Swing Mode（長期・低頻度）
θ_neutral_swing = max(
    spread × 0.8,           # コスト感度低下
    ATR_H1 × 0.4            # H1ベースの長期ボラ
)

# 使用例
if trend_strength < 0.7:
    threshold = θ_neutral_scalp
else:
    threshold = θ_neutral_swing
```

#### Phase 2拡張: ボラティリティレジーム（将来）

```python
# ATR比率によるレジーム判定
def calculate_volatility_regime(
    atr_short: float,   # M5 ATR(14)
    atr_long: float     # H1 ATR(14)
) -> str:
    """
    Returns: 'low', 'normal', 'high'
    """
    ratio = atr_short / atr_long
    
    if ratio < 0.6:
        return "low"        # 短期ボラ低下（レンジ）
    elif ratio > 1.4:
        return "high"       # 短期ボラ急増（ブレイクアウト）
    else:
        return "normal"

# レジーム別閾値調整
regime_multiplier = {
    "low": 0.8,      # レンジ相場：閾値を下げて反応向上
    "normal": 1.0,
    "high": 1.3      # 高ボラ相場：閾値を上げてノイズ除外
}

θ_neutral_phase2 = max(
    spread × k_spread,
    ATR_short × k_atr
) × regime_multiplier[regime]
```

### 価格幅ラベル（デュアル）

```python
# Scalp Mode用（70-80%のトレード）
# 条件: 1時間以内にクローズ、trend_strength < 0.7
y_scalp = abs(exit_price - entry_price) × 10  # pips
  範囲: 0.5-2.0 pips
  TP/SL: 固定（ATR × 0.8 / 0.5）

# Swing Extension用（20-30%のトレード）
# 条件: trend_strength >= 0.7、トレールで延長
y_swing = abs(final_exit - entry_price) × 10  # pips
  範囲: 2.0-5.0 pips
  決済: トレーリングストップ（+0.8 pips起動、0.3 pips幅）
```

#### 価格幅ラベルのロバスト化

**目的**: 極端な価格幅による損失主導と過学習を防止する。

**実装**: Quantile Clipping (p1, p99) + Adaptive Huber δ

```python
def compute_robust_magnitude_label(
    magnitude_raw: float,
    mode: str,  # 'scalp' or 'swing'
    historical_magnitudes: np.ndarray,
    quantile_range: Tuple[float, float] = (0.01, 0.99)
) -> float:
    """
    ロバストな価格幅ラベル計算

    Args:
        magnitude_raw: 生の価格幅（pips）
        mode: 'scalp' または 'swing'
        historical_magnitudes: 過去の価格幅分布（同一モード）
        quantile_range: クリッピング範囲（デフォルト: p1, p99）

    Returns:
        float: ロバスト化された価格幅
    """
    # 分位数によるクリッピング
    p_low, p_high = quantile_range
    q_low = np.quantile(historical_magnitudes, p_low)
    q_high = np.quantile(historical_magnitudes, p_high)

    magnitude_clipped = np.clip(magnitude_raw, q_low, q_high)

    return magnitude_clipped


def compute_adaptive_huber_delta(
    magnitudes: np.ndarray,
    mode: str
) -> float:
    """
    Huber Loss の δ パラメータを適応的に計算

    Args:
        magnitudes: 価格幅分布
        mode: 'scalp' または 'swing'

    Returns:
        float: 適応的な δ 値
    """
    # MAD (Median Absolute Deviation) ベースの δ
    median = np.median(magnitudes)
    mad = np.median(np.abs(magnitudes - median))

    # モード別係数
    if mode == 'scalp':
        delta = 1.0 * mad  # より敏感
    elif mode == 'swing':
        delta = 1.5 * mad  # より緩やか
    else:
        raise ValueError(f"Unknown mode: {mode}")

    # 下限制約
    delta = max(delta, 0.1)  # 最小 0.1 pips

    return delta


# 学習時の適用例
class MagnitudeLoss(nn.Module):
    def __init__(self, mode='scalp'):
        super().__init__()
        self.mode = mode
        self.delta = None  # 動的に更新

    def forward(self, pred, target, historical_targets):
        # δの動的更新（エポックごと）
        if self.delta is None or self.training:
            self.delta = compute_adaptive_huber_delta(
                historical_targets.cpu().numpy(),
                self.mode
            )

        # Huber Loss with adaptive δ
        loss = F.huber_loss(pred, target, delta=self.delta)

        return loss


# トレーニングループ内での使用
scalp_loss_fn = MagnitudeLoss(mode='scalp')
swing_loss_fn = MagnitudeLoss(mode='swing')

# バッチごとに適応的δを更新
loss_scalp = scalp_loss_fn(
    pred_scalp,
    target_scalp_clipped,  # quantile clipping済み
    historical_scalp_targets  # 過去N日分
)
```

**成功指標**:
- 幅 loss の変動係数（CV）< 0.3
- 外れ値サンプル（>p99）の loss 寄与率 < 10%

**検証**:
```python
def test_magnitude_loss_stability():
    """価格幅損失の安定性を検証"""
    # 正常データ
    normal_targets = np.random.normal(1.0, 0.3, 1000)  # 平均1.0pips

    # 外れ値混入
    outlier_targets = np.concatenate([
        normal_targets,
        np.array([10.0, 15.0, 20.0])  # 極端な幅
    ])

    # クリッピング前後の損失比較
    loss_before = compute_loss(model, outlier_targets)
    loss_after = compute_loss(model, clip_magnitudes(outlier_targets))

    # 損失の安定化を確認
    assert loss_after.std() < loss_before.std() * 0.7, "ロバスト化不十分"
```

### トレンド強度ラベル

```python
# H1/H4の次4時間のトレンド維持率
y_trend_strength = calculate_trend_persistence(
    current_time,
    lookforward_hours=4,
    timeframes=['H1', 'H4']
)

def calculate_trend_persistence(t, lookforward_hours, timeframes):
    """
    次N時間のトレンド方向一致率を計算

    Returns:
        float: 0-1の値（1=完全なトレンド維持）
    """
    direction_t = get_direction_at(t)
    future_bars = []

    for tf in timeframes:
        bars = get_bars(tf, t, t + lookforward_hours)
        direction_consistent = (bars['close'] > bars['open']) == direction_t
        future_bars.append(direction_consistent.mean())

    return np.mean(future_bars)  # TF間平均
```

#### TrendStrength生成関数の標準定義

**目的**: ラベル生成の一貫性確保と再学習時の再現性保証。

**実装方式**: EMA比率ベース

```python
def compute_trend_strength(
    close_series: np.ndarray,
    window: Tuple[int, int] = (12, 26),  # [w_short, w_long]
    method: str = 'ema_ratio',
    smoothing_gamma: float = 0.1
) -> float:
    """
    トレンド強度を計算（再現性保証）

    Args:
        close_series: 終値系列（H1またはH4）
        window: [短期窓, 長期窓]（EMA期間）
        method: 'ema_ratio' | 'trend_consistency' | 'directional_movement'
        smoothing_gamma: 平滑化係数（0-1）

    Returns:
        float: トレンド強度 [0, 1]

    メタデータ書き込み:
        - method, window, smoothing_gamma
        - 計算タイムスタンプ
        - バージョンハッシュ

    成功条件:
        連続再学習でラベル再現差 < 1e-6
    """
    w_short, w_long = window

    if method == 'ema_ratio':
        # EMA比率による強度計算
        ema_short = pd.Series(close_series).ewm(span=w_short).mean().iloc[-1]
        ema_long = pd.Series(close_series).ewm(span=w_long).mean().iloc[-1]

        # 正規化された差分
        strength_raw = abs(ema_short - ema_long) / ema_long

        # [0, 1]にクリップ + 平滑化
        strength = np.clip(strength_raw * 100, 0, 1)
        strength = strength * (1 - smoothing_gamma) + 0.5 * smoothing_gamma

    elif method == 'trend_consistency':
        # 方向一致率（既存実装）
        strength = calculate_trend_persistence(...)

    elif method == 'directional_movement':
        # ADX風の方向性指標
        strength = calculate_adx_like(close_series, window[0])

    else:
        raise ValueError(f"Unknown method: {method}")

    return strength


# メタデータ保存（HDF5）
def save_trend_strength_metadata(h5_file, params):
    """
    ラベル生成パラメータをメタデータとして保存

    保存内容:
        /metadata/labeling/trend_strength/
            - method: str
            - window_short: int
            - window_long: int
            - smoothing_gamma: float
            - version_hash: str (params + code hash)
            - timestamp: str
    """
    meta_group = h5_file.require_group('metadata/labeling/trend_strength')
    meta_group.attrs['method'] = params['method']
    meta_group.attrs['window_short'] = params['window'][0]
    meta_group.attrs['window_long'] = params['window'][1]
    meta_group.attrs['smoothing_gamma'] = params['smoothing_gamma']
    meta_group.attrs['version_hash'] = compute_param_hash(params)
    meta_group.attrs['timestamp'] = datetime.now().isoformat()
```

**検証**:
```python
# 再現性テスト
def test_trend_strength_reproducibility():
    """連続実行でラベル再現差 < 1e-6を確認"""
    params = {'method': 'ema_ratio', 'window': (12, 26), 'smoothing_gamma': 0.1}

    result1 = compute_trend_strength(test_data, **params)
    result2 = compute_trend_strength(test_data, **params)

    assert abs(result1 - result2) < 1e-6, "再現性違反"
```

---

## ⚙️ ハイパーパラメータ

```yaml
training:
  optimizer:
    type: AdamW
    lr: 1e-3
    warmup_ratio: 0.05
  
  scheduler:
    type: cosine
    min_lr: 1e-6
  
  loss_weights:
    direction: 0.40          # 方向（最重要）
    magnitude_scalp: 0.35    # スキャルピング価格幅
    magnitude_swing: 0.15    # スイング延長価格幅
    trend_strength: 0.10     # トレンド強度
    dynamic_adjust: true     # 動的調整有効化
  
  precision: fp16            # Mixed precision
  
  labeling:
    neutral_threshold:
      # 実装フェーズ1: 基本実装
      k_spread: 1.0          # スプレッド倍率
      k_atr: 0.3             # ATR倍率
      atr_period: 14         # ATR計算期間
      atr_timeframe: "M5"    # ATRベースとなるTF
      spread_default: 1.2    # pips（動的取得失敗時）
      
      # デュアルモード別調整
      scalp_mode:
        k_spread_multiplier: 1.2   # コストマージン増
        atr_timeframe: "M1"        # M1ベース
        k_atr: 0.25
      swing_mode:
        k_spread_multiplier: 0.8   # コスト感度低
        atr_timeframe: "H1"        # H1ベース
        k_atr: 0.4
      
      # 実装フェーズ2: レジーム拡張（将来）
      regime_detection:
        enabled: false       # Phase 2で有効化
        atr_ratio_low: 0.6
        atr_ratio_high: 1.4
        regime_multiplier:
          low: 0.8
          normal: 1.0
          high: 1.3
  
  model:
    lstm_hidden: 128
    fusion_method: attention
    d_model: 128
  
  reproducibility:
    seed: 42
    deterministic: true
```

---

## 📈 期待値再構成

学習後の実用化に向けて：

```python
# 期待値計算
E[ΔP] = Σ P(direction) × predicted_magnitude

# コスト考慮
NetExpectancy = E[ΔP] - (spread + slippage + commission)
```

---

## ✅ データリーク防止

### 必須チェック
- 入力最終時刻 < ラベル参照時刻
- `shift(-n)` 使用禁止
- 未来rolling禁止

### 検証
学習前に自動チェック実行

---

## 📊 品質検査

### スケール不変性
平行移動・拡大後の embedding 類似度 > τ

### クラス分布
NEUTRAL比率が範囲外の場合 WARNING

### マルチホライズン整合性テスト

短期・長期予測の論理的整合性を検証し、矛盾する予測（近距離DOWN、遠距離UP等）を検出：

```python
class MultiHorizonConsistencyChecker:
    """マルチホライズン予測の整合性検証"""
    
    def __init__(self, config: dict):
        self.max_reversal_rate = config.get("max_reversal_rate", 0.01)  # 1%未満
        self.monotonicity_penalty = config.get("monotonicity_penalty", 1.0)
    
    def check_consistency(self, predictions: dict) -> tuple[bool, dict]:
        """
        マルチホライズン予測の整合性チェック
        
        Args:
            predictions: {
                "scalp_magnitude": 0.8 pips,     # 短期（次数本）
                "swing_magnitude": 2.5 pips,     # 中期（数時間）
                "scalp_direction": "UP",
                "swing_direction": "UP",
                "trend_strength": 0.65
            }
        
        Returns:
            (is_consistent, statistics)
        """
        stats = {
            "direction_reversal": False,
            "magnitude_monotonic": True,
            "reversal_count": 0,
            "consistency_score": 1.0
        }
        
        # 1. 方向逆転検出
        scalp_dir = predictions.get("scalp_direction")
        swing_dir = predictions.get("swing_direction")
        
        if scalp_dir and swing_dir and scalp_dir != swing_dir:
            # 短期UP、長期DOWNは戦略混乱を招く
            stats["direction_reversal"] = True
            stats["reversal_count"] += 1
            logger.warning(
                f"方向逆転検出: scalp={scalp_dir}, swing={swing_dir}"
            )
        
        # 2. マグニチュード単調性チェック
        scalp_mag = predictions.get("scalp_magnitude", 0)
        swing_mag = predictions.get("swing_magnitude", 0)
        
        # 短期 > 長期は異常（通常は長期の方が大きい）
        if scalp_mag > swing_mag * 1.5:  # 1.5倍以上の場合
            stats["magnitude_monotonic"] = False
            logger.warning(
                f"マグニチュード非単調: scalp={scalp_mag:.2f} > swing={swing_mag:.2f}"
            )
        
        # 3. 整合性スコア計算
        if stats["direction_reversal"]:
            stats["consistency_score"] *= 0.5  # ペナルティ
        
        if not stats["magnitude_monotonic"]:
            stats["consistency_score"] *= 0.8
        
        # 4. トレンド強度との整合性
        trend_strength = predictions.get("trend_strength", 0.5)
        
        # 強トレンド（>0.7）なのに方向逆転は矛盾
        if trend_strength > 0.7 and stats["direction_reversal"]:
            stats["consistency_score"] *= 0.3
            logger.error(
                f"重大な矛盾: trend_strength={trend_strength:.2f}, "
                f"but direction reversal"
            )
        
        is_consistent = stats["consistency_score"] >= 0.8
        
        return is_consistent, stats
    
    def assert_consistency_during_training(self, batch_predictions: dict):
        """
        学習時のバッチ整合性検証
        
        Args:
            batch_predictions: {
                "scalp_magnitude": [batch_size],
                "swing_magnitude": [batch_size],
                ...
            }
        """
        batch_size = len(batch_predictions["scalp_direction"])
        reversal_count = 0
        
        for i in range(batch_size):
            pred = {
                "scalp_magnitude": batch_predictions["scalp_magnitude"][i],
                "swing_magnitude": batch_predictions["swing_magnitude"][i],
                "scalp_direction": batch_predictions["scalp_direction"][i],
                "swing_direction": batch_predictions["swing_direction"][i],
                "trend_strength": batch_predictions.get("trend_strength", [0.5])[i]
            }
            
            is_consistent, stats = self.check_consistency(pred)
            
            if stats["direction_reversal"]:
                reversal_count += 1
        
        # 逆転率チェック
        reversal_rate = reversal_count / batch_size
        
        if reversal_rate > self.max_reversal_rate:
            logger.error(
                f"マルチホライズン逆転率異常: {reversal_rate:.2%} > "
                f"{self.max_reversal_rate:.2%}, 学習停止推奨"
            )
            # 異常時は例外（学習停止）
            raise ValueError(
                f"Consistency violation: reversal_rate={reversal_rate:.2%}"
            )
        
        return reversal_rate


# 使用例: 学習時の検証
consistency_checker = MultiHorizonConsistencyChecker({
    "max_reversal_rate": 0.01,  # 1%未満
    "monotonicity_penalty": 1.0
})

# バッチ予測後にチェック
predictions = {
    "scalp_magnitude": torch.tensor([0.8, 1.2, 0.5, ...]),
    "swing_magnitude": torch.tensor([2.5, 3.0, 1.8, ...]),
    "scalp_direction": ["UP", "UP", "DOWN", ...],
    "swing_direction": ["UP", "DOWN", "DOWN", ...],  # 2番目が逆転
    "trend_strength": torch.tensor([0.65, 0.55, 0.72, ...])
}

try:
    reversal_rate = consistency_checker.assert_consistency_during_training(predictions)
    logger.info(f"整合性チェック通過: 逆転率={reversal_rate:.2%}")
except ValueError as e:
    logger.error(f"整合性エラー: {e}")
    # 学習パラメータ調整または停止
```

**マルチホライズン整合性テスト仕様**:
- **逆転率閾値**: < 1%（99%以上が整合）
- **方向逆転検出**: scalp ≠ swing
- **マグニチュード単調性**: scalp < swing × 1.5
- **トレンド強度整合**: trend_strength > 0.7 で逆転禁止
- **成功指標**: 逆転率 < 1%、整合性スコア >= 0.8

**効果**:
- 矛盾予測による戦略混乱防止
- モデル学習の安定性向上
- デバッグ可能性向上（異常パターン早期発見）

---

## 📝 ログ出力

### 時刻表示ルール
- **全ログ**: 日本時間(JST)で表示
- **フォーマット**: `YYYY-MM-DD HH:MM:SS JST`
- **学習開始/終了時刻**: 日本時間で明記

```
🔄 第4段階: 学習開始 [2025-10-24 00:15:30 JST]
📂 入力: models/fx_mtf_20251022_100000_preprocessed.h5
   学習期間: 2024-01-01 00:00:00 JST ～ 2024-10-31 23:59:00 JST
   検証期間: 2024-11-01 00:00:00 JST ～ 2024-12-31 23:59:00 JST

🔄 Epoch 1/100 [2025-10-24 00:16:12 JST]
📊 Loss: total=0.523, direction=0.312, magnitude=0.211
🎯 Accuracy: direction=0.68, NEUTRAL_ratio=0.33
⚙️ Weights: α=0.52, β=0.48

✅ 学習完了 [2025-10-24 03:45:18 JST]
   総学習時間: 3時間29分48秒
```

---

## 💾 再現性メタデータ

HDF5に保存:
```
/metadata/training_info
  - config_hash
  - feature_names
  - horizon_set
  - commit_hash
  - seed
  - timestamp
```

---

## 🚨 エラー条件

- データリーク検知
- クラス分布異常（NEUTRAL > 60% or < 10%）
- 損失NaN/Inf
- 勾配爆発

---

## 🔗 関連仕様書

- **前段階**: 第3段階: [PREPROCESSOR_SPEC.md](./PREPROCESSOR_SPEC.md) - 前処理
- **次工程**: 第5段階: [VALIDATOR_SPEC.md](./VALIDATOR_SPEC.md) - 検証
- **詳細仕様**:
  - [trainer/MULTI_TF_FUSION_SPEC.md](./trainer/MULTI_TF_FUSION_SPEC.md) - マルチTF融合
  - [trainer/MODEL_ARCHITECTURE_SCALP_EXTENSION_SPEC.md](./trainer/MODEL_ARCHITECTURE_SCALP_EXTENSION_SPEC.md) - スカルプ拡張
  - [trainer/GPU_OPTIMIZATION_SPEC.md](./trainer/GPU_OPTIMIZATION_SPEC.md) - GPU最適化

---

## 運用品質・保守性向上

### Huber δ動的調整

**目的**: 固定δはボラティリティregime変化で外れ値扱い誤差が増大

**解決策**: ボラティリティ適応型δ自動更新

```python
class AdaptiveHuberLoss:
    """ボラティリティ適応型Huber損失"""
    
    def __init__(self, config: dict):
        self.k_factor = config.get("huber_k_factor", 1.5)  # δ = median * k
        self.update_interval = config.get("huber_update_interval", 1000)  # steps
        self.min_delta = config.get("huber_min_delta", 0.1)
        self.max_delta = config.get("huber_max_delta", 5.0)
        
        self.step_count = 0
        self.current_delta = 1.0  # 初期値
    
    def update_delta(self, targets: torch.Tensor):
        """
        δを動的更新
        
        Args:
            targets: ターゲット値（価格幅）テンソル
        
        Returns:
            updated_delta: 新しいδ値
        """
        # 中央値ベース計算
        median_abs = torch.median(torch.abs(targets)).item()
        
        # p90幅ベース（オプション）
        p90 = torch.quantile(torch.abs(targets), 0.9).item()
        
        # δ = max(median * k, p90 * 0.5)
        delta_median = median_abs * self.k_factor
        delta_p90 = p90 * 0.5
        
        new_delta = max(delta_median, delta_p90)
        new_delta = np.clip(new_delta, self.min_delta, self.max_delta)
        
        # 変化率チェック
        if hasattr(self, 'current_delta'):
            change_ratio = abs(new_delta - self.current_delta) / self.current_delta
            if change_ratio > 0.3:
                logger.warning(
                    f"Huber δ大幅変更: {self.current_delta:.3f} → {new_delta:.3f} "
                    f"(変化率={change_ratio:.2%})"
                )
        
        self.current_delta = new_delta
        return new_delta
    
    def forward(
        self,
        predictions: torch.Tensor,
        targets: torch.Tensor
    ) -> torch.Tensor:
        """
        適応型Huber損失計算
        
        Args:
            predictions: 予測値
            targets: 正解値
        
        Returns:
            loss: Huber損失
        """
        # δ更新（定期実行）
        self.step_count += 1
        if self.step_count % self.update_interval == 0:
            self.update_delta(targets)
        
        # Huber損失計算
        residual = predictions - targets
        abs_residual = torch.abs(residual)
        
        quadratic = torch.min(abs_residual, torch.tensor(self.current_delta))
        linear = abs_residual - quadratic
        
        loss = 0.5 * quadratic ** 2 + self.current_delta * linear
        
        return loss.mean()


# 使用例
adaptive_huber = AdaptiveHuberLoss({
    "huber_k_factor": 1.5,
    "huber_update_interval": 1000,
    "huber_min_delta": 0.1,
    "huber_max_delta": 5.0
})

# 学習ループ内
loss_magnitude = adaptive_huber.forward(pred_magnitude, target_magnitude)
```

**KPI（項目10）**:
- δ変化率: 連続30%超変更 → ボラregime shift検出
- 幅head loss改善率: ≥+5%（固定δ比較）
- δ範囲維持: [0.1, 5.0] pips内

---

### Multi-head勾配干渉対策（PCGrad）

**目的**: 長期head勾配が短期スカルプheadを押し潰し方向確率平滑化

**解決策**: PCGrad（Project Conflicting Gradients）導入

```python
class PCGradOptimizer:
    """勾配干渉解消Optimizer"""
    
    def __init__(self, optimizer: torch.optim.Optimizer, config: dict):
        self.optimizer = optimizer
        self.enabled = config.get("pcgrad_enabled", False)
        self.log_interval = config.get("pcgrad_log_interval", 100)
        
        self.step_count = 0
        self.interference_stats = []
    
    def pc_grad_update(self, losses: Dict[str, torch.Tensor]):
        """
        PCGrad適用
        
        Args:
            losses: タスク別損失辞書 {"direction": loss1, "magnitude": loss2, ...}
        """
        if not self.enabled:
            # 通常更新
            total_loss = sum(losses.values())
            self.optimizer.zero_grad()
            total_loss.backward()
            self.optimizer.step()
            return
        
        # タスク別勾配取得
        grads = {}
        for task_name, loss in losses.items():
            self.optimizer.zero_grad()
            loss.backward(retain_graph=True)
            
            # 全パラメータの勾配を収集
            task_grads = []
            for param in self.optimizer.param_groups[0]['params']:
                if param.grad is not None:
                    task_grads.append(param.grad.clone().flatten())
            
            grads[task_name] = torch.cat(task_grads)
        
        # 干渉検出・射影
        task_names = list(grads.keys())
        projected_grads = {name: grads[name].clone() for name in task_names}
        
        for i, task_i in enumerate(task_names):
            for j, task_j in enumerate(task_names):
                if i >= j:
                    continue
                
                g_i = grads[task_i]
                g_j = grads[task_j]
                
                # 内積計算
                dot_product = torch.dot(g_i, g_j)
                
                # 干渉検出（負の内積 = 対立）
                if dot_product < 0:
                    # task_iの勾配からtask_j成分を射影除去
                    g_j_norm_sq = torch.dot(g_j, g_j)
                    if g_j_norm_sq > 0:
                        projected_grads[task_i] -= (dot_product / g_j_norm_sq) * g_j
                    
                    # 統計記録
                    interference_ratio = abs(dot_product / (torch.norm(g_i) * torch.norm(g_j) + 1e-8))
                    self.interference_stats.append({
                        "task_i": task_i,
                        "task_j": task_j,
                        "interference_ratio": interference_ratio.item()
                    })
        
        # 射影後勾配を適用
        self.optimizer.zero_grad()
        param_idx = 0
        for param in self.optimizer.param_groups[0]['params']:
            if param.grad is not None:
                param_size = param.numel()
                
                # 全タスクの射影勾配を平均
                combined_grad = torch.zeros_like(param.flatten())
                for task_name in task_names:
                    task_grad_slice = projected_grads[task_name][param_idx:param_idx+param_size]
                    combined_grad += task_grad_slice
                
                combined_grad /= len(task_names)
                param.grad = combined_grad.view_as(param)
                param_idx += param_size
        
        self.optimizer.step()
        
        # 統計ログ
        self.step_count += 1
        if self.step_count % self.log_interval == 0 and self.interference_stats:
            avg_interference = np.mean([s["interference_ratio"] for s in self.interference_stats])
            logger.info(f"PCGrad 干渉率: {avg_interference:.3f}")
            self.interference_stats = []


# 使用例
pcgrad_optimizer = PCGradOptimizer(
    optimizer=torch.optim.Adam(model.parameters(), lr=0.001),
    config={"pcgrad_enabled": True, "pcgrad_log_interval": 100}
)

# 学習ループ
losses = {
    "direction": loss_direction,
    "magnitude_scalp": loss_magnitude_scalp,
    "magnitude_swing": loss_magnitude_swing
}
pcgrad_optimizer.pc_grad_update(losses)
```

**KPI（項目20）**:
- 干渉率: <15%
- scalp head accuracy改善: ≥+2%（baseline比較）
- per-head grad_cosine: >0（対立なし）

---

### コスト要素同時最適化ロス

**目的**: 方向精度偏重でネット利益が負化

**解決策**: Cost-aware複合損失関数

```python
class CostAwareLoss:
    """コスト考慮複合損失"""
    
    def __init__(self, config: dict):
        self.cost_penalty_weight = config.get("cost_penalty_weight", 0.3)
        self.direction_weight = config.get("direction_weight", 0.4)
        self.magnitude_weight = config.get("magnitude_weight", 0.3)
        
        self.spread_baseline = config.get("spread_baseline_pips", 1.5)
        self.slip_baseline = config.get("slip_baseline_pips", 0.3)
    
    def forward(
        self,
        pred_direction: torch.Tensor,  # [batch, 3] (UP/DOWN/NEUTRAL)
        pred_magnitude: torch.Tensor,  # [batch, 1]
        target_direction: torch.Tensor,  # [batch]
        target_magnitude: torch.Tensor,  # [batch, 1]
        spread: torch.Tensor,  # [batch, 1]
        slip_estimate: torch.Tensor  # [batch, 1]
    ) -> Dict[str, torch.Tensor]:
        """
        コスト考慮複合損失計算
        
        Returns:
            losses: {"total": total_loss, "direction": ..., "magnitude": ..., "cost_penalty": ...}
        """
        # 1. 方向損失（CE）
        loss_direction = F.cross_entropy(pred_direction, target_direction)
        
        # 2. 価格幅損失（Huber）
        loss_magnitude = F.smooth_l1_loss(pred_magnitude, target_magnitude)
        
        # 3. コストペナルティ
        # ネット期待値 = 予測価格幅 - 2*spread - slip
        net_expectancy = pred_magnitude - 2 * spread - slip_estimate
        
        # 負の期待値にペナルティ
        cost_penalty = torch.relu(-net_expectancy).mean()
        
        # 4. 統合損失
        total_loss = (
            self.direction_weight * loss_direction +
            self.magnitude_weight * loss_magnitude +
            self.cost_penalty_weight * cost_penalty
        )
        
        return {
            "total": total_loss,
            "direction": loss_direction,
            "magnitude": loss_magnitude,
            "cost_penalty": cost_penalty
        }


# 使用例
cost_aware_loss = CostAwareLoss({
    "cost_penalty_weight": 0.3,
    "direction_weight": 0.4,
    "magnitude_weight": 0.3,
    "spread_baseline_pips": 1.5,
    "slip_baseline_pips": 0.3
})

# 学習ループ
losses = cost_aware_loss.forward(
    pred_direction=model.direction_head(features),
    pred_magnitude=model.magnitude_head(features),
    target_direction=batch["direction_label"],
    target_magnitude=batch["magnitude_label"],
    spread=batch["spread"],
    slip_estimate=batch["slip_estimate"]
)

losses["total"].backward()
optimizer.step()
```

**KPI（項目99）**:
- cost-adjusted expectancy>0 サンプル率: +10%
- ネット利益改善: ≥+5%（baseline比較）
- コストペナルティ損失: 学習進行で減少傾向

---

## 📌 注意事項

1. **エラー握りつぶし禁止**: 異常時は `raise` で停止
2. **シード固定**: 再現性確保
3. **FP16使用**: GPU効率化
4. **動的損失重み**: 収束安定化（オプション）

---

## 🔮 将来拡張

- パターン抽出エンコーダ統合
- マイクロ構造特徴量融合
- ハザード予測ヘッド追加
- マルチホライゾン予測
- レジーム適応型閾値
