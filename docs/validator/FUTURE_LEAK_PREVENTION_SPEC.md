# Future Leak Prevention Specification

## 目的

特徴量計算・モデル学習において、未来データの誤参照（Future Leak）を防止するツール群の仕様を定義する。

---

## 問題定義

### Future Leak とは

予測対象時点（Target Time）より未来の情報を特徴量に含めてしまう誤実装。

**具体例**:
```python
# ❌ NG: t+1 の情報を t の特徴量に含む
df['ma'] = df['close'].shift(-5).rolling(10).mean()  # 未来5本分を参照

# ❌ NG: ターゲット時刻以降のデータを使用
features = df[df['time'] <= target_time]  # OK
features['future_high'] = df[df['time'] > target_time]['high'].max()  # NG
```

**影響**:
- 学習時: 異常に高精度（過学習）
- 推論時: 未来データ存在せず、性能大幅劣化
- 検出困難: 通常の検証では発見しづらい

---

## 適用フェーズと検査内容

各処理段階での未来リーク検査の責務を明確化:

| 処理段階 | 検査タイミング | 検査内容 | ツール |
|---------|---------------|---------|--------|
| **第1段階: データ収集** | 収集後 | タイムスタンプ単調性、重複検出 | `validate_timestamp_order.py` |
| **第2段階: 特徴量計算** | 計算中（開発時） | 負のシフト、前方参照ローリング検出 | `detect_future_leak.py` (静的解析) |
| **第2段階: 特徴量計算** | 計算後 | 特徴量時刻 < ラベル時刻の検証 | `validate_timestamp_order.py` |
| **第3段階: 前処理** | シーケンス化後 | シーケンス内時系列順序、マルチTF整合性 | `validate_timestamp_order.py` |
| **第4段階: 学習** | 学習前 | 最終データセット時刻順序検証 | `validate_timestamp_order.py` |
| **第5段階: 検証** | バックテスト時 | 推論時タイムスタンプ順序遵守 | Runtime assertion |

### 検査の優先順位

1. **開発時（最優先）**: `detect_future_leak.py` で静的解析
   - 実装段階でコードレビュー
   - CI/CDパイプラインに組み込み

2. **データパイプライン実行時**: `validate_timestamp_order.py` で動的検証
   - 各段階の出力HDF5ファイルを検証
   - 異常検出時は即座にエラー停止

3. **バックテスト時**: Runtime assertion
   - 推論時の時刻順序違反を検出
   - ログに記録して後で分析

### 未来リーク防止とFEATURE_CALCULATOR対応表

| FEATURE_CALCULATOR操作 | 検出対象パターン | 検出ツール | 安全な使い方 | 検出段階 |
|----------------------|----------------|----------|-----------|---------|
| **`.shift(1)`** | 正のシフト（過去参照） | - | ✅ `close.shift(1)` | - |
| **`.shift(-n)`** | 負のシフト（未来参照） | detect_future_leak.py | ❌ 使用禁止 | 第2段階開発時 |
| **`.diff()`** | 1期前との差分 | - | ✅ `close.diff()` = `close - close.shift(1)` | - |
| **`.rolling(n).mean()`** | 過去n期の移動平均 | - | ✅ `close.rolling(5).mean()` | - |
| **`.rolling(n).std()`** | 過去n期の標準偏差 | - | ✅ `close.rolling(12).std()` | - |
| **`.rolling(n).sum()`** | 過去n期の合計 | - | ✅ `changes.rolling(20).sum()` | - |
| **`.rolling(n).quantile()`** | 過去n期の分位数 | - | ✅ `atr.rolling(100).quantile(0.33)` | - |
| **`.rolling(n).corr()`** | 過去n期の相関係数 | - | ✅ `close_m5.rolling(20).corr(close_m15)` | - |
| **`.ewm(span=n).mean()`** | 指数移動平均（EMA） | - | ✅ `close.ewm(span=12).mean()` | - |
| **`.iloc[i+n]`** | 未来行への直接アクセス | detect_future_leak.py | ❌ 使用禁止 | 第2段階開発時 |
| **`.loc[future_index]`** | 未来時刻への参照 | detect_future_leak.py | ❌ 使用禁止 | 第2段階開発時 |
| **`.cumsum()[::-1]`** | 累積計算逆順 | detect_future_leak.py | ❌ 使用禁止 | 第2段階開発時 |

**FEATURE_CALCULATOR仕様書別使用箇所**:

| 操作パターン | BASIC_MULTI_TF | MICROSTRUCTURE | VOLATILITY_REGIME | MOMENTUM | SESSION_TIME |
|-----------|----------------|----------------|-------------------|---------|--------------|
| `.shift(1)` | 8箇所 | 3箇所 | 4箇所 | 3箇所 | - |
| `.diff()` | - | 2箇所 | - | 1箇所 | - |
| `.rolling().mean()` | 3箇所 | 5箇所 | 2箇所 | 3箇所 | - |
| `.rolling().std()` | - | 2箇所 | - | 1箇所 | - |
| `.rolling().sum()` | - | 2箇所 | - | - | - |
| `.rolling().quantile()` | - | - | 2箇所 | - | - |
| `.rolling().corr()` | 3箇所 | - | - | - | - |
| `.ewm().mean()` | - | - | - | 4箇所 | - |

**注記**:
- **緑色✅**: 過去のみ参照、安全
- **赤色❌**: 未来参照、使用禁止
- 全てのrolling/ewm操作はデフォルトで過去参照（`min_periods`未指定時は最低期間分の履歴必要）
- `shift(1)` は1期前（過去）、`shift(-1)` は1期後（未来）を参照

**検証方法**:
```bash
# 第2段階開発時: 静的解析で未来参照検出
bash ./docker_run.sh python3 tools/validator/detect_future_leak.py src/feature_calculator/

# 第2段階計算後: 動的検証で時刻順序確認
bash ./docker_run.sh python3 tools/validator/validate_timestamp_order.py \
  --features models/features.h5 \
  --targets models/features.h5 \
  --check-feature-time
```

---

## 検出アプローチ

### 1. 静的解析（コードレベル）

**ツール**: `tools/validator/detect_future_leak.py`

**検出パターン**:
1. **負のシフト**: `shift(-n)`, `.iloc[i+n]`, `.loc[future_index]`
2. **前方参照ローリング**: `rolling().apply(lambda x: x[-1])` での未来参照
3. **累積計算の逆順**: `cumsum()[::-1]`, `cumprod()[::-1]`
4. **ターゲット時刻以降のフィルタ**: `df[df['time'] > target_time]`

**実装方式**: Python AST（Abstract Syntax Tree）解析

### 2. 動的検証（データレベル）

**ツール**: `tools/validator/validate_timestamp_order.py`

**検証内容**:
1. **タイムスタンプ順序**: `features.time.max() < targets.time.min()`
2. **シーケンス時系列**: 各シーケンス内でタイムスタンプ昇順
3. **マルチTF整合性**: M1/M5/M15/H1/H4 の時刻同期

---

## ツール仕様

### 1. detect_future_leak.py（静的解析）

#### 機能

ソースコード（`.py`）を解析し、Future Leak の疑いがある箇所を検出。

#### 使用方法

```bash
# 特定ディレクトリを解析
bash ./docker_run.sh python3 tools/validator/detect_future_leak.py src/

# 特定ファイルのみ
bash ./docker_run.sh python3 tools/validator/detect_future_leak.py src/preprocessor/alignment.py

# 除外パターン指定
bash ./docker_run.sh python3 tools/validator/detect_future_leak.py src/ --exclude "*/test_*.py,*/_tool_*.py"

# 詳細モード
bash ./docker_run.sh python3 tools/validator/detect_future_leak.py src/ --verbose
```

#### 出力例

```
🔍 Future Leak 検出開始: src/

📂 src/preprocessor/features.py
  ⚠️  Line 45: df['ma'] = df['close'].shift(-5).rolling(10).mean()
      → 負のシフト検出: shift(-5)
  
  ⚠️  Line 78: high_future = df.iloc[i+10]['high']
      → 前方参照検出: iloc[i+10]

📊 検出結果サマリ:
  - 検査ファイル数: 12
  - 検出件数: 2
  - 疑わしいパターン: shift(-n), iloc[future]

❌ Future Leak の疑いあり（終了コード: 1）
```

#### 実装概要

```python
import ast
import sys
from pathlib import Path

class FutureLeakDetector(ast.NodeVisitor):
    def __init__(self):
        self.violations = []
    
    def visit_Call(self, node):
        # shift(-n) 検出
        if isinstance(node.func, ast.Attribute):
            if node.func.attr == 'shift' and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.UnaryOp) and isinstance(arg.op, ast.USub):
                    self.violations.append({
                        'line': node.lineno,
                        'pattern': 'shift(-n)',
                        'code': ast.unparse(node)
                    })
        
        # iloc[i+n] 検出
        if isinstance(node.func, ast.Attribute):
            if node.func.attr == 'iloc':
                # インデックスが i+n の形式か確認
                if self._is_forward_index(node):
                    self.violations.append({
                        'line': node.lineno,
                        'pattern': 'iloc[future]',
                        'code': ast.unparse(node)
                    })
        
        self.generic_visit(node)
    
    def _is_forward_index(self, node):
        # i+n, i+1 等の加算パターン検出
        # 実装詳細は省略
        pass

def detect_future_leak(target_path: Path, exclude_patterns: list = None):
    detector = FutureLeakDetector()
    
    for py_file in target_path.rglob('*.py'):
        if exclude_patterns and any(py_file.match(p) for p in exclude_patterns):
            continue
        
        with open(py_file, 'r', encoding='utf-8') as f:
            tree = ast.parse(f.read(), filename=str(py_file))
            detector.visit(tree)
    
    return detector.violations

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('target', type=Path, help='解析対象パス')
    parser.add_argument('--exclude', type=str, help='除外パターン（カンマ区切り）')
    parser.add_argument('--verbose', action='store_true', help='詳細出力')
    
    args = parser.parse_args()
    
    violations = detect_future_leak(
        args.target,
        args.exclude.split(',') if args.exclude else None
    )
    
    if violations:
        print(f"❌ Future Leak の疑いあり: {len(violations)}件")
        sys.exit(1)
    else:
        print("✅ Future Leak 検出なし")
        sys.exit(0)
```

---

### 2. validate_timestamp_order.py（動的検証）

#### 機能

HDF5データファイルを読み込み、タイムスタンプの順序・整合性を検証。

#### 使用方法

```bash
# 特定ファイルを検証
bash ./docker_run.sh python3 tools/validator/validate_timestamp_order.py --file data/preprocessed.h5

# 複数ファイル
bash ./docker_run.sh python3 tools/validator/validate_timestamp_order.py --file data/aligned_m1.h5 data/aligned_m5.h5

# マルチTF同時検証
bash ./docker_run.sh python3 tools/validator/validate_timestamp_order.py --multi-tf data/aligned_*.h5
```

#### 出力例

```
🔍 タイムスタンプ順序検証開始: data/preprocessed.h5

📊 基本検証:
  ✅ features タイムスタンプ: 昇順
  ✅ targets タイムスタンプ: 昇順
  ✅ Future Leak チェック: features.time.max() < targets.time.min()
  
  📈 詳細統計:
    - features 範囲: 2024-01-01 00:00:00 ~ 2024-03-31 23:59:00
    - targets 範囲:  2024-01-01 00:05:00 ~ 2024-04-01 00:04:00
    - タイムギャップ: 5 分
    - シーケンス数: 25920

📊 マルチTF整合性検証:
  ✅ M1-M5 時刻同期: OK
  ✅ M5-M15 時刻同期: OK
  ✅ M15-H1 時刻同期: OK
  ✅ H1-H4 時刻同期: OK

✅ タイムスタンプ検証完了（異常なし）
```

#### 実装概要

```python
import h5py
import numpy as np
from pathlib import Path
from datetime import datetime

def validate_timestamp_order(file_path: Path):
    """タイムスタンプ順序検証"""
    with h5py.File(file_path, 'r') as f:
        # 基本検証
        features_time = f['features/time'][:]
        targets_time = f['targets/time'][:]
        
        # 昇順チェック
        features_sorted = np.all(features_time[:-1] <= features_time[1:])
        targets_sorted = np.all(targets_time[:-1] <= targets_time[1:])
        
        # Future Leak チェック
        no_future_leak = features_time.max() < targets_time.min()
        
        return {
            'features_sorted': features_sorted,
            'targets_sorted': targets_sorted,
            'no_future_leak': no_future_leak,
            'features_range': (features_time.min(), features_time.max()),
            'targets_range': (targets_time.min(), targets_time.max()),
            'time_gap': int(targets_time.min() - features_time.max())
        }

def validate_multi_tf_sync(file_paths: list[Path]):
    """マルチTF時刻同期検証"""
    tf_data = {}
    
    for path in file_paths:
        # M1, M5 等のタイムフレーム識別
        tf_name = path.stem.split('_')[-1].upper()  # aligned_m1 → M1
        
        with h5py.File(path, 'r') as f:
            tf_data[tf_name] = f['features/time'][:]
    
    # 各TF間の時刻同期確認
    sync_results = {}
    tf_names = sorted(tf_data.keys())
    
    for i in range(len(tf_names) - 1):
        tf1, tf2 = tf_names[i], tf_names[i+1]
        
        # 低TFの最大時刻 <= 高TFの最大時刻
        sync_ok = tf_data[tf1].max() <= tf_data[tf2].max()
        sync_results[f'{tf1}-{tf2}'] = sync_ok
    
    return sync_results

if __name__ == '__main__':
    import argparse
    import sys
    
    parser = argparse.ArgumentParser()
    parser.add_argument('--file', nargs='+', type=Path, help='検証対象HDF5ファイル')
    parser.add_argument('--multi-tf', nargs='+', type=Path, help='マルチTF検証')
    
    args = parser.parse_args()
    
    all_ok = True
    
    if args.file:
        for file_path in args.file:
            result = validate_timestamp_order(file_path)
            
            if not all(result.values()):
                print(f"❌ {file_path}: タイムスタンプ異常")
                all_ok = False
    
    if args.multi_tf:
        sync_results = validate_multi_tf_sync(args.multi_tf)
        
        if not all(sync_results.values()):
            print(f"❌ マルチTF同期異常")
            all_ok = False
    
    sys.exit(0 if all_ok else 1)
```

---

## 運用方針

### 開発フロー統合

#### 1. 機能実装時

```bash
# 特徴量計算実装後
bash ./docker_run.sh python3 tools/validator/detect_future_leak.py src/preprocessor/

# データ生成後
bash ./docker_run.sh python3 tools/validator/validate_timestamp_order.py --file data/preprocessed.h5
```

#### 2. PR提出前

```bash
# 全ソースコード検査
bash ./docker_run.sh python3 tools/validator/detect_future_leak.py src/

# 全データファイル検証
bash ./docker_run.sh python3 tools/validator/validate_timestamp_order.py --file data/*.h5
```

#### 3. 定期実行（推奨）

```bash
# 週次: 全コードベース静的解析
bash ./docker_run.sh python3 tools/validator/detect_future_leak.py src/ > logs/leak_check.log

# 日次: 最新データ検証
bash ./docker_run.sh python3 tools/validator/validate_timestamp_order.py --file models/*_latest.h5
```

---

## CI/CD 統合の制約

### 実現不可能な理由

**データファイル（`*.h5`）が Git 管理外**:
- `.gitignore` で除外されているため、GitHub Actions 等で参照不可
- 動的検証（`validate_timestamp_order.py`）は CI/CD 統合できない
- 静的解析（`detect_future_leak.py`）のみ CI/CD 可能だが、単独開発では過剰

### 推奨運用

**手動実行を基本とする**:
- 開発時: 機能実装後に都度実行
- PR前: 全コード・全データを手動検証
- 定期実行: スクリプト化してローカルで週次実行

**理由**:
- 単独開発のため、自動化コストが見合わない
- データ検証は必然的にローカル実行
- コード検証も同じフローで統一した方がシンプル

---

## 既知の制約

### 1. 静的解析の限界

- **動的生成コード**: `eval()`, `exec()` 内は検出不可
- **間接参照**: 変数経由のシフト（`n=5; df.shift(-n)`）は検出困難
- **誤検出**: 正当な前方参照（例: データ準備時の補完処理）も検出される可能性

### 2. 動的検証の前提

- **HDF5構造依存**: `/features/time`, `/targets/time` の存在が前提
- **メモリ制限**: 大規模データ（>1GB）の全件読み込みは非推奨
- **実行環境**: ローカル Docker 環境でのみ実行可能（CI/CD不可）

---

## トラブルシューティング

### 誤検出への対応

```python
# 正当な前方参照の場合、コメントで明示
# FUTURE_LEAK_OK: データ準備フェーズでの補完処理
df['filled'] = df['close'].shift(-1).fillna(method='bfill')
```

静的解析ツールで `# FUTURE_LEAK_OK` コメントを検出し、該当行をスキップする機能を実装可能。

### パフォーマンス問題

大規模コードベースの場合:

```bash
# 並列実行（GNU parallel）
find src/ -name "*.py" | parallel -j 4 python3 tools/validator/detect_future_leak.py {}
```

---

## 関連仕様書

- **データ収集**: `docs/data_collector/TIMESTAMP_ALIGNMENT_SPEC.md`
  - タイムスタンプ整合処理との連携必須
  - 再同期後のシーケンス生成時に境界検証を実行
  - 長期欠損セグメントの除外が未来リーク防止に寄与
- **特徴量計算**: `docs/FEATURE_CALCULATOR_SPEC.md`
  - rolling/shift操作での未来参照禁止
  - 計算窓は常に過去方向のみ（forward-looking禁止）
- **前処理**: `docs/PREPROCESSOR_SPEC.md`
  - シーケンス生成時の境界条件: `seq_end_times < label_times`
  - horizon_offset計算式の明確化
- **学習**: `docs/TRAINER_SPEC.md`
  - データ分割時の時系列順序維持（cutoff_timestamp明示）
  - 検証データが学習データより未来であることを保証

---

## 項目97対応: Leak Validation自動化運用

**目的**: 手動実行では検証漏れリスクがある

**解決策**: Makefile統合 + 運用フロー明確化

### Makefile統合

```makefile
# Makefile

.PHONY: validate_leak
validate_leak:
	@echo "🔍 未来リーク検証開始..."
	@bash ./docker_run.sh python3 tools/validator/detect_future_leak.py src/ || exit 1
	@bash ./docker_run.sh python3 tools/validator/validate_timestamp_order.py --file data/*.h5 || exit 1
	@echo "✅ 未来リーク検証完了（異常なし）"

.PHONY: validate_leak_code_only
validate_leak_code_only:
	@echo "🔍 コード静的解析のみ実行..."
	@bash ./docker_run.sh python3 tools/validator/detect_future_leak.py src/ || exit 1
	@echo "✅ コード検証完了"

.PHONY: validate_leak_data_only
validate_leak_data_only:
	@echo "🔍 データタイムスタンプ検証のみ実行..."
	@bash ./docker_run.sh python3 tools/validator/validate_timestamp_order.py --file data/*.h5 || exit 1
	@echo "✅ データ検証完了"

.PHONY: test
test: validate_leak
	@echo "🧪 全テスト実行（leak検証含む）"
	@bash ./docker_run.sh pytest tests/
```

### 実行フロー

```bash
# 統合検証（コード + データ）
make validate_leak

# コードのみ（PR前の高速チェック）
make validate_leak_code_only

# データのみ（新規データ生成後）
make validate_leak_data_only

# テスト実行時に自動検証
make test
```

### 運用ガイドライン（項目97）

| タイミング | コマンド | 目的 |
|-----------|---------|------|
| **特徴量実装後** | `make validate_leak_code_only` | 新規コードの即時検証 |
| **データ生成後** | `make validate_leak_data_only` | HDF5タイムスタンプ整合性確認 |
| **PR提出前** | `make validate_leak` | コード+データ全体検証 |
| **週次定期実行** | `make validate_leak > logs/leak_weekly.log` | 継続的監視 |
| **テスト実行時** | `make test` | 自動トリガー |

### KPI（項目97）

- **実行率**: ≥100%（PR前必須）
- **検出漏れ**: 0件（過去6ヶ月）
- **誤検出対応時間**: <10分/件
- **実行時間**: <30秒（コードのみ）、<2分（データ含む）

### CI/CD統合の制約と対応策

**制約**: データファイル（`*.h5`）がGit管理外のため、GitHub Actionsでの完全自動化は不可

**対応策**:
1. **コード検証のみCI/CD統合**（将来的な拡張）
   ```yaml
   # .github/workflows/leak_check.yml（参考実装）
   name: Future Leak Check
   on: [pull_request]
   jobs:
     leak-check:
       runs-on: ubuntu-latest
       steps:
         - uses: actions/checkout@v3
         - name: Setup Python
           uses: actions/setup-python@v4
         - name: Run static analysis
           run: python3 tools/validator/detect_future_leak.py src/
   ```

2. **手動実行を必須フロー化**
   - PR提出前チェックリストに `make validate_leak` 実行を明記
   - CONTRIBUTING.mdに運用ガイドライン記載

3. **定期実行のスクリプト化**
   ```bash
   # tools/cron/weekly_leak_check.sh
   #!/bin/bash
   set -e
   
   cd /home/mania/github.com/premani/mt5_multi-timeframe_model
   make validate_leak > logs/leak_check_$(date +%Y%m%d).log 2>&1
   
   # crontab設定例（毎週月曜9時）
   # 0 9 * * 1 /home/mania/github.com/premani/mt5_multi-timeframe_model/tools/cron/weekly_leak_check.sh
   ```

### トラブルシューティング（項目97追加）

**問題**: `make validate_leak` が失敗

**実装**:
1. エラー内容確認:
   ```bash
   make validate_leak 2>&1 | tee logs/leak_error.log
   ```
2. 個別実行で切り分け:
   ```bash
   make validate_leak_code_only  # コード検証
   make validate_leak_data_only  # データ検証
   ```
3. 誤検出の場合:
   - コードに `# FUTURE_LEAK_OK: <理由>` コメント追加
   - または検証ツールの除外パターン設定

---

## 参考資料

- **プロジェクト概要**: `README.md`
- **ツール戦略**: `tools/TOOLS.md`
- **前処理仕様**: `docs/PREPROCESSOR_SPEC.md`
- **検証仕様**: `docs/VALIDATOR_SPEC.md`
