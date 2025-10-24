# DATA_COLLECTOR_SPEC.md

**バージョン**: 2.0
**更新日**: 2025-10-23
**責任者**: core-team
**処理段階**: 第1段階: データ収集

---

## 📋 目的

`src/data_collector.py` が **MT5 API Server** (HTTP/REST) 経由でマルチタイムフレーム (M1/M5/M15/H1/H4) のバーデータとTickデータ（Ask/Bid時系列）を収集し、UTC整合・品質保証を行い、HDF5形式で保存する。

**設計方針**:
- **完全データ収集**: バーデータ + 全期間Tickデータを一度に取得
- **MT5 API Server経由**: HTTP/REST APIで安定した接続
- **旧プロジェクト踏襲**: 実績のある `mt5_lstm-model` の実装パターンを継承
- **容量想定**: 
  - **1ヶ月**: 約65 MB（実測）
    - バーデータ: 約2MB（5TF × 8列 × mixed dtype × 約31,642行/TF、整合後）
    - Tickデータ: 約63MB（約1,619,474件）
  - **6ヶ月**: 約491MB（実測、圧縮なし）
    - バーデータ: 約12MB 
    - Tickデータ: 約479MB（13,840,269件実測）
  - **7年**: 約6.9GB（推定、圧縮なし）
    - バーデータ: 約168MB 
    - Tickデータ: 約6.7GB（推定）
  - **月分割取得**: メモリ効率的（1ヶ月=約65MB）

---

## 🎯 スコープ

### ✅ 実装範囲

**バーデータ（OHLC）**:
- **タイムフレーム**: M1, M5, M15, H1, H4
- **データ項目**: time, open, high, low, close, tick_volume, spread, real_volume
- **型**: time(**int64**), OHLC(float32), volumes(float32)
  - ⚠️ **タイムスタンプは必ずint64**: float32では精度不足で単調性違反が発生
  - UNIX時間は10桁、float32の精度は約7桁（仮数部23ビット）
  - 実装時は`np.hstack([time_col(int64), price_cols(float32)])`で結合

**Tickデータ（Ask/Bid時系列）**:
- **データ項目**: time, time_msc, bid, ask, last, volume, flags
- **型**: time/time_msc(int64), bid/ask/last(float32), volume/flags(int32)
- **取得方法**: MT5 API Server `/ticks` エンドポイント
- **月分割取得**: 1ヶ月以上の期間は月単位で分割取得し、HDF5に追記保存
  - **理由**: 大量Tickデータ（1ヶ月=約200-400万件）のメモリ圧縮とタイムアウト回避
  - **処理フロー**: 期間を月単位に分割 → 各月を順次取得 → HDF5に追記
  - **初回クリーン**: バーデータ収集前に既存Tickデータを削除（重複防止）
  - **タイムアウト**: 300秒（1ヶ月約60秒想定、5分の余裕）

**接続方式**: MT5 API Server（HTTP/REST）
- **バーデータ**: `POST /historical` エンドポイント
- **Tickデータ**: `POST /ticks` エンドポイント
- **認証**: Bearer Token（環境変数 `MT5_API_KEY`）
- **タイムアウト**: 
  - バーデータ: 60秒（デフォルト）
  - Tickデータ: 300秒（月分割取得用、環境変数 `MT5_API_TIMEOUT` で変更可能）

**対象シンボル**: USDJPY（初期、複数シンボルへ拡張可能）  
**時刻管理**: MT5から返されるUTCタイムスタンプをそのまま使用  
**圧縮**: 無効（処理速度優先、学習用は別途圧縮版作成）

**重要**: 
- ATR14等の特徴量は**第2段階で正式に計算**（第1段階ではキャッシュしない）
- Tickデータは月分割で全期間保存（6ヶ月=491MB実測、7年=約6.9GB推定）
- 月分割取得でメモリ効率化（1ヶ月=約80MB、タイムアウトリスク低減）

### 時刻管理方針

#### MT5 API Serverからの時刻データ
- **返却形式**: UNIXタイムスタンプ（秒またはミリ秒）
- **タイムゾーン**: MT5が返すタイムスタンプは **既にUTC**
  - `mt5.copy_rates_range()` → `time`: UTCエポック秒
  - `mt5.copy_ticks_range()` → `time`: UTCエポック秒、`time_msc`: UTCエポックミリ秒
  - ブローカータイムゾーン設定に関わらず、常にUTC基準
- **変換不要**: API ServerからのレスポンスをそのままHDF5に保存

#### HDF5内部保存形式
- **バーデータ**: `time` 列(int64, UTCエポック秒)
- **Tickデータ**: `time` 列(int64, 秒), `time_msc` 列(int64, ミリ秒)
- **理由**: 
  - タイムゾーン変換の複雑性を排除
  - 国際標準との整合性
  - ミリ秒精度でTickの正確な順序保証

#### ログ・レポート表示形式
- **ログ出力**: 日本時間(JST, UTC+9)で表示
- **レポート**: 日本時間(JST, UTC+9)で表示
- **理由**: 運用者の可読性向上、日本市場との対応関係明確化

#### 変換ルール
```python
# 内部保持: UTC
timestamp_utc = datetime(2025, 10, 23, 14, 30, 0, tzinfo=timezone.utc)

# ログ・レポート表示: JST
timestamp_jst = timestamp_utc.astimezone(timezone(timedelta(hours=9)))
logger.info(f"データ収集完了: {timestamp_jst.strftime('%Y-%m-%d %H:%M:%S JST')}")
```

#### 表示フォーマット
- **日時形式**: `YYYY-MM-DD HH:MM:SS JST`
- **期間表示**: 開始/終了とも日本時間で明記
- **タイムゾーン表記**: 必ず`JST`サフィックスを付与

### 非対象
- 板情報（Depth）・DOM履歴
- 経済指標イベント
- 約定履歴
- spread_min/spread_max（MT5 API未対応、将来的にAPI拡張で追加検討）

---

## 📊 入出力

### 入力

**環境変数（.env）**:
```bash
MT5_API_KEY=mt5-api-2024-xK9mN7pQ3vR8sL2eW6tY0uI4oP1aS5dF
MT5_API_ENDPOINT=http://192.168.50.172:8000
MT5_API_TIMEOUT=300  # Tick月分割取得用（1ヶ月約60秒、300秒=5分の余裕）
```

**MT5 API Server - バーデータエンドポイント**:
```http
POST /historical
Authorization: Bearer {MT5_API_KEY}
Content-Type: application/json

{
  "symbol": "USDJPY",
  "timeframe": "M5",
  "start": "2024-01-01T00:00:00",
  "end": "2024-12-31T23:59:59",
  "limit": 0
}
```

**レスポンス**:
```json
{
  "total": 105120,
  "count": 105120,
  "offset": 0,
  "data": [
    {
      "time": 1704067200,
      "open": 141.234,
      "high": 141.256,
      "low": 141.212,
      "close": 141.245,
      "tick_volume": 1234,
      "spread": 3,
      "real_volume": 0
    }
  ]
}
```

**MT5 API Server - Tickデータエンドポイント（新規実装）**:
```http
POST /ticks
Authorization: Bearer {MT5_API_KEY}
Content-Type: application/json

{
  "symbol": "USDJPY",
  "start": "2024-01-01T00:00:00",
  "end": "2024-12-31T23:59:59",
  "tick_type": "INFO",
  "limit": 0
}
```

**レスポンス**:
```json
{
  "total": 36000000,
  "count": 36000000,
  "offset": 0,
  "data": [
    {
      "time": 1704067200,
      "time_msc": 1704067200123,
      "bid": 141.234,
      "ask": 141.237,
      "last": 0.0,
      "volume": 0,
      "flags": 6
    }
  ]
}
```

**データ型変換**:
- `time`: **int64**（UTCエポック秒）
  - ⚠️ **重要**: float32では精度不足（仮数部23ビット ≈ 7桁、UNIX時間は10桁）
  - float32に変換すると丸め誤差で単調性違反が発生
  - 必ずint64で保持すること
- `time_msc`: **int64**（UTCエポックミリ秒）
- `open/high/low/close/bid/ask`: float32（価格は有効桁数5-6桁で十分）
- `tick_volume/spread/real_volume`: float32
- `volume/flags`: int32

**実装例（正）**:
```python
# タイムスタンプはint64で分離保持
time_col = np.array([bar['time'] for bar in bars], dtype=np.int64)
price_cols = np.array([[bar['open'], bar['high'], ...] for bar in bars], dtype=np.float32)
return np.hstack([time_col.reshape(-1, 1), price_cols])
```

**実装例（誤）**:
```python
# ❌ 全データをfloat32に変換 → タイムスタンプ精度損失
return np.array([[bar['time'], bar['open'], ...] for bar in bars], dtype=np.float32)
```

### 出力

---

## 📦 出力データ仕様

### 出力ファイル

| ファイル | 用途 | 既存ファイル処理 |
|---------|------|----------------|
| `data/data_collector.h5` | HDF5データ（バーデータ + Tickデータ） | JST日時プレフィックス付きリネーム |
| `data/data_collector_report.json` | 統計情報（次処理の入力パラメータ） | JST日時プレフィックス付きリネーム |
| `data/data_collector_report.md` | 人間可読レポート（検証用） | JST日時プレフィックス付きリネーム |

**既存ファイル処理例**:
- 既存: `data/data_collector.h5` (最終更新: 2025-10-23 14:30:45 JST)
- リネーム: `data/20251023_143045_data_collector.h5`
- リネーム: `data/20251023_143045_data_collector_report.json`
- リネーム: `data/20251023_143045_data_collector_report.md`
- 新規作成: `data/data_collector.h5`, `data/data_collector_report.json`, `data/data_collector_report.md`

**HDF5構造**: `data/data_collector.h5`

**HDF5構造**:
```
/M1/data: (N, 8) mixed dtype
  - 列0: time (int64) - タイムスタンプ
  - 列1-7: OHLC, volumes, spread (float32)
/M5/data: (N, 8) mixed dtype（同上）
/M15/data: (N, 8) mixed dtype（同上）
/H1/data: (N, 8) mixed dtype（同上）
/H4/data: (N, 8) mixed dtype（同上）
/ticks/data: (M, 7) structured array
  - time(int64), time_msc(int64), bid/ask/last(float32), volume/flags(int32)
/metadata: JSON文字列（収集条件、API endpoint、統計情報等）
```

**注意**: 
- バーデータの実際の配列は`np.hstack([time_col(int64), price_cols(float32)])`の結果
- HDF5に保存時は混合型として格納されるが、各列の型は保持される
- 読み込み時は`data[:, 0].astype(np.int64)`でタイムスタンプを取得

**メタデータ例**:
```json
{
  "symbol": "USDJPY",
  "start_date": "2024-01-01",
  "end_date": "2024-12-31",
  "api_endpoint": "http://192.168.50.172:8000",
  "collection_time": "2025-10-23T23:30:45+09:00",
  "bar_counts": {
    "M1": 525600,
    "M5": 105120,
    "M15": 35040,
    "H1": 8760,
    "H4": 2190
  },
  "tick_count": 36000000,
  "file_size_mb": 9216
}
```
```

**補助系列**:
```
/micro/M1/{mid_open, mid_close, session_flag}
/indicators/M1/atr14  # 欠損判定用キャッシュのみ、特徴量は第2段階で計算
```

**Tick（直近期間のみ）**:
```
/ticks_recent/{time, bid, ask, last, volume, flags}
/ticks_recent/{inter_arrival_ms, direction_flag, signed_volume, spread_recalc, mid_price}
```

**メタデータ**:
```
/metadata/collection_info       # 収集期間、件数、シンボル情報
/metadata/quality_stats         # 欠損率、異常値件数
/metadata/alignment_info        # TF整合統計
/metadata/spread_stats          # spread統計（mean/p95/max/jump_count）
/metadata/microstructure_stats  # tick頻度、方向転換率、到着間隔統計
```

---

## 🔄 処理フロー

### 0. 初期化
- 既存HDF5ファイルのバックアップ（JST日時プレフィックス付きリネーム）
- 既存Tickデータのクリーン（`clear_tick_data()`実行）
  - **重要**: バーデータ収集前に実行し、前回実行のTickデータ残留を防止
  - **背景**: HDF5を`'a'`モードで開くと既存データが保持されるため、明示的削除が必要

### 1. データ取得
各タイムフレームの生データをMT5 API Serverから取得

**タイムフレーム**: M1, M5, M15, H1, H4（5種類）
**エンドポイント**: `POST /historical`
**戻り値**: numpy配列（N行 × 8列: time, OHLC, tick_volume, spread, real_volume）

### 2. タイムスタンプ整合（実装完了）
全タイムフレームをM1基準（1分間隔）に整合

**実装クラス**: `TimestampAligner`（`src/data_collector/timestamp_aligner.py`）

**処理内容**:
1. M1のUNIXタイムスタンプをdatetime系列に変換（基準）
2. 各TF（M5/M15/H1/H4）をM1時系列に`reindex`（前方補完）
3. 整合済みnumpy配列を返す

**結果**:
- 全TFが同じ行数（M1基準）に統一
- 補完率: M5(80%), M15(93%), H1(98%), H4(99.6%)

詳細: [TIMESTAMP_ALIGNMENT_SPEC.md](./data_collector/TIMESTAMP_ALIGNMENT_SPEC.md)

### 3. タイムゾーン変換
ブローカータイム → UTC（全TF + Tick）

### 3. タイムゾーン変換
ブローカータイム → UTC（全TF + Tick）

**重要**: MT5が返すタイムスタンプは**実際の市場イベント発生時刻**を表す
- ブローカーがUTC+3で表示していても、それは「表示形式」
- UTCに変換することで、実際の世界標準時刻を取得
- セッション判定（東京/欧州/NY）は、変換後のUTCで正しく機能する

**例**:
```python
# MT5が返す値（ブローカー表示: UTC+3）
broker_time = datetime(2025, 10, 23, 10, 0, 0, tzinfo=timezone(timedelta(hours=3)))

# UTC変換（実際の世界標準時）
utc_time = broker_time.astimezone(timezone.utc)
# → datetime(2025, 10, 23, 7, 0, 0, tzinfo=UTC)

# この時刻での実際の市場状態:
# - 東京市場（JST 16:00 = UTC 7:00）: 閉場後
# - 欧州市場（UTC 7:00-15:00）: 営業中
# - NY市場（UTC 13:00-21:00）: 未開場
```

**検証ログ**:
```python
def convert_to_utc(timestamp, broker_tz='UTC+3'):
    """
    タイムスタンプをUTCに変換
    
    二重UTC正規化を検出してログ出力
    """
    if timestamp.tzinfo is None:
        # タイムゾーン情報なし: broker_tzと仮定
        converted = timestamp.replace(tzinfo=broker_tz).astimezone(UTC)
        logger.debug(f"Timezone conversion: naive -> UTC (assumed {broker_tz})")
        return converted, True
    
    elif timestamp.tzinfo == UTC:
        # 既にUTC: 変換不要
        logger.warning(
            f"Timezone already UTC: {timestamp}\n"
            f"  Double UTC normalization risk detected.\n"
            f"  Check data source configuration."
        )
        return timestamp, False
    
    else:
        # 他のタイムゾーン: UTC変換
        converted = timestamp.astimezone(UTC)
        logger.debug(f"Timezone conversion: {timestamp.tzinfo} -> UTC")
        return converted, True

# 統計集計
tz_stats = {
    'converted': 0,      # 変換実行
    'already_utc': 0,    # 既にUTC
    'naive': 0           # タイムゾーン情報なし
}

# 変換後に統計を出力
logger.info(
    f"🔄 タイムゾーン変換統計\n"
    f"   変換実行: {tz_stats['converted']}件\n"
    f"   既にUTC: {tz_stats['already_utc']}件 (二重変換リスク)\n"
    f"   naive時刻: {tz_stats['naive']}件"
)

# 閾値監視
if tz_stats['already_utc'] / total_count > 0.01:  # 1%超
    logger.error(
        f"二重UTC変換リスク: {tz_stats['already_utc']}件 "
        f"({tz_stats['already_utc']/total_count*100:.1f}%)\n"
        f"データソース設定を確認してください。"
    )
```

### 3. タイムスタンプ整合（実装完了）

**目的**: 全タイムフレーム（M1/M5/M15/H1/H4）のバーデータを、M1基準の1分間隔に整合し、TF間計算を可能にする。

**実装方式**:
- **基準タイムフレーム**: M1（1分間隔、最も細かい粒度）
- **整合アルゴリズム**: pandas `reindex()` + 前方補完（forward fill）
- **処理タイミング**: バーデータ収集後、HDF5保存前

**処理フロー**:
```python
# 1. M1のUNIX時刻をdatetimeに変換（基準時系列）
m1_times = pd.to_datetime(M1[:, 0].astype(np.int64), unit='s', utc=True)

# 2. 各TF（M5/M15/H1/H4）をM1基準に整合
for tf in ['M5', 'M15', 'H1', 'H4']:
    # 2-1. TFデータをDataFrameに変換
    tf_df = pd.DataFrame(tf_array, columns=BAR_COLUMNS)
    tf_df.index = pd.to_datetime(tf_array[:, 0].astype(np.int64), unit='s', utc=True)
    
    # 2-2. M1時系列に合わせてreindex（前方補完）
    aligned_df = tf_df.reindex(m1_times, method='ffill')
    
    # 2-3. numpy配列に戻す
    aligned_array = aligned_df.values.astype(np.float64)

# 結果: 全TFが同じ行数（M1基準）に統一
```

**補完動作**:
- M5バーが5分間に1本 → M1基準では5行に前方補完（最初5行が同じ値）
- M15バーが15分間に1本 → M1基準では15行に前方補完
- H1バーが60分間に1本 → M1基準では60行に前方補完
- H4バーが240分間に1本 → M1基準では240行に前方補完

**実測結果**（2024-10-01 ～ 2024-10-31、1ヶ月）:
- **M1**: 31,642行（基準）
- **M5**: 6,337行 → 31,642行（補完率: 80.0%）
- **M15**: 2,113行 → 31,642行（補完率: 93.3%）
- **H1**: 529行 → 31,642行（補完率: 98.3%）
- **H4**: 132行 → 31,642行（補完率: 99.6%）

**品質保証**:
- ✅ 全TFの単調性検査合格
- ✅ 重複なし
- ✅ 前方補完動作確認（M5の最初5行が同じ値を保持）
- ✅ H4先頭のNaN: 正常動作（M1開始時刻とH4バー時刻の不一致）

**実装クラス**: `TimestampAligner`（`src/data_collector/timestamp_aligner.py`）

**詳細仕様**: `docs/data_collector/TIMESTAMP_ALIGNMENT_SPEC.md`

### 4. Tick処理（月分割取得）
- **期間分割**: 収集期間を月単位に分割（例: 2025-04-01～2025-09-30 → 6ヶ月）
  - 実装: `dateutil.relativedelta` 使用、月初～月末のISO8601文字列生成
- **月ごと取得**: 各月のTickデータをMT5 APIから取得
  - タイムアウト: 300秒（1ヶ月約60秒想定、余裕を持たせた設定）
- **HDF5追記保存**: 
  - 初回: `create_dataset()` with `maxshape=(None,)` で可変長データセット作成
  - 2回目以降: `dataset.resize()` で領域拡張後、データ追記
- **単調性検査**: time 厳密増加（月ごとに検証）
- **異常除去**: 重複、順序逆行
- **マイクロ構造指標計算**:
  - `inter_arrival_ms` = 前tickとの時間差（ms）
  - `direction_flag` = sign(mid_price - prev_mid_price) ∈ {-1, 0, 1}
  - `signed_volume` = direction_flag × volume
  - `spread_recalc` = ask - bid（検算用）
- **詳細**: `docs/data_collector/MICROSTRUCTURE_SPEC.md`

### 5. 品質検証
各種検証条件をチェック（後述）

### 6. HDF5保存
整合済みバーデータ + Tick + 補助系列 + メタデータを保存

### 5. 品質検証
各種検証条件をチェック（後述）

### 6. HDF5保存
バーデータ + Tick + 補助系列 + メタデータを保存

**実装クラス**: `HDF5Writer`（`src/data_collector/hdf5_writer.py`）

**クラス定数**:
```python
# Tickデータのフィールド定義（構造化配列用）
TICK_DTYPE = [
    ('time', 'i8'),
    ('time_msc', 'i8'),
    ('bid', 'f4'),
    ('ask', 'f4'),
    ('last', 'f4'),
    ('volume', 'i4'),
    ('flags', 'i4')
]
```

**主要メソッド**:
- `backup_existing()`: 既存ファイルをJST日時プレフィックス付きでリネーム
- `clear_tick_data()`: 既存Tickデータセットを削除（月分割取得の初回クリーン用）
- `write_bar_data()`: バーデータを保存（上書きモード）
- `append_tick_data()`: Tickデータを追記（初回は `maxshape=(None,)` で作成、2回目以降は `resize()` + 追記）
- `write_metadata()`: メタデータをJSON文字列として保存

**保存例**:
```python
# HDF5への保存例
with h5py.File('data/data_collector.h5', 'w') as f:
    # M1, M5, M15, H1, H4 バーデータ
    for tf in ['M1', 'M5', 'M15', 'H1', 'H4']:
        f.create_dataset(f'{tf}/data', data=bar_data[tf])
    
    # Tickデータ（構造化配列、月分割追記対応）
    f.create_dataset('ticks/data', data=tick_data, maxshape=(None,))
    
    # メタデータ
    f.attrs['symbol'] = 'USDJPY'
    f.attrs['timezone'] = 'UTC'
```

### 7. レポート生成

#### JSONレポート (`data/data_collector_report.json`)

次処理（特徴量計算）が読み込むパラメータ情報:

```json
{
  "timestamp": "2025-10-24T14:30:45+09:00",
  "process": "data_collector",
  "version": "1.0",
  "input": {
    "api_server": "http://192.168.50.172:8000",
    "symbol": "USDJPY",
    "period": {
      "start": "2018-01-01T00:00:00Z",
      "end": "2025-10-23T23:59:59Z"
    }
  },
  "output": {
    "file": "data/data_collector.h5",
    "size_mb": 9500
  },
  "timeframes": {
    "M1": {
      "bars": 2500000,
      "missing_count": 5000,
      "missing_rate": 0.002,
      "period": {"start": "2018-01-01T00:00:00Z", "end": "2025-10-23T23:59:59Z"}
    },
    "M5": {
      "bars": 500000,
      "missing_count": 500,
      "missing_rate": 0.001,
      "period": {"start": "2018-01-01T00:00:00Z", "end": "2025-10-23T23:59:59Z"}
    },
    "M15": {"bars": 166666, "missing_count": 150, "missing_rate": 0.0009},
    "H1": {"bars": 41666, "missing_count": 30, "missing_rate": 0.0007},
    "H4": {"bars": 10416, "missing_count": 5, "missing_rate": 0.0005}
  },
  "ticks": {
    "count": 13840269,
    "months": 6,
    "storage_mb": 491,
    "period": {"start": "2025-04-01T00:00:00Z", "end": "2025-09-30T23:59:59Z"}
  },
  "quality": {
    "duplicates_removed": 0,
    "timestamp_errors": 0,
    "monotonic_check": "passed",
    "spread_outliers": 12
  },
  "performance": {
    "execution_time_sec": 1200,
    "api_requests": 150,
    "avg_request_time_ms": 800
  }
}
```

#### Markdownレポート (`data/data_collector_report.md`)

人間による検証用の可読レポート:

```markdown
# データ収集 実行レポート

**実行日時**: 2025-10-24 14:30:45 JST  
**処理時間**: 20分00秒  
**バージョン**: 1.0

## 📊 入力

- **MT5 API Server**: http://192.168.50.172:8000
- **通貨ペア**: USDJPY
- **期間**: 2018-01-01 00:00:00 UTC ～ 2025-10-23 23:59:59 UTC (7年間)

## 🎯 処理結果

- **出力ファイル**: `data/data_collector.h5`
- **ファイルサイズ**: 9,500 MB

### タイムフレーム別統計

| TF | バー数 | 欠損数 | 欠損率 | 期間 |
|----|--------|--------|--------|------|
| M1 | 2,500,000 | 5,000 | 0.20% | 2018-01-01 ～ 2025-10-23 |
| M5 | 500,000 | 500 | 0.10% | 2018-01-01 ～ 2025-10-23 |
| M15 | 166,666 | 150 | 0.09% | 2018-01-01 ～ 2025-10-23 |
| H1 | 41,666 | 30 | 0.07% | 2018-01-01 ～ 2025-10-23 |
| H4 | 10,416 | 5 | 0.05% | 2018-01-01 ～ 2025-10-23 |

### Tickデータ統計

- **Tick数**: 13,840,269
- **ストレージ**: 491 MB
- **期間**: 2025-04-01 ～ 2025-09-30（6ヶ月）
- **取得方法**: 月分割取得（6ヶ月 → 6回API呼び出し）

## 📈 品質統計

| 項目 | 値 |
|-----|-----|
| 重複除去数 | 0 |
| タイムスタンプエラー | 0 |
| 単調性チェック | ✅ 合格 |
| スプレッド外れ値 | 12 |

## ⚙️ パフォーマンス

- **API リクエスト数**: 150回
- **平均レスポンス時間**: 800ms

## ⚠️ 警告・注意事項

- M1の欠損率が0.20%（許容範囲内）
- スプレッド外れ値12件を除外（Flash Crash等）

## ✅ 検証結果

- ✅ 全タイムフレームの単調性チェック合格
- ✅ 重複データなし
- ✅ タイムスタンプ整合性確認
- ✅ Tickデータ品質良好
```

---

## ✅ 検証条件

### 品質検証項目

| 項目 | 条件 | 失敗時処理 | 詳細出力 |
|------|------|------------|---------|
| タイムスタンプ単調性 | 厳密増加（全TF + Tick） | ERROR停止 | 最初の違反箇所（index, timestamp, diff）を出力 |
| 重複 | 0件 | ERROR停止 | 重複値とインデックスを出力 |
| 欠損率 | < 0.5% (TF別) | WARNING | 欠損数、欠損率を出力 |
| spread妥当性 | spread_min ≤ snapshot ≤ spread_max | ERROR停止 | 負spread件数を出力 |
| 負spread | 0件 | ERROR停止 | 負spread件数を出力 |
| tick_volume連続ゼロ | < 120本 | WARNING | 最大連続ゼロ数を出力 |
| Tick順序異常 | 0件 | ERROR停止 | 違反箇所の詳細を出力 |

### 設定検証（実行前チェック）

データ収集開始前に `ConfigManager.validate_data_collection_config()` で以下を検証：

| 項目 | 検証内容 | エラー時の対応 |
|------|---------|---------------|
| タイムフレーム | `['M1', 'M5', 'M15', 'H1', 'H4']` のみ許可 | ValueError + 有効値リスト表示 |
| 通貨ペア | 大文字、6-10文字 | ValueError + フォーマット説明 |
| 期間（start/end） | `YYYY-MM-DD` 形式、start < end | ValueError + 正しいフォーマット例 |
| 未来日チェック | 終了日 > 今日 | Warning（実行は継続） |
| 品質閾値 | 0 < 閾値 < 1 | ValueError + 有効範囲表示 |

### 実装の品質改善

**1. マジックナンバーの定数化**:
```python
# DataCollectorクラス内定義
BAR_COLUMNS = {
    'time': 0,
    'open': 1,
    'high': 2,
    'low': 3,
    'close': 4,
    'tick_volume': 5,
    'spread': 6,
    'real_volume': 7
}

# 使用例
timestamps = bar_array[:, self.BAR_COLUMNS['time']].astype(np.int64)
spreads = bar_array[:, self.BAR_COLUMNS['spread']]
tick_volumes = bar_array[:, self.BAR_COLUMNS['tick_volume']]
```

**2. 型ヒントの完全化**:
- すべてのメソッドに戻り値の型ヒント（`-> None`, `-> bool` 等）を明記
- `Optional`, `List`, `Dict`, `Tuple` 等の型を `typing` から適切にインポート

**3. エラーログの詳細化**:
- 単調性違反時: 違反インデックス、タイムスタンプ値、差分を出力
- 重複検出時: 重複値、出現回数、インデックスリストを出力
- 設定エラー時: 無効値、有効値リスト、修正例を出力

---

## 📝 ログ出力

### 時刻表示ルール
- **全ログ**: 日本時間(JST)で表示
- **フォーマット**: `YYYY-MM-DD HH:MM:SS JST`
- **期間表示**: 開始/終了とも日本時間で明記

### 最小限の情報
```
📂 データ取得完了 [2025-10-23 23:30:45 JST]
   期間: 2024-01-01 00:00:00 JST ～ 2024-12-31 23:59:00 JST
   M1=50000件, M5=10000件, M15=3333件, H1=833件, H4=208件
   Tick=120000件

🔍 欠損検出
   M1短期=5本, M5長期=2セグメント, 休場=10セグメント

🔄 補完処理
   M1=5本補完, 除外=12セグメント

📊 spread統計
   mean=1.2pips, p95=1.8pips, max=3.5pips, jump=8回

🧪 マイクロ構造統計
   tick_freq_mean=180/min, inter_arrival_p95=850ms
   direction_flip_rate=0.42, spread_jump=8回

✅ 品質検証: 全TF合格 [2025-10-23 23:31:02 JST]
```

---

## ⚙️ 設定例

```yaml
data_collection:
  symbols: ["USDJPY"]
  timeframes: ["M1", "M5", "M15", "H1", "H4"]
  
  timezone:
    broker: "Europe/London"      # ブローカーのタイムゾーン
    storage: "UTC"                # HDF5内部保存形式（固定）
    display: "Asia/Tokyo"         # ログ・レポート表示（JST）
  
  quality_thresholds:
    max_gap_ratio: 0.005        # 欠損率上限 0.5%
    max_gap_fill: 3             # 短期欠損判定（3本未満は補完）
    max_zero_streak: 120        # tick_volume連続ゼロ上限
  
  spread:
    store_min: true
    store_max: true
    jump:
      enabled: true
      lookback: 120
      threshold_multiplier: 1.5
  
  mid_price_samples: ["open", "close"]
  
  atr_cache:
    enabled: true
    windows: [14]
    purpose: "欠損データ検出用の補助キャッシュ。特徴量としては第2段階で再計算される。"
  
  session_flag:
    mode: market_session         # market_session | utc_hour
  
  ticks:
    enabled: true
    retention:
      # 詳細は STORAGE_POLICY_SPEC.md を参照
      # Training: 3 months, Inference: 24 hours
      mode: months               # years | months | days
      value: 3                   # 学習用は3ヶ月、推論用は24時間（別ストレージ）
      rolling_update: true
    microstructure_raw:
      store_inter_arrival: true
      store_direction_flag: true
      store_signed_volume: true
      store_spread_recalc: true
    quality_thresholds:
      max_inter_arrival_ms: 3000
      max_direction_flat_ratio: 0.15
  
  compression_enabled: false     # 処理速度優先（推論用）
                                 # 学習用はgzip有効（STORAGE_POLICY_SPEC.md）
  
  validation:
    check_monotonic: true
    check_duplicates: true
    check_spread_valid: true
```

---

## 🚨 エラー条件

以下の条件で処理を停止（ERROR）:

- タイムスタンプ重複（TF or Tick）
- タイムスタンプ単調性違反
- 長期欠損率超過（TF別）
- タイムゾーン変換失敗
- spread_negative > 0
- Tick順序逆行件数 > 0
- ATR14計算失敗（NaN多発）

---

## 🔗 関連仕様書

- **次工程**: 第2段階: [FEATURE_CALCULATOR_SPEC.md](./FEATURE_CALCULATOR_SPEC.md) - 特徴量計算
- **詳細仕様**:
  - [data_collector/TIMESTAMP_ALIGNMENT_SPEC.md](./data_collector/TIMESTAMP_ALIGNMENT_SPEC.md) - タイムスタンプ整合
  - [data_collector/MICROSTRUCTURE_SPEC.md](./data_collector/MICROSTRUCTURE_SPEC.md) - マイクロ構造指標
  - [data_collector/STORAGE_POLICY_SPEC.md](./data_collector/STORAGE_POLICY_SPEC.md) - ストレージポリシー（学習用/推論用の分離設計）

---

## 📌 注意事項

### コーディング規約
1. **PEP 8準拠**: インポート順序（標準ライブラリ → サードパーティ → ローカル）
2. **型ヒント完全化**: すべてのメソッドに戻り値型（`-> None`, `-> bool` 等）を明記
3. **マジックナンバー禁止**: 配列インデックスは `BAR_COLUMNS` 等の定数で定義
4. **エラーログ詳細化**: 
   - 単調性違反: 違反インデックス、タイムスタンプ値、差分を出力
   - 重複検出: 重複値、出現回数、インデックスリストを出力
   - 設定エラー: 無効値、有効値リスト、修正例を提示

### データ管理
5. **圧縮設定**: 推論用は無効（速度優先）、学習用は有効（gzip level 4）
6. **Git管理外**: `data/*.h5` はGitignore対象
7. **既存ファイル自動退避**: 処理実行時、既存ファイル（HDF5, JSON, Markdown）はJST日時プレフィックス付きで自動保存
8. **エラー握りつぶし禁止**: 異常検出時は必ず `raise` で停止

### 設計方針
9. **シンボル拡張**: 複数シンボル対応は設計済み（config で切替可能）
10. **D1バー**: 取得せず、必要時はH4から派生サマリ生成
11. **ストレージ分離**: 学習用(3ヶ月)と推論用(24時間)で別ファイル管理（STORAGE_POLICY_SPEC.md参照）
12. **設定検証**: 実行前に `validate_data_collection_config()` で全設定を検証
    - タイムフレーム、通貨ペア、期間、閾値の妥当性チェック
    - エラー時は詳細メッセージと修正例を表示

### 統計データ整合性
13. **HDF5メタデータとレポートの一致保証**:
    - ⚠️ **旧プロジェクトの教訓**: 統計辞書の上書きによる齟齬が発生
    - ✅ **現実装**: `dict.update()` で統計をマージし、複数ソースからのデータを統合
    - 実装箇所: `_validate_bars()` と `_collect_bars()` で同一キーに対して `update()` 使用
    - 検証方法: `tools/data_collector/inspect_hdf5.py` でメタデータ確認後、JSONレポートと件数比較

---

## 🔮 将来拡張

- 複数シンボル同時取得（config.symbols >1）
- インテリジェント圧縮（古いデータほど高圧縮率）
- 分散ストレージ（SSD/HDD/S3階層化）
- 板情報（Depth）統合
- 追加ATR窓（21/50）
- 派生日次サマリ自動生成
- volume-bar / imbalance-bar保存
- order flow proxy解析

---

## 🔧 検査ツール

### inspect_hdf5.py

**パス**: `tools/data_collector/inspect_hdf5.py`

**目的**: データ収集結果のHDF5ファイルを検査し、データ品質を確認。

**使用方法**:
```bash
# デフォルト実行（構造とメタデータのみ）
bash ./docker_run.sh python3 tools/data_collector/inspect_hdf5.py

# 特定ファイル指定
bash ./docker_run.sh python3 tools/data_collector/inspect_hdf5.py data/20251024_120809_data_collector.h5

# M1タイムフレーム詳細表示（サンプル5件）
bash ./docker_run.sh python3 tools/data_collector/inspect_hdf5.py --timeframe M1

# 全タイムフレーム表示（サンプル3件）
bash ./docker_run.sh python3 tools/data_collector/inspect_hdf5.py --all -n 3

# Tickデータ表示
bash ./docker_run.sh python3 tools/data_collector/inspect_hdf5.py --ticks

# ヘルプ表示
bash ./docker_run.sh python3 tools/data_collector/inspect_hdf5.py --help
```

**主な機能**:
- HDF5構造表示（グループ、データセット、shape、dtype）
- メタデータ表示（JSON形式パース）
- タイムフレーム別統計（件数、期間、単調性、重複チェック）
- Tickデータ統計とサンプル表示
- タイムスタンプ精度問題の検出（float32精度損失警告）

**検出される問題**:
- ⚠️ タイムスタンプ単調性違反（float32精度問題）
- ⚠️ 重複レコード
- ✅ 正常データには緑チェックマーク表示

**トラブルシューティング**:

タイムスタンプ精度問題の症状と解決:
```
症状: M1で大量の単調性違反（例: 196,949件）
原因: データがfloat32形式で保存（UNIX時間10桁、float32は7桁精度）
解決: 
  1. src/data_collector/collector.py の _convert_bars_to_array() を確認
  2. タイムスタンプ列をint64で分離保存していることを確認
  3. データを再収集
```

````
