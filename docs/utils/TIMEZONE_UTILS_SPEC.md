# TIMEZONE_UTILS_SPEC.md

**バージョン**: 1.0
**更新日**: 2025-10-23
**責任者**: core-team
**カテゴリ**: 共通ユーティリティ

---

## 📋 目的

`src/utils/timezone_utils.py` がプロジェクト全体で統一された時刻管理を提供する。

**責任範囲**:
- UTC ⇔ JST(日本時間)の相互変換
- ログ・レポート用の日本時間フォーマット
- タイムスタンプのバリデーション
- タイムゾーン付きdatetimeオブジェクトの生成

---

## 🎯 設計方針

### 内部保持形式
- **全データ**: UTC統一で保存
- **HDF5内time列**: UTC UNIXタイムスタンプ(秒)
- **理由**: タイムゾーン変換の複雑性を排除、国際標準との整合性

### ログ・レポート表示形式
- **ログ出力**: 日本時間(JST, UTC+9)で表示
- **レポート**: 日本時間(JST, UTC+9)で表示
- **理由**: 運用者の可読性向上、日本市場との対応関係明確化

### 標準フォーマット
- **日時形式**: `YYYY-MM-DD HH:MM:SS JST`
- **期間表示**: 開始/終了とも日本時間で明記
- **タイムゾーン表記**: 必ず`JST`サフィックスを付与

---

## 📚 主要関数

### 1. UTC ⇔ JST 変換

#### `utc_to_jst(timestamp_utc: datetime) -> datetime`
UTC時刻を日本時間に変換

**入力**:
- `timestamp_utc`: UTC timezone-aware datetime

**出力**:
- JST timezone-aware datetime

**例**:
```python
from datetime import datetime, timezone
from src.utils.timezone_utils import utc_to_jst

utc_time = datetime(2025, 10, 23, 14, 30, 0, tzinfo=timezone.utc)
jst_time = utc_to_jst(utc_time)
# datetime(2025, 10, 23, 23, 30, 0, tzinfo=JST)
```

#### `jst_to_utc(timestamp_jst: datetime) -> datetime`
日本時間をUTCに変換

**入力**:
- `timestamp_jst`: JST timezone-aware datetime

**出力**:
- UTC timezone-aware datetime

**例**:
```python
from src.utils.timezone_utils import jst_to_utc, JST

jst_time = datetime(2025, 10, 23, 23, 30, 0, tzinfo=JST)
utc_time = jst_to_utc(jst_time)
# datetime(2025, 10, 23, 14, 30, 0, tzinfo=timezone.utc)
```

### 2. フォーマット関数

#### `format_jst(timestamp_utc: datetime) -> str`
UTC時刻を日本時間文字列に変換（ログ・レポート用）

**入力**:
- `timestamp_utc`: UTC timezone-aware datetime

**出力**:
- `YYYY-MM-DD HH:MM:SS JST` 形式の文字列

**例**:
```python
from src.utils.timezone_utils import format_jst

utc_time = datetime(2025, 10, 23, 14, 30, 0, tzinfo=timezone.utc)
formatted = format_jst(utc_time)
# "2025-10-23 23:30:00 JST"
```

#### `format_jst_period(start_utc: datetime, end_utc: datetime) -> str`
UTC期間を日本時間範囲文字列に変換

**入力**:
- `start_utc`: 開始UTC時刻
- `end_utc`: 終了UTC時刻

**出力**:
- `YYYY-MM-DD HH:MM:SS JST ～ YYYY-MM-DD HH:MM:SS JST` 形式

**例**:
```python
from src.utils.timezone_utils import format_jst_period

start = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
end = datetime(2024, 12, 31, 23, 59, 0, tzinfo=timezone.utc)
period = format_jst_period(start, end)
# "2024-01-01 09:00:00 JST ～ 2025-01-01 08:59:00 JST"
```

### 3. 現在時刻取得

#### `now_utc() -> datetime`
現在時刻をUTCで取得

**出力**:
- UTC timezone-aware datetime

**例**:
```python
from src.utils.timezone_utils import now_utc

current_utc = now_utc()
# datetime(2025, 10, 23, 14, 45, 30, tzinfo=timezone.utc)
```

#### `now_jst() -> datetime`
現在時刻を日本時間で取得

**出力**:
- JST timezone-aware datetime

**例**:
```python
from src.utils.timezone_utils import now_jst

current_jst = now_jst()
# datetime(2025, 10, 23, 23, 45, 30, tzinfo=JST)
```

### 4. バリデーション

#### `validate_timezone_aware(timestamp: datetime) -> None`
datetimeオブジェクトがtimezone-awareか検証

**入力**:
- `timestamp`: 検証対象datetime

**例外**:
- `ValueError`: timezone情報がない場合

**例**:
```python
from src.utils.timezone_utils import validate_timezone_aware

# OK: timezone-aware
validate_timezone_aware(datetime(2025, 10, 23, 14, 30, 0, tzinfo=timezone.utc))

# NG: naive datetime
validate_timezone_aware(datetime(2025, 10, 23, 14, 30, 0))
# ValueError: Timestamp must be timezone-aware
```

---

## 📊 定数

```python
from datetime import timezone, timedelta

# 日本標準時タイムゾーン
JST = timezone(timedelta(hours=9))

# 標準フォーマット
JST_FORMAT = "%Y-%m-%d %H:%M:%S JST"
```

---

## 🔄 使用例

### ログ出力での使用

```python
from src.utils.timezone_utils import now_utc, format_jst
import logging

logger = logging.getLogger(__name__)

# データ収集開始時
start_time_utc = now_utc()
logger.info(f"データ収集開始 [{format_jst(start_time_utc)}]")
# "データ収集開始 [2025-10-23 23:30:45 JST]"

# データ収集完了時
end_time_utc = now_utc()
logger.info(f"データ収集完了 [{format_jst(end_time_utc)}]")
# "データ収集完了 [2025-10-23 23:31:02 JST]"
```

### データ期間表示での使用

```python
from src.utils.timezone_utils import format_jst_period
import h5py

with h5py.File('models/data.h5', 'r') as f:
    start_timestamp = f['/data/M1/time'][0]
    end_timestamp = f['/data/M1/time'][-1]

    # UNIXタイムスタンプをdatetimeに変換
    from datetime import datetime, timezone
    start_utc = datetime.fromtimestamp(start_timestamp, tz=timezone.utc)
    end_utc = datetime.fromtimestamp(end_timestamp, tz=timezone.utc)

    logger.info(f"期間: {format_jst_period(start_utc, end_utc)}")
    # "期間: 2024-01-01 09:00:00 JST ～ 2024-12-31 23:59:00 JST"
```

### HDF5保存時の時刻管理

```python
from src.utils.timezone_utils import now_utc, format_jst
import h5py

# 内部はUTCで保存
with h5py.File('models/data.h5', 'w') as f:
    # タイムスタンプはUTC UNIXタイムスタンプで保存
    timestamps_utc = [...array of UTC timestamps...]
    f.create_dataset('/data/M1/time', data=timestamps_utc)

    # メタデータ
    current_utc = now_utc()
    f.attrs['collection_timestamp'] = current_utc.timestamp()
    f.attrs['collection_timestamp_jst'] = format_jst(current_utc)

logger.info(f"HDF5保存完了 [{format_jst(current_utc)}]")
```

---

## 🚨 エラー処理

### Naive Datetime 検出

```python
from src.utils.timezone_utils import validate_timezone_aware
from datetime import datetime

try:
    # naive datetimeは拒否
    naive_time = datetime(2025, 10, 23, 14, 30, 0)
    validate_timezone_aware(naive_time)
except ValueError as e:
    logger.error(f"タイムゾーン情報なし: {e}")
    # タイムゾーン情報を追加してリトライ
```

### ブローカータイム変換

```python
from src.utils.timezone_utils import jst_to_utc, JST
from datetime import datetime

# ブローカーがJSTを返す場合
broker_time_jst = datetime(2025, 10, 23, 23, 30, 0, tzinfo=JST)
utc_time = jst_to_utc(broker_time_jst)

# HDF5に保存（UTC UNIXタイムスタンプ）
timestamp_unix = utc_time.timestamp()
```

---

## 📌 注意事項

### タイムゾーン付きdatetimeを必須とする理由

1. **曖昧性の排除**: naive datetimeは「どのタイムゾーンか」が不明
2. **変換ミスの防止**: 二重変換や逆変換の防止
3. **明示的な意図**: UTC/JSTが明確に区別される

### サマータイム非対応

- **日本標準時**: サマータイムなし（UTC+9固定）
- **ブローカー時刻**: サマータイム対応が必要な場合は別途処理

---

## 🔗 関連仕様書

- [DATA_COLLECTOR_SPEC.md](../DATA_COLLECTOR_SPEC.md): データ収集時の時刻管理
- [FEATURE_CALCULATOR_SPEC.md](../FEATURE_CALCULATOR_SPEC.md): 特徴量計算時のログ
- [PREPROCESSOR_SPEC.md](../PREPROCESSOR_SPEC.md): 前処理時のログ
- [TRAINER_SPEC.md](../TRAINER_SPEC.md): 学習時のログ
- [VALIDATOR_SPEC.md](../VALIDATOR_SPEC.md): 検証時のログ

---

## 🔮 将来拡張

### 複数タイムゾーン対応

```python
# 例: ニューヨーク時間表示
from datetime import timezone, timedelta

EST = timezone(timedelta(hours=-5))

def format_est(timestamp_utc: datetime) -> str:
    """UTC時刻をEST文字列に変換"""
    est_time = timestamp_utc.astimezone(EST)
    return est_time.strftime("%Y-%m-%d %H:%M:%S EST")
```

### ブローカー時刻対応

```python
# ブローカーのタイムゾーン設定
BROKER_TZ = timezone(timedelta(hours=3))  # UTC+3

def broker_to_utc(timestamp_broker: datetime) -> datetime:
    """ブローカー時刻をUTCに変換"""
    return timestamp_broker.astimezone(timezone.utc)
```
