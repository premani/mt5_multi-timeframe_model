# ツール戦略

## 概要

本プロジェクトでは、4段階の処理フェーズごとにツールディレクトリを分け、処理名と一致させることで可読性と保守性を確保します。

---

## ディレクトリ構成

### フェーズ別ツール（処理名と一致）

```
tools/
├── data_collector/            # [1] データ収集
├── preprocessor/              # [2] 前処理
├── trainer/                   # [3] 学習
├── validator/                 # [4] 検証
└── utils/                     # 共通モジュール
```

各フェーズディレクトリには以下を配置:
- `test_*.py`: pytest単体テスト
- `test_integration_*.py`: 次フェーズとの連携テスト
- `validate_*.py`: CLI実行可能な検証スクリプト
- `detect_*.py`: 静的解析・品質検査スクリプト
- `fixtures/`: テストデータ（小規模推奨）

---

## 実行方法

### 単体テスト実行

```bash
# 特定フェーズのテスト
bash ./docker_run.sh pytest tools/preprocessor/test_*.py
bash ./docker_run.sh pytest tools/trainer/test_*.py

# 複数フェーズ
bash ./docker_run.sh pytest tools/data_collector/ tools/preprocessor/

# 全テスト実行
bash ./docker_run.sh pytest tools/
```

### 統合テスト実行

```bash
# 特定フェーズの統合テスト
bash ./docker_run.sh pytest tools/preprocessor/test_integration_*.py

# 全統合テスト
bash ./docker_run.sh pytest tools/*/test_integration_*.py
```

### 検証スクリプト実行

```bash
# 前処理結果確認（デフォルト: data/preprocessor.h5）
bash ./docker_run.sh python3 tools/preprocessor/inspect_preprocessor.py
bash ./docker_run.sh python3 tools/preprocessor/inspect_preprocessor.py data/preprocessor.h5
bash ./docker_run.sh python3 tools/preprocessor/inspect_preprocessor.py data/20251023_143045_preprocessor.h5

# HDF5構造確認
bash ./docker_run.sh python3 tools/preprocessor/validate_output.py --file data/preprocessed.h5

# タイムスタンプ順序検証
bash ./docker_run.sh python3 tools/validator/validate_timestamp_order.py --file data/aligned.h5
```

### 静的解析スクリプト実行

```bash
# Future Leak検出
bash ./docker_run.sh python3 tools/validator/detect_future_leak.py src/

# コード品質チェック
bash ./docker_run.sh python3 tools/utils/detect_code_quality.py src/
```

---

## 命名規則

### 1. 単体テストファイル
```
tools/<処理名>/test_<モジュール機能>.py
```
例:
- `tools/preprocessor/test_alignment.py`
- `tools/trainer/test_lstm_model.py`
- `tools/utils/test_hdf5_dataset.py`

### 2. 統合テストファイル（次フェーズとの連携）
```
tools/<処理名>/test_integration_to_<次フェーズ>.py
```
例:
- `tools/data_collector/test_integration_to_preprocessor.py`
- `tools/preprocessor/test_integration_to_trainer.py`
- `tools/trainer/test_integration_to_validator.py`

### 3. 検証スクリプト
```
tools/<処理名>/validate_<検証内容>.py
tools/<処理名>/inspect_<検査対象>.py
```
例:
- `tools/preprocessor/inspect_preprocessor.py` - 前処理結果確認
- `tools/preprocessor/validate_output.py` - 出力ファイル検証
- `tools/validator/validate_timestamp_order.py` - タイムスタンプ順序検証
- `tools/trainer/validate_model_weights.py` - モデル重み検証

### 4. 静的解析スクリプト
```
tools/<処理名>/detect_<検出内容>.py
```
例:
- `tools/validator/detect_future_leak.py`
- `tools/utils/detect_code_quality.py`
- `tools/preprocessor/detect_data_anomaly.py`

### 5. テストクラス・関数
```python
class Test<機能名>:
    def test_<検証内容>(self):
        ...
```
例:
```python
class TestTimestampAlignment:
    def test_multi_timeframe_sync(self):
        ...
    
    def test_missing_data_handling(self):
        ...
```

### 6. テストフィクスチャ
```
tools/<処理名>/fixtures/sample_<内容>_<行数>rows.<ext>
```
例:
- `tools/preprocessor/fixtures/sample_ohlcv_500rows.h5`
- `tools/trainer/fixtures/sample_sequences_train.h5`

---

## 開発ガイドライン

### 単体テスト作成
1. 機能実装と同時に作成
2. 処理名ディレクトリ配下に配置（`tools/<処理名>/test_*.py`）
3. pytest実行可能な形式（`test_*.py`, `Test*クラス`, `test_*関数`）
4. 小規模フィクスチャを同梱（`fixtures/`）

### 統合テスト作成
1. フェーズ間連携の実装完了時に作成
2. 同じ処理ディレクトリ配下に配置（`tools/<処理名>/test_integration_*.py`）
3. 次フェーズへの出力互換性を検証

### 検証スクリプト作成
1. デバッグ・データ確認時に作成
2. 同じ処理ディレクトリ配下に配置（`tools/<処理名>/validate_*.py`）
3. CLI実行可能な形式（`argparse`等）
4. 再利用可能な汎用ツールとして保存

### 静的解析スクリプト作成
1. コード品質・データ品質チェック時に作成
2. 同じ処理ディレクトリ配下に配置（`tools/<処理名>/detect_*.py`）
3. CLI実行可能な形式（`argparse`等）
4. CI/CD統合可能な設計（終了コード 0=OK, 1=NG）

### 一時テストファイル
- ルート直下に `_test_*.py` で作成
- 実験・検証後は削除（Git管理外）
- 再利用価値があれば `tools/<処理名>/` へ移動

---

## ツールカバレッジ目標

| フェーズ | 目標カバレッジ | 優先度 |
|---------|--------------|--------|
| **共通モジュール** (`utils/`) | 80%以上 | 🔥 最高 |
| **前処理** | 70%以上 | 🔥 最高 |
| **学習** | 70%以上 | 🔥 最高 |
| **データ収集** | 60%以上 | 🔶 高 |
| **検証** | 60%以上 | 🔶 高 |
| **統合テスト** | 各フェーズ間連携をカバー | 🔶 高 |

---

## 段階的導入ロードマップ

### Phase 1: 基盤整備（現在）
```
tools/
├── TOOLS.md
└── utils/
    ├── validate_hdf5_structure.py
    └── validate_timestamp_format.py
```

### Phase 2: 実装開始時
```
tools/
├── utils/
│   ├── test_hdf5_dataset.py
│   ├── test_logging_manager.py
│   └── validate_*.py
├── data_collector/
│   └── inspect_hdf5.py
├── preprocessor/
│   ├── inspect_preprocessor.py        # 前処理結果確認ツール
│   ├── test_alignment.py
│   ├── test_integration_to_trainer.py
│   ├── validate_output.py
│   └── fixtures/
│       └── sample_ohlcv_500rows.h5
└── validator/
    ├── detect_future_leak.py
    └── validate_timestamp_order.py
```

### Phase 3: 学習フェーズ実装後
```
tools/
├── trainer/
│   ├── test_lstm_model.py
│   ├── test_multi_tf_fusion.py
│   ├── test_integration_to_validator.py
│   ├── validate_model_weights.py
│   └── fixtures/
│       └── sample_sequences_train.h5
└── validator/
    ├── test_backtest.py
    ├── validate_results.py
    ├── detect_future_leak.py
    └── validate_timestamp_order.py
```

---

## トラブルシューティング

### pytest が tools/ を認識しない
```bash
# conftest.py の配置を確認
# または PYTHONPATH を明示
bash ./docker_run.sh env PYTHONPATH=/workspace pytest tools/
```

### フィクスチャが大きすぎる
- 100行以下の小規模データ推奨
- 1MB以下を目安にGit管理
- 大規模データは `.gitignore` で除外し、README に生成手順記載

### 検証スクリプトが実行できない
```bash
# Docker環境で実行
bash ./docker_run.sh python3 tools/<処理名>/validate_*.py --file <path>

# 権限確認
chmod +x tools/<処理名>/*.py
```

### 静的解析スクリプトが誤検出する
```bash
# 除外パターンを指定
bash ./docker_run.sh python3 tools/validator/detect_future_leak.py src/ --exclude "*/test_*.py"

# デバッグモードで実行
bash ./docker_run.sh python3 tools/validator/detect_future_leak.py src/ --verbose
```

---

## 参考資料

- **プロジェクト全体概要**: `README.md`
- **AI開発ガイド**: `AGENTS.md`
- **各フェーズ仕様**: `docs/*_SPEC.md`
