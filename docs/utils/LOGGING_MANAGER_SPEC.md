# LOGGING_MANAGER_SPEC - ロギング管理仕様

**バージョン**: 1.0  
**更新日**: 2025-10-23  
**参照**: `src/utils/logging_manager.py`

---

## 📋 目的

プロジェクト全体で統一されたロギング初期化・制御を提供し、モジュール毎の重複実装を排除する。

**旧プロジェクト（mt5_lstm-model）からの継承**: 実績あるログファイル命名規則・フォーマットを踏襲

---

## 🔧 提供関数

### `setup_logger(name, log_level, log_dir, log_suffix) -> Logger`

| 引数 | 型 | デフォルト | 説明 |
|------|---|-----------|------|
| `name` | str | 必須 | ロガー名（フェーズ名: `data_collector`, `feature_calculator` 等） |
| `log_level` | str | `"INFO"` | ログレベル（DEBUG / INFO / WARNING / ERROR） |
| `log_dir` | str | `"logs"` | ログ出力ディレクトリ |
| `log_suffix` | str | `""` | ログファイル名サフィックス（例: `"_validation"`） |

**戻り値**: 初期化済み `logging.Logger` インスタンス

---

## 📝 ログファイル命名規則

### フォーマット

```
logs/YYYYMMDD_HHMMSS_<phase_name><suffix>.log
```

**重要**:
- タイムスタンプは **日本時間(JST)** を使用
- フォーマット: `%Y%m%d_%H%M%S` (例: `20251023_233045`)
- 理由: 
  - 運用者の直感的な時刻理解（日本市場との対応）
  - ファイル名ソート順が実行時系列と一致

### 命名例

```
logs/20251023_233045_data_collector.log           # JST 23:30:45
logs/20251023_233120_feature_calculator.log       # JST 23:31:20
logs/20251023_233145_preprocessor.log
logs/20251023_233200_trainer.log
logs/20251023_233200_trainer_01.log               # 同一秒内2回目実行
logs/20251023_233230_trainer_validation.log       # サフィックス付き
logs/20251023_233250_onnx_converter.log
logs/20251023_233300_validator.log
```

### 衝突時の連番処理

同一秒内で複数回実行された場合、自動的に連番サフィックス（`_01`, `_02`, ..., `_99`）を付与：

```python
# 同一秒内の連番例（JST）
20251023_233200_data_collector.log      # 1回目
20251023_233200_data_collector_01.log   # 2回目（同一秒）
20251023_233200_data_collector_02.log   # 3回目（同一秒）
```

**上限**: 99回（`_01` ~ `_99`）。超過時は `RuntimeError`

---

## 📄 ログフォーマット

### 標準フォーマット

```
YYYY-MM-DD HH:MM:SS LEVEL message
```

**例**:
```
2025-10-23 14:30:45 INFO  🔄 データ収集開始
2025-10-23 14:30:50 INFO  📂 config/data_collector.yaml 読み込み
2025-10-23 14:35:12 INFO  ✅ データ収集完了
```

### Python logging 設定

```python
formatter = logging.Formatter(
    fmt='%(asctime)s %(levelname)-5s %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
```

---

## 📊 ログレベル解釈

| 指定 | Python logging | 用途 |
|------|---------------|------|
| DEBUG | logging.DEBUG (10) | 詳細なデバッグ情報・内部変数・データ形状 |
| INFO | logging.INFO (20) | 処理の進行状況・主要イベント・統計サマリ |
| WARNING | logging.WARNING (30) | 警告（処理は継続可能、要注意） |
| ERROR | logging.ERROR (40) | エラー（処理失敗・例外発生） |

### INFO と DEBUG の使い分け

| レベル | 出力内容 |
|--------|---------|
| **INFO** | フェーズ開始/完了、進捗表示（emoji付き）、保存完了、統計サマリ |
| **DEBUG** | 内部変数の値、詳細な処理ステップ、中間結果、データ形状 |

**原則**: ユーザーが処理進行を把握するための情報は INFO、開発者がデバッグするための詳細情報は DEBUG

---

## 🎨 ログアイコン標準（emoji統一）

全処理で統一されたemoji iconを使用：

| アイコン | 用途 | 使用例 |
|---------|------|--------|
| 🔄 | 処理開始 | `logger.info("🔄 データ収集開始")` |
| 📂 | ファイル読み込み | `logger.info("📂 data/input.h5 読み込み")` |
| 🔍 | 検証・品質チェック | `logger.info("🔍 必須列確認: time, open, high, low, close")` |
| 🧮 | 計算・特徴量生成 | `logger.info("🧮 basic_multi_tf: 20特徴量計算")` |
| ⚙️ | 処理・変換 | `logger.info("⚙️ NaN除外: 8列削除")` |
| 📊 | 統計・サマリ | `logger.info("📊 最終特徴量数: 65/73")` |
| 💾 | ファイル保存 | `logger.info("💾 data/output.h5 保存")` |
| ✅ | 処理完了 | `logger.info("✅ データ収集完了")` |
| ⚠️ | 警告 | `logger.warning("⚠️ NaN率 5%超の列: volume_surge")` |
| ❌ | エラー | `logger.error("❌ ファイル読み込み失敗")` |

---

## 🛠️ Handler 構成

| Handler | 出力先 | フォーマット | 用途 |
|---------|--------|-------------|------|
| **FileHandler** | `logs/*.log` | 標準フォーマット | 永続保存・後日分析 |
| **StreamHandler** | 標準出力（stdout） | 標準フォーマット | リアルタイム監視 |

### 重複防止（冪等性）

- 既存ハンドラをクリア: `logger.handlers.clear()`
- 同一ロガー名で複数回 `setup_logger()` を呼んでも、ハンドラは1セットのみ

---

## 🚨 例外処理方針

| 状況 | 対応 |
|------|------|
| ログディレクトリ作成失敗 | `Path.mkdir(parents=True, exist_ok=True)` で自動作成 |
| ログファイル書き込み失敗 | StreamHandler（コンソール）のみで継続 |
| 衝突連番上限超過（99回） | `RuntimeError` で停止 |

---

## 💻 利用例

### 基本的な使い方

```python
from utils.logging_manager import setup_logger

# ロガー初期化（JST日時プレフィックス付きファイル自動生成）
logger = setup_logger('data_collector')

# ログ出力（emoji icon付き）
logger.info("🔄 データ収集開始")
logger.info("📂 config/data_collector.yaml 読み込み")
logger.debug(f"   設定内容: {config}")  # DEBUG時のみ出力
logger.info("✅ データ収集完了")
```

### サフィックス付きログファイル

```python
# 検証フェーズ用のサフィックス付きログ
logger = setup_logger('trainer', log_suffix='_validation')
# → logs/20251023_233230_trainer_validation.log (JST)
```

### カスタムログディレクトリ

```python
# カスタムディレクトリ
logger = setup_logger('data_collector', log_dir='logs/debug')
# → logs/debug/20251023_233045_data_collector.log (JST)
```

### DEBUGレベル有効化

```python
# 詳細デバッグ情報を出力
logger = setup_logger('feature_calculator', log_level='DEBUG')
logger.debug("データ形状: (105120, 8)")
logger.debug(f"欠損値: {df.isnull().sum().to_dict()}")
```

---

## 📌 注意事項

1. **タイムスタンプ形式**: UTC固定、`%Y%m%d_%H%M%S` 形式（旧プロジェクト準拠）
2. **emoji使用**: 全ログで統一されたアイコンを使用
3. **エラー握りつぶし禁止**: 例外発生時は必ず `logger.error()` + `raise`
4. **衝突対策**: 同一秒内の連番は自動付与（最大99回）
5. **Git管理外**: `logs/*.log` は `.gitignore` に追加

---

## 🔗 関連仕様書

- **使用側**: 全フェーズのメインスクリプト（`src/*.py`）
- **時刻管理**: [TIMEZONE_UTILS_SPEC.md](./TIMEZONE_UTILS_SPEC.md)
- **トレースID**: [TRACE_ID_SPEC.md](./TRACE_ID_SPEC.md)（Phase 2以降実装予定）

---

**Version**: 1.0 (旧プロジェクト準拠版)  
**更新日**: 2025-10-23  
**継承元**: mt5_lstm-model/docs/utils/LOGGING_MANAGER_SPEC.md
