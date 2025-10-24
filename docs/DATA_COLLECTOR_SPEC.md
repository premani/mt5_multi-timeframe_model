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
- **容量想定**: 7年間で約9-10 GB（圧縮なし）、2-3 GB（圧縮あり）

---

## 🎯 スコープ

### ✅ 実装範囲

**バーデータ（OHLC）**:
- **タイムフレーム**: M1, M5, M15, H1, H4
- **データ項目**: time, open, high, low, close, tick_volume, spread, real_volume
- **型**: time(int64), OHLC(float32), volumes(float32)

**Tickデータ（Ask/Bid時系列）**:
- **データ項目**: time, time_msc, bid, ask, last, volume, flags
- **型**: time/time_msc(int64), bid/ask/last(float32), volume/flags(int32)
- **取得方法**: MT5 API Server `/ticks` エンドポイント（新規実装必要）

**接続方式**: MT5 API Server（HTTP/REST）
- **バーデータ**: `POST /historical` エンドポイント
- **Tickデータ**: `POST /ticks` エンドポイント（追加実装）
- **認証**: Bearer Token（環境変数 `MT5_API_KEY`）
- **タイムアウト**: 60秒（環境変数 `MT5_API_TIMEOUT` で変更可能）

**対象シンボル**: USDJPY（初期、複数シンボルへ拡張可能）  
**時刻管理**: MT5から返されるUTCタイムスタンプをそのまま使用  
**圧縮**: 無効（処理速度優先、学習用は別途圧縮版作成）

**重要**: 
- ATR14等の特徴量は**第2段階で正式に計算**（第1段階ではキャッシュしない）
- Tickデータは全期間保存（7年間で約9-10 GB想定）

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
MT5_API_TIMEOUT=60
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
- `time`: int64（UTCエポック秒）
- `time_msc`: int64（UTCエポックミリ秒）
- `open/high/low/close/bid/ask`: float32
- `tick_volume/spread/real_volume`: float32
- `volume/flags`: int32

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
/M1/data: (N, 8) float32 [time, open, high, low, close, tick_volume, spread, real_volume]
/M5/data: (N, 8) float32
/M15/data: (N, 8) float32
/H1/data: (N, 8) float32
/H4/data: (N, 8) float32
/ticks/data: (M, 7) mixed [time(int64), time_msc(int64), bid/ask/last(float32), volume/flags(int32)]
/metadata: JSON文字列（収集条件、API endpoint、統計情報等）
```

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

### 1. データ取得
各タイムフレームの生データをMT5 APIから取得

### 2. タイムゾーン変換
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

### 3. タイムスタンプ整合
- **連続性検査**: 期待間隔（M1=60s, M5=300s, M15=900s, H1=3600s, H4=14400s）と実際の差分を比較
- **欠損分類**:
  - 短期（<3本）: forward fill（M1/M5のみ）+ `filled=True` フラグ
  - 長期（≥3本）: セグメント除外リストへ記録（学習時マスク）
  - 休場（週末/祝日）: `trading_halt_mask` 付与
- **詳細**: `docs/data_collector/TIMESTAMP_ALIGNMENT_SPEC.md`

### 4. Tick処理
- **単調性検査**: time 厳密増加
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
バーデータ + Tick + 補助系列 + メタデータを保存

```python
# HDF5への保存例
with h5py.File('data/data_collector.h5', 'w') as f:
    # M1, M5, M15, H1, H4 バーデータ
    for tf in ['M1', 'M5', 'M15', 'H1', 'H4']:
        f.create_dataset(f'{tf}/data', data=bar_data[tf])
    
    # Tickデータ
    f.create_dataset('ticks/data', data=tick_data)
    
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
    "count": 15000000,
    "storage_mb": 9000,
    "period": {"start": "2018-01-01T00:00:00Z", "end": "2025-10-23T23:59:59Z"}
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

- **Tick数**: 15,000,000
- **ストレージ**: 9,000 MB
- **期間**: 2018-01-01 ～ 2025-10-23

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

| 項目 | 条件 | 失敗時処理 |
|------|------|------------|
| タイムスタンプ単調性 | 厳密増加（全TF + Tick） | ERROR停止 |
| 重複 | 0件 | ERROR停止 |
| 欠損率 | < 0.5% (TF別) | WARNING |
| spread妥当性 | spread_min ≤ snapshot ≤ spread_max | ERROR停止 |
| 負spread | 0件 | ERROR停止 |
| tick_volume連続ゼロ | < 120本 | WARNING |
| Tick順序異常 | 0件 | ERROR停止 |

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

1. **圧縮設定**: 推論用は無効（速度優先）、学習用は有効（gzip level 4）
2. **Git管理外**: `data/*.h5` はGitignore対象
3. **既存ファイル自動退避**: 処理実行時、既存ファイルはJST日時プレフィックス付きで自動保存
4. **エラー握りつぶし禁止**: 異常検出時は必ず `raise` で停止
5. **シンボル拡張**: 複数シンボル対応は設計済み（config で切替可能）
6. **D1バー**: 取得せず、必要時はH4から派生サマリ生成
7. **ストレージ分離**: 学習用(3ヶ月)と推論用(24時間)で別ファイル管理（STORAGE_POLICY_SPEC.md参照）

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
