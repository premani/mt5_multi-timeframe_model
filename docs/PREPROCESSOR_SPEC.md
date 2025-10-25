# PREPROCESSOR_SPEC.md

**バージョン**: 2.1
**更新日**: 2025-10-25
**責任者**: core-team
**処理段階**: 第3段階: 前処理（正規化・シーケンス化）

---

## 📋 目的

`src/preprocessor.py` が**第2段階で計算済みの特徴量**を学習可能な形式に変換する。

**責任範囲**:
- 特徴量の正規化（RobustScaler等）
- シーケンス化（時系列ウィンドウ生成）
- 品質検証（NaN/定数列/高相関除外）
- 未来リーク検査

**処理段階の分離**:
- **第1段階（データ収集）**: `src/data_collector.py` → `data/data_collector.h5`
- **第2段階（特徴量計算）**: `src/feature_calculator.py` → `data/feature_calculator.h5`
- **第3段階（前処理）**: `src/preprocessor.py` → `data/preprocessor.h5`

---

## 🔄 処理フロー

```
入力: models/*_features.h5（第2段階で生成）
  ├─ features: (N, 50-80) 計算済み特徴量
  ├─ feature_names: 特徴量名リスト
  └─ metadata: 計算統計情報
    ↓
[ステップ1: HDF5ロード]
  - 第2段階で計算済みの特徴量を読み込み
    ↓
[ステップ2: 品質フィルタリング]
  - NaN/Inf 検出・除外
  - 定数列除外（IQR < 1e-6）
  - 高相関ペア除外（|ρ| > 0.95）
    ↓
[ステップ3: 正規化]
  - RobustScaler適用（外れ値耐性）
  - パラメータ保存（逆変換用）
    ↓
[ステップ4: シーケンス化]
  - マルチTF別ウィンドウ作成
    - M1: (N, 480, F)  # 8時間
    - M5: (N, 288, F)  # 24時間
    - M15: (N, 192, F) # 48時間
    - H1: (N, 96, F)   # 4日
    - H4: (N, 48, F)   # 8日
    ↓
[ステップ5: 未来リーク検査]
  - タイムスタンプ順序確認
  - ターゲット時刻より未来のデータ混入チェック
    ↓
[ステップ6: 品質統計出力]
  - フィルタリング結果
  - 正規化パラメータ
  - シーケンス統計
    ↓
出力: data/preprocessor.h5
  ├─ sequences: Dict[str, array] # TF別シーケンス
  ├─ scaler_params: bytes (JSON) # 正規化パラメータ
  ├─ feature_names: array         # 最終特徴量名
  └─ metadata: bytes (JSON)       # 処理統計

※ 既存ファイルがある場合、JST日時プレフィックス付きでリネーム退避
  例: data/20251023_143045_preprocessor.h5
```

### 第2段階との分離

| 処理 | 第2段階 (feature_calculator.py) | 第3段階 (preprocessor.py) |
|------|----------------------------------|---------------------------|
| **特徴量計算** | ✅ RSI, MACD, ATR, 価格変化等 | ❌ 計算済みを読み込むのみ |
| **TF間特徴** | ✅ M5-M1差分, 相関等 | ❌ 計算済みを読み込むのみ |
| **正規化** | ❌ 生値のまま出力 | ✅ RobustScaler適用 |
| **シーケンス化** | ❌ DataFrame形式 | ✅ TF別ウィンドウ生成 |
| **品質フィルタ** | ❌ 全特徴量出力 | ✅ NaN/相関/分散除外 |

---

## 📊 処理詳細

### 1. 品質フィルタリング

```python
def filter_features(features: pd.DataFrame) -> pd.DataFrame:
    """
    品質基準に満たない特徴量を除外
    
    除外条件:
    - NaN/Inf 含有率 > 1%（列単位）
    - NaN/Inf 含有行（行単位で完全除外） ← 追加
    - IQR < 1e-6（定数列）
    - 他特徴との相関 |ρ| > 0.95
    """
    # 1. NaN/Inf含有列除外（列単位）
    nan_ratio = features.isna().sum() / len(features)
    inf_ratio = np.isinf(features.select_dtypes(include=[np.number])).sum() / len(features)
    valid_cols = (nan_ratio + inf_ratio) <= 0.01
    features = features.loc[:, valid_cols]
    
    # 2. NaN/Inf含有行除外（行単位で完全除外） ← 追加
    features = features.replace([np.inf, -np.inf], np.nan)
    features = features.dropna()
    logger.info(f"   NaN/Inf含有行除外: {len(features)} 行残存")
    
    # 3. 定数列除外
    from scipy.stats import iqr
    feature_iqr = features.apply(iqr)
    features = features.loc[:, feature_iqr >= 1e-6]
    
    # 4. 高相関ペア除外（上三角走査）
    corr_matrix = features.corr().abs()
    upper_tri = corr_matrix.where(
        np.triu(np.ones(corr_matrix.shape), k=1).astype(bool)
    )
    to_drop = [col for col in upper_tri.columns 
               if any(upper_tri[col] > 0.95)]
    features = features.drop(columns=to_drop)
    
    return features
```

### 2. 正規化（RobustScaler）

```python
from sklearn.preprocessing import RobustScaler

def normalize_features(features: pd.DataFrame) -> Tuple[np.ndarray, dict]:
    """
    RobustScalerで正規化（外れ値耐性）
    
    Returns:
        normalized: 正規化後の配列
        params: 逆変換用パラメータ（center_, scale_）
    """
    scaler = RobustScaler()
    normalized = scaler.fit_transform(features)
    
    # 正規化後の検証（NaN/Inf検出） ← 追加
    if np.isnan(normalized).any() or np.isinf(normalized).any():
        raise ValueError("正規化後にNaN/Infが発生しました")
    
    params = {
        'center_': scaler.center_.tolist(),
        'scale_': scaler.scale_.tolist(),
        'feature_names': features.columns.tolist()
    }
    
    return normalized, params
```

### 3. シーケンス化

```python
def create_sequences(
    features: np.ndarray,
    tf_configs: Dict[str, int]
) -> Dict[str, np.ndarray]:
    """
    TF別にシーケンスウィンドウを生成

    Args:
        features: (N, F) 正規化済み特徴量
        tf_configs: {'M1': 480, 'M5': 288, ...} # ウィンドウ長

    Returns:
        {'M1': (N-480, 480, F), 'M5': (N-288, 288, F), ...}
    """
    sequences = {}

    for tf_name, window_size in tf_configs.items():
        seq_list = []
        for i in range(len(features) - window_size):
            seq_list.append(features[i:i+window_size])
        sequences[tf_name] = np.array(seq_list)

    return sequences
```

#### TF別マスク処理

**目的**: TF長差異による暗黙的forward fillと情報歪み（高時間軸への勾配集中）を防止する。

**実装**: per-TF mask行列 + 有効率閾値（max_valid_ratio=0.95）による品質管理

```python
def create_sequences_with_mask(
    features_per_tf: Dict[str, pd.DataFrame],  # TF別生データ
    tf_configs: Dict[str, int],
    max_valid_ratio: float = 0.95,
    filled_weight_decay: float = 0.6
) -> Dict[str, Any]:
    """
    TF別マスク処理付きシーケンス生成

    Args:
        features_per_tf: {'M1': DataFrame(N_m1, F), 'M5': DataFrame(N_m5, F), ...}
        tf_configs: {'M1': 480, 'M5': 288, ...}
        max_valid_ratio: 欠損率閾値（超過時TF除外）
        filled_weight_decay: forward fill後の損失重み減衰率

    Returns:
        {
            'sequences': {'M1': (N, 480, F), ...},
            'masks': {'M1': (N, 480), ...},  # 1=有効, 0=欠損/filled
            'loss_weights': {'M1': (N, 480), ...},  # 学習重み
            'tf_validity': {'M1': 0.98, ...},  # TF別有効率
            'excluded_tfs': ['H4']  # 除外されたTF
        }
    """
    result = {
        'sequences': {},
        'masks': {},
        'loss_weights': {},
        'tf_validity': {},
        'excluded_tfs': []
    }

    for tf_name, window_size in tf_configs.items():
        if tf_name not in features_per_tf:
            continue

        df = features_per_tf[tf_name]
        N = len(df)

        # 欠損フラグ（元データ）
        is_missing = df.isna().any(axis=1).values  # (N,)

        # Forward fill適用
        df_filled = df.fillna(method='ffill')

        # filled フラグ
        was_filled = is_missing & ~df_filled.isna().any(axis=1).values

        # シーケンス化
        seq_list = []
        mask_list = []
        weight_list = []

        for i in range(N - window_size):
            window = df_filled.iloc[i:i+window_size].values  # (window, F)
            seq_list.append(window)

            # マスク生成（欠損+filled箇所を0）
            window_missing = is_missing[i:i+window_size]
            window_filled = was_filled[i:i+window_size]
            mask = ~(window_missing | window_filled)  # 有効=True
            mask_list.append(mask.astype(float))

            # 損失重み生成
            weight = np.ones(window_size, dtype=float)
            weight[window_filled] = filled_weight_decay  # filled箇所を減衰
            weight_list.append(weight)

        sequences = np.array(seq_list)  # (N, window, F)
        masks = np.array(mask_list)  # (N, window)
        weights = np.array(weight_list)  # (N, window)

        # TF別有効率計算
        valid_ratio = masks.mean()

        # 閾値チェック
        if valid_ratio < (1.0 - max_valid_ratio):
            logger.warning(
                f"TF {tf_name} 除外: 有効率={valid_ratio:.3f} < {1.0-max_valid_ratio:.3f}"
            )
            result['excluded_tfs'].append(tf_name)
            continue

        result['sequences'][tf_name] = sequences
        result['masks'][tf_name] = masks
        result['loss_weights'][tf_name] = weights
        result['tf_validity'][tf_name] = valid_ratio

    return result
```

**整列図**:
```
TF別データ整列（欠損差異の可視化）

M1:  [■■■■■■■■■□□■■■■■■■■■]  ← 欠損2箇所（□）
M5:  [■■■■■■■■■■■■■■■■■■■■]  ← 欠損なし
H1:  [■■□□□■■■■■■■■■■■■■■■]  ← 欠損3箇所
H4:  [□□□□□□■■■■■■■■■■■■■■]  ← 欠損6箇所（除外候補）

mask適用後:
M1:  [1 1 1 1 1 1 1 1 1 0 0 1 1 1 1 1 1 1 1 1]
M5:  [1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1]
H1:  [1 1 0 0 0 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1]
H4:  [0 0 0 0 0 0 1 1 1 1 1 1 1 1 1 1 1 1 1 1]  ← 有効率60% → 除外

loss_weight適用:
M1:  [1.0 1.0 ... 0.6 0.6 1.0 ...]  ← filled箇所は0.6
```

**成功指標**:
- 無効TF除外率 < 5%
- 欠損補完バー学習重み ≤ 0.6
- 補完サンプルの期待値誤差 |Δ| < 0.3pips

**検証**:
```python
def test_tf_mask_processing():
    """TF別マスク処理の検証"""
    # ダミーデータ（M5に欠損なし、H4に40%欠損）
    features_per_tf = {
        'M5': pd.DataFrame(np.random.randn(1000, 50)),
        'H4': pd.DataFrame(np.random.randn(1000, 50))
    }
    # H4に欠損注入
    features_per_tf['H4'].iloc[:400] = np.nan

    result = create_sequences_with_mask(
        features_per_tf,
        tf_configs={'M5': 288, 'H4': 48},
        max_valid_ratio=0.95
    )

    # H4が除外されることを確認
    assert 'H4' in result['excluded_tfs'], "H4が除外されるべき"
    assert 'M5' in result['sequences'], "M5は残るべき"

    # M5の有効率確認
    assert result['tf_validity']['M5'] > 0.95, "M5有効率が高いべき"
```

#### 欠損補完時の学習重み減衰

**目的**: forward fill補完による方向確率過信（confidence過大）を防止する。

**実装**: filled_flag付与 → loss_weight指数減衰（連続補完時） → 品質ログ出力

```python
def compute_filled_loss_weights(
    filled_flags: np.ndarray,  # (N, window) bool
    base_weight: float = 1.0,
    decay_per_consecutive: float = 0.9,
    min_weight: float = 0.3
) -> np.ndarray:
    """
    連続欠損補完に対する指数減衰重み計算

    Args:
        filled_flags: filled箇所のフラグ (True=filled)
        base_weight: 基本重み
        decay_per_consecutive: 連続ごとの減衰率（例: 0.9^k）
        min_weight: 最小重み

    Returns:
        loss_weights: (N, window) 学習重み
    """
    N, window = filled_flags.shape
    weights = np.full((N, window), base_weight, dtype=float)

    for i in range(N):
        consecutive_count = 0
        for j in range(window):
            if filled_flags[i, j]:
                consecutive_count += 1
                # 指数減衰: base_weight * (decay^k)
                decay_factor = decay_per_consecutive ** consecutive_count
                weights[i, j] = max(base_weight * decay_factor, min_weight)
            else:
                consecutive_count = 0  # リセット

    return weights


# 品質ログ出力
class FilledDataQualityLogger:
    """補完データの品質監視"""

    def __init__(self):
        self.filled_ratios = []
        self.expectancy_errors = []

    def log_batch(self, filled_flags, predictions, targets):
        """
        バッチごとの補完データ品質を記録

        Args:
            filled_flags: (batch, seq) bool
            predictions: (batch,) predicted values
            targets: (batch,) true values
        """
        # 補完率
        filled_ratio = filled_flags.sum() / filled_flags.size
        self.filled_ratios.append(filled_ratio)

        # filled箇所の期待値誤差
        filled_mask = filled_flags.any(axis=1)  # バッチレベル
        if filled_mask.sum() > 0:
            filled_preds = predictions[filled_mask]
            filled_targets = targets[filled_mask]
            error = np.abs(filled_preds - filled_targets).mean()
            self.expectancy_errors.append(error)

    def check_quality_kpi(self):
        """KPI達成確認"""
        mean_error = np.mean(self.expectancy_errors)

        if mean_error > 0.3:  # 0.3pips閾値
            logger.warning(
                f"補完サンプル期待値誤差超過: {mean_error:.4f} pips > 0.3 pips"
            )
            return False

        return True


# トレーニングループ内
quality_logger = FilledDataQualityLogger()

for batch in dataloader:
    sequences, masks, filled_flags = batch['sequences'], batch['masks'], batch['filled']

    # 重み計算
    loss_weights = compute_filled_loss_weights(filled_flags)

    # 予測
    predictions = model(sequences, masks)

    # 損失計算（重み適用）
    loss = weighted_loss(predictions, targets, loss_weights)

    # 品質ログ
    quality_logger.log_batch(filled_flags, predictions.detach(), targets)

# エポック終了時
quality_logger.check_quality_kpi()
```

**成功指標**:
- 補完サンプルの期待値誤差 |Δ| < 0.3pips
- 連続補完3回以上の箇所: 重み ≤ 0.5

**検証**:
```python
def test_filled_weight_decay():
    """連続補完の重み減衰を検証"""
    # 連続3箇所filled
    filled_flags = np.array([[False, True, True, True, False, False]])

    weights = compute_filled_loss_weights(
        filled_flags,
        base_weight=1.0,
        decay_per_consecutive=0.9,
        min_weight=0.3
    )

    # 連続1回目: 1.0 * 0.9 = 0.9
    # 連続2回目: 1.0 * 0.9^2 = 0.81
    # 連続3回目: 1.0 * 0.9^3 = 0.729
    assert abs(weights[0, 1] - 0.9) < 0.01
    assert abs(weights[0, 2] - 0.81) < 0.01
    assert abs(weights[0, 3] - 0.729) < 0.01
    assert weights[0, 0] == 1.0
    assert weights[0, 4] == 1.0
```

### 4. 未来リーク検査

```python
def check_future_leak(
    sequences: Dict[str, np.ndarray],
    timestamps: np.ndarray,
    target_times: np.ndarray
) -> bool:
    """
    シーケンス内にターゲット時刻より未来のデータが混入していないか確認
    
    Returns:
        True: リークなし
        False: リーク検出
    """
    for tf_name, seq in sequences.items():
        seq_end_times = timestamps[len(timestamps) - len(seq):]
        
        # シーケンス最終時刻 < ターゲット時刻
        if not all(seq_end_times < target_times[:len(seq_end_times)]):
            logger.error(f"未来リーク検出: {tf_name}")
            return False
    
    return True
```

---

## 📊 HDF5スキーマ

### 出力ファイル: `models/*_preprocessed.h5`

```python
with h5py.File('preprocessed.h5', 'w') as f:
    # TF別シーケンス（グループ化）
    sequences_group = f.create_group('sequences')
    sequences_group.create_dataset('M1', data=seq_M1, dtype='float32')
    sequences_group.create_dataset('M5', data=seq_M5, dtype='float32')
    sequences_group.create_dataset('M15', data=seq_M15, dtype='float32')
    sequences_group.create_dataset('H1', data=seq_H1, dtype='float32')
    sequences_group.create_dataset('H4', data=seq_H4, dtype='float32')
    
    # 正規化パラメータ（JSON）
    f.create_dataset('scaler_params',
                     data=json.dumps(scaler_params).encode())
    
    # 最終特徴量名
    f.create_dataset('feature_names',
                     data=[name.encode() for name in feature_names])
    
    # メタデータ
    f.create_dataset('metadata',
                     data=json.dumps({
                         'input_features': 60,
                         'filtered_features': 52,
                         'nan_filtered': 3,
                         'const_filtered': 2,
                         'corr_filtered': 3,
                         'sequence_lengths': {
                             'M1': 480, 'M5': 288, 'M15': 192,
                             'H1': 96, 'H4': 48
                         },
                         'future_leak_check': 'PASS',
                         'timestamp': '2025-10-22T12:00:00Z'
                     }).encode())
```

---

## 品質統計

ログ出力例:
```
📂 第2段階特徴量読込: 60列
🔍 品質フィルタリング:
   - NaN除外: 3列
   - 定数列除外: 2列
   - 高相関除外: 3列
   → 最終特徴量: 52列

⚙️ 正規化: RobustScaler適用
   - center範囲: [-0.05, 0.08]
   - scale範囲: [0.3, 2.1]

📊 シーケンス化:
   - M1: (45000, 480, 52)
   - M5: (45000, 288, 52)
   - M15: (45000, 192, 52)
   - H1: (45000, 96, 52)
   - H4: (45000, 48, 52)

✅ 未来リーク検査: PASS
   出力: models/fx_mtf_20251022_120000_preprocessed.h5
```

---

## 🚨 エラー条件

| 条件 | 閾値 | 対応 |
|------|------|------|
| NaN/Inf 含有率 | >1% | エラー終了（第2段階確認） |
| フィルタ後特徴量数 | <30列 | 警告（第2段階で特徴追加検討） |
| 未来リーク検出 | 1件でも | エラー終了 |
| シーケンス生成失敗 | 時系列不整合 | エラー終了（第1段階確認） |
| 正規化パラメータ異常 | center/scale NaN | エラー終了 |

---

## 💾 出力ファイル

| ファイル名 | 内容 | Git管理 |
|-----------|------|---------|
| `data/preprocessor.h5` | 正規化済みシーケンス | ❌ 除外 |
| `data/preprocessor_report.json` | 正規化パラメータ・品質統計 | ❌ 除外 |
| `data/preprocessor_report.md` | 人間可読レポート | ❌ 除外 |

**バックアップ**: 既存ファイルは `YYYYMMDD_HHMMSS_preprocessor.<ext>` にリネーム (JST)

例: `20251024_143500_preprocessor.h5`

---

## 📄 レポート生成

### JSONレポート (`data/preprocessor_report.json`)

次処理（学習）が読み込むパラメータ情報:

```json
{
  "timestamp": "2025-10-24T14:35:15+09:00",
  "process": "preprocessor",
  "version": "1.0",
  "input": {
    "file": "data/feature_calculator.h5",
    "source_report": "data/feature_calculator_report.json",
    "features": 66,
    "samples": 2500000
  },
  "output": {
    "file": "data/preprocessor.h5",
    "size_mb": 350
  },
  "filtering": {
    "original_features": 66,
    "removed_nan": 2,
    "removed_constant": 1,
    "removed_correlation": 3,
    "final_features": 60,
    "removed_columns": ["col_A", "col_B", "col_C", "col_D", "col_E", "col_F"]
  },
  "normalization": {
    "method": "RobustScaler",
    "scaler_params": {
      "feature_1": {"center": 0.0015, "scale": 0.0023},
      "feature_2": {"center": 0.0008, "scale": 0.0019},
      "...": "60 features total"
    }
  },
  "sequences": {
    "window_size": 360,
    "stride": 1,
    "total_sequences": 2499640,
    "valid_sequences": 2499500,
    "dropped_sequences": 140
  },
  "quality": {
    "avg_quality_score": 0.92,
    "low_quality_sequences": 124975,
    "low_quality_ratio": 0.05,
    "future_leak_check": "passed",
    "monotonic_check": "passed"
  },
  "performance": {
    "execution_time_sec": 45,
    "memory_peak_mb": 8000
  }
}
```

### Markdownレポート (`data/preprocessor_report.md`)

人間による検証用の可読レポート:

```markdown
# 前処理 実行レポート

**実行日時**: 2025-10-24 14:35:15 JST  
**処理時間**: 45秒  
**バージョン**: 1.0

## 📊 入力

- **入力ファイル**: `data/feature_calculator.h5`
- **特徴量数**: 66列
- **サンプル数**: 2,500,000

## 🎯 処理結果

- **出力ファイル**: `data/preprocessor.h5`
- **ファイルサイズ**: 350 MB
- **最終特徴量数**: 60列
- **シーケンス数**: 2,499,500

### フィルタリング結果

| 項目 | 除外数 | 残存数 |
|-----|--------|--------|
| 元の特徴量 | - | 66 |
| NaN列除外 | 2 | 64 |
| 定数列除外 | 1 | 63 |
| 高相関除外 | 3 | 60 |

**除外された列**: col_A, col_B, col_C, col_D, col_E, col_F

### 正規化パラメータ

**手法**: RobustScaler (IQR基準)

正規化例 (最初の5特徴量):

| 特徴量名 | Center | Scale |
|---------|--------|-------|
| M1_price_change_pips | 0.0015 | 0.0023 |
| M5_price_change_pips | 0.0008 | 0.0019 |
| M15_price_change_pips | 0.0012 | 0.0021 |
| spread_pips | 0.0005 | 0.0003 |
| tick_volume | 1200.0 | 850.5 |

### シーケンス生成

| 項目 | 値 |
|-----|-----|
| ウィンドウサイズ | 360 (6時間) |
| ストライド | 1 |
| 総シーケンス | 2,499,640 |
| 有効シーケンス | 2,499,500 |
| 除外シーケンス | 140 (0.006%) |

## 📈 品質統計

| 項目 | 値 |
|-----|-----|
| 平均品質スコア | 0.92 |
| 低品質シーケンス | 124,975 (5.0%) |
| 未来リークチェック | ✅ 合格 |
| 単調性チェック | ✅ 合格 |

## ⚙️ パフォーマンス

- **実行時間**: 45秒
- **ピークメモリ**: 8,000 MB

## ⚠️ 警告・注意事項

- 6列を品質フィルタで除外（NaN、定数、高相関）
- 低品質シーケンス5.0%（ボラティリティ異常期間）
- 140シーケンスを除外（NaN含有）

## ✅ 検証結果

- ✅ 全特徴量の正規化完了
- ✅ 未来リークなし
- ✅ 時系列の単調性確認
- ✅ 正規化パラメータ保存完了
```

---

## 📝 ログ出力

### 時刻表示ルール
- **全ログ**: 日本時間(JST)で表示
- **フォーマット**: `YYYY-MM-DD HH:MM:SS JST`
- **データ期間**: 日本時間で明記
- **詳細**: [TIMEZONE_UTILS_SPEC.md](./utils/TIMEZONE_UTILS_SPEC.md)

### 出力例
```
🔄 第3段階: 前処理開始 [2025-10-23 23:50:30 JST]
📂 入力: models/fx_mtf_20251022_100000_features.h5
   期間: 2024-01-01 00:00:00 JST ～ 2024-12-31 23:59:00 JST
   特徴量: 58列

🔍 入力品質スコア計算
   平均スコア: 0.92, 低品質シーケンス: 5%

🧹 品質フィルタリング
   NaN除外: 2列, 定数列除外: 1列, 高相関除外: 3列
   残存特徴量: 52列

📊 正規化実施
   RobustScaler適用完了

✅ 前処理完了 [2025-10-23 23:51:15 JST]
   出力: models/fx_mtf_20251022_100000_preprocessed.h5
```

---

## ⚙️ 設定例

```yaml
# config/preprocessing.yaml
preprocessing:
  # 品質フィルタ
  quality_filter:
    max_nan_ratio: 0.01          # 1%
    min_iqr: 1.0e-6              # 定数列閾値
    max_correlation: 0.95         # 高相関閾値
  
  # 正規化
  normalization:
    method: robust                # robust | standard | minmax
    quantile_range: [25, 75]     # RobustScaler用
  
  # シーケンス化
  sequences:
    M1: 480   # 8時間
    M5: 288   # 24時間
    M15: 192  # 48時間
    H1: 96    # 4日
    H4: 48    # 8日
  
  # 未来リーク検査
  leak_check:
    enabled: true
    strict_mode: true
  
  # エラー閾値
  thresholds:
    min_features_after_filter: 30
```

---

## 🔗 関連仕様書

- **前段階**:
  - 第1段階: [DATA_COLLECTOR_SPEC.md](./DATA_COLLECTOR_SPEC.md) - 生データ収集
  - 第2段階: [FEATURE_CALCULATOR_SPEC.md](./FEATURE_CALCULATOR_SPEC.md) - 特徴量計算
- **次工程**: 第4段階: [TRAINER_SPEC.md](./TRAINER_SPEC.md) - 学習
- **参照**:
  - [FUTURE_LEAK_PREVENTION_SPEC.md](./validator/FUTURE_LEAK_PREVENTION_SPEC.md) - 未来リーク検査詳細

---

## 📌 注意事項

### 処理段階分離の重要性

**旧プロジェクトの失敗**: シーケンス内で特徴量計算 → 責任不明確・デバッグ困難

**本プロジェクトの改善**:
```
第2段階: 特徴量計算
  - 入力: raw_data.h5（OHLCV）
  - 処理: RSI, MACD, ATR, TF間差分等
  - 出力: features.h5（DataFrame形式）

第3段階: 前処理（本仕様書）
  - 入力: features.h5（計算済み特徴量）
  - 処理: 正規化・シーケンス化・品質検証
  - 出力: preprocessed.h5（学習可能形式）
```

### 実装時の注意

1. **第2段階の計算結果を信頼**: 特徴量の再計算禁止
2. **正規化パラメータの保存必須**: 
   - 推論時の逆変換に必要（`scaler_params` を必ず保存）
   - 学習時と推論時で同じパラメータを使用（再計算禁止）
   - モデルファイルと `scaler_params` を必ずセットで管理
   - 詳細は「[🔄 推論時の復元](#-推論時の復元)」セクション参照
3. **シーケンス長の固定**: MULTI_TF_FUSION_SPEC.md の設計に準拠
4. **未来リーク検査は必須**: エラー時は即座に停止

---

## 🔮 将来拡張

### 実装フェーズ1: 基本実装（現在）
- RobustScaler正規化
- TF別固定ウィンドウ
- 基本品質フィルタ

### 実装フェーズ2: 拡張機能
- データ拡張（Augmentation）
  - ノイズ付加
  - 時間スケール変動
- 動的ウィンドウサイズ
- オンライン正規化パラメータ更新

### 実装フェーズ3: 最適化
- 並列シーケンス生成
- メモリ効率化（lazy loading）
- GPU正規化（cupy統合）

---

## 🔄 推論時の復元

### 概要

**学習時に保存した正規化パラメータを使用して、モデル予測値を元のスケールに復元する手順**。

**重要原則**:
1. **学習時と同じパラメータを使用**: 推論時に正規化パラメータを再計算してはいけない
2. **パラメータの一意性保証**: モデルファイルと `scaler_params` を必ずセットで管理
3. **特徴量順序の一致**: `feature_names` で列順序を保証

### パラメータ読み込み

**HDF5から正規化パラメータを読み込み**:

```python
import h5py
import json
import numpy as np
from sklearn.preprocessing import RobustScaler

def load_scaler_params(preprocessed_h5_path: str) -> RobustScaler:
    """
    学習時に保存した正規化パラメータをRobustScalerとして復元
    
    Args:
        preprocessed_h5_path: 前処理済みHDF5ファイルパス
        
    Returns:
        復元されたRobustScalerインスタンス
        
    Raises:
        KeyError: scaler_paramsが存在しない
        ValueError: パラメータ形式が不正
    """
    with h5py.File(preprocessed_h5_path, 'r') as f:
        # JSON形式で保存されたパラメータを読み込み
        scaler_params = json.loads(f['scaler_params'][()])
        
        # RobustScalerを復元
        scaler = RobustScaler()
        scaler.center_ = np.array(scaler_params['center_'])
        scaler.scale_ = np.array(scaler_params['scale_'])
        
        # 特徴量名も復元（順序検証用）
        feature_names = scaler_params['feature_names']
        scaler.feature_names_in_ = np.array(feature_names)
        scaler.n_features_in_ = len(feature_names)
        
    return scaler, feature_names
```

### 予測値の逆変換

**モデル出力（正規化値）を元のスケールに復元**:

```python
def inverse_transform_predictions(
    predictions_normalized: np.ndarray,
    scaler: RobustScaler
) -> np.ndarray:
    """
    正規化された予測値を元のスケールに復元
    
    Args:
        predictions_normalized: モデル出力（正規化値）
        scaler: load_scaler_paramsで復元したScaler
        
    Returns:
        元のスケールに復元された予測値
        
    Example:
        >>> # モデル予測（正規化値）
        >>> predictions_norm = model.predict(input_sequences)
        >>> # 元のスケールに復元
        >>> predictions_original = inverse_transform_predictions(
        ...     predictions_norm, scaler
        ... )
    """
    # inverse_transformで元のスケールに復元
    predictions_original = scaler.inverse_transform(predictions_normalized)
    
    return predictions_original
```

### 推論パイプライン全体例

```python
def inference_pipeline(
    raw_data: pd.DataFrame,
    preprocessed_h5_path: str,
    model_path: str
) -> np.ndarray:
    """
    推論時の完全なパイプライン
    
    Args:
        raw_data: 生データ（特徴量計算前）
        preprocessed_h5_path: 学習時の前処理パラメータ
        model_path: 学習済みモデル
        
    Returns:
        元のスケールでの予測値
    """
    # 1. 正規化パラメータ読み込み
    scaler, feature_names = load_scaler_params(preprocessed_h5_path)
    
    # 2. 同じ順序で特徴量を選択・正規化
    features = raw_data[feature_names]  # 列順序を保証
    features_normalized = scaler.transform(features)  # fit_transformではなくtransform
    
    # 3. シーケンス化（学習時と同じウィンドウサイズ）
    sequences = create_sequences_for_inference(features_normalized)
    
    # 4. モデル予測
    model = load_model(model_path)
    predictions_normalized = model.predict(sequences)
    
    # 5. 元のスケールに復元
    predictions_original = inverse_transform_predictions(
        predictions_normalized, scaler
    )
    
    return predictions_original
```

### 重要な注意事項

#### 1. 学習時と同じパラメータを使用

❌ **NG**: 推論時に再計算
```python
# 推論時に新たにfit → パラメータがバラつく
scaler = RobustScaler()
scaler.fit(inference_data)  # 絶対禁止
predictions_norm = model.predict(scaler.transform(inference_data))
```

✅ **OK**: 学習時のパラメータを読み込み
```python
# 学習時のパラメータを復元
scaler, _ = load_scaler_params('data/preprocessor.h5')
predictions_norm = model.predict(scaler.transform(inference_data))
predictions_original = scaler.inverse_transform(predictions_norm)
```

#### 2. パラメータの一意性保証

**モデルと `scaler_params` を必ずセットで管理**:

```
models/
├── fx_lstm_model_20251023_143045.pth         # 学習済みモデル
└── fx_lstm_model_20251023_143045_preprocessed.h5  # 対応する正規化パラメータ
```

**推奨ファイル管理方法**:
- タイムスタンプで対応関係を保証
- メタデータに `preprocessed_h5_hash` を記録
- 誤った組み合わせ検出機能

#### 3. 特徴量順序の一致

**`feature_names` で列順序を保証**:

```python
# HDF5から特徴量名を読み込み
_, feature_names = load_scaler_params('data/preprocessor.h5')

# 推論時も同じ順序で選択
inference_features = raw_data[feature_names]  # 順序が一致
```

#### 4. ONNX変換時の扱い

**Option 1: 前処理・後処理を外部化**
```python
# ONNX変換前に正規化
features_norm = scaler.transform(features)
onnx_output = onnx_model.run(None, {'input': features_norm})
predictions = scaler.inverse_transform(onnx_output[0])
```

**Option 2: 前処理をONNXグラフに統合**（将来拡張）
- RobustScaler演算をONNX opに変換
- パラメータ（center_, scale_）をグラフ定数として埋め込み

### 検証方法

**学習時と推論時の一致を確認**:

```python
def verify_inference_consistency():
    """
    学習データで推論パイプラインを実行し、
    学習時の正規化値と一致するか検証
    """
    # 学習時の正規化値を読み込み
    with h5py.File('data/preprocessor.h5', 'r') as f:
        train_normalized = f['sequences']['M5'][:]  # 例: M5シーケンス
    
    # 推論パイプラインで同じデータを処理
    scaler, feature_names = load_scaler_params('data/preprocessor.h5')
    inference_normalized = scaler.transform(train_features[feature_names])
    
    # 一致確認（浮動小数点誤差を考慮）
    np.testing.assert_allclose(
        train_normalized,
        inference_normalized,
        rtol=1e-7,
        err_msg="推論時の正規化が学習時と不一致"
    )
```

---

## 📚 サブ仕様書

詳細な実装仕様は以下のサブ仕様書を参照：

### 入力品質管理
- **[INPUT_QUALITY_SPEC.md](./preprocessor/INPUT_QUALITY_SPEC.md)** - 入力品質劣化設計、欠損判定、ギャップ除外

  **内容**:
  - 入力品質スコアによる信頼度調整
  - 主要列/補助列の欠損分離処理
  - 長期欠損後のシーケンス分断
  - 連続ギャップ除外基準

### データ整合性検証
- **[DATA_INTEGRITY_SPEC.md](./preprocessor/DATA_INTEGRITY_SPEC.md)** - 列順序検証、TFマッピング

  **内容**:
  - 列順序ハッシュ検証
  - TFマッピング失敗時フォールバック

### 正規化仕様
- **[NORMALIZATION_SPEC.md](./preprocessor/NORMALIZATION_SPEC.md)** - 正規化パラメータ管理

  **内容**:
  - RobustScaler詳細仕様
  - 正規化パラメータ保存・管理

---

## 🔧 検証ツール

### 前処理結果確認ツール

**ツール**: `tools/preprocessor/inspect_preprocessor.py`

前処理済みHDF5ファイル（`data/preprocessor.h5`）の内容を詳細に確認できる専用ツール。

**機能**:
- シーケンス情報表示（TF別の形状・統計）
- 正規化パラメータ詳細（center_, scale_等）
- 特徴量名リスト表示
- メタデータ表示（生成日時・フィルタリング統計）
- HDF5構造のツリー表示
- **NaN/Inf検証**（全TFデータの品質検証） ← 追加

**使用方法**:

```bash
# デフォルトファイル（data/preprocessor.h5）を確認
bash ./docker_run.sh python3 tools/preprocessor/inspect_preprocessor.py

# 特定ファイルを指定
bash ./docker_run.sh python3 tools/preprocessor/inspect_preprocessor.py data/preprocessor.h5

# バックアップファイルを確認
bash ./docker_run.sh python3 tools/preprocessor/inspect_preprocessor.py data/20251023_143045_preprocessor.h5
```

**出力例**:

```
================================================================================
🔍 前処理結果確認ツール
================================================================================

📁 ファイル: /workspace/data/preprocessor.h5
   サイズ: 2.19 GB

================================================================================
📊 シーケンス情報
================================================================================

利用可能なタイムフレーム: ['H1', 'H4', 'M1', 'M15', 'M5']

⏱️  M1:
   Shape: (31162, 480, 17)
   - シーケンス数: 31,162
   - ウィンドウサイズ: 480
   - 特徴量数: 17
   - データ型: float32
   - メモリサイズ: 970.01 MB

📈 総シーケンス数: 157,106

================================================================================
🎯 正規化パラメータ
================================================================================

正規化方法: robust
特徴量数: 17

【RobustScaler パラメータ】
四分位範囲: [25, 75]

Center（先頭5個）: [0.0, 2.200, 5.599, ...]
Scale（先頭5個）: [2.101, 2.000, 4.200, ...]

【特徴量名リスト】（全17個）
   1. M1_price_change_pips
   2. M1_range_pips
   ...

================================================================================
✅ NaN/Inf検証
================================================================================

🔍 データ品質検証:
   - M1: NaN 0個 (0.00%), Inf 0個 (0.00%)
   - M5: NaN 0個 (0.00%), Inf 0個 (0.00%)
   - M15: NaN 0個 (0.00%), Inf 0個 (0.00%)
   - H1: NaN 0個 (0.00%), Inf 0個 (0.00%)
   - H4: NaN 0個 (0.00%), Inf 0個 (0.00%)

✅ 全タイムフレームでNaN/Infなし（品質OK）
```

**使用シーン**:
- 前処理実行後の結果確認
- 正規化パラメータの妥当性チェック
- シーケンス形状の検証
- デバッグ・トラブルシューティング

---

**更新履歴**:
- 2025-10-25 (v2.1): 推論時の復元セクション追加（パラメータ読み込み・逆変換手順の明確化）
- 2025-10-22 (v2.0): サブ仕様書に分離（INPUT_QUALITY, DATA_INTEGRITY, NORMALIZATION）
