# TIMESTAMP_ALIGNMENT_SPEC.md

**バージョン**: 1.0  
**更新日**: 2025-10-21

---

## 📋 目的

多タイムフレーム (M1/M5/M15/H1/H4) の時刻をUTC基準で揃え、後段で一貫したインデックス参照を可能にする。

**時刻管理方針**:
- **内部処理**: UTC統一で処理・保存
- **ログ表示**: 日本時間(JST)で表示
- 詳細: [docs/utils/TIMEZONE_UTILS_SPEC.md](../utils/TIMEZONE_UTILS_SPEC.md)

---

## 🔄 TIMEZONE_UTILS連携シーケンス

**処理順序**: TIMEZONE_UTILS → TIMESTAMP_ALIGNMENT

```
データ収集フロー（時刻処理）:

┌──────────────────────────────────────────────────────────────┐
│ 1. MT5 Broker からデータ取得                                  │
│    - ブローカー時刻（例: UTC+3）でタイムスタンプ取得           │
└──────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────┐
│ 2. TIMEZONE_UTILS: ブローカー時刻 → UTC変換                   │
│    - broker_to_utc(timestamp_broker) → timestamp_utc         │
│    - タイムゾーン付きdatetime生成（timezone-aware必須）         │
│    - validate_timezone_aware() で検証                         │
└──────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────┐
│ 3. TIMESTAMP_ALIGNMENT: UTC基準での多TF揃え                   │
│    - 正規インデックス生成（M1/M5/M15/H1/H4）                   │
│    - 再インデックス（reindex）                                │
│    - 欠損検出・補完                                           │
│    - TF間整合マッピング                                       │
└──────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────┐
│ 4. HDF5保存: UTC UNIXタイムスタンプ                            │
│    - timestamp_utc.timestamp() で秒単位に変換                 │
│    - models/raw_data.h5 に保存                               │
└──────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────┐
│ 5. ログ出力: TIMEZONE_UTILS で JST表示                         │
│    - format_jst(timestamp_utc) → "YYYY-MM-DD HH:MM:SS JST"   │
│    - 例: "2025-10-23 19:30:00 JST"                           │
└──────────────────────────────────────────────────────────────┘
```

**コード例**:
```python
from src.utils.timezone_utils import (
    broker_to_utc, format_jst, validate_timezone_aware, now_utc
)
from datetime import timezone, timedelta
import pandas as pd

# ブローカータイムゾーン（例: UTC+3）
BROKER_TZ = timezone(timedelta(hours=3))

# 1. MT5からデータ取得
mt5_bars = fetch_mt5_data(symbol, timeframe)
timestamps_broker = pd.Series(mt5_bars['time'], dtype='datetime64[ns]')
timestamps_broker = timestamps_broker.dt.tz_localize(BROKER_TZ)

# 2. TIMEZONE_UTILS: UTC変換
timestamps_utc = timestamps_broker.dt.tz_convert(timezone.utc)

# 検証: timezone-aware確認
for ts in timestamps_utc.head():
    validate_timezone_aware(ts.to_pydatetime())

# 3. TIMESTAMP_ALIGNMENT: 正規インデックス生成
start_utc = timestamps_utc.min()
end_utc = timestamps_utc.max()

# M5用正規インデックス（5分間隔）
full_index = pd.date_range(
    start=start_utc.floor('5min'),
    end=end_utc.ceil('5min'),
    freq='5min',
    tz=timezone.utc
)

# 再インデックス
df_aligned = df.reindex(full_index)

# 欠損補完
gaps = df_aligned.isna().any(axis=1)
df_aligned.loc[gaps, 'filled'] = True

# 4. HDF5保存（UTC UNIXタイムスタンプ）
df_aligned.to_hdf(
    'models/raw_data.h5',
    key='/data/M5',
    mode='a',
    format='table'
)

# 5. ログ出力（JST表示）
logger.info(f"データ収集完了: {format_jst(now_utc())}")
logger.info(f"期間: {format_jst_period(start_utc, end_utc)}")
# 出力例: "データ収集完了: 2025-10-23 19:30:00 JST"
# 出力例: "期間: 2025-01-01 09:00:00 JST ～ 2025-12-31 23:59:00 JST"
```

**重要な設計原則**:
1. **TIMEZONE_UTILS が先**: ブローカー時刻→UTC変換を最初に実行
2. **TIMESTAMP_ALIGNMENT は UTC前提**: 全ての時刻がUTC timezone-awareであることを前提
3. **ログ表示のみ JST**: 内部データは常にUTC、表示時のみ `format_jst()` で変換
4. **timezone-aware 必須**: naive datetimeは `validate_timezone_aware()` でエラー

---

## 🔄 処理手順

### 1. タイムゾーン変換
```python
timestamp_utc = timestamp_broker.tz_convert('UTC')
```

### 2. 正規インデックス生成
最小開始時刻〜最大終了時刻をTF間隔でステップ

| TF | 間隔(秒) |
|----|---------|
| M1 | 60 |
| M5 | 300 |
| M15 | 900 |
| H1 | 3600 |
| H4 | 14400 |

### 3. 再インデックス
```python
df_aligned = df.reindex(full_index)
```

### 4. 欠損検出
```python
gaps = df_aligned.isna().any(axis=1)
```

### 5. 欠損分類と対応

| 分類 | 条件 | 対応 |
|------|------|------|
| 短期 | 連続 < 3本 | forward fill + `filled=True` フラグ |
| 長期 | 連続 ≥ 3本 | 除外リスト記録 |
| 休場 | 週末/祝日 | `trading_halt_mask` 付与 |

### 6. TF間整合マッピング
上位TF（M15/H1/H4）は下位TFの開始バーへキー一致

例: H1 timestamp → 同一時刻のM5行

---

## 📊 メタデータ出力

```json
{
  "alignment_stats": {
    "M1": {"total": 50000, "short_filled": 5, "long_gaps": 2},
    "M5": {"total": 10000, "short_filled": 3, "long_gaps": 1},
    "M15": {"total": 3333, "short_filled": 1, "long_gaps": 0},
    "H1": {"total": 833, "short_filled": 0, "long_gaps": 0},
    "H4": {"total": 208, "short_filled": 0, "long_gaps": 0}
  },
  "long_gap_segments": [
    {"tf": "M5", "start": "2025-10-15T10:30:00Z", "start_jst": "2025-10-15 19:30:00 JST", "length": 5},
    {"tf": "M1", "start": "2025-10-16T14:00:00Z", "start_jst": "2025-10-16 23:00:00 JST", "length": 10}
  ]
}
```

---

## 🚨 エラー条件

- 変換不可timestamp（NaT混入） → ERROR停止
- 重複timestamp > 0 → ERROR停止
- 長期欠損率 > `max_gap_ratio` → ERROR停止

---

## ✅ テスト要件

- 全TFで最終index長と期待レンジ長が一致
- H1各バー開始時刻がM5に存在
- Tickの時刻がバーの範囲内に収まる

---

## 🔗 参照

- **親仕様書**: `docs/DATA_COLLECTOR_SPEC.md`
- **相互関連仕様書**:
  - `docs/validator/FUTURE_LEAK_PREVENTION_SPEC.md` - タイムスタンプ整合後の未来リーク検証
    - 再同期後、シーケンス生成時の境界検証が必須
    - `assert(ts_label > ts_last_feature)` で未来リーク防止
  - `docs/PREPROCESSOR_SPEC.md` - 整合済みデータの前処理
    - 長期欠損セグメントの除外処理
    - filled=True フラグを用いた学習重み減衰

