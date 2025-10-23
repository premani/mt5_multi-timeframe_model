# ストレージポリシー仕様

**バージョン**: 1.0.0  
**最終更新**: 2025-10-22  
**Author**: System Architect  
**Reviewer**: -  
**Approver**: Project Lead

---

## 目的

データ保持期間、バッファサイズ、アーカイブ戦略を明確化し、ストレージ効率と再現性を両立する。

---

## データ保持期間

### Training（学習用データ）

| タイムフレーム | 保持期間 | Ring Buffer容量 | 理由 |
|---------------|----------|----------------|------|
| M1 | 30日 | 43,200本 (30日 × 1440本/日) | 短期パターン学習 |
| M5 | 90日 | 25,920本 (90日 × 288本/日) | 中期トレンド把握 |
| M15 | 180日 | 17,280本 (180日 × 96本/日) | 長期コンテキスト |
| H1 | 180日 | 4,320本 (180日 × 24本/日) | スイング分析 |
| H4 | 365日 | 2,190本 (365日 × 6本/日) | 超長期パターン |

### Inference（推論用データ）

| タイムフレーム | 保持期間 | Ring Buffer容量 | 理由 |
|---------------|----------|----------------|------|
| M1 | 8時間 | 480本 | 直近パターンのみ |
| M5 | 24時間 | 288本 | 1日分の履歴 |
| M15 | 48時間 | 192本 | 2日分の文脈 |
| H1 | 48時間 | 48本 | 2日分のトレンド |
| H4 | 7日 | 42本 | 1週間の流れ |

**修正内容**:
- H1 inference: `retention=48h` と `buffer=48本` に統一（以前は24h/24本の不整合あり）

---

## Ring Buffer仕様

### 基本設計

```python
from collections import deque
from datetime import datetime, timedelta

class RingBuffer:
    """
    固定サイズの循環バッファ
    古いデータは自動的に上書きされる
    """
    
    def __init__(self, capacity: int, timeframe: str):
        self.capacity = capacity
        self.timeframe = timeframe
        self.buffer = deque(maxlen=capacity)
        self.oldest_time = None  # 項目52対応: 初期化時に明示的にNoneを設定
        self.newest_time = None
        self.wrap_count = 0  # 上書き回数
    
    def append(self, bar: dict):
        """
        バーを追加
        
        Args:
            bar: {
                'time': datetime,
                'open': float,
                'high': float,
                'low': float,
                'close': float,
                'volume': int
            }
        """
        bar_time = bar['time']
        
        # 初回挿入時にoldest_timeを設定
        if self.oldest_time is None:
            self.oldest_time = bar_time
        
        # バッファ満杯時のwrap検出
        if len(self.buffer) == self.capacity:
            self.wrap_count += 1
            # wrap後は新しいoldest_timeを設定
            if len(self.buffer) > 0:
                self.oldest_time = self.buffer[1]['time']  # 次に残る最古データ
        
        self.buffer.append(bar)
        self.newest_time = bar_time
    
    def get_age_seconds(self) -> float:
        """
        バッファの時間幅を秒で返す
        
        Returns:
            float: oldest_time から newest_time までの秒数
        """
        if self.oldest_time is None or self.newest_time is None:
            return 0.0
        return (self.newest_time - self.oldest_time).total_seconds()
```

### Wrap境界での再検証

```python
def on_wrap(self):
    """
    Ring Bufferが一周した際の再検証処理
    """
    # ギャップ統計の再計算
    self.recalculate_gap_stats()
    
    # 差分特徴量（ATR, EMA等）の再初期化
    self.reinitialize_incremental_features()
    
    logger.info(f"Ring buffer wrapped: {self.timeframe}, wrap_count={self.wrap_count}")

def recalculate_gap_stats(self):
    """
    wrap後のギャップ再検証
    """
    gaps = []
    for i in range(1, len(self.buffer)):
        prev_time = self.buffer[i-1]['time']
        curr_time = self.buffer[i]['time']
        expected_delta = self._get_expected_delta()
        actual_delta = (curr_time - prev_time).total_seconds()
        
        if actual_delta > expected_delta * 1.5:
            gaps.append({
                'start': prev_time,
                'end': curr_time,
                'duration_seconds': actual_delta
            })
    
    self.gap_stats = {
        'gap_count': len(gaps),
        'total_gap_seconds': sum(g['duration_seconds'] for g in gaps),
        'max_gap_seconds': max((g['duration_seconds'] for g in gaps), default=0)
    }
```

---

## アーカイブ戦略

### アーカイブタイミング

| Phase | Archive開始 | Grace Period | 最終削除 |
|-------|------------|--------------|----------|
| raw | 保持期限到達時 | +30日 | Grace期限後 |
| aligned | 保持期限到達時 | +14日 | Grace期限後 |
| features | 保持期限到達時 | +14日 | Grace期限後 |
| sequences | 保持期限到達時 | +30日 | Grace期限後 |
| trained | 保持期限到達時 | +90日 | Grace期限後 |

**Grace Period**:
- 目的: 保持期限到達直後のアクセス不可を防ぎ、再現性検証の猶予を確保
- 期間中: 読み取り可能だが新規学習には使用しない
- 警告: Grace期間中のアクセスはWARNログを出力

### アーカイブフロー

```
[Active Storage]
    ↓ (retention期限到達)
    ↓
[Grace Period Storage] ← 読み取り可、WARN出力
    ↓ (grace期限到達)
    ↓
[Archive Storage] (圧縮、低速ストレージ)
    ↓ (archive期限到達)
    ↓
[Deleted]
```

### 実装例

```python
from datetime import datetime, timedelta
from pathlib import Path
import shutil

class StorageManager:
    def __init__(self, base_dir: Path, config: dict):
        self.base_dir = base_dir
        self.active_dir = base_dir / "active"
        self.grace_dir = base_dir / "grace"
        self.archive_dir = base_dir / "archive"
        self.config = config
    
    def check_and_rotate(self, symbol: str, phase: str):
        """
        ファイルのローテーション処理
        """
        retention_days = self.config[phase]['retention_days']
        grace_days = self.config[phase]['grace_days']
        
        now = datetime.utcnow()
        
        # Active → Grace
        for file in self.active_dir.glob(f"{symbol}_*_{phase}_*.h5"):
            info = validate_filename(file.name)
            if not info['valid']:
                continue
            
            file_age_days = (now - info['datetime']).days
            
            if file_age_days > retention_days:
                logger.warning(f"Moving to grace period: {file.name}")
                dest = self.grace_dir / file.name
                shutil.move(str(file), str(dest))
        
        # Grace → Archive
        for file in self.grace_dir.glob(f"{symbol}_*_{phase}_*.h5"):
            info = validate_filename(file.name)
            if not info['valid']:
                continue
            
            file_age_days = (now - info['datetime']).days
            
            if file_age_days > retention_days + grace_days:
                logger.info(f"Archiving: {file.name}")
                dest = self.archive_dir / file.name
                
                # 圧縮して保存
                compress_and_move(file, dest)
    
    def load_file(self, file_path: Path) -> dict:
        """
        ファイル読込（Grace期間中は警告）
        """
        if self.grace_dir in file_path.parents:
            logger.warning(
                f"Loading file from grace period: {file_path.name}\n"
                f"  This file is beyond retention period.\n"
                f"  It will be archived soon. Use for verification only."
            )
        
        return load_hdf5(file_path)
```

---

## ストレージ健全性監視

### 監視項目

| 項目 | 閾値 | アクション |
|------|------|-----------|
| ディスク使用率 | >85% | WARN、古い世代の早期アーカイブ |
| ディスク使用率 | >95% | CRITICAL、データ収集一時停止 |
| Iノード使用率 | >80% | WARN、小ファイル統合 |
| 書込速度 | <10MB/s | WARN、I/O競合調査 |

### 監視実装例（項目54修正対応）

```python
import shutil
from pathlib import Path

def check_disk_health(directory: Path) -> dict:
    """
    ディスク健全性チェック
    
    Returns:
        dict: {
            'total_bytes': int,
            'used_bytes': int,
            'free_bytes': int,
            'used_percent': float,  # 項目54修正: 自前で計算
            'status': str  # 'OK', 'WARNING', 'CRITICAL'
        }
    """
    usage = shutil.disk_usage(str(directory))
    
    # 使用率を計算（項目54修正: percentプロパティは存在しないため自前計算）
    used_percent = (usage.used / usage.total) * 100
    
    # ステータス判定
    if used_percent >= 95:
        status = 'CRITICAL'
    elif used_percent >= 85:
        status = 'WARNING'
    else:
        status = 'OK'
    
    return {
        'total_bytes': usage.total,
        'used_bytes': usage.used,
        'free_bytes': usage.free,
        'used_percent': used_percent,
        'status': status
    }

def monitor_storage():
    """
    定期的なストレージ監視
    """
    health = check_disk_health(Path('/data'))
    
    logger.info(
        f"Disk usage: {health['used_percent']:.1f}% "
        f"({health['used_bytes'] / (1024**3):.1f}GB / "
        f"{health['total_bytes'] / (1024**3):.1f}GB)"
    )
    
    if health['status'] == 'CRITICAL':
        logger.critical("Disk usage critical! Stopping data collection.")
        # データ収集停止処理
        stop_data_collection()
    elif health['status'] == 'WARNING':
        logger.warning("Disk usage high. Triggering early archive.")
        # 早期アーカイブ処理
        trigger_early_archive()
```

---

## HDF5並行アクセス制御

### ロック排他戦略

```python
import fcntl
from pathlib import Path
from contextlib import contextmanager

@contextmanager
def lock_file(file_path: Path, timeout: float = 30.0):
    """
    ファイルロックコンテキストマネージャ
    
    Args:
        file_path: ロック対象ファイル
        timeout: タイムアウト秒数
    
    Raises:
        TimeoutError: ロック取得失敗
    """
    lock_path = file_path.with_suffix('.lock')
    lock_fd = None
    
    try:
        lock_fd = open(lock_path, 'w')
        
        # 非ブロッキングでロック試行
        start_time = time.time()
        while True:
            try:
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.time() - start_time > timeout:
                    raise TimeoutError(f"Failed to acquire lock: {file_path}")
                time.sleep(0.1)
        
        yield
        
    finally:
        if lock_fd:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
            lock_fd.close()
            if lock_path.exists():
                lock_path.unlink()

# 使用例
def save_hdf5_safe(file_path: Path, data: dict):
    """
    排他制御付きHDF5保存
    """
    with lock_file(file_path):
        save_hdf5(file_path, data)
```

---

## 設定例

```yaml
# config/storage_policy.yaml

storage:
  base_dir: /data
  
  training:
    M1:
      retention_days: 30
      buffer_capacity: 43200
      grace_days: 30
    M5:
      retention_days: 90
      buffer_capacity: 25920
      grace_days: 30
    M15:
      retention_days: 180
      buffer_capacity: 17280
      grace_days: 30
    H1:
      retention_days: 180
      buffer_capacity: 4320
      grace_days: 30
    H4:
      retention_days: 365
      buffer_capacity: 2190
      grace_days: 30
  
  inference:
    M1:
      retention_hours: 8
      buffer_capacity: 480
      grace_days: 7
    M5:
      retention_hours: 24
      buffer_capacity: 288
      grace_days: 7
    M15:
      retention_hours: 48
      buffer_capacity: 192
      grace_days: 7
    H1:
      retention_hours: 48  # 項目49修正: 24h→48hに統一
      buffer_capacity: 48   # 項目49修正: 24本→48本に統一
      grace_days: 7
    H4:
      retention_days: 7
      buffer_capacity: 42
      grace_days: 7
  
  phases:
    raw:
      grace_days: 30
    aligned:
      grace_days: 14
    features:
      grace_days: 14
    sequences:
      grace_days: 30
    trained:
      grace_days: 90
  
  monitoring:
    check_interval_seconds: 300  # 5分ごと
    disk_warning_percent: 85
    disk_critical_percent: 95
```

---

## 成功条件（KPI）

| 指標 | 目標値 | 測定方法 |
|------|--------|----------|
| 誤設定インシデント | 0件/30日 | ログ監視 |
| H1保持期間不整合 | 0件 | 自動検証 |
| Grace期間アクセス | WARN出力100% | ログ検証 |
| ストレージ使用率 | <85% 維持 | 監視ダッシュボード |
| ファイルロック競合 | <1件/日 | ロックログ分析 |

---

## 関連SPEC

- `NAMING_CONVENTION.md`: ファイル命名規約
- `DATA_COLLECTOR_SPEC.md`: データ保存戦略
- `PREPROCESSOR_SPEC.md`: データ読込戦略
- `README.md`: 全体データフロー

---

## 変更履歴

| 日付 | バージョン | 変更内容 |
|------|-----------|----------|
| 2025-10-22 | 1.0.0 | 初版作成（項目49, 50, 51, 52, 53, 54対応） |
