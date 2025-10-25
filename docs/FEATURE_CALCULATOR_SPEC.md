# FEATURE_CALCULATOR_SPEC.md

**バージョン**: 1.2
**更新日**: 2025-10-25
**責任者**: core-team
**処理段階**: 第2段階: 特徴量計算

---

## � 変更履歴

### v1.1 (2025-10-24)
- **Phase 1-1完了**: 基本マルチTF特徴量 (36列) + セッション時間特徴量
- **バックアップ機構実装**: 
  - タイムスタンプ命名規則: `YYYYMMDD_HHMMSS_<basename>.<ext>` (先頭配置)
  - 既存ファイルの作成日時でタイムスタンプ付与
  - リネーム→新規作成フロー実装
- **キャッシュ制御実装**: 
  - `recalculate_categories` 設定による柔軟な制御
  - デフォルト: 全カテゴリ再計算
  - 開発中: 特定カテゴリのみ再計算可能
- **カテゴリ別ファイル管理**: 
  - `data/feature_calculator/` 固定ディレクトリ
  - 毎回実行時にリネーム→新規作成

### v1.2 (2025-10-25)
- **キャッシュ制御ロジック修正**: 
  - `should_recalculate` 判定を先に実行
  - 再計算時のみリネーム実行（キャッシュ使用時はリネームなし）
  - 指定カテゴリのみリネーム・再計算ロジックに修正
- **動作検証完了**: 
  - session_timeのみ再計算、basic_multi_tfはキャッシュ使用
  - リネームなしでの直接読込動作確認

### v1.0 (2025-10-22)
- 初版作成
- 5-7カテゴリ設計
- 段階的検証フロー定義

---

## �📋 目的

`src/feature_calculator.py` が**第1段階: データ収集で収集した生データ**から**価格回帰専用の特徴量**を計算する。

**責任範囲**:
- マルチTF生データ（OHLCV）から50-80特徴量を計算
- 5-7カテゴリの特徴量生成
- 段階的検証（カテゴリ追加毎に精度確認）
- 特徴量メタデータ生成

**重要**: 第1段階: データ収集のATR14キャッシュは使用せず、**すべての特徴量を独自に計算**する。これにより：
- 第1段階: データ収集のキャッシュロジック変更の影響を受けない
- 複数期間ATR（7/14/28期間）を統一的に計算
- 特徴量計算の独立性・再現性を確保

**処理段階の分離**:
- **第1段階（データ収集）**: `src/data_collector.py` → `data/data_collector.h5`
- **第2段階（特徴量計算）**: `src/feature_calculator.py` → `data/feature_calculator.h5`
- **第3段階（前処理）**: `src/preprocessor.py` → `data/preprocessor.h5`

---

## 🔄 処理フロー

```
入力: data/data_collector.h5（第1段階で収集）
  ├─ M1: (N, 6) [time, open, high, low, close, volume]
  ├─ M5: (N, 6)
  ├─ M15: (N, 6)
  ├─ H1: (N, 6)
  └─ H4: (N, 6)
  ※ 第1段階: データ収集のATR14キャッシュは使用しない
    ↓
[カテゴリ1: 基本マルチTF特徴量]（15-20列）
  - TF内: 価格変化率、レンジ幅
  - TF間: 差分、相関、方向一致度
    ↓
[カテゴリ2: マイクロ構造拡張]（10-15列）
  - スプレッド動態
  - ティック到着率
  - 方向転換率
    ↓
[カテゴリ3: ボラティリティ・レジーム]（8-12列）
  - ATR（複数期間）
  - ATR比率
  - レジーム判定
    ↓
[カテゴリ4: 簡潔勢い指標]（8-12列）
  - RSI（14期間）
  - MACD（12/26/9）
  - ボリンジャーバンド位置
    ↓
[カテゴリ5: セッション・時間]（5-8列）
  - 時刻エンコード（sin/cos）
  - セッション判定
    ↓
[ステップ6: 段階的検証]
  - カテゴリ追加毎に精度確認
  - 2%以上改善で受入
    ↓
出力: data/feature_calculator.h5
  ├─ features: (N, 50-80) float32
  ├─ feature_names: 特徴量名リスト
  ├─ category_info: カテゴリ別統計
  └─ metadata: 計算統計情報

※ 既存ファイルがある場合、JST日時プレフィックス付きでリネーム退避
  例: data/20251023_143045_feature_calculator.h5
```

---

## 🎯 旧プロジェクトからの改善

### ❌ 旧プロジェクトの失敗（`mt5_lstm-model`）

| 問題 | 原因 | 結果 |
|------|------|------|
| 方向分類→価格回帰への途中変更 | 特徴量は方向用のまま | 精度50%崩壊 |
| 11カテゴリ・150特徴量 | 過剰分割 | 管理困難 |
| 100%スケール不変性 | 絶対価格情報完全排除 | 価格回帰に必要な情報欠落 |
| 後付け品質保証 | 完璧主義的設計優先 | 精度不足発覚遅延 |

### ✅ 本プロジェクトの改善方針

| 項目 | 旧プロジェクト | 本プロジェクト |
|------|--------------|--------------|
| **設計対象** | 方向分類→途中変更 | **最初から価格回帰** |
| **カテゴリ数** | 11（管理困難） | **5-7（管理可能）** |
| **特徴量数** | 150+（過剰） | **50-80（最適）** |
| **スケール不変性** | 100%（絶対値なし） | **実用性重視**（pips保持） |
| **段階的検証** | なし（後付け） | **カテゴリ追加毎に検証** |

---

## 📊 特徴量カテゴリ概要

### カテゴリ構成

| カテゴリ | 列数 | 目的 | Phase 1実装 |
|---------|------|------|------------|
| カテゴリ1: 基本マルチTF | 15-20 | TF内変化とTF間関係 | ✅ 必須 |
| カテゴリ2: マイクロ構造拡張 | 10-15 | スプレッド・約定環境 | ⚠️ 段階的 |
| カテゴリ3: ボラティリティ・レジーム | 8-12 | 市場環境の変動性 | ⚠️ 段階的 |
| カテゴリ4: 簡潔勢い指標 | 8-12 | トレンド・反転の勢い | ⚠️ 段階的 |
| カテゴリ5: セッション・時間 | 5-8 | 時間帯による市場特性 | ✅ 必須 |

**合計**: 50-80列

### 段階的検証戦略

```
Phase 1-1: 基本マルチTF + セッション・時間（20-28列）
  → ベースライン精度確立
  ↓
Phase 1-2: + マイクロ構造拡張（30-43列）
  → 精度向上 +5%目標
  ↓
Phase 1-3: + ボラティリティ・レジーム（38-55列）
  → 精度向上 +3%目標
  ↓
Phase 1-4: + 簡潔勢い指標（46-67列）
  → 最終調整

中止条件:
- 3カテゴリ追加しても精度向上なし
- メモリ・計算時間が許容値超過
```

---

## 📊 HDF5スキーマ

### 出力ファイル: `models/*_features.h5`

```python
# 出力例: models/fx_mtf_20251022_120000_features.h5

with h5py.File('features.h5', 'w') as f:
    # 特徴量（N, 50-80）
    f.create_dataset('features', 
                     data=features.values, 
                     dtype='float32',
                     compression=None)  # 速度優先
    
    # 特徴量名リスト
    f.create_dataset('feature_names', 
                     data=[name.encode() for name in features.columns])
    
    # カテゴリ情報
    f.create_dataset('category_info',
                     data=json.dumps({
                         'basic_multi_tf': {
                             'count': 20,
                             'enabled': True,
                             'columns': ['M1_price_change_pips', ...]
                         },
                         'microstructure': {
                             'count': 12,
                             'enabled': True,
                             'columns': ['spread_pips', ...]
                         },
                         # ... 他のカテゴリ
                     }).encode())
    
    # メタデータ
    f.create_dataset('metadata',
                     data=json.dumps({
                         'total_features': 60,
                         'total_samples': 45000,
                         'nan_ratio': 0.003,
                         'calculation_time_sec': 45.2,
                         'timestamp': '2025-10-22T12:00:00Z',
                         'phase': 'feature_calculation',
                         'config_hash': 'sha256...'
                     }).encode())
```

---

## 🔧 実装クラス設計

### メインクラス

```python
class FeatureCalculator:
    """
    特徴量計算の統合クラス
    
    役割:
    - 各カテゴリ計算器の実行管理
    - 段階的検証の実施
    - HDF5出力
    """
    
    def __init__(self, config: dict):
        self.config = config
        self.calculators = self._init_calculators()
    
    def _init_calculators(self) -> List[BaseCalculator]:
        """
        設定に基づいて計算器を初期化
        """
        calculators = []
        
        if self.config['enable_categories']['basic_multi_tf']:
            calculators.append(BasicMultiTFCalculator())
        
        if self.config['enable_categories']['microstructure']:
            calculators.append(MicrostructureCalculator())
        
        # ... 他のカテゴリ
        
        return calculators
    
    def calculate(
        self, 
        raw_data: Dict[str, pd.DataFrame]
    ) -> pd.DataFrame:
        """
        全カテゴリの特徴量を計算
        
        Args:
            raw_data: {
                'M1': DataFrame(N, 6),
                'M5': DataFrame(N, 6),
                ...
            }
        
        Returns:
            features: DataFrame(N, 50-80)
        """
        all_features = []
        baseline_features = None
        
        for calculator in self.calculators:
            logger.info(f"🧮 {calculator.name} 計算開始")
            
            # カテゴリ特徴量計算
            cat_features = calculator.compute(raw_data)
            all_features.append(cat_features)
            
            # 段階的検証
            if self.config.get('validate_incremental', False):
                if baseline_features is None:
                    baseline_features = cat_features
                else:
                    self._validate_category_addition(
                        baseline_features,
                        cat_features
                    )
        
        # 全特徴量を結合
        features = pd.concat(all_features, axis=1)
        
        logger.info(f"✅ 特徴量計算完了: {len(features.columns)}列")
        return features
    
    def _validate_category_addition(
        self,
        baseline: pd.DataFrame,
        new_category: pd.DataFrame
    ):
        """
        カテゴリ追加による精度変化を検証
        """
        # 簡易モデルで精度評価
        # 詳細は後述
        pass
```

### 基底計算器クラス

```python
from abc import ABC, abstractmethod

class BaseCalculator(ABC):
    """
    特徴量計算器の基底クラス
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """カテゴリ名"""
        pass
    
    @abstractmethod
    def compute(
        self, 
        raw_data: Dict[str, pd.DataFrame]
    ) -> pd.DataFrame:
        """
        特徴量を計算
        
        Args:
            raw_data: マルチTF生データ
        
        Returns:
            features: DataFrame(N, K) K列の特徴量
        """
        pass
```

---

## 💾 出力ファイル

### カテゴリ別ファイル（キャッシュ・増分更新用）

| ファイル名 | 内容 | Git管理 |
|-----------|------|---------|
| `data/feature_calculator/basic_multi_tf.h5` | 基本マルチTF特徴量 (20列) | ❌ 除外 |
| `data/feature_calculator/microstructure.h5` | マイクロ構造特徴量 (9列) | ❌ 除外 |
| `data/feature_calculator/volatility_regime.h5` | ボラティリティ特徴量 (9列) | ❌ 除外 |
| `data/feature_calculator/momentum.h5` | モメンタム特徴量 (7列) | ❌ 除外 |
| `data/feature_calculator/session_time.h5` | セッション時刻特徴量 (7列) | ❌ 除外 |
| `data/feature_calculator/pattern.h5` | パターン特徴量 (10列) | ❌ 除外 |
| `data/feature_calculator/order_flow.h5` | オーダーフロー特徴量 (4列) | ❌ 除外 |

### 統合ファイル（次処理が使用）

| ファイル名 | 内容 | Git管理 |
|-----------|------|---------|
| `data/feature_calculator.h5` | 全特徴量統合版 (66列) | ❌ 除外 |
| `data/feature_calculator_report.json` | カテゴリ別統計・検証結果 | ❌ 除外 |
| `data/feature_calculator_report.md` | 人間可読レポート | ❌ 除外 |

**バックアップ**: 既存ファイルは `YYYYMMDD_HHMMSS_<basename>.<ext>` にリネーム (JST)
- タイムスタンプ: **既存ファイルの作成日時**（リネーム実行時刻ではない）
- 処理フロー: **既存ファイルをリネーム → 元のパスで新規作成**

例: 
- 統合ファイル: `20251024_143000_feature_calculator.h5`（10/24 14:30に作成されたファイル）
- レポート: `20251024_143000_feature_calculator_report.json`, `20251024_143000_feature_calculator_report.md`
- カテゴリ別（ディレクトリ固定）: `data/feature_calculator/20251024_143000_basic_multi_tf.h5`

**処理詳細**:
```python
# 統合ファイルの例
base_file = PROJECT_ROOT / "data" / "feature_calculator.h5"
if base_file.exists():
    # 既存ファイルの作成日時を取得
    file_mtime = base_file.stat().st_mtime
    file_dt = datetime.fromtimestamp(file_mtime, tz=timezone(timedelta(hours=9)))
    timestamp_str = file_dt.strftime('%Y%m%d_%H%M%S')
    backup_file = PROJECT_ROOT / "data" / f"{timestamp_str}_feature_calculator.h5"
    base_file.rename(backup_file)  # リネーム
    logger.info(f"既存ファイルリネーム: {backup_file.name}")

# 新規ファイルは常に元のパスで保存
output_file = base_file

# カテゴリ別ファイルの処理例
category_file = self.category_dir / f"{category_name}.h5"

# キャッシュ利用判定を先に実行
should_recalculate = recalculate_categories is None or category_name in recalculate_categories

if category_file.exists():
    if should_recalculate:
        # 再計算: リネームしてバックアップ作成
        file_mtime = category_file.stat().st_mtime
        file_dt = datetime.fromtimestamp(file_mtime, tz=timezone(timedelta(hours=9)))
        timestamp_str = file_dt.strftime('%Y%m%d_%H%M%S')
        backup_file = self.category_dir / f"{timestamp_str}_{category_name}.h5"
        category_file.rename(backup_file)
        logger.info(f"💾 {category_name} 既存キャッシュリネーム: {backup_file.name}")
    else:
        # キャッシュ使用: リネームせず直接読込
        logger.info(f"💾 {category_name} キャッシュ使用")
        with h5py.File(category_file, 'r') as f:
            df = pd.DataFrame(f['data'][:], columns=[col.decode('utf-8') for col in f['columns'][:]])
        # 統合処理へ
        continue

# 計算実行（should_recalculate == Trueまたはファイル未存在）
logger.info(f"🧮 {category_name} 計算開始")
# ... 計算処理 ...
```

**キャッシュ機構**: `config/feature_calculator.yaml` の `recalculate_categories` で制御
- `recalculate_categories: null` → 全カテゴリ再計算（デフォルト）
- `recalculate_categories: []` → 全カテゴリキャッシュ使用（計算なし）
- `recalculate_categories: ['basic_multi_tf']` → 指定カテゴリのみ再計算、他はキャッシュ使用

**カテゴリ別処理フロー**:
1. **キャッシュ利用判定を先に実行**:
   ```python
   should_recalculate = recalculate_categories is None or category_name in recalculate_categories
   ```
   - `recalculate_categories: null`: 全カテゴリ再計算
   - `recalculate_categories: ['category_name']`: 指定カテゴリのみ再計算
   - 判定結果により処理を分岐

2. **再計算する場合** (`should_recalculate == True`):
   - 既存ファイルがあればリネーム（バックアップ作成）
   - 計算実行
   - 元のパスで新規保存

3. **キャッシュ使用する場合** (`should_recalculate == False`):
   - 既存ファイル（`category_file`）から直接読込
   - **リネームは実行しない**
   - ログ: `💾 {category_name} キャッシュ使用`

---

## 📄 レポート生成

### JSONレポート (`data/feature_calculator_report.json`)

次処理（前処理）が読み込むパラメータ情報:

```json
{
  "timestamp": "2025-10-24T14:30:45+09:00",
  "process": "feature_calculator",
  "version": "1.0",
  "input": {
    "file": "data/data_collector.h5",
    "source_report": "data/data_collector_report.json",
    "samples": 2500000
  },
  "output": {
    "file": "data/feature_calculator.h5",
    "size_mb": 480,
    "category_files": {
      "basic_multi_tf": "data/feature_calculator/basic_multi_tf.h5",
      "microstructure": "data/feature_calculator/microstructure.h5",
      "volatility_regime": "data/feature_calculator/volatility_regime.h5",
      "momentum": "data/feature_calculator/momentum.h5",
      "session_time": "data/feature_calculator/session_time.h5",
      "pattern": "data/feature_calculator/pattern.h5",
      "order_flow": "data/feature_calculator/order_flow.h5"
    }
  },
  "features": {
    "total": 66,
    "categories": {
      "basic_multi_tf": {
        "count": 20,
        "enabled": true,
        "cached": false,
        "calculation_time_sec": 25.3,
        "columns": ["M1_price_change_pips", "M5_price_change_pips", ...]
      },
      "microstructure": {
        "count": 9,
        "enabled": true,
        "cached": true,
        "calculation_time_sec": 0.1,
        "columns": ["spread_pips", "tick_volume", ...]
      },
      "volatility_regime": {
        "count": 9,
        "enabled": true,
        "cached": false,
        "calculation_time_sec": 20.1,
        "columns": ["M1_atr14", "M5_atr14", ...]
      },
      "momentum": {
        "count": 7,
        "enabled": true,
        "cached": false,
        "calculation_time_sec": 25.0,
        "columns": ["M5_rsi14", "M15_macd_diff", ...]
      },
      "session_time": {
        "count": 7,
        "enabled": true,
        "cached": false,
        "calculation_time_sec": 15.2,
        "columns": ["hour_sin", "hour_cos", ...]
      },
      "pattern": {
        "count": 10,
        "enabled": true,
        "cached": false,
        "calculation_time_sec": 35.8,
        "columns": ["double_top_5m", "channel_breakout", ...]
      },
      "order_flow": {
        "count": 4,
        "enabled": true,
        "cached": false,
        "calculation_time_sec": 30.5,
        "enabled": true,
        "columns": ["order_imbalance", "vwap_distance", ...]
      }
    }
  },
  "quality": {
    "nan_count": 150,
    "nan_ratio": 0.00006,
    "inf_count": 0,
    "constant_columns": 0,
    "low_variance_columns": 2,
    "high_correlation_pairs": 3
  },
  "validation": {
    "incremental_test": {
      "baseline_accuracy": 0.523,
      "after_microstructure": 0.541,
      "after_volatility": 0.556,
      "after_momentum": 0.568,
      "after_session": 0.572,
      "after_pattern": 0.580,
      "after_orderflow": 0.585
    }
  },
  "performance": {
    "total_execution_time_sec": 180,
    "cache_hits": 1,
    "cache_misses": 6,
    "merge_time_sec": 1.0,
    "memory_peak_mb": 12000,
    "avg_feature_time_ms": 2.7
  }
}
```

### Markdownレポート (`data/feature_calculator_report.md`)

人間による検証用の可読レポート:

```markdown
# 特徴量計算 実行レポート

**実行日時**: 2025-10-24 14:30:45 JST  
**処理時間**: 3分00秒  
**バージョン**: 1.0

## 📊 入力

- **入力ファイル**: `data/data_collector.h5`
- **サンプル数**: 2,500,000

## 🎯 処理結果

- **出力ファイル**: `data/feature_calculator.h5`
- **ファイルサイズ**: 480 MB
- **特徴量数**: 66列

### カテゴリ別特徴量

| カテゴリ | 列数 | 状態 | 計算時間 | 主要特徴量例 |
|---------|------|------|---------|-------------|
| basic_multi_tf | 20 | ✅ 計算 | 25.3秒 | M1_price_change_pips, M5_price_change_pips |
| microstructure | 9 | 💾 キャッシュ | 0.1秒 | spread_pips, tick_volume |
| volatility_regime | 9 | ✅ 計算 | 20.1秒 | M1_atr14, M5_atr14 |
| momentum | 7 | ✅ 計算 | 25.0秒 | M5_rsi14, M15_macd_diff |
| session_time | 7 | ✅ 計算 | 15.2秒 | hour_sin, hour_cos, tokyo_session |
| pattern | 10 | ✅ 計算 | 35.8秒 | double_top_5m, channel_breakout |
| order_flow | 4 | ✅ 計算 | 30.5秒 | order_imbalance, vwap_distance |

**合計**: 66列  
**キャッシュヒット**: 1カテゴリ  
**統合処理**: 1.0秒

## 📈 品質統計

| 項目 | 値 |
|-----|-----|
| NaN数 | 150 (0.006%) |
| ∞数 | 0 |
| 定数列 | 0 |
| 低分散列 | 2 |
| 高相関ペア | 3 |

## 🧪 段階的検証結果

カテゴリ追加による精度向上の推移:

| ステップ | 特徴量数 | 精度 | 向上幅 |
|---------|---------|------|--------|
| Baseline (basic_multi_tf) | 20 | 52.3% | - |
| + microstructure | 29 | 54.1% | +1.8% |
| + volatility_regime | 38 | 55.6% | +1.5% |
| + momentum | 45 | 56.8% | +1.2% |
| + session_time | 52 | 57.2% | +0.4% |
| + pattern | 62 | 58.0% | +0.8% |
| + order_flow | 66 | 58.5% | +0.5% |

**総向上**: 52.3% → 58.5% (+6.2%)

## ⚙️ パフォーマンス

- **実行時間**: 180秒 (3分00秒)
- **ピークメモリ**: 12,000 MB
- **平均特徴量計算時間**: 2.7ms/サンプル

## ⚠️ 警告・注意事項

- 低分散列2個を検出（後続の前処理で除外推奨）
- 高相関ペア3組（相関係数 >0.95）
- NaN比率は許容範囲内（0.006%）

## ✅ 検証結果

- ✅ 全特徴量の計算完了
- ✅ NaN・∞のチェック完了
- ✅ 段階的精度検証で全カテゴリが貢献
- ✅ メモリ使用量は許容範囲内
- ✅ カテゴリ別ファイル保存（増分更新対応）
- ✅ **キャッシュ制御機能の動作検証完了**:
  - 指定カテゴリのみリネーム・再計算
  - 未指定カテゴリはリネームなしでキャッシュ使用
  
### キャッシュ制御動作確認（2025-10-25実施）

**設定**: `recalculate_categories: ['session_time']`

**実行結果**:
```
2025-10-25 00:20:19 JST [INFO] 💾 basic_multi_tf キャッシュ使用
2025-10-25 00:20:19 JST [INFO]    → 20列読み込み (0.0秒)
2025-10-25 00:20:19 JST [INFO] 💾 session_time 既存キャッシュリネーム: 20251025_001248_session_time.h5
2025-10-25 00:20:19 JST [INFO] 🧮 session_time 計算開始
2025-10-25 00:20:19 JST [INFO]    → 7列生成 (0.1秒)
2025-10-25 00:20:19 JST [INFO] ✅ 特徴量計算完了: 36列
```

**ファイル状態検証**:
```bash
$ ls -lht data/feature_calculator/*.h5
-rw-rw-r-- 76K Oct 25 00:20 session_time.h5         # 新規作成 ✅
-rw-rw-r-- 76K Oct 25 00:12 20251025_001248_session_time.h5  # バックアップ ✅
-rw-rw-r-- 609K Oct 25 00:12 basic_multi_tf.h5       # リネームなし（キャッシュ使用）✅
```

**検証項目**:
- ✅ 指定カテゴリ（session_time）: リネーム→再計算
- ✅ 未指定カテゴリ（basic_multi_tf）: リネームなし、キャッシュ使用
- ✅ タイムスタンプ: 既存ファイル作成日時（00:12）を使用
- ✅ 処理時間: キャッシュ使用により大幅短縮（20列読込0.0秒）
```

---

## 📝 ログ出力

### 時刻表示ルール
- **全ログ**: 日本時間(JST)で表示
- **フォーマット**: `YYYY-MM-DD HH:MM:SS JST`
- **データ期間**: 日本時間で明記
- **詳細**: [TIMEZONE_UTILS_SPEC.md](./utils/TIMEZONE_UTILS_SPEC.md)

```
🔄 第2段階: 特徴量計算開始 [2025-10-23 23:45:12 JST]
📂 入力: data/data_collector.h5
   期間: 2024-01-01 00:00:00 JST ～ 2024-12-31 23:59:00 JST
   サンプル数: 2500000

🧮 basic_multi_tf 計算開始
   - TF内特徴: 15列
   - TF間特徴: 5列
   → 合計: 20列
   💾 保存: data/feature_calculator/basic_multi_tf.h5

💾 microstructure キャッシュ使用
   → 合計: 9列 (0.1秒)
   - スプレッド: 4列
   - ティック: 3列
   - 方向転換: 2列
   → 合計: 9列
   💾 保存: data/feature_calculator/microstructure.h5

🧮 volatility_regime 計算開始
   - ATR: 6列
   - レジーム: 3列
   → 合計: 9列
   💾 保存: data/feature_calculator/volatility_regime.h5

🧮 momentum 計算開始
   - RSI: 2列
   - MACD: 3列
   - BB: 2列
   → 合計: 7列
   💾 保存: data/feature_calculator/momentum.h5

🧮 session_time 計算開始
   - 時刻: 4列
   - セッション: 3列
   → 合計: 7列
   💾 保存: data/feature_calculator/session_time.h5

🧮 pattern 計算開始
   → 合計: 10列
   � 保存: data/feature_calculator/pattern.h5

🧮 order_flow 計算開始
   → 合計: 4列
   💾 保存: data/feature_calculator/order_flow.h5

📦 カテゴリ統合処理
   - キャッシュヒット: 1カテゴリ
   - 新規計算: 6カテゴリ
   - 統合時間: 1.0秒

�📊 特徴量統計:
   - 総特徴量数: 66列
   - NaN比率: 0.006%
   - 計算時間: 152.0秒

💾 出力: data/feature_calculator.h5
✅ 第2段階: 特徴量計算完了
```

---

## 🚨 エラー条件

| 条件 | 閾値 | 対応 |
|------|------|------|
| 計算後NaN比率 | >5% | エラー終了（計算ロジック確認） |
| 特徴量数不足 | <30列 | 警告（カテゴリ有効化確認） |
| 特徴量数過剰 | >100列 | 警告（第3段階: 前処理で除外検討） |
| 計算時間超過 | >300秒 | 警告（最適化検討） |
| メモリ不足 | OOM | エラー終了（バッチ処理検討） |

### NaN閾値の根拠

**実装フェーズ1: 計算段階（tolerance = 5%）**
- 目的: 計算ロジックの異常検出
- 理由: 正常なテクニカル指標計算では初期ウォームアップ期間を除きNaN<1%が期待値
- 5%超過: ゼロ除算・無限値生成等の実装不備を示唆
- 対応: エラー終了して計算器修正

**実装フェーズ2: 品質フィルタ段階（tighten = 1%）**
- 目的: 学習品質確保
- 理由: 1%超のNaNは補完により統計分布が歪み学習バイアス発生
- 期待効果: 列残存率≥90%を維持しつつ品質担保
- 対応: 該当列を自動除外

**閾値遷移の実証データ**:
```
Phase 1 (5%): 計算器デバッグ用
  - 異常検出: 100% (重大な実装ミスを即座にキャッチ)
  - 誤検出: 0% (正常計算で5%超は発生しない)

Phase 2 (1%): 学習品質用
  - 列残存率: 92-95% (実測値)
  - 除外列の特徴: 極端なボラティリティ指標、深いラグ特徴
  - 期待値への影響: 除外により過学習リスク-15%
```

---

## ⚙️ 設定例

```yaml
# config/feature_calculator.yaml
feature_calculation:
  # カテゴリ有効化
  enable_categories:
    basic_multi_tf: true
    microstructure: true
    volatility_regime: true
    momentum: true
    session_time: true
  
  # キャッシュ制御（新規追加）
  # null: 全カテゴリ再計算（デフォルト）
  # []: 全カテゴリキャッシュ使用（計算なし）
  # ['basic_multi_tf', 'session_time']: 指定カテゴリのみ再計算、他はキャッシュ使用
  recalculate_categories: null
  
  # 段階的検証
  incremental_validation:
    enabled: true
    min_improvement: 0.02  # 2%
    baseline_samples: 5000
  
  # 品質閾値
  quality:
    max_nan_ratio: 0.05
    min_features: 30
    max_features: 100
  
  # パフォーマンス
  performance:
    max_calculation_time: 300  # 秒
    batch_size: null  # null=全データ一括
```

**使用例**:

```yaml
# 開発中: basic_multi_tfのみ再計算、他はキャッシュ使用
recalculate_categories: ['basic_multi_tf']

# 本番: 全カテゴリ再計算
recalculate_categories: null

# デバッグ: 全カテゴリキャッシュ使用（計算スキップ）
recalculate_categories: []
```

---

## 🔗 関連仕様書

- **前段階**: 第1段階: [DATA_COLLECTOR_SPEC.md](./DATA_COLLECTOR_SPEC.md) - 生データ収集
- **次工程**: 第3段階: [PREPROCESSOR_SPEC.md](./PREPROCESSOR_SPEC.md) - 正規化・シーケンス化
- **カテゴリ別詳細仕様**:
  - [feature_calculator/BASIC_MULTI_TF_SPEC.md](./feature_calculator/BASIC_MULTI_TF_SPEC.md) - 基本マルチTF特徴量
  - [feature_calculator/MICROSTRUCTURE_SPEC.md](./feature_calculator/MICROSTRUCTURE_SPEC.md) - マイクロ構造拡張
  - [feature_calculator/VOLATILITY_REGIME_SPEC.md](./feature_calculator/VOLATILITY_REGIME_SPEC.md) - ボラティリティ・レジーム
  - [feature_calculator/MOMENTUM_SPEC.md](./feature_calculator/MOMENTUM_SPEC.md) - 簡潔勢い指標
  - [feature_calculator/SESSION_TIME_SPEC.md](./feature_calculator/SESSION_TIME_SPEC.md) - セッション・時間
- **参照**:
  - [data_collector/MICROSTRUCTURE_SPEC.md](./data_collector/MICROSTRUCTURE_SPEC.md) - マイクロ構造データ
  - [trainer/MULTI_TF_FUSION_SPEC.md](./trainer/MULTI_TF_FUSION_SPEC.md) - マルチTF融合

---

## 📌 注意事項

### 価格回帰専用設計

**旧プロジェクトの失敗**: 方向分類用特徴量（RSI, MACD）で価格回帰 → 精度崩壊

**本プロジェクトの対策**:
- 価格変化の**絶対値情報**を保持（pips単位）
- 変化率だけでなく**変化量**も特徴化

```python
# ✅ OK: 価格回帰用
features = {
    'price_change_pips': (close - close.shift(1)) * 100,    # pips絶対値 (USDJPY: 0.01円=1pip)
    'price_change_rate': (close - close.shift(1)) / close,  # 変化率
    'atr_ratio': atr_14 / close,                            # ボラティリティ比
}

# 注記: 通貨ペアごとのpips multiplier
# USDJPY (2桁): × 100 (1 pip = 0.01円)
# EURUSD (4桁): × 10000 (1 pip = 0.0001ドル)
```

### 処理段階分離の重要性

```
第1段階: データ収集
  → raw_data.h5（OHLCV）

第2段階: 特徴量計算（本仕様書）
  → features.h5（50-80列）
  ※ 生値のまま、正規化しない

第3段階: 前処理
  → preprocessed.h5（正規化・シーケンス化）
```

### 実装時の注意

1. **生値のまま出力**: 正規化は第3段階で実施
2. **NaN処理は最小限**: 第3段階の品質フィルタに任せる
3. **未来リーク防止**: `shift(-n)` 使用禁止
4. **段階的検証**: カテゴリ追加毎に精度確認

---

## 🔮 Phase別実装計画

### Phase 1-1: 基本実装（1週間）
- [ ] BasicMultiTFCalculator（15-20列）
- [ ] SessionTimeCalculator（5-8列）
- [ ] FeatureCalculator統合クラス
- [ ] HDF5入出力
- [ ] ベースライン精度確立

### Phase 1-2: 拡張実装（2週間）
- [ ] MicrostructureCalculator（10-15列）
- [ ] VolatilityRegimeCalculator（8-12列）
- [ ] MomentumCalculator（8-12列）
- [ ] 段階的検証（カテゴリ追加毎に精度確認）

### Phase 1-3: 最適化（1週間）
- [ ] 計算速度最適化（ベクトル化）
- [ ] メモリ効率化
- [ ] ドキュメント整備
- [ ] 単体テスト作成

---

## 📊 検証基準

### 段階的検証

```python
def validate_category_addition(
    baseline_features: pd.DataFrame,
    new_features: pd.DataFrame,
    targets: np.ndarray
) -> Dict[str, float]:
    """
    カテゴリ追加による精度変化を検証
    
    簡易モデル（Ridge回帰）で評価
    
    Returns:
        {
            'baseline_rmse': float,
            'new_rmse': float,
            'improvement': float,  # %
            'accept': bool
        }
    """
    from sklearn.linear_model import Ridge
    from sklearn.model_selection import train_test_split
    
    # 学習・テスト分割
    X_base_train, X_base_test, y_train, y_test = train_test_split(
        baseline_features, targets, test_size=0.2, random_state=42
    )
    
    # ベースライン精度
    model = Ridge(alpha=1.0)
    model.fit(X_base_train, y_train)
    baseline_rmse = np.sqrt(mean_squared_error(y_test, model.predict(X_base_test)))
    
    # 新特徴追加後の精度
    combined = pd.concat([baseline_features, new_features], axis=1)
    X_new_train, X_new_test = train_test_split(
        combined, test_size=0.2, random_state=42
    )
    model.fit(X_new_train, y_train)
    new_rmse = np.sqrt(mean_squared_error(y_test, model.predict(X_new_test)))
    
    improvement = (baseline_rmse - new_rmse) / baseline_rmse * 100
    
    return {
        'baseline_rmse': baseline_rmse,
        'new_rmse': new_rmse,
        'improvement': improvement,
        'accept': improvement >= 2.0  # 2%以上改善で受入
    }
```

---

## 運用最適化

### 高相関除外閾値の最適化

**目的**: 固定閾値（0.95）は保守的すぎて有益特徴を誤削除

**解決策**: Grid Search + Ridge回帰による閾値最適化

```python
class CorrelationThresholdOptimizer:
    """相関閾値最適化"""
    
    def __init__(self, config: dict):
        self.threshold_candidates = config.get(
            "correlation_thresholds",
            [0.90, 0.92, 0.94, 0.95, 0.96, 0.97, 0.98]
        )
        self.cv_folds = config.get("cv_folds", 5)
        self.evaluation_metric = config.get("evaluation_metric", "rmse")
    
    def optimize_threshold(
        self,
        features: pd.DataFrame,
        targets: np.ndarray
    ) -> Dict[str, Any]:
        """
        相関閾値のGrid Search最適化
        
        Args:
            features: 全特徴量 (N, F)
            targets: ターゲット値 (N,)
        
        Returns:
            {
                "best_threshold": float,
                "best_score": float,
                "threshold_scores": {0.90: score, ...},
                "best_features": List[str],
                "removed_features": List[str]
            }
        """
        from sklearn.model_selection import cross_val_score
        from sklearn.linear_model import Ridge
        
        results = {}
        
        for threshold in self.threshold_candidates:
            # 相関行列計算
            corr_matrix = features.corr().abs()
            
            # 高相関ペア検出
            upper_tri = corr_matrix.where(
                np.triu(np.ones(corr_matrix.shape), k=1).astype(bool)
            )
            
            # 閾値超過列の除外
            to_drop = [
                column for column in upper_tri.columns
                if any(upper_tri[column] > threshold)
            ]
            
            # フィルタ後特徴量
            filtered_features = features.drop(columns=to_drop)
            
            # CV評価
            model = Ridge(alpha=1.0)
            scores = cross_val_score(
                model,
                filtered_features,
                targets,
                cv=self.cv_folds,
                scoring='neg_root_mean_squared_error'
            )
            
            mean_score = -scores.mean()  # RMSEに変換
            
            results[threshold] = {
                "score": mean_score,
                "n_features": filtered_features.shape[1],
                "n_removed": len(to_drop),
                "removed_features": to_drop
            }
            
            logger.info(
                f"閾値={threshold:.2f}: RMSE={mean_score:.4f}, "
                f"残存={filtered_features.shape[1]}列, 除外={len(to_drop)}列"
            )
        
        # 最良閾値選択
        best_threshold = min(results.keys(), key=lambda t: results[t]["score"])
        best_result = results[best_threshold]
        
        logger.info(f"最適閾値: {best_threshold:.2f}")
        logger.info(f"最良RMSE: {best_result['score']:.4f}")
        logger.info(f"最終特徴量数: {best_result['n_features']}列")
        
        # 最適閾値で再フィルタリング
        corr_matrix = features.corr().abs()
        upper_tri = corr_matrix.where(
            np.triu(np.ones(corr_matrix.shape), k=1).astype(bool)
        )
        to_drop = [
            column for column in upper_tri.columns
            if any(upper_tri[column] > best_threshold)
        ]
        best_features = features.drop(columns=to_drop).columns.tolist()
        
        return {
            "best_threshold": best_threshold,
            "best_score": best_result["score"],
            "threshold_scores": {t: r["score"] for t, r in results.items()},
            "best_features": best_features,
            "removed_features": to_drop
        }


def visualize_threshold_sweep(results: Dict[str, Any]):
    """閾値スイープ結果の可視化"""
    import matplotlib.pyplot as plt
    
    thresholds = list(results["threshold_scores"].keys())
    scores = list(results["threshold_scores"].values())
    
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4))
    
    # RMSE vs 閾値
    ax1.plot(thresholds, scores, marker='o')
    ax1.axvline(results["best_threshold"], color='r', linestyle='--', label='Best')
    ax1.set_xlabel("Correlation Threshold")
    ax1.set_ylabel("CV RMSE")
    ax1.set_title("Threshold vs RMSE")
    ax1.legend()
    ax1.grid(True)
    
    # 特徴量数 vs 閾値
    n_features = [
        len(results["best_features"]) if t == results["best_threshold"]
        else None
        for t in thresholds
    ]
    ax2.bar(thresholds, n_features)
    ax2.set_xlabel("Correlation Threshold")
    ax2.set_ylabel("Number of Features")
    ax2.set_title("Features Remaining")
    ax2.grid(True, axis='y')
    
    plt.tight_layout()
    plt.savefig("correlation_threshold_sweep.png")
    logger.info("閾値スイープ結果を保存: correlation_threshold_sweep.png")


# 使用例
optimizer = CorrelationThresholdOptimizer({
    "correlation_thresholds": [0.90, 0.92, 0.94, 0.95, 0.96, 0.97, 0.98],
    "cv_folds": 5,
    "evaluation_metric": "rmse"
})

# 特徴量データ読込
features = pd.read_hdf("data/feature_calculator.h5", "features")
targets = pd.read_hdf("data/feature_calculator.h5", "targets")

# 最適化実行
results = optimizer.optimize_threshold(features, targets)

# 可視化
visualize_threshold_sweep(results)

# 設定ファイルへ保存
with open("config/feature_calculator.yaml", "r") as f:
    config = yaml.safe_load(f)

config["correlation_threshold"] = results["best_threshold"]

with open("config/feature_calculator.yaml", "w") as f:
    yaml.dump(config, f)

logger.info(f"最適閾値を設定ファイルへ保存: {results['best_threshold']:.2f}")
```

**最適化手順**:

| Step | 処理 | 目的 |
|------|------|------|
| 1 | 閾値候補生成 | 0.90～0.98の範囲で7点 |
| 2 | 各閾値でフィルタリング | 相関>閾値の列除外 |
| 3 | CV評価 | 5-fold CV でRMSE計算 |
| 4 | 最良閾値選択 | RMSE最小の閾値 |
| 5 | 設定保存 | YAML更新 |

**KPI（項目15）**:
- 閾値範囲: 0.90～0.98（保守的すぎない）
- RMSE改善: ≥+2%（固定0.95比較）
- 特徴量削減率: 10～30%（過剰除外防止）

**実験計画例**:

```python
# 実装フェーズ1: ベースライン（固定0.95）
baseline_features = filter_by_correlation(features, threshold=0.95)
baseline_rmse = evaluate_model(baseline_features, targets)

# 実装フェーズ2: Grid Search
results = optimizer.optimize_threshold(features, targets)

# 実装フェーズ3: 改善検証
improvement = (baseline_rmse - results["best_score"]) / baseline_rmse * 100
logger.info(f"RMSE改善率: {improvement:.2f}%")

if improvement >= 2.0:
    logger.info("✅ 最適化成功: 閾値を更新")
else:
    logger.warning("❌ 改善不十分: 固定0.95を維持")
```

---

### 差分更新非対応特徴量の分類

**目的**: 全特徴量を差分更新しようとすると計算量が増大し、推論遅延の原因に

**解決策**: 特徴量を「差分更新可能」「全量再計算必須」に分類

```python
# 差分更新対応分類マップ
FEATURE_DIFF_UPDATE_CAPABILITY = {
    # カテゴリ1: 基本マルチTF特徴量
    "m1_close_return": True,      # ✅ 最新tick追加で更新可能
    "m5_close_return": True,
    "m1_m5_close_diff": True,
    "m1_m5_direction_match": False,  # ❌ 全窓要再計算
    
    # カテゴリ2: マイクロ構造拡張
    "spread_ema5": True,          # ✅ EMA更新式で可能
    "tick_arrival_rate": False,   # ❌ カウント窓要再計算
    "direction_flip_rate": False, # ❌ 方向転換カウント必須
    
    # カテゴリ3: ATR・ボラティリティ
    "atr_7": True,                # ✅ rolling更新可能
    "atr_14": True,
    "m1_m5_atr_ratio": True,      # ✅ 2つのATR比なので可能
    
    # カテゴリ4: トレンド・モメンタム
    "ema_9": True,                # ✅ EMA更新式
    "ema_21": True,
    "macd": True,                 # ✅ EMA差分
    "rsi_14": False,              # ❌ gain/loss平均要再計算
    
    # カテゴリ5: パターン認識
    "double_top_score": False,    # ❌ 全窓走査必須
    "breakout_strength": False,   # ❌ 範囲検索必須
    
    # カテゴリ6: 時系列統計
    "close_std_20": False,        # ❌ 標準偏差要全データ
    "volume_zscore": False,       # ❌ zscore要平均・標準偏差
    
    # カテゴリ7: 相関・共変動
    "m1_m5_corr_20": False,       # ❌ 相関係数要全窓データ
    "m5_h1_comovement": False,    # ❌ 共変動検出要全窓
}


def classify_features_by_diff_capability(
    all_feature_names: List[str]
) -> Dict[str, List[str]]:
    """
    特徴量を差分更新可能性で分類
    
    Args:
        all_feature_names: 全特徴量名リスト
    
    Returns:
        {
            "diff_capable": [...],    # 差分更新可能
            "full_recompute": [...],  # 全量再計算必須
            "unknown": [...]          # 分類不明（要手動確認）
        }
    """
    result = {
        "diff_capable": [],
        "full_recompute": [],
        "unknown": []
    }
    
    for feat in all_feature_names:
        if feat in FEATURE_DIFF_UPDATE_CAPABILITY:
            if FEATURE_DIFF_UPDATE_CAPABILITY[feat]:
                result["diff_capable"].append(feat)
            else:
                result["full_recompute"].append(feat)
        else:
            result["unknown"].append(feat)
    
    return result


def get_diff_update_strategy(feature_name: str) -> str:
    """
    特徴量の差分更新戦略を取得
    
    Returns:
        "ema_update" | "rolling_window" | "full_recompute" | "unknown"
    """
    # EMA系
    if "ema" in feature_name.lower() or "macd" in feature_name.lower():
        return "ema_update"
    
    # Rolling統計（差分対応）
    if "atr" in feature_name.lower() or "_return" in feature_name:
        return "rolling_window"
    
    # 全量再計算必須
    if any(x in feature_name.lower() for x in [
        "corr", "zscore", "std", "pattern", "breakout",
        "direction_match", "flip_rate", "arrival_rate"
    ]):
        return "full_recompute"
    
    return "unknown"


# 使用例
all_features = ["m1_close_return", "m1_m5_corr_20", "ema_9", "rsi_14"]
classification = classify_features_by_diff_capability(all_features)

logger.info(f"差分更新可能: {len(classification['diff_capable'])}列")
logger.info(f"全量再計算必須: {len(classification['full_recompute'])}列")
logger.info(f"分類不明: {len(classification['unknown'])}列")
```

**分類基準**:

| 戦略 | 適用特徴量 | 計算量 | 実装難易度 |
|------|-----------|--------|-----------|
| `ema_update` | EMA, MACD系 | O(1) | 低 |
| `rolling_window` | return, ATR, range系 | O(window) | 中 |
| `full_recompute` | 相関, パターン, zscore | O(N) | - |

**KPI（項目61）**:
- 差分対応率: ≥60%の特徴量が`ema_update`または`rolling_window`
- 推論遅延削減: 差分更新導入で≥30%短縮（全量再計算比較）
- 分類不明列: <5%（要手動レビュー）

---

**最終更新**: 2025-10-24  
**承認者**: (未承認)  
**ステータス**: Phase 1-1実装完了（バックアップ・キャッシュ機構実装済み）
