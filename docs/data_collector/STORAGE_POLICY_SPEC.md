# STORAGE_POLICY_SPEC.md

**バージョン**: 1.0  
**更新日**: 2025-10-21  
**責任者**: core-team

---

## 📋 目的

学習用とリアルタイム推論用のデータストレージを分離し、スキャルピング戦略に最適化された保持期間とメモリ効率を実現する。

---

## 🎯 設計原則

### 問題認識

```
矛盾:
- 学習: 長期履歴が必要（季節性、多様なパターン学習）
- 推論: 直近データのみ必要（24時間以内の保有戦略）

従来の1年保持:
❌ スキャルピングに過剰（1時間保有に1年分不要）
❌ ストレージ肥大化（Tickは巨大）
❌ I/O遅延（推論時に不要な古いデータも読み込み）
```

### 解決方針

**2系統のストレージ管理**:
1. **Training Storage**: 長期保持、バッチ更新、圧縮有効
2. **Inference Storage**: 短期保持、リアルタイム更新、圧縮無効（速度優先）

---

## 📦 ストレージ分類

### 1. Training Storage（学習・バックテスト用）

```yaml
training_storage:
  # 保持期間
  retention:
    tick_data: 3 months      # 四半期分（季節性カバー）
    bar_data: 6 months       # M1/M5/M15/H1/H4
    reason: "3ヶ月で多様な市場環境（トレンド/レンジ/高低ボラ）を学習可能"
  
  # ファイル形式
  file_naming: "fx_train_{symbol}_{YYYYMMDD}_{YYYYMMDD}.h5"
  example: "fx_train_USDJPY_20250101_20250331.h5"  # 3ヶ月分
  
  # 圧縮設定
  compression:
    enabled: true
    algorithm: "gzip"
    level: 4                  # 圧縮率と速度のバランス
    reason: "長期保存でストレージ削減優先"
  
  # 更新頻度
  update_frequency: daily     # 日次で新規データ追加
  update_time: "06:00 UTC"    # 東京市場開始前
  
  # 用途
  purposes:
    - model_training          # LSTM学習
    - hyperparameter_tuning   # グリッドサーチ
    - backtesting            # 履歴検証
    - validation             # ホールドアウト評価
    - feature_engineering    # 新特徴量開発
  
  # ローテーション
  rotation:
    interval: monthly
    archive_after: 6 months   # 6ヶ月超は別ストレージへ
    archive_format: "tar.gz"
    deletion_after: 2 years   # アーカイブも2年で削除
```

### 2. Inference Storage（リアルタイム推論用）

```yaml
inference_storage:
  # 保持期間
  retention:
    tick_data: 24 hours       # 直近1日分のみ
    bar_data: 48 hours        # M1/M5は24h、H1/H4は48h
    reason: "スキャルプ/スイングは数時間保有、24-48h分で十分"
  
  # ファイル形式
  file_naming: "fx_live_{symbol}_latest.h5"
  example: "fx_live_USDJPY_latest.h5"  # 常に最新24h分
  
  # 圧縮設定
  compression:
    enabled: false            # 速度優先
    reason: "リアルタイム推論でレイテンシ重視（圧縮展開コスト回避）"
  
  # 更新頻度
  update_frequency: real_time  # Tick受信ごと
  write_mode: "append"         # 追記モード
  
  # メモリ設計
  memory_structure:
    type: "ring_buffer"        # 固定サイズの循環バッファ
    max_size: 
      M1: 1440 bars            # 24時間
      M5: 288 bars             # 24時間
      tick: 100000 records     # 約24時間分（流動性による）
    overflow_behavior: "overwrite_oldest"  # 古いデータを上書き
  
  # 用途
  purposes:
    - real_time_prediction    # リアルタイム推論
    - pattern_detection       # 直近パターン認識
    - entry_signal_generation # エントリーシグナル
    - position_monitoring     # ポジション管理
  
  # 自動クリーンアップ
  auto_cleanup:
    enabled: true
    check_interval: "1 hour"
    delete_older_than: "24 hours"  # 24時間超のデータ削除
```

---

## 🏗️ ファイル構造

### Training Storage階層

```
data/training/
├── 2025Q1/
│   ├── fx_train_USDJPY_20250101_20250331.h5  # 3ヶ月分（現在使用中）
│   ├── fx_train_EURUSD_20250101_20250331.h5
│   └── metadata_2025Q1.json
├── 2024Q4/
│   ├── fx_train_USDJPY_20241001_20241231.h5  # 過去四半期（アーカイブ候補）
│   └── metadata_2024Q4.json
└── archive/
    ├── 2024Q3.tar.gz                          # 6ヶ月超のアーカイブ
    └── 2024Q2.tar.gz
```

### Inference Storage階層

```
data/inference/
├── fx_live_USDJPY_latest.h5     # 常に最新24時間（リング バッファ）
├── fx_live_EURUSD_latest.h5
└── metadata_live.json           # 最終更新時刻、データ範囲
```

---

## 📊 HDF5内部構造

### Training Storage

```python
# fx_train_USDJPY_20250101_20250331.h5

/tick                          # Tickデータ（圧縮有効）
  └── data: [N, 6]             # [time, bid, ask, volume, flags, spread]
      compression: gzip level 4
      chunks: (10000, 6)        # 10k行単位

/M1, /M5, /M15, /H1, /H4       # バーデータ
  └── data: [N, features]
      compression: gzip level 4
      chunks: (1000, features)

/metadata
  └── attrs: {
       "start_date": "2025-01-01T00:00:00",
       "end_date": "2025-03-31T23:59:59",
       "total_bars_M1": 129600,
       "total_ticks": 8500000,
       "purpose": "training",
       "git_commit": "abc123",
     }
```

### Inference Storage（Ring Buffer設計）

```python
# fx_live_USDJPY_latest.h5

/tick                          # 圧縮無効（速度優先）
  └── data: [100000, 6]        # 固定サイズ（Ring Buffer）
      compression: none
      fillvalue: NaN            # 未使用スロット
      attrs: {
        "write_index": 45123,   # 現在の書き込み位置
        "wrap_count": 2,        # ラップアラウンド回数
        "oldest_time": "2025-10-20T12:00:00",
        "newest_time": "2025-10-21T11:59:59",
      }

/M1                            # M1バー（24時間 = 1440本）
  └── data: [1440, features]   # 固定サイズ
      compression: none
      attrs: {
        "write_index": 823,
        "oldest_bar": "2025-10-20T12:00:00",
      }

/M5, /M15, /H1, /H4            # 同様の構造
```

**Ring Bufferの動作（項目72対応: wrap境界再初期化）**:
```python
def append_tick(h5_file, new_tick):
    """Tickをring bufferに追記（wrap境界で差分特徴量リセット）"""
    tick_dataset = h5_file["/tick/data"]
    write_idx = tick_dataset.attrs["write_index"]
    max_size = tick_dataset.shape[0]
    wrap_count_before = tick_dataset.attrs.get("wrap_count", 0)
    
    # 循環書き込み
    tick_dataset[write_idx % max_size] = new_tick
    
    # インデックス更新
    tick_dataset.attrs["write_index"] = write_idx + 1
    
    # wrap検出
    if write_idx > 0 and (write_idx % max_size) == 0:
        wrap_count_new = wrap_count_before + 1
        tick_dataset.attrs["wrap_count"] = wrap_count_new
        
        logger.info(f"Ring Buffer wrap検出: wrap_count={wrap_count_new}, "
                   f"oldest_index={write_idx % max_size}")
        
        # 差分特徴量の再初期化フック
        _reinitialize_differential_features(h5_file, timeframe="tick")


def _reinitialize_differential_features(h5_file, timeframe: str):
    """
    Ring Buffer wrap時の差分特徴量再初期化
    
    対象特徴量:
    - ATR（Average True Range）: 移動平均ウィンドウがwrap境界を跨ぐ
    - EMA（指数移動平均）: 過去値依存で不連続
    - その他の差分系特徴量（momentum, ROC等）
    
    再初期化手順:
    1. wrap境界の前後N本（例: 100本）を読み込み
    2. 差分特徴量を再計算
    3. 統計情報をログ出力（wrap前後の差分）
    """
    logger.info(f"差分特徴量再初期化開始: {timeframe}")
    
    # wrap境界付近のデータ読み込み（前100本、後100本）
    tick_data = h5_file[f"/{timeframe}/data"]
    write_idx = tick_data.attrs["write_index"]
    max_size = tick_data.shape[0]
    current_pos = (write_idx - 1) % max_size
    
    # 再計算対象範囲（wrap前100本 + wrap後100本）
    window_size = 100
    start_idx = max(0, current_pos - window_size)
    end_idx = min(max_size, current_pos + window_size)
    
    # 差分特徴量の再計算（例: ATR）
    # ※実際の実装では特徴量計算器を呼び出し
    high = tick_data[start_idx:end_idx, 2]  # High価格
    low = tick_data[start_idx:end_idx, 3]   # Low価格
    close = tick_data[start_idx:end_idx, 4] # Close価格
    
    # ATR再計算（簡略版）
    true_range = np.maximum(high - low, np.abs(high - np.roll(close, 1)))
    atr_recalc = np.mean(true_range[-14:])  # 14期間ATR
    
    # 統計ログ（wrap前後の差分確認）
    if f"/{timeframe}/features/atr" in h5_file:
        atr_old = h5_file[f"/{timeframe}/features/atr"][current_pos]
        logger.info(f"ATR再計算: old={atr_old:.6f}, new={atr_recalc:.6f}, "
                   f"delta={abs(atr_recalc - atr_old):.6f}")
        
        # 閾値チェック（差分が大きい場合は警告）
        if abs(atr_recalc - atr_old) > atr_old * 0.1:  # 10%以上差分
            logger.warning(f"ATR wrap境界で大きな飛び検出: {abs(atr_recalc - atr_old):.6f}")
        
        # 再計算値で更新
        h5_file[f"/{timeframe}/features/atr"][current_pos] = atr_recalc
    
    # EMA、momentum等の他の差分特徴量も同様に再計算
    # ...（省略）
    
    # 再初期化完了フラグ
    tick_data.attrs["last_reinit_wrap_count"] = tick_data.attrs.get("wrap_count", 0)
    logger.info(f"差分特徴量再初期化完了: {timeframe}")


# 使用例
with h5py.File("data/inference/USDJPY_inference_20251022.h5", "a") as h5:
    # Tick追記（自動wrap検出・再初期化）
    append_tick(h5, new_tick)
```

**Ring Buffer wrap再初期化仕様**:
- **検出条件**: `write_index % max_size == 0`
- **対象特徴量**: ATR, EMA, momentum, ROC等の差分系
- **再計算範囲**: wrap境界前後100本（調整可能）
- **統計ログ**: wrap前後のATR差分を記録（閾値10%で警告）
- **成功指標**: wrap後の特徴量飛び < 10%（ATR基準）

**wrap再初期化の効果**:
- 計算窓崩れによる指標飛び防止
- 推論品質の安定化（wrap境界での異常シグナル抑制）
- デバッグ可能性向上（wrap統計のログ出力）

---

## 🔄 データフロー

### 学習フェーズ

```
MT5 API → Data Collector → Training Storage (3ヶ月分)
                             ↓
                        Preprocessor → 特徴量HDF5
                             ↓
                        Trainer → 学習済みモデル
```

### 推論フェーズ

```
MT5 Tick Stream → Data Collector → Inference Storage (24h Ring Buffer)
                                      ↓
                                  Preprocessor (Incremental)
                                      ↓
                                  Model Inference (< 10ms)
                                      ↓
                                  Trade Signal
```

---

## ⚙️ 実装詳細

### 1. Training Storage更新（日次バッチ）

```python
class TrainingStorageManager:
    """学習用ストレージの管理"""
    
    def __init__(self, base_dir: str = "data/training"):
        self.base_dir = Path(base_dir)
        self.current_quarter = self._get_current_quarter()
    
    def daily_update(self, symbol: str, date: datetime):
        """日次で新規データを追加"""
        # 現在の四半期ファイルを開く
        h5_path = self._get_quarter_file(symbol, self.current_quarter)
        
        # MT5から前日分を取得
        tick_data = fetch_mt5_ticks(symbol, date, date + timedelta(days=1))
        bar_data = fetch_mt5_bars(symbol, date, date + timedelta(days=1))
        
        # 追記（圧縮有効）
        with h5py.File(h5_path, "a") as f:
            self._append_ticks(f, tick_data, compression="gzip")
            self._append_bars(f, bar_data, compression="gzip")
        
        logger.info(f"Training storage updated: {symbol} {date}")
    
    def rotate_quarterly(self):
        """四半期ローテーション"""
        old_quarters = self._get_quarters_older_than(months=6)
        
        for quarter in old_quarters:
            archive_path = self.base_dir / "archive" / f"{quarter}.tar.gz"
            self._archive_quarter(quarter, archive_path)
            logger.info(f"Archived quarter: {quarter}")
```

### 2. Inference Storage更新（リアルタイム）

```python
class InferenceStorageManager:
    """推論用ストレージの管理（Ring Buffer）"""
    
    def __init__(self, base_dir: str = "data/inference"):
        self.base_dir = Path(base_dir)
        self.max_tick_size = 100000
        self.max_bar_sizes = {"M1": 1440, "M5": 288, "M15": 96, "H1": 24, "H4": 12}
    
    def initialize_ring_buffer(self, symbol: str):
        """Ring Buffer初期化"""
        h5_path = self.base_dir / f"fx_live_{symbol}_latest.h5"
        
        with h5py.File(h5_path, "w") as f:
            # Tick用Ring Buffer
            f.create_dataset(
                "/tick/data",
                shape=(self.max_tick_size, 6),
                dtype="float32",
                fillvalue=np.nan,
                compression=None,  # 圧縮無効
            )
            f["/tick/data"].attrs["write_index"] = 0
            f["/tick/data"].attrs["wrap_count"] = 0
            
            # 各TF用Ring Buffer
            for tf, size in self.max_bar_sizes.items():
                f.create_dataset(
                    f"/{tf}/data",
                    shape=(size, 50),  # 50特徴量（例）
                    dtype="float32",
                    fillvalue=np.nan,
                    compression=None,
                )
                f[f"/{tf}/data"].attrs["write_index"] = 0
    
    def append_tick(self, symbol: str, tick: np.ndarray):
        """Tickをring bufferに追記（リアルタイム）"""
        h5_path = self.base_dir / f"fx_live_{symbol}_latest.h5"
        
        with h5py.File(h5_path, "a") as f:
            dataset = f["/tick/data"]
            write_idx = dataset.attrs["write_index"]
            max_size = dataset.shape[0]
            
            # 循環書き込み
            dataset[write_idx % max_size] = tick
            
            # インデックス更新
            dataset.attrs["write_index"] = write_idx + 1
            dataset.attrs["newest_time"] = tick[0]  # timestamp
            
            # ラップアラウンド検出
            if write_idx > 0 and write_idx % max_size == 0:
                dataset.attrs["wrap_count"] += 1
                dataset.attrs["oldest_time"] = tick[0]
    
    def get_recent_data(self, symbol: str, tf: str, bars: int) -> np.ndarray:
        """直近N本を取得（推論用）"""
        h5_path = self.base_dir / f"fx_live_{symbol}_latest.h5"
        
        with h5py.File(h5_path, "r") as f:
            dataset = f[f"/{tf}/data"]
            write_idx = dataset.attrs["write_index"]
            max_size = dataset.shape[0]
            
            # 循環バッファから直近N本を抽出
            if write_idx < bars:
                # まだラップしていない
                return dataset[:write_idx]
            else:
                # ラップ済み → 最新位置から逆算
                start = (write_idx - bars) % max_size
                end = write_idx % max_size
                
                if start < end:
                    return dataset[start:end]
                else:
                    # バッファ末尾と先頭にまたがる
                    return np.vstack([
                        dataset[start:],
                        dataset[:end]
                    ])
    
    def auto_cleanup(self, symbol: str):
        """24時間超のデータを削除"""
        # Ring Bufferでは自動上書きされるため、特別な処理不要
        # ただしメタデータのoldest_timeを更新
        h5_path = self.base_dir / f"fx_live_{symbol}_latest.h5"
        
        with h5py.File(h5_path, "a") as f:
            write_idx = f["/tick/data"].attrs["write_index"]
            max_size = f["/tick/data"].shape[0]
            
            if write_idx >= max_size:
                # ラップ済み → 古いデータは自動的に上書きされている
                oldest_idx = write_idx % max_size
                oldest_time = f["/tick/data"][oldest_idx, 0]  # timestamp列
                f["/tick/data"].attrs["oldest_time"] = oldest_time
                
                logger.debug(f"Auto cleanup: oldest_time updated to {oldest_time}")
```

### 3. ストレージ切替ロジック

```python
class DataCollector:
    """データ収集の統合管理"""
    
    def __init__(self, mode: str = "training"):
        self.mode = mode
        
        if mode == "training":
            self.storage = TrainingStorageManager()
        elif mode == "inference":
            self.storage = InferenceStorageManager()
        else:
            raise ValueError(f"Unknown mode: {mode}")
    
    def collect_and_store(self, symbol: str, **kwargs):
        """モードに応じたデータ収集"""
        if self.mode == "training":
            # バッチ収集（日次更新）
            self.storage.daily_update(symbol, kwargs["date"])
        
        elif self.mode == "inference":
            # リアルタイム収集（Tick単位）
            tick_stream = subscribe_mt5_ticks(symbol)
            for tick in tick_stream:
                self.storage.append_tick(symbol, tick)
```

---

## 📏 サイズ見積もり

### Training Storage（3ヶ月分）

```
Tick（圧縮後）:
- 1 tick = 24 bytes（6 float32）
- 1日 = 約100,000 ticks（流動性による）
- 3ヶ月 = 9,000,000 ticks × 24 bytes = 216 MB
- gzip圧縮 (level 4) → 約 60 MB

Bar（M1/M5/M15/H1/H4、圧縮後）:
- M1: 129,600 bars × 50 features × 4 bytes = 25.9 MB → 圧縮後 10 MB
- M5: 25,920 bars × 2.6 MB → 圧縮後 1 MB
- M15/H1/H4: 各 < 1 MB

合計: 約 75 MB / 四半期 / シンボル
```

### Inference Storage（24時間分）

```
Tick（圧縮なし）:
- 100,000 ticks × 24 bytes = 2.4 MB（固定サイズ）

Bar（M1=1440本、M5=288本、圧縮なし）:
- M1: 1440 × 50 × 4 = 0.28 MB
- M5: 288 × 50 × 4 = 0.06 MB
- M15/H1/H4: 各 < 0.05 MB

合計: 約 3 MB / シンボル（固定）
```

**比較**:
- Training: 75 MB × 4四半期 = 300 MB/年（圧縮済み）
- Inference: 3 MB（常に固定、古いデータは上書き）

---

## 🔧 設定ファイル

### config/data_collector.yaml

```yaml
storage_policy:
  # モード選択
  mode: training  # training | inference
  
  # Training Storage設定
  training:
    base_dir: "data/training"
    retention:
      tick_data: 3 months
      bar_data: 6 months
    compression:
      enabled: true
      algorithm: gzip
      level: 4
    update:
      frequency: daily
      time: "06:00 UTC"
    rotation:
      interval: monthly
      archive_after: 6 months
      archive_dir: "data/training/archive"
  
  # Inference Storage設定
  inference:
    base_dir: "data/inference"
    retention:
      tick_data: 24 hours
      bar_data:
        M1: 24 hours
        M5: 24 hours
        M15: 48 hours
        H1: 48 hours
        H4: 48 hours
    compression:
      enabled: false  # 速度優先
    ring_buffer:
      max_tick_size: 100000
      max_bar_sizes:
        M1: 1440
        M5: 288
        M15: 192
        H1: 96
        H4: 48
    auto_cleanup:
      enabled: true
      check_interval: 1 hour
      delete_older_than: 24 hours
```

---

## 🚨 エラー条件

以下の条件で処理を停止（ERROR）:

1. **Ring Buffer溢れ**: `write_index` が異常に進んでいる（> max_size × 10）
2. **ディスク容量不足**: Training Storageが95%超
3. **タイムスタンプ異常**: 24時間以上の古いデータがInference Storageに残存
4. **書き込み失敗**: HDF5ファイルロックエラー

### HDF5ロックエラー再試行戦略

HDF5ファイルの同時書き込み時、一過性ロックエラーで即停止を避けるための指数バックオフリトライ実装：

```python
import time
import h5py
from functools import wraps

class HDF5LockError(Exception):
    """HDF5ロック関連エラー"""
    pass


def hdf5_retry(max_attempts: int = 3, initial_delay: float = 0.1, 
               backoff_factor: float = 2.0, readonly_retry: bool = True):
    """
    HDF5アクセスのリトライデコレータ
    
    Args:
        max_attempts: 最大試行回数（デフォルト3回）
        initial_delay: 初回待機時間（秒）
        backoff_factor: 遅延増加係数（指数バックオフ）
        readonly_retry: リードオンリーモードでのリトライ有効化
    
    戦略:
    - 1回目失敗: 0.1秒待機
    - 2回目失敗: 0.2秒待機（0.1 * 2^1）
    - 3回目失敗: 0.4秒待機（0.1 * 2^2）
    - 3回失敗後: 例外を上位に伝播
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            delay = initial_delay
            last_exception = None
            
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                
                except (OSError, IOError) as e:
                    # HDF5ロックエラー検出
                    if "unable to lock file" in str(e) or "Resource temporarily unavailable" in str(e):
                        last_exception = e
                        
                        if attempt < max_attempts:
                            logger.warning(
                                f"HDF5ロックエラー [{attempt}/{max_attempts}]: {e}, "
                                f"待機: {delay:.2f}秒"
                            )
                            time.sleep(delay)
                            delay *= backoff_factor
                        else:
                            logger.error(
                                f"HDF5ロックエラー最大試行回数到達: {max_attempts}回, "
                                f"諦めます"
                            )
                            raise HDF5LockError(
                                f"HDF5アクセス失敗（{max_attempts}回試行）: {e}"
                            ) from e
                    else:
                        # ロック以外のエラーは即座に伝播
                        raise
                
                except Exception as e:
                    # その他のエラーはリトライせず即座に伝播
                    raise
            
            # 到達しないが、型チェッカー対策
            if last_exception:
                raise last_exception
        
        return wrapper
    return decorator


# 使用例: 書き込み操作
@hdf5_retry(max_attempts=3, initial_delay=0.1)
def write_inference_tick(h5_path: str, tick_data: np.ndarray):
    """推論用Tick書き込み（リトライ付き）"""
    with h5py.File(h5_path, "a") as f:
        write_idx = f["/tick/data"].attrs["write_index"]
        max_size = f["/tick/data"].shape[0]
        f["/tick/data"][write_idx % max_size] = tick_data
        f["/tick/data"].attrs["write_index"] = write_idx + 1


# 使用例: リードオンリーリトライ
@hdf5_retry(max_attempts=5, initial_delay=0.05, readonly_retry=True)
def read_recent_bars(h5_path: str, n_bars: int = 480):
    """直近バー読み込み（リトライ付き）"""
    with h5py.File(h5_path, "r") as f:  # リードオンリーモード
        return f["/M1/data"][-n_bars:]


# エラーハンドリング例
try:
    write_inference_tick("data/inference/USDJPY.h5", new_tick)
except HDF5LockError as e:
    logger.critical(f"HDF5書き込み失敗: {e}")
    # 代替処理（例: メモリバッファに一時保存）
    buffer.append(new_tick)
```

**HDF5ロックエラー再試行仕様**:
- **max_attempts**: 3回（書き込み）/ 5回（読み込み）
- **初回待機**: 0.1秒（書き込み）/ 0.05秒（読み込み）
- **バックオフ係数**: 2.0（指数的に増加）
- **合計待機時間**: 最大 0.7秒（3回試行: 0.1 + 0.2 + 0.4）
- **リードオンリーモード**: より多くのリトライ許可（5回）
- **成功指標**: ロックエラーによる全体停止 = 0回

**一過性ロック vs 恒久的エラー**:
- **一過性**: 他プロセスの短期書き込み → リトライで解決
- **恒久的**: ファイル破損、権限エラー → 即座に例外伝播

---

## ⚡ パフォーマンス最適化

### 1. 書き込み最適化

```python
# Training: バッチ書き込み（圧縮有効）
with h5py.File(path, "a") as f:
    f["/tick/data"].resize((current_size + batch_size, 6))
    f["/tick/data"][current_size:] = batch_data  # 1000行単位
    # gzip圧縮で書き込み遅いが、学習時読み込みは高速

# Inference: 単一行書き込み（圧縮無効）
with h5py.File(path, "a") as f:
    idx = write_index % max_size
    f["/tick/data"][idx] = single_tick  # 圧縮なしで高速
```

### 2. 読み込み最適化

```python
# Training: 大量データをチャンク単位で読み込み
with h5py.File(path, "r") as f:
    for i in range(0, total_size, chunk_size):
        chunk = f["/tick/data"][i:i+chunk_size]
        process_chunk(chunk)

# Inference: 直近データのみスライス読み込み
with h5py.File(path, "r") as f:
    recent = f["/M1/data"][-480:]  # 直近8時間分のみ
    predict(recent)  # 不要な古いデータは読まない
```

---

## 🔍 モニタリング

### 定期チェック項目

```python
def monitor_storage_health():
    """ストレージ健全性チェック"""
    
    # Training Storage
    training_size = get_directory_size("data/training")
    if training_size > 10 * 1024**3:  # 10 GB超
        logger.warning(f"Training storage large: {training_size / 1024**3:.1f} GB")
    
    # Inference Storage
    for symbol in ["USDJPY", "EURUSD"]:
        h5_path = f"data/inference/fx_live_{symbol}_latest.h5"
        with h5py.File(h5_path, "r") as f:
            oldest_time = f["/tick/data"].attrs.get("oldest_time", 0)
            age_hours = (time.time() - oldest_time) / 3600
            
            if age_hours > 30:  # 30時間超の古いデータ
                logger.error(f"Inference storage stale: {symbol} oldest={age_hours:.1f}h")
    
    # ディスク容量
    disk_usage = shutil.disk_usage("data")
    if disk_usage.percent > 90:
        logger.critical(f"Disk usage high: {disk_usage.percent}%")
```

---

## 🔮 将来拡張

### 実装フェーズ2: インテリジェント圧縮

```yaml
adaptive_compression:
  # 古いデータほど高圧縮
  recent_data:
    age: < 1 month
    compression: gzip level 4
  
  old_data:
    age: 1-3 months
    compression: gzip level 9  # 高圧縮
  
  archive:
    age: > 3 months
    compression: lzma          # 最高圧縮率
```

### 実装フェーズ3: 分散ストレージ

```yaml
distributed_storage:
  # 高速SSD + 大容量HDD
  hot_storage:
    location: /ssd/inference
    retention: 24 hours
    type: NVMe SSD
  
  warm_storage:
    location: /hdd/training
    retention: 3 months
    type: HDD
  
  cold_storage:
    location: /archive/backup
    retention: 2 years
    type: S3 / NAS
```

---

## 📚 関連仕様

- [DATA_COLLECTOR_SPEC.md](../DATA_COLLECTOR_SPEC.md) - データ収集全体仕様
- [EXECUTION_LATENCY_SPEC.md](../validator/EXECUTION_LATENCY_SPEC.md) - 推論レイテンシ要件

---

## 📝 変更履歴

- **2025-10-21**: 初版作成
  - Training/Inference Storage分離設計
  - Ring Buffer実装詳細
  - 3ヶ月/24時間の保持期間定義
  - サイズ見積もり・パフォーマンス最適化
