# GPU Optimization Specification

## 目的

学習フェーズにおけるGPU最適化手法を定義し、処理時間を最小化する。

---

## 設計方針

### 最優先原則：メガバッチ方式（ChunkDataLoader）

**コンセプト**: GPUメモリに目一杯データを展開し、ディスクI/Oボトルネックを解消

**旧プロジェクト（mt5_lstm-model）検証結果**:
- 学習時間: **59.9%短縮**（17分48秒 → 7分8秒）
- Issue #263 Phase 3 で実証済み

**処理フロー**:
```
1. HDF5から大きなチャンク読み込み（例: 12GB）
2. GPUメモリに一括転送
3. GPUメモリ上でバッチ処理完結
4. 次チャンクへ（必要に応じて）
```

---

## ChunkDataLoader 実装

### 基本設計

```python
class ChunkDataLoader:
    """
    HDF5から大きなチャンク単位でGPUメモリに直接転送
    
    メモリ使用例:
    - GPUメモリ: 16GB（例: NVIDIA RTX 4070）
    - チャンクサイズ: 12GB（GPUメモリの75%）
    - 全データ: 51,779サンプル × 360 × 167 × 4bytes ≈ 12.4GB
    - チャンク数: 1チャンク（全データをGPUに一括転送可能）
    """
    
    def __init__(
        self,
        hdf5_path: str,
        batch_size: int = 128,
        chunk_size_gb: float = 12.0,
        device: str = 'cuda',
        shuffle: bool = False,
        drop_last: bool = False
    ):
        self.hdf5_path = hdf5_path
        self.batch_size = batch_size
        self.chunk_size_gb = chunk_size_gb
        self.device = torch.device(device)
        
        # データセット情報取得
        with h5py.File(hdf5_path, 'r') as f:
            self.num_samples = f['features'].shape[0]
            self.sequence_length = f['features'].shape[1]
            self.feature_count = f['features'].shape[2]
        
        # チャンク境界計算
        bytes_per_sample = (
            self.sequence_length * self.feature_count * 4 +  # features (float32)
            self.target_length * 4  # targets (float32)
        )
        samples_per_chunk = int((chunk_size_gb * 1024**3) / bytes_per_sample)
        samples_per_chunk = max(batch_size, min(samples_per_chunk, self.num_samples))
        
        # チャンク範囲計算
        self.chunk_ranges = []
        for start in range(0, self.num_samples, samples_per_chunk):
            end = min(start + samples_per_chunk, self.num_samples)
            self.chunk_ranges.append((start, end))
    
    def _load_chunk_to_gpu(self, start: int, end: int):
        """HDF5からチャンクを読み込み、GPUメモリに転送"""
        with h5py.File(self.hdf5_path, 'r') as f:
            # HDF5から読み込み
            features = f['features'][start:end]
            targets = f['targets'][start:end]
        
        # GPUに転送（ピン留めメモリ経由で高速化）
        chunk_features = torch.from_numpy(features).pin_memory().to(self.device, non_blocking=True)
        chunk_targets = torch.from_numpy(targets).pin_memory().to(self.device, non_blocking=True)
        
        return chunk_features, chunk_targets
    
    def __iter__(self):
        """イテレータ: チャンクごとにGPUメモリ展開 → バッチ処理"""
        for start, end in self.chunk_ranges:
            # チャンクをGPUメモリに展開
            chunk_features, chunk_targets = self._load_chunk_to_gpu(start, end)
            
            # GPUメモリ上でバッチ処理
            chunk_size = end - start
            for i in range(0, chunk_size, self.batch_size):
                batch_end = min(i + self.batch_size, chunk_size)
                
                # GPUメモリ上でスライス（高速）
                batch_features = chunk_features[i:batch_end]
                batch_targets = chunk_targets[i:batch_end]
                
                yield batch_features, batch_targets
            
            # チャンク処理完了後、メモリ解放
            del chunk_features, chunk_targets
            torch.cuda.empty_cache()
```

### 使用方法

```python
# ChunkDataLoader作成
train_loader = ChunkDataLoader(
    hdf5_path='data/aligned_train.h5',
    batch_size=128,
    chunk_size_gb=12.0,  # GPUメモリの75%
    device='cuda',
    shuffle=False,  # マルチTFでは時系列維持必須
    drop_last=False
)

# 学習ループ
for epoch in range(num_epochs):
    for batch_features, batch_targets in train_loader:
        # 既にGPU上にあるため、to(device)不要
        outputs = model(batch_features)
        loss = criterion(outputs, batch_targets)
        loss.backward()
        optimizer.step()
```

---

## GPU メモリ別推奨設定

### チャンクサイズ計算式

```python
# 安全マージン: GPUメモリの75%を使用
chunk_size_gb = gpu_memory_gb * 0.75

# サンプル1つあたりのメモリ使用量
bytes_per_sample = (
    sequence_length * feature_count * 4 +  # features (float32)
    target_length * 4  # targets (float32)
)

# チャンク内サンプル数
samples_per_chunk = int((chunk_size_gb * 1024**3) / bytes_per_sample)
```

### GPU メモリ別推奨値

| GPU メモリ | チャンクサイズ | バッチサイズ | 備考 |
|-----------|--------------|------------|------|
| **8GB** | 6.0 GB | 64 | エントリーレベル |
| **12GB** | 9.0 GB | 96 | ミドルレンジ |
| **16GB** | 12.0 GB | 128 | 推奨構成 ⭐ |
| **24GB** | 18.0 GB | 192 | ハイエンド |

**マルチTF の追加考慮**:
- M1: 480 bars × F features
- M5: 288 bars × F features
- M15: 192 bars × F features
- H1: 96 bars × F features
- H4: 48 bars × F features

合計シーケンス長: 480+288+192+96+48 = **1104 bars**

**メモリ使用量例**（F=128, float32）:
```
features: 1104 × 128 × 4 bytes = 565 KB/sample
targets: 36 × 1 × 4 bytes = 144 bytes/sample
total: ~565 KB/sample

16GB GPU の場合:
chunk_samples = (12 * 1024^3) / (565 * 1024) ≈ 21,000 samples
```

---

## DataLoader 最適化設定

### 重要パラメータ

```python
# 推奨設定（旧プロジェクト検証済み）
dataloader_config = {
    'batch_size': 128,
    'num_workers': 0,        # シングルプロセス（COW問題回避）
    'pin_memory': True,      # GPU転送高速化
    'prefetch_factor': None, # num_workers=0 時は不要
    'persistent_workers': False,  # num_workers=0 時は不要
    'drop_last': False       # 全データ使用
}
```

### num_workers=0 の理由

**Copy-on-Write (COW) 問題回避**:
- マルチプロセス時、子プロセスがデータをコピー → メモリ使用量増大
- HDF5ファイルハンドルの共有問題
- メガバッチ方式では、ディスクI/Oがボトルネックでないため不要

**例外**: 小規模データ（GPU に一括展開不可）の場合は `num_workers=2〜4` も検討

### pin_memory=True の効果

**CPU → GPU 転送高速化**:
- ページロック（ピン留め）メモリ使用
- DMA（Direct Memory Access）による高速転送
- 約 10〜30% 高速化

**実装例**:
```python
# NumPy → Tensor 変換時にピン留め
tensor = torch.from_numpy(data).pin_memory().to(device, non_blocking=True)
```

---

## Mixed Precision (FP16/AMP)

### 効果

- **GPU計算速度**: 2〜3倍高速化
- **メモリ使用量**: 約50%削減
- **精度**: ほぼ劣化なし（動的Loss Scaling使用時）

### PyTorch実装

```python
from torch.cuda.amp import autocast, GradScaler

# スケーラー初期化
scaler = GradScaler()

# 学習ループ
for batch_features, batch_targets in train_loader:
    optimizer.zero_grad()
    
    # Mixed Precision で forward
    with autocast():
        outputs = model(batch_features)
        loss = criterion(outputs, batch_targets)
    
    # スケールした勾配で backward
    scaler.scale(loss).backward()
    
    # 勾配クリッピング（オプション）
    scaler.unscale_(optimizer)
    torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
    
    # オプティマイザステップ
    scaler.step(optimizer)
    scaler.update()
```

### 数値安定性対策

**Loss Scaling**:
- 勾配アンダーフロー防止
- PyTorch の GradScaler が自動調整
- 初期スケール: 2^16、動的に増減

**注意点**:
- BatchNorm は FP32 で計算（PyTorch 自動処理）
- Loss 計算も FP32 推奨（精度維持）

---

## Gradient Accumulation

### 目的

実効バッチサイズを拡大（GPUメモリ不足時）

### 実装

```python
accumulation_steps = 4  # 実効batch_size = 128 × 4 = 512

optimizer.zero_grad()

for i, (batch_features, batch_targets) in enumerate(train_loader):
    with autocast():
        outputs = model(batch_features)
        loss = criterion(outputs, batch_targets)
    
    # 勾配を累積（スケール調整）
    loss = loss / accumulation_steps
    scaler.scale(loss).backward()
    
    # accumulation_steps ごとに更新
    if (i + 1) % accumulation_steps == 0:
        scaler.step(optimizer)
        scaler.update()
        optimizer.zero_grad()
```

**注意**: メガバッチ方式では通常不要（既に大きなバッチサイズ確保可能）

---

## メモリ最適化テクニック

### 1. Gradient Checkpointing

**メモリ削減**: 約50%（計算時間 +20%のトレードオフ）

```python
from torch.utils.checkpoint import checkpoint

class LSTMWithCheckpointing(nn.Module):
    def forward(self, x):
        # 中間層でチェックポイント
        x = checkpoint(self.lstm_layer, x)
        return self.output_layer(x)
```

**推奨**: GPUメモリ不足時のみ使用

### 2. モデル圧縮

**量子化**（推論時のみ推奨）:
```python
# INT8量子化（推論専用）
quantized_model = torch.quantization.quantize_dynamic(
    model, {torch.nn.LSTM, torch.nn.Linear}, dtype=torch.qint8
)
```

### 3. メモリ断片化対策

```python
# エポック間でメモリクリア
torch.cuda.empty_cache()

# メモリプール初期化（必要時）
torch.cuda.reset_peak_memory_stats()
```

---

## マルチGPU対応（将来拡張）

### 現状

単独GPU構成（Phase 1）

### 将来対応（Phase 2以降）

**DistributedDataParallel (DDP)**:
```python
import torch.distributed as dist
from torch.nn.parallel import DistributedDataParallel as DDP

# 初期化
dist.init_process_group(backend='nccl')
local_rank = int(os.environ['LOCAL_RANK'])
torch.cuda.set_device(local_rank)

# モデルをDDPでラップ
model = model.to(local_rank)
model = DDP(model, device_ids=[local_rank])

# DistributedSampler使用
train_sampler = torch.utils.data.distributed.DistributedSampler(dataset)
train_loader = DataLoader(dataset, sampler=train_sampler, ...)
```

**注意**: マルチTFの時系列整合性を維持する必要あり

---

## パフォーマンス監視

### GPU使用率確認

```python
import torch

def log_gpu_stats(logger):
    if torch.cuda.is_available():
        allocated = torch.cuda.memory_allocated(0) / 1024**3
        reserved = torch.cuda.memory_reserved(0) / 1024**3
        total = torch.cuda.get_device_properties(0).total_memory / 1024**3
        
        logger.info(f"🎮 GPU メモリ:")
        logger.info(f"   割り当て: {allocated:.2f}GB / {total:.2f}GB ({allocated/total*100:.1f}%)")
        logger.info(f"   予約: {reserved:.2f}GB")
```

### nvidia-smi 監視

```bash
# リアルタイム監視
watch -n 1 nvidia-smi

# ログ出力
nvidia-smi --query-gpu=timestamp,memory.used,memory.total,utilization.gpu --format=csv -l 1 > gpu_log.csv
```

---

## トラブルシューティング

### CUDA Out of Memory

**対処優先順位**:
1. **チャンクサイズ削減**: `chunk_size_gb` を 75% → 60% に
2. **バッチサイズ削減**: 128 → 96 → 64
3. **Gradient Accumulation**: 実効バッチサイズ維持
4. **Gradient Checkpointing**: メモリ50%削減（速度-20%）
5. **Mixed Precision**: 既に有効な場合は効果薄

### メモリリーク検出

```python
import gc
import torch

initial_memory = torch.cuda.memory_allocated()

for epoch in range(num_epochs):
    # 学習処理
    ...
    
    # エポック終了時チェック
    current_memory = torch.cuda.memory_allocated()
    memory_increase = (current_memory - initial_memory) / 1024**2
    
    if memory_increase > 100:  # 100MB以上増加
        logger.warning(f"⚠️ メモリリーク疑い: +{memory_increase:.1f}MB")
        gc.collect()
        torch.cuda.empty_cache()
```

### 低いGPU使用率

**原因**:
- CPU前処理がボトルネック → メガバッチ方式で解決
- 小さすぎるバッチサイズ → 増加
- ディスクI/O待ち → ChunkDataLoader で解決

---

## 設定例（config/training.yaml）

```yaml
gpu_optimization:
  # メガバッチ方式（推奨）
  use_chunk_loader: true
  chunk_size_gb: 12.0        # GPU 16GB の場合
  
  # DataLoader設定
  batch_size: 128
  num_workers: 0             # シングルプロセス
  pin_memory: true           # GPU転送高速化
  
  # Mixed Precision
  use_amp: true              # FP16有効化
  
  # Gradient Accumulation（通常不要）
  gradient_accumulation_steps: 1
  
  # メモリ管理
  empty_cache_every_n_epochs: 1
  
  # モニタリング
  log_gpu_stats_every_n_batches: 100
```

---

## 期待効果（旧プロジェクト実績）

| 最適化手法 | 学習時間短縮 | 備考 |
|-----------|------------|------|
| 実装フェーズ1: batch_size=128 | **4.1%** | 17分48秒 → 17分3秒 |
| 実装フェーズ2: hidden状態引き継ぎ | - | 時系列連続性確保 |
| 実装フェーズ3: ChunkDataLoader | **59.9%** | 17分48秒 → **7分8秒** ⭐ |
| Mixed Precision (AMP) | **2〜3倍** | 追加的効果 |

**合計効果**: 従来比 **約80%短縮** 可能

---

## 参考資料

- **学習仕様**: `docs/TRAINER_SPEC.md`
- **マルチTF融合**: `docs/trainer/MULTI_TF_FUSION_SPEC.md`
- **旧プロジェクト実装**: `mt5_lstm-model/src/train/chunk_dataloader.py`
- **旧プロジェクト検証**: `mt5_lstm-model/docs/TRAIN_SPEC.md` (Issue #263)
