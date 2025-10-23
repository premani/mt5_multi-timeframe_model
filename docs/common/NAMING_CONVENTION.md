# ファイル命名規約

**バージョン**: 1.0.0  
**最終更新**: 2025-10-22  
**Author**: System Architect  
**Reviewer**: -  
**Approver**: Project Lead

---

## 目的

データファイル命名の一貫性を保証し、自動検出・世代管理・再学習ウィンドウの正確性を確保する。

---

## HDF5データファイル命名規則

### 基本フォーマット

```
<symbol>_<timeframe>_<phase>_<YYYYMMDD>_<HHMMSS>.h5
```

### 各要素の定義

| 要素 | 説明 | 例 |
|------|------|-----|
| `symbol` | 通貨ペア（大文字） | `USDJPY`, `EURUSD` |
| `timeframe` | タイムフレーム | `M1`, `M5`, `M15`, `H1`, `H4`, `D1` |
| `phase` | 処理フェーズ | `raw`, `aligned`, `features`, `sequences`, `trained` |
| `YYYYMMDD` | 作成日付 | `20251022` |
| `HHMMSS` | 作成時刻（UTC） | `143052` |

### 具体例

```
USDJPY_M5_raw_20251022_143052.h5
USDJPY_M5_aligned_20251022_143105.h5
USDJPY_M5_features_20251022_143230.h5
USDJPY_M15_sequences_20251022_143450.h5
USDJPY_multi_trained_20251022_150000.h5
```

### Phase定義

| Phase | 説明 | 含まれるデータ |
|-------|------|----------------|
| `raw` | 生データ | MT5から取得した未加工OHLCV |
| `aligned` | タイムスタンプ整合済み | 複数TF間で時刻が揃えられたデータ |
| `features` | 特徴量計算済み | テクニカル指標等の特徴量 |
| `sequences` | シーケンス化済み | LSTM入力用の時系列シーケンス |
| `trained` | 学習済みモデル付属データ | 正規化パラメータ、メタデータ |

---

## マルチタイムフレーム統合ファイル

複数TFを統合したファイルは `multi` を使用：

```
<symbol>_multi_<phase>_<YYYYMMDD>_<HHMMSS>.h5
```

**例**:
```
USDJPY_multi_sequences_20251022_150000.h5
USDJPY_multi_trained_20251022_153000.h5
```

---

## 正規表現パターン

### 自動検出用パターン

```python
# 単一TFファイル
SINGLE_TF_PATTERN = r'^([A-Z]{6})_(M[0-9]+|H[0-9]+|D[0-9]+)_(raw|aligned|features|sequences|trained)_(\d{8})_(\d{6})\.h5$'

# マルチTFファイル
MULTI_TF_PATTERN = r'^([A-Z]{6})_multi_(sequences|trained)_(\d{8})_(\d{6})\.h5$'
```

### 検証実装例

```python
import re
from datetime import datetime
from pathlib import Path

def validate_filename(filename: str) -> dict:
    """
    ファイル名の妥当性を検証し、パース結果を返す
    
    Returns:
        dict: {
            'valid': bool,
            'symbol': str,
            'timeframe': str,
            'phase': str,
            'date': str,
            'time': str,
            'datetime': datetime
        }
    """
    # 単一TF
    match = re.match(SINGLE_TF_PATTERN, filename)
    if match:
        symbol, tf, phase, date_str, time_str = match.groups()
        dt = datetime.strptime(f"{date_str}_{time_str}", "%Y%m%d_%H%M%S")
        return {
            'valid': True,
            'symbol': symbol,
            'timeframe': tf,
            'phase': phase,
            'date': date_str,
            'time': time_str,
            'datetime': dt,
            'multi': False
        }
    
    # マルチTF
    match = re.match(MULTI_TF_PATTERN, filename)
    if match:
        symbol, phase, date_str, time_str = match.groups()
        dt = datetime.strptime(f"{date_str}_{time_str}", "%Y%m%d_%H%M%S")
        return {
            'valid': True,
            'symbol': symbol,
            'timeframe': 'multi',
            'phase': phase,
            'date': date_str,
            'time': time_str,
            'datetime': dt,
            'multi': True
        }
    
    return {'valid': False}

def get_latest_file(directory: Path, symbol: str, phase: str, timeframe: str = None) -> Path:
    """
    最新のファイルを取得
    
    Args:
        directory: 検索ディレクトリ
        symbol: 通貨ペア
        phase: 処理フェーズ
        timeframe: タイムフレーム（None の場合は multi）
    
    Returns:
        Path: 最新ファイルのパス
    
    Raises:
        FileNotFoundError: 該当ファイルが存在しない
    """
    if timeframe:
        pattern = f"{symbol}_{timeframe}_{phase}_*.h5"
    else:
        pattern = f"{symbol}_multi_{phase}_*.h5"
    
    files = list(directory.glob(pattern))
    
    if not files:
        raise FileNotFoundError(f"No files found for pattern: {pattern}")
    
    # ファイル名から日時を抽出してソート
    valid_files = []
    for f in files:
        info = validate_filename(f.name)
        if info['valid']:
            valid_files.append((f, info['datetime']))
    
    if not valid_files:
        raise FileNotFoundError(f"No valid files found for pattern: {pattern}")
    
    # 最新ファイルを返す
    return max(valid_files, key=lambda x: x[1])[0]
```

---

## 命名逸脱時の対応

### 検証タイミング

1. **ファイル作成時**: 命名規約チェック
2. **ファイル読込時**: パターンマッチ検証
3. **CI/CD**: 全ファイル名検証

### 逸脱時の動作

| 検出箇所 | 動作 | ログレベル |
|----------|------|-----------|
| 作成時 | 例外発生、作成中止 | `ERROR` |
| 読込時 | 警告ログ、処理続行可（互換モード） | `WARNING` |
| CI/CD | テスト失敗、マージブロック | `CRITICAL` |

### 警告ログ例

```
WARNING: File name does not match naming convention
  File: usdjpy_m5_raw_2025-10-22.h5
  Expected pattern: <SYMBOL>_<TF>_<PHASE>_<YYYYMMDD>_<HHMMSS>.h5
  Example: USDJPY_M5_raw_20251022_143052.h5
```

---

## 世代管理とローテーション

### ファイル世代数

| Phase | 保持世代数 | 理由 |
|-------|-----------|------|
| `raw` | 最新3世代 | ディスク容量節約 |
| `aligned` | 最新2世代 | 再計算可能 |
| `features` | 最新2世代 | 再計算可能 |
| `sequences` | 最新3世代 | 学習再現性確保 |
| `trained` | 最新5世代 | モデル比較・ロールバック用 |

### 自動削除ロジック

```python
def cleanup_old_generations(directory: Path, symbol: str, phase: str, keep_count: int = 3):
    """
    古い世代のファイルを削除
    
    Args:
        directory: 対象ディレクトリ
        symbol: 通貨ペア
        phase: 処理フェーズ
        keep_count: 保持する世代数
    """
    pattern = f"{symbol}_*_{phase}_*.h5"
    files = list(directory.glob(pattern))
    
    # 有効なファイルのみ抽出
    valid_files = []
    for f in files:
        info = validate_filename(f.name)
        if info['valid']:
            valid_files.append((f, info['datetime']))
    
    # 日時でソート（新しい順）
    valid_files.sort(key=lambda x: x[1], reverse=True)
    
    # 古い世代を削除
    for f, dt in valid_files[keep_count:]:
        logger.info(f"Deleting old generation: {f.name} (created: {dt})")
        f.unlink()
```

---

## 再学習ウィンドウとの連携

### タイムスタンプベース選択

```python
from datetime import datetime, timedelta

def get_files_in_window(
    directory: Path,
    symbol: str,
    phase: str,
    start_date: datetime,
    end_date: datetime
) -> list[Path]:
    """
    指定期間内のファイルを取得
    
    Args:
        directory: 検索ディレクトリ
        symbol: 通貨ペア
        phase: 処理フェーズ
        start_date: 開始日時
        end_date: 終了日時
    
    Returns:
        list[Path]: 該当ファイルのリスト（日時順）
    """
    pattern = f"{symbol}_*_{phase}_*.h5"
    files = list(directory.glob(pattern))
    
    valid_files = []
    for f in files:
        info = validate_filename(f.name)
        if info['valid'] and start_date <= info['datetime'] <= end_date:
            valid_files.append((f, info['datetime']))
    
    # 日時でソート
    valid_files.sort(key=lambda x: x[1])
    
    return [f for f, _ in valid_files]
```

---

## 成功条件（KPI）

| 指標 | 目標値 | 測定方法 |
|------|--------|----------|
| 命名規約準拠率 | 100% | CI/CD自動検証 |
| 命名逸脱インシデント | 0件/30日 | ログ監視 |
| 誤世代参照事故 | 0件/30日 | トレース分析 |
| 自動検出失敗率 | 0% | DataCollector→Preprocessor連携テスト |

---

## 関連SPEC

- `DATA_COLLECTOR_SPEC.md`: 生データ保存時の命名
- `PREPROCESSOR_SPEC.md`: ファイル読込・検証
- `STORAGE_POLICY_SPEC.md`: 世代管理・アーカイブ
- `FUTURE_LEAK_PREVENTION_SPEC.md`: 再学習ウィンドウ選択

---

## 変更履歴

| 日付 | バージョン | 変更内容 |
|------|-----------|----------|
| 2025-10-22 | 1.0.0 | 初版作成（120項目レビュー項目5対応） |
