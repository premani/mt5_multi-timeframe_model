# Config Manager Specification

## 目的

全フェーズ共通の設定管理モジュールを定義し、YAML設定ファイルの読み込み・検証・アクセスを統一する。

---

## 設計方針

### 共通化の利点

1. **コード重複削減**: 各フェーズで個別実装していた ConfigManager を統一
2. **規約統一**: ファイル命名、YAML構造、パラメータ命名を一元管理
3. **クロスファイル整合性**: symbol, timeframes 等の共通パラメータを自動検証
4. **保守性向上**: 設定変更時の影響範囲を最小化

### 旧プロジェクトからの改善

**旧プロジェクト**:
- 各フェーズで独自の ConfigManager 実装
- 設定ファイル形式がフェーズごとに異なる
- クロスファイル検証なし

**本プロジェクト**:
- `src/utils/config_manager.py` で統一
- 4フェーズ共通の構造規約
- 共通パラメータの自動整合性チェック

---

## ファイル構成

### 設定ファイル配置

```
config/
├── data_collector_config.template.yaml   # テンプレート（Git管理）
├── data_collector_config.yaml            # 実運用（Git管理外）
├── preprocessor_config.template.yaml
├── preprocessor_config.yaml
├── trainer_config.template.yaml
├── trainer_config.yaml
├── validator_config.template.yaml
└── validator_config.yaml
```

### 命名規則

| フェーズ | テンプレート | 実ファイル |
|---------|------------|----------|
| データ収集 | `data_collector_config.template.yaml` | `data_collector_config.yaml` |
| 前処理 | `preprocessor_config.template.yaml` | `preprocessor_config.yaml` |
| 学習 | `trainer_config.template.yaml` | `trainer_config.yaml` |
| 検証 | `validator_config.template.yaml` | `validator_config.yaml` |

---

## YAML 構造規約

### トップレベルキー

各フェーズの設定ファイルは以下のトップレベルキーを持つ：

```yaml
# 共通セクション（全フェーズ必須）
common:
  symbol: "USDJPY"
  timeframes: ["M1", "M5", "M15", "H1", "H4"]
  project_name: "mt5_multi_timeframe_model"

# フェーズ固有セクション
<phase_name>:
  # フェーズ固有パラメータ
  ...

# パス設定（オプション）
paths:
  input_dir: "data"
  output_dir: "models"
  log_dir: "logs"
```

### インデント・フォーマット規約

- **インデント**: 2スペース統一
- **リスト**: ハイフン形式（`- item`）
- **コメント**: 各セクションに日本語説明必須
- **論理値**: `true` / `false`（小文字）
- **NULL値**: `null`

**例**:
```yaml
# データ収集設定
data_collector:
  # 取得期間
  period:
    start_date: "2024-01-01"  # 開始日（YYYY-MM-DD形式）
    end_date: "2024-03-31"    # 終了日
  
  # タイムフレーム設定
  timeframes:
    - M1   # 1分足
    - M5   # 5分足
    - M15  # 15分足
    - H1   # 1時間足
    - H4   # 4時間足
  
  # マイクロ構造設定
  microstructure:
    enabled: true         # 有効化フラグ
    tick_threshold: 10    # Tick閾値
```

---

## ConfigManager 基底クラス

### クラス設計

```python
from pathlib import Path
from typing import Dict, Any, Optional
import yaml
import logging

logger = logging.getLogger(__name__)


class ConfigManager:
    """全フェーズ共通の設定管理基底クラス"""
    
    def __init__(
        self,
        config_path: Optional[str] = None,
        phase_name: str = None,
        required_sections: list[str] = None
    ):
        """
        Args:
            config_path: 設定ファイルパス（省略時はデフォルト）
            phase_name: フェーズ名（data_collector, preprocessor, trainer, validator）
            required_sections: 必須セクションリスト
        """
        self.phase_name = phase_name
        self.required_sections = required_sections or ['common']
        
        # デフォルトパス設定
        if config_path is None:
            config_path = f"config/{phase_name}_config.yaml"
        
        self.config_path = Path(config_path)
        self.config = self._load_config()
        self._validate_config()
    
    def _load_config(self) -> Dict[str, Any]:
        """設定ファイルを読み込み"""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            
            logger.info(f"✅ 設定ファイル読み込み: {self.config_path}")
            return config
        
        except FileNotFoundError:
            template_path = self.config_path.parent / f"{self.config_path.stem}.template.yaml"
            
            if template_path.exists():
                logger.error(
                    f"❌ 設定ファイルが存在しません: {self.config_path}\n"
                    f"   テンプレートからコピーしてください:\n"
                    f"   cp {template_path} {self.config_path}"
                )
            else:
                logger.error(
                    f"❌ 設定ファイルもテンプレートも見つかりません: {self.config_path}"
                )
            raise
        
        except yaml.YAMLError as e:
            logger.error(f"❌ YAML解析エラー: {e}")
            raise
    
    def _validate_config(self):
        """設定ファイルの基本検証"""
        # 必須セクション存在確認
        for section in self.required_sections:
            if section not in self.config:
                raise ValueError(f"必須セクション欠如: {section}")
        
        # 共通セクションの必須パラメータ確認
        if 'common' in self.config:
            common = self.config['common']
            
            if 'symbol' not in common:
                raise ValueError("common.symbol が未定義")
            
            if 'timeframes' not in common or not common['timeframes']:
                raise ValueError("common.timeframes が未定義または空")
    
    def get_common_config(self) -> Dict[str, Any]:
        """共通設定を取得"""
        return self.config.get('common', {})
    
    def get_phase_config(self) -> Dict[str, Any]:
        """フェーズ固有設定を取得"""
        return self.config.get(self.phase_name, {})
    
    def get_paths_config(self) -> Dict[str, Any]:
        """パス設定を取得"""
        return self.config.get('paths', {})
    
    def get(self, key: str, default: Any = None) -> Any:
        """設定値を取得（ドット記法対応）
        
        Args:
            key: キー（例: "common.symbol", "trainer.batch_size"）
            default: デフォルト値
        
        Returns:
            設定値
        """
        keys = key.split('.')
        value = self.config
        
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        
        return value
```

### フェーズ別 ConfigManager

各フェーズで継承して使用：

```python
class DataCollectorConfigManager(ConfigManager):
    """データ収集設定管理"""
    
    def __init__(self, config_path: Optional[str] = None):
        super().__init__(
            config_path=config_path,
            phase_name='data_collector',
            required_sections=['common', 'data_collector']
        )


class PreprocessorConfigManager(ConfigManager):
    """前処理設定管理"""
    
    def __init__(self, config_path: Optional[str] = None):
        super().__init__(
            config_path=config_path,
            phase_name='preprocessor',
            required_sections=['common', 'preprocessor']
        )


class TrainerConfigManager(ConfigManager):
    """学習設定管理"""
    
    def __init__(self, config_path: Optional[str] = None):
        super().__init__(
            config_path=config_path,
            phase_name='trainer',
            required_sections=['common', 'trainer']
        )


class ValidatorConfigManager(ConfigManager):
    """検証設定管理"""
    
    def __init__(self, config_path: Optional[str] = None):
        super().__init__(
            config_path=config_path,
            phase_name='validator',
            required_sections=['common', 'validator']
        )
```

---

## クロスファイル整合性検証

### 共通パラメータの自動チェック

```python
class ConfigCrossValidator:
    """複数設定ファイル間の整合性検証"""
    
    @staticmethod
    def validate_cross_file_consistency(
        data_collector_config: Dict[str, Any],
        preprocessor_config: Dict[str, Any],
        trainer_config: Dict[str, Any],
        validator_config: Dict[str, Any]
    ):
        """全フェーズの設定整合性を検証
        
        チェック項目:
        - symbol が全フェーズで一致
        - timeframes が全フェーズで一致
        - シーケンス長の整合性
        """
        # Symbol 整合性
        symbols = {
            'data_collector': data_collector_config['common']['symbol'],
            'preprocessor': preprocessor_config['common']['symbol'],
            'trainer': trainer_config['common']['symbol'],
            'validator': validator_config['common']['symbol']
        }
        
        if len(set(symbols.values())) > 1:
            raise ValueError(
                f"Symbol 不一致検出:\n" +
                "\n".join([f"  {k}: {v}" for k, v in symbols.items()])
            )
        
        # Timeframes 整合性
        timeframes_list = [
            set(data_collector_config['common']['timeframes']),
            set(preprocessor_config['common']['timeframes']),
            set(trainer_config['common']['timeframes']),
            set(validator_config['common']['timeframes'])
        ]
        
        if not all(tf == timeframes_list[0] for tf in timeframes_list):
            raise ValueError("Timeframes 不一致検出")
        
        # シーケンス長整合性（preprocessor → trainer）
        prep_seq_length = preprocessor_config['preprocessor'].get('sequence_length')
        train_seq_length = trainer_config['trainer'].get('input_sequence_length')
        
        if prep_seq_length and train_seq_length:
            if prep_seq_length != train_seq_length:
                raise ValueError(
                    f"シーケンス長不一致: "
                    f"preprocessor={prep_seq_length}, trainer={train_seq_length}"
                )
        
        logger.info("✅ クロスファイル整合性検証完了")
```

---

## 設定ファイルテンプレート例

### data_collector_config.template.yaml

```yaml
# マルチタイムフレームモデル - データ収集設定

# 共通設定
common:
  symbol: "USDJPY"
  timeframes: ["M1", "M5", "M15", "H1", "H4"]
  project_name: "mt5_multi_timeframe_model"

# データ収集設定
data_collector:
  # 取得期間
  period:
    mode: "months"       # days, weeks, months, years
    value: 3             # 3ヶ月分
  
  # MT5接続設定
  mt5:
    server: "MetaQuotes-Demo"
    login: 12345678
    password: "your_password"
    timeout: 60000
  
  # マイクロ構造設定
  microstructure:
    enabled: true
    tick_threshold: 10
    bid_ask_spread_max: 5.0
  
  # タイムスタンプ整合設定
  timestamp_alignment:
    method: "forward_fill"
    max_gap_minutes: 60

# パス設定
paths:
  output_dir: "data"
  backup_dir: "data/backup"
  log_dir: "logs"
```

### preprocessor_config.template.yaml

```yaml
# マルチタイムフレームモデル - 前処理設定

# 共通設定
common:
  symbol: "USDJPY"
  timeframes: ["M1", "M5", "M15", "H1", "H4"]
  project_name: "mt5_multi_timeframe_model"

# 前処理設定
preprocessor:
  # シーケンス設定
  sequence_length:
    M1: 480   # 8時間
    M5: 288   # 24時間
    M15: 192  # 48時間
    H1: 96    # 4日
    H4: 48    # 8日
  
  # 正規化設定
  normalization:
    method: "robust"      # robust, standard, minmax
    quantile_range: [0.05, 0.95]
  
  # 特徴量選択
  feature_selection:
    variance_threshold: 0.01
    correlation_threshold: 0.95
    max_features: 150

# パス設定
paths:
  input_dir: "data"
  output_dir: "models"
  log_dir: "logs"
```

### trainer_config.template.yaml

```yaml
# マルチタイムフレームモデル - 学習設定

# 共通設定
common:
  symbol: "USDJPY"
  timeframes: ["M1", "M5", "M15", "H1", "H4"]
  project_name: "mt5_multi_timeframe_model"

# 学習設定
trainer:
  # データ設定
  input_sequence_length:
    M1: 480
    M5: 288
    M15: 192
    H1: 96
    H4: 48
  
  target_length: 36
  
  # GPU最適化
  gpu_optimization:
    use_chunk_loader: true
    chunk_size_gb: 12.0
    batch_size: 128
    num_workers: 0
    pin_memory: true
    use_amp: true
  
  # モデル設定
  model:
    lstm_hidden: 128
    fusion_method: "attention"
    d_model: 128
    num_heads: 4
  
  # 学習パラメータ
  optimizer:
    type: "AdamW"
    lr: 1e-3
    weight_decay: 1e-4
  
  scheduler:
    type: "cosine"
    min_lr: 1e-6
  
  # 損失重み
  loss_weights:
    direction: 0.40
    magnitude_scalp: 0.35
    magnitude_swing: 0.15
    trend_strength: 0.10

# パス設定
paths:
  input_dir: "models"
  output_dir: "models"
  log_dir: "logs"
```

### validator_config.template.yaml

```yaml
# マルチタイムフレームモデル - 検証設定

# 共通設定
common:
  symbol: "USDJPY"
  timeframes: ["M1", "M5", "M15", "H1", "H4"]
  project_name: "mt5_multi_timeframe_model"

# 検証設定
validator:
  # バックテスト設定
  backtest:
    initial_balance: 1000000
    leverage: 25
    lot_size: 0.1
  
  # 動的Exit戦略
  dynamic_exit:
    scalp_mode:
      tp_base: 0.8
      sl_base: 0.5
    swing_mode:
      tp_base: 2.0
      trailing_stop: true
  
  # コストモデル
  cost_model:
    spread_pips: 1.2
    commission_per_lot: 0.0
    slippage_pips: 0.5
  
  # レイテンシ設定
  latency:
    max_acceptable_ms: 100
    warning_threshold_ms: 50

# パス設定
paths:
  input_dir: "models"
  output_dir: "reports"
  log_dir: "logs"
```

---

## 使用方法

### 基本的な使い方

```python
from src.utils.config_manager import TrainerConfigManager

# 設定読み込み
config_manager = TrainerConfigManager()

# 共通設定取得
symbol = config_manager.get('common.symbol')
timeframes = config_manager.get('common.timeframes')

# フェーズ固有設定取得
batch_size = config_manager.get('trainer.gpu_optimization.batch_size')
lr = config_manager.get('trainer.optimizer.lr')

# デフォルト値付き取得
chunk_size = config_manager.get('trainer.gpu_optimization.chunk_size_gb', default=12.0)
```

### クロスファイル整合性検証

```python
from src.utils.config_manager import (
    DataCollectorConfigManager,
    PreprocessorConfigManager,
    TrainerConfigManager,
    ValidatorConfigManager,
    ConfigCrossValidator
)

# 全設定読み込み
dc_config = DataCollectorConfigManager().config
prep_config = PreprocessorConfigManager().config
train_config = TrainerConfigManager().config
val_config = ValidatorConfigManager().config

# 整合性検証
ConfigCrossValidator.validate_cross_file_consistency(
    dc_config, prep_config, train_config, val_config
)
```

---

## 初期セットアップ手順

### 1. テンプレートからコピー

```bash
# 全フェーズのテンプレートをコピー
for phase in data_collector preprocessor trainer validator; do
  cp config/${phase}_config.template.yaml config/${phase}_config.yaml
done
```

### 2. 必須パラメータ編集

各ファイルで以下を編集：

- `common.symbol`: 取引通貨ペア
- `common.timeframes`: 使用するタイムフレーム
- MT5接続情報（data_collector のみ）
- パス設定（必要に応じて）

### 3. 整合性検証

```bash
# 整合性確認スクリプト実行
bash ./docker_run.sh python3 tools/utils/validate_config_consistency.py
```

---

## トラブルシューティング

### ファイルが見つからない

```
❌ 設定ファイルが存在しません: config/trainer_config.yaml
   テンプレートからコピーしてください:
   cp config/trainer_config.template.yaml config/trainer_config.yaml
```

**対処**: テンプレートからコピー

### YAML解析エラー

```
❌ YAML解析エラー: mapping values are not allowed here
```

**原因**: インデント不正、コロン後のスペース欠如  
**対処**: YAML構文を修正（インデント2スペース統一）

### クロスファイル不一致

```
❌ Symbol 不一致検出:
  data_collector: USDJPY
  preprocessor: USDJPY
  trainer: EURJPY  ← 不一致
  validator: USDJPY
```

**対処**: 全ファイルで `common.symbol` を統一

---

## 参考資料

- **プロジェクト概要**: `README.md`
- **各フェーズ仕様**: `docs/DATA_COLLECTOR_SPEC.md`, `docs/TRAINER_SPEC.md` 等
- **旧プロジェクト実装**: `mt5_lstm-model/src/*/config_manager.py`
