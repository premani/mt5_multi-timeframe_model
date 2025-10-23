# ONNX_CONVERTER_SPEC.md

**バージョン**: 1.0
**更新日**: 2025-10-22
**責任者**: core-team
**処理段階**: 第6段階: ONNX変換

---

## 📋 目的

`src/onnx_converter.py` が**第4段階で学習済みモデル**をONNX形式に変換し、**リアルタイム推論**用に最適化する。

**責任範囲**:
- PyTorchモデル (.pt) → ONNX (.onnx) への変換
- 量子化（FP16/INT8）による推論高速化
- レイテンシ検証（p95 < 10ms目標）
- 精度劣化検証（< 1%）

**処理段階の分離**:
- **第4段階（学習）**: `src/trainer.py` → `models/*_training.pt`
- **第5段階（検証）**: `src/validator.py` → 学習済みモデルの評価
- **第6段階（ONNX変換）**: `src/onnx_converter.py` → `models/*_model.onnx`

---

## 🔄 処理フロー

```
入力: models/*_training.pt（第4段階で学習）
  - MultiTFLSTMModel（PyTorch）
  - モデルアーキテクチャ
  - 学習パラメータ
    ↓
[ステップ1: モデルロード]
  - 構造検証（入力/出力形状）
  - 重みロード確認
    ↓
[ステップ2: ONNX変換]
  - torch.onnx.export()
  - オペレータ互換性確認
  - ダイナミック軸設定
    ↓
[ステップ3: 量子化（オプション）]
  - FP32 → FP16（デフォルト）
  - FP16 → INT8（オプション）
    ↓
[ステップ4: レイテンシ検証]
  - 1000サンプルで推論速度測定
  - p95 < 10ms 確認
    ↓
[ステップ5: 精度劣化検証]
  - 同一入力でPyTorch vs ONNX比較
  - RMSE劣化 < 1% 確認
    ↓
出力: models/*_model.onnx
  - 最適化済みモデル
  - メタデータ（精度・速度）
```

---

## 🎯 ONNX変換の利点

### リアルタイム推論に必要な性能

| 要件 | PyTorch | ONNX Runtime |
|------|---------|--------------|
| **推論速度** | 遅い（Python GIL） | 高速（C++実装） |
| **レイテンシ** | p95 ≈ 30ms | p95 < 10ms（目標） |
| **メモリ使用量** | 大（動的グラフ） | 小（静的グラフ） |
| **デプロイ** | Pythonランタイム必須 | 軽量ランタイム |

### MT5 Expert Advisor統合

```mql5
// MT5側でONNXモデルを使用
#include <Trade\Trade.mqh>
#include <ONNX\ONNX.mqh>

// ONNXモデルロード
long model_handle = OnnxCreateFromBuffer(model_buffer, ONNX_DEFAULT);

// 推論実行
float input[5][360][52];  // M1/M5/M15/H1/H4 x 360本 x 52特徴量
float output[36];         // 36本先までの価格予測

OnnxRun(model_handle, input, output);

// pips変換 (USDJPY: 0.01円=1pip)
double predicted_change_pips = output[0] * 100;  // USDJPY用

// 注記: 通貨ペアごとに変更必要
// EURUSD: output[0] * 10000
```

---

## 📊 変換戦略

### 1. 標準変換（FP32）

```python
import torch
import torch.onnx

def convert_to_onnx_fp32(
    model: torch.nn.Module,
    model_path: str,
    output_path: str,
    input_shape: Tuple[int, ...]
):
    """
    PyTorchモデルをONNX FP32形式に変換
    
    Args:
        model: 学習済みモデル
        model_path: .ptファイルパス
        output_path: .onnxファイルパス
        input_shape: (batch, tf, seq, features)
                     例: (1, 5, 360, 52)
    """
    # モデルロード
    model.load_state_dict(torch.load(model_path))
    model.eval()
    
    # ダミー入力（形状確認用）
    dummy_input = torch.randn(*input_shape)
    
    # ONNX変換
    torch.onnx.export(
        model,
        dummy_input,
        output_path,
        export_params=True,
        opset_version=17,  # ONNX Runtime 1.16+
        do_constant_folding=True,
        input_names=['input'],
        output_names=['output'],
        dynamic_axes={
            'input': {0: 'batch_size'},   # バッチサイズ可変
            'output': {0: 'batch_size'}
        }
    )
    
    logger.info(f"✅ ONNX変換完了: {output_path}")
```

### 2. FP16量子化（推奨）

```python
import onnx
from onnxruntime.quantization import quantize_dynamic, QuantType

def convert_to_onnx_fp16(
    onnx_fp32_path: str,
    output_path: str
):
    """
    FP32モデルをFP16に量子化
    
    メリット:
    - モデルサイズ 50%削減
    - 推論速度 1.5-2倍向上
    - 精度劣化 < 0.5%
    """
    model = onnx.load(onnx_fp32_path)
    
    # FP16変換
    from onnxconverter_common import float16
    model_fp16 = float16.convert_float_to_float16(model)
    
    onnx.save(model_fp16, output_path)
    
    logger.info(f"✅ FP16変換完了: {output_path}")
```

### 3. INT8量子化（高度）

```python
def convert_to_onnx_int8(
    onnx_fp32_path: str,
    output_path: str,
    calibration_data: np.ndarray
):
    """
    FP32モデルをINT8に量子化
    
    注意:
    - キャリブレーションデータ必須
    - 推論速度 2-4倍向上
    - 精度劣化 0.5-2%（要検証）
    
    Args:
        calibration_data: (1000, 5, 360, 52)
    """
    quantize_dynamic(
        onnx_fp32_path,
        output_path,
        weight_type=QuantType.QInt8,
        optimize_model=True
    )
    
    logger.info(f"✅ INT8変換完了: {output_path}")
```

---

## 🏎️ レイテンシ検証

### 推論速度測定

```python
import onnxruntime as ort
import time

def benchmark_latency(
    onnx_path: str,
    input_shape: Tuple[int, ...],
    num_samples: int = 1000
) -> Dict[str, float]:
    """
    ONNXモデルのレイテンシを測定
    
    目標: p95 < 10ms
    
    Returns:
        {
            'mean_ms': float,
            'p50_ms': float,
            'p95_ms': float,
            'p99_ms': float
        }
    """
    # ONNXランタイムセッション作成
    session = ort.InferenceSession(
        onnx_path,
        providers=['CUDAExecutionProvider', 'CPUExecutionProvider']
    )
    
    # ダミー入力生成
    dummy_input = np.random.randn(*input_shape).astype(np.float32)
    
    # ウォームアップ（JIT最適化）
    for _ in range(10):
        session.run(None, {'input': dummy_input})
    
    # レイテンシ測定
    latencies = []
    for _ in range(num_samples):
        start = time.perf_counter()
        session.run(None, {'input': dummy_input})
        end = time.perf_counter()
        latencies.append((end - start) * 1000)  # ms
    
    latencies = np.array(latencies)
    
    results = {
        'mean_ms': np.mean(latencies),
        'p50_ms': np.percentile(latencies, 50),
        'p95_ms': np.percentile(latencies, 95),
        'p99_ms': np.percentile(latencies, 99)
    }
    
    logger.info(f"📊 レイテンシ: p95={results['p95_ms']:.2f}ms")
    
    # 目標達成確認
    if results['p95_ms'] > 10.0:
        logger.warning(f"⚠️ p95レイテンシ目標未達: {results['p95_ms']:.2f}ms > 10ms")
    
    return results
```

### レイテンシ最適化

```python
def optimize_onnx_model(onnx_path: str, output_path: str):
    """
    ONNXモデルを最適化
    
    - 不要ノード削除
    - 定数畳み込み
    - 冗長計算除去
    """
    import onnxoptimizer
    
    model = onnx.load(onnx_path)
    
    # 最適化パス
    passes = [
        'eliminate_deadend',
        'eliminate_identity',
        'eliminate_nop_transpose',
        'fuse_consecutive_transposes',
        'fuse_matmul_add_bias_into_gemm',
        'fuse_bn_into_conv'
    ]
    
    optimized_model = onnxoptimizer.optimize(model, passes)
    onnx.save(optimized_model, output_path)
    
    logger.info(f"✅ ONNX最適化完了: {output_path}")
```

### GPU/ONNX ウォームアップ測定開始基準

**目的**: 初期数件が統計歪めSLA誤判定。初期遅延をp50/p95統計から除外する明確条件不在。

**実装**: warmup_calls N超過後計測開始ルール記述

```python
def benchmark_latency_with_warmup(
    onnx_path: str,
    input_shape: Tuple[int, ...],
    warmup_calls: int = 20,  # ウォームアップ回数
    measurement_calls: int = 1000,
    warmup_detection: str = 'fixed'  # 'fixed' | 'adaptive'
) -> Dict[str, Any]:
    """
    ウォームアップ除外付きレイテンシ測定

    Args:
        warmup_calls: 固定ウォームアップ回数（fixed mode）
        measurement_calls: 測定回数
        warmup_detection: 'fixed' = 固定回数除外
                         'adaptive' = 安定化検出後計測開始

    Returns:
        {
            'mean_ms': float,
            'p50_ms': float,
            'p95_ms': float,
            'p99_ms': float,
            'warmup_completed_at': int,  # ウォームアップ完了インデックス
            'warmup_latencies': List[float],  # 除外されたウォームアップ結果
            'measurement_latencies': List[float]  # 測定対象
        }
    """
    import onnxruntime as ort
    import time

    session = ort.InferenceSession(
        onnx_path,
        providers=['CUDAExecutionProvider', 'CPUExecutionProvider']
    )

    dummy_input = np.random.randn(*input_shape).astype(np.float32)

    all_latencies = []
    warmup_completed_at = None

    if warmup_detection == 'fixed':
        # 固定回数ウォームアップ
        logger.info(f"🔥 ウォームアップ開始（固定{warmup_calls}回）")

        for i in range(warmup_calls):
            start = time.perf_counter()
            session.run(None, {'input': dummy_input})
            end = time.perf_counter()
            latency_ms = (end - start) * 1000
            all_latencies.append(latency_ms)

        warmup_completed_at = warmup_calls
        logger.info(f"✅ ウォームアップ完了（{warmup_calls}回）")

        # 測定開始
        logger.info(f"📊 測定開始（{measurement_calls}回）")
        for i in range(measurement_calls):
            start = time.perf_counter()
            session.run(None, {'input': dummy_input})
            end = time.perf_counter()
            latency_ms = (end - start) * 1000
            all_latencies.append(latency_ms)

    elif warmup_detection == 'adaptive':
        # 適応的ウォームアップ（レイテンシ安定化検出）
        logger.info(f"🔥 ウォームアップ開始（適応的）")

        window_size = 10
        stability_threshold = 0.1  # CV < 0.1で安定と判定

        for i in range(warmup_calls + measurement_calls):
            start = time.perf_counter()
            session.run(None, {'input': dummy_input})
            end = time.perf_counter()
            latency_ms = (end - start) * 1000
            all_latencies.append(latency_ms)

            # 安定化判定（最低10回実行後）
            if warmup_completed_at is None and len(all_latencies) >= window_size:
                recent = all_latencies[-window_size:]
                mean_lat = np.mean(recent)
                std_lat = np.std(recent)
                cv = std_lat / mean_lat if mean_lat > 0 else 1.0

                if cv < stability_threshold:
                    warmup_completed_at = len(all_latencies)
                    logger.info(
                        f"✅ ウォームアップ完了（{warmup_completed_at}回、CV={cv:.3f}）"
                    )
                    # 測定継続（残り回数）
                    remaining = measurement_calls - (len(all_latencies) - warmup_completed_at)
                    logger.info(f"📊 測定継続（残り{remaining}回）")

        # 適応的で安定化しなかった場合のフォールバック
        if warmup_completed_at is None:
            warmup_completed_at = warmup_calls
            logger.warning(
                f"⚠️ 安定化未検出、固定{warmup_calls}回でウォームアップ終了"
            )

    # ウォームアップと測定の分離
    warmup_latencies = all_latencies[:warmup_completed_at]
    measurement_latencies = all_latencies[warmup_completed_at:]

    # 統計計算（測定データのみ）
    measurement_array = np.array(measurement_latencies)

    results = {
        'mean_ms': np.mean(measurement_array),
        'p50_ms': np.percentile(measurement_array, 50),
        'p95_ms': np.percentile(measurement_array, 95),
        'p99_ms': np.percentile(measurement_array, 99),
        'warmup_completed_at': warmup_completed_at,
        'warmup_latencies': warmup_latencies,
        'measurement_latencies': measurement_latencies,
        'num_warmup': len(warmup_latencies),
        'num_measurement': len(measurement_latencies)
    }

    logger.info(f"📊 レイテンシ統計（ウォームアップ除外後）:")
    logger.info(f"   - p50: {results['p50_ms']:.2f}ms")
    logger.info(f"   - p95: {results['p95_ms']:.2f}ms")
    logger.info(f"   - p99: {results['p99_ms']:.2f}ms")
    logger.info(f"   - ウォームアップ除外: {results['num_warmup']}回")

    # SLA判定
    if results['p95_ms'] > 10.0:
        logger.warning(f"⚠️ p95レイテンシ目標未達: {results['p95_ms']:.2f}ms > 10ms")

    return results


def visualize_warmup_effect(results: Dict[str, Any]):
    """
    ウォームアップ効果の可視化

    Args:
        results: benchmark_latency_with_warmup()の結果
    """
    import matplotlib.pyplot as plt

    warmup_idx = results['warmup_completed_at']
    all_lat = results['warmup_latencies'] + results['measurement_latencies']

    plt.figure(figsize=(12, 5))

    # サブプロット1: 全レイテンシ
    plt.subplot(1, 2, 1)
    plt.plot(all_lat, marker='o', markersize=2, alpha=0.6)
    plt.axvline(warmup_idx, color='red', linestyle='--', label=f'Warmup完了 (call={warmup_idx})')
    plt.axhline(results['p95_ms'], color='green', linestyle='--', label=f'p95={results["p95_ms"]:.2f}ms')
    plt.xlabel('Call #')
    plt.ylabel('Latency (ms)')
    plt.title('Latency Over Time (with Warmup)')
    plt.legend()
    plt.grid(True, alpha=0.3)

    # サブプロット2: ヒストグラム比較
    plt.subplot(1, 2, 2)
    plt.hist(results['warmup_latencies'], bins=30, alpha=0.5, label='Warmup', color='orange')
    plt.hist(results['measurement_latencies'], bins=30, alpha=0.5, label='Measurement', color='blue')
    plt.axvline(results['p95_ms'], color='green', linestyle='--', label=f'p95={results["p95_ms"]:.2f}ms')
    plt.xlabel('Latency (ms)')
    plt.ylabel('Count')
    plt.title('Latency Distribution')
    plt.legend()
    plt.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig('latency_warmup_analysis.png', dpi=150)
    logger.info("📊 ウォームアップ分析グラフ保存: latency_warmup_analysis.png")


# 使用例
if __name__ == '__main__':
    # 固定ウォームアップ
    results_fixed = benchmark_latency_with_warmup(
        'models/fx_model.onnx',
        input_shape=(1, 5, 360, 52),
        warmup_calls=20,
        measurement_calls=1000,
        warmup_detection='fixed'
    )

    # 適応的ウォームアップ
    results_adaptive = benchmark_latency_with_warmup(
        'models/fx_model.onnx',
        input_shape=(1, 5, 360, 52),
        warmup_calls=50,  # 最大ウォームアップ
        measurement_calls=1000,
        warmup_detection='adaptive'
    )

    # 可視化
    visualize_warmup_effect(results_fixed)
```

**ウォームアップ推奨設定**:

| 実行環境 | warmup_calls | warmup_detection | 理由 |
|---------|--------------|------------------|------|
| GPU (初回起動) | 30-50 | adaptive | カーネル初期化・メモリ転送が不安定 |
| GPU (2回目以降) | 10-20 | fixed | 既にウォームなので固定で十分 |
| CPU | 10-15 | fixed | CPUは安定が早い |
| Quantized (INT8) | 20-30 | adaptive | 量子化演算の初期化に時間 |

**成功指標**:
- ウォームアップ除外率: < 5%（過剰除外防止）
- 測定サンプル数: ≥ 1000回
- CV(measurement_latencies) < 0.15（安定性）

**検証**:
```python
def test_warmup_exclusion():
    """ウォームアップ除外の検証"""
    # ダミー結果
    results = benchmark_latency_with_warmup(
        'test_model.onnx',
        (1, 5, 360, 52),
        warmup_calls=20,
        measurement_calls=100
    )

    # 検証1: ウォームアップが除外されている
    assert results['num_warmup'] == 20
    assert results['num_measurement'] == 100

    # 検証2: 測定データのみで統計計算
    measurement_p95 = np.percentile(results['measurement_latencies'], 95)
    assert abs(measurement_p95 - results['p95_ms']) < 0.01

    # 検証3: ウォームアップ除外による改善確認
    warmup_mean = np.mean(results['warmup_latencies'])
    measurement_mean = results['mean_ms']

    # ウォームアップは通常遅い
    assert warmup_mean > measurement_mean, "ウォームアップが測定より遅いべき"
```

---

## 📊 精度劣化検証

### PyTorch vs ONNX比較

```python
def validate_accuracy(
    pytorch_model: torch.nn.Module,
    onnx_path: str,
    test_data: np.ndarray,
    test_targets: np.ndarray
) -> Dict[str, float]:
    """
    PyTorchモデルとONNXモデルの精度を比較
    
    許容範囲: RMSE劣化 < 1%
    
    Args:
        test_data: (N, 5, 360, 52)
        test_targets: (N, 36)
    
    Returns:
        {
            'pytorch_rmse': float,
            'onnx_rmse': float,
            'degradation_pct': float,
            'accept': bool
        }
    """
    # PyTorch推論
    pytorch_model.eval()
    with torch.no_grad():
        pytorch_pred = pytorch_model(
            torch.from_numpy(test_data).float()
        ).numpy()
    
    pytorch_rmse = np.sqrt(mean_squared_error(test_targets, pytorch_pred))
    
    # ONNX推論
    session = ort.InferenceSession(onnx_path)
    onnx_pred = session.run(None, {'input': test_data})[0]
    
    onnx_rmse = np.sqrt(mean_squared_error(test_targets, onnx_pred))
    
    # 劣化率
    degradation = (onnx_rmse - pytorch_rmse) / pytorch_rmse * 100
    
    results = {
        'pytorch_rmse': pytorch_rmse,
        'onnx_rmse': onnx_rmse,
        'degradation_pct': degradation,
        'accept': degradation < 1.0
    }
    
    logger.info(f"📊 精度比較:")
    logger.info(f"   PyTorch RMSE: {pytorch_rmse:.4f}")
    logger.info(f"   ONNX RMSE: {onnx_rmse:.4f}")
    logger.info(f"   劣化: {degradation:.2f}%")
    
    if not results['accept']:
        logger.warning(f"⚠️ 精度劣化が許容範囲を超過")
    
    return results
```

### ONNXスケール二重換算防止

**目的**: 2重pips conversionはバックテスト収益評価破綻しモデル昇格誤判定。

**実装**: ONNXグラフ末端scaleノード有無検証 + metadata.scaling_applied + runtime assert

```python
def verify_output_scaling(
    onnx_path: str,
    check_graph: bool = True,
    check_metadata: bool = True
) -> Dict[str, Any]:
    """
    ONNX出力のスケール適用状態を検証

    Args:
        onnx_path: ONNXモデルパス
        check_graph: グラフ構造からスケールノード検出
        check_metadata: メタデータからscaling_applied確認

    Returns:
        {
            'has_scale_node': bool,
            'metadata_scaling_applied': bool | None,
            'safe': bool,  # True=安全（二重適用なし）
            'warnings': List[str]
        }
    """
    import onnx
    from onnx import helper

    model = onnx.load(onnx_path)
    result = {
        'has_scale_node': False,
        'metadata_scaling_applied': None,
        'safe': True,
        'warnings': []
    }

    # 1. グラフ構造チェック
    if check_graph:
        # 出力ノード直前のOp検索
        output_nodes = []
        output_names = [o.name for o in model.graph.output]

        for node in model.graph.node:
            if any(out in output_names for out in node.output):
                output_nodes.append(node)

        # スケール関連Op検出（Mul, Div, Sub, Add等）
        scale_ops = ['Mul', 'Div', 'Add', 'Sub']
        for node in output_nodes:
            if node.op_type in scale_ops:
                result['has_scale_node'] = True
                result['warnings'].append(
                    f"出力直前にスケールOp検出: {node.op_type} (name={node.name})"
                )
                break

    # 2. メタデータチェック
    if check_metadata:
        metadata_dict = {prop.key: prop.value for prop in model.metadata_props}

        if 'scaling_applied' in metadata_dict:
            result['metadata_scaling_applied'] = (
                metadata_dict['scaling_applied'].lower() == 'true'
            )

            if result['metadata_scaling_applied'] and result['has_scale_node']:
                result['safe'] = False
                result['warnings'].append(
                    "⚠️ 二重スケール適用懸念: "
                    "metadata.scaling_applied=true かつ グラフにスケールノード存在"
                )
        else:
            result['warnings'].append(
                "metadata.scaling_applied未設定（推奨: 明示的に設定）"
            )

    # 3. 安全性判定
    if result['has_scale_node'] and result['metadata_scaling_applied'] is None:
        result['warnings'].append(
            "スケールノード存在するがメタデータ未設定: "
            "runtime適用時に二重スケールリスク"
        )

    return result


def assert_no_double_scaling_at_runtime(
    session: ort.InferenceSession,
    apply_scaling_in_runtime: bool,
    onnx_model_path: str
):
    """
    実行時のスケール二重適用を防止

    Args:
        session: ONNX Runtime セッション
        apply_scaling_in_runtime: Runtimeでスケール適用するか
        onnx_model_path: ONNXモデルパス（検証用）

    Raises:
        AssertionError: 二重スケール適用懸念がある場合
    """
    verification = verify_output_scaling(onnx_model_path)

    # Runtime適用 かつ グラフにスケールノード存在
    if apply_scaling_in_runtime and verification['has_scale_node']:
        raise AssertionError(
            "二重スケール適用エラー: "
            f"Runtime適用={apply_scaling_in_runtime}, "
            f"グラフ内スケール={verification['has_scale_node']}"
        )

    # メタデータとの整合性確認
    if verification['metadata_scaling_applied']:
        if apply_scaling_in_runtime:
            raise AssertionError(
                "二重スケール適用エラー: "
                "metadata.scaling_applied=true だが Runtime適用も指定"
            )

    logger.info(f"✅ スケール検証完了: 二重適用なし")
    logger.info(f"   - グラフ内スケール: {verification['has_scale_node']}")
    logger.info(f"   - Runtime適用: {apply_scaling_in_runtime}")


# 使用例: ONNX変換時
def export_onnx_with_scaling_metadata(
    model: torch.nn.Module,
    dummy_input: torch.Tensor,
    output_path: str,
    scaling_applied: bool  # モデル内部で既にスケール済みか
):
    """
    スケール状態をメタデータに記録してONNX変換

    Args:
        scaling_applied: True = モデル出力が既にpipsスケール済み
                        False = raw値（Runtime側でスケール必要）
    """
    torch.onnx.export(
        model,
        dummy_input,
        output_path,
        input_names=['input'],
        output_names=['output'],
        opset_version=17,
        dynamic_axes={'input': {0: 'batch'}, 'output': {0: 'batch'}}
    )

    # メタデータ追加
    import onnx
    onnx_model = onnx.load(output_path)

    # scaling_applied メタデータ
    meta = onnx_model.metadata_props.add()
    meta.key = 'scaling_applied'
    meta.value = 'true' if scaling_applied else 'false'

    # 説明
    meta_desc = onnx_model.metadata_props.add()
    meta_desc.key = 'scaling_description'
    meta_desc.value = (
        'Output in pips (scaled)' if scaling_applied
        else 'Output in raw units (requires scaling)'
    )

    onnx.save(onnx_model, output_path)

    logger.info(f"✅ ONNX変換完了: scaling_applied={scaling_applied}")


# 推論時の適用例
def run_inference_with_scaling_check(
    onnx_path: str,
    input_data: np.ndarray,
    apply_pips_scaling: bool = True,
    pips_multiplier: float = 100.0  # USDJPY: 0.01円=1pip
) -> np.ndarray:
    """
    スケール検証付き推論

    Args:
        apply_pips_scaling: Runtimeでpipsスケール適用するか

    Returns:
        predictions (pipsスケール)
    """
    session = ort.InferenceSession(onnx_path)

    # 二重スケール防止チェック
    assert_no_double_scaling_at_runtime(
        session,
        apply_pips_scaling,
        onnx_path
    )

    # 推論
    outputs = session.run(None, {'input': input_data})[0]

    # 必要に応じてスケール適用
    if apply_pips_scaling:
        outputs = outputs * pips_multiplier

    return outputs
```

**成功指標**:
- スケール二重適用インシデント: 0件
- メタデータ設定率: 100%
- Runtime検証実行率: 100%

**検証**:
```python
def test_scaling_verification():
    """スケール検証の動作確認"""
    # ケース1: グラフ内スケールあり、メタデータtrue → 安全
    # ケース2: グラフ内スケールあり、メタデータfalse → 警告
    # ケース3: グラフ内スケールなし、Runtime適用 → 安全

    # ダミーモデル（スケール層あり）
    class ModelWithScaling(torch.nn.Module):
        def forward(self, x):
            return x * 100.0  # pips変換 (USDJPY)

    model = ModelWithScaling()
    dummy_input = torch.randn(1, 5, 360, 52)

    # ONNX変換（scaling_applied=true）
    export_onnx_with_scaling_metadata(
        model, dummy_input, 'test_scaled.onnx', scaling_applied=True
    )

    # 検証
    result = verify_output_scaling('test_scaled.onnx')
    assert result['has_scale_node'] == True
    assert result['metadata_scaling_applied'] == True
    assert result['safe'] == True  # 整合性あり

    # Runtime適用試行 → エラー
    try:
        session = ort.InferenceSession('test_scaled.onnx')
        assert_no_double_scaling_at_runtime(
            session, apply_scaling_in_runtime=True, onnx_model_path='test_scaled.onnx'
        )
        assert False, "エラーが発生すべき"
    except AssertionError as e:
        assert "二重スケール" in str(e)
```

---

## 📝 ログ出力

### 時刻表示ルール
- **全ログ**: 日本時間(JST)で表示
- **フォーマット**: `YYYY-MM-DD HH:MM:SS JST`
- **変換開始/終了時刻**: 日本時間で明記

```
🔄 第6段階: ONNX変換開始 [2025-10-24 04:15:20 JST]
📂 入力: models/fx_mtf_20251022_150000_training.pt
   - モデル: MultiTFLSTMModel
   - パラメータ: 1.2M
   - 入力形状: (1, 5, 360, 52)
   - 出力形状: (1, 36)

[ステップ1: モデルロード]
   ✅ 構造検証完了
   ✅ 重みロード完了

[ステップ2: ONNX変換（FP32）]
   - opset_version: 17
   - dynamic_axes: batch_size
   ✅ 変換完了: models/fx_mtf_20251022_150000_model_fp32.onnx

[ステップ3: FP16量子化]
   - モデルサイズ: 4.8MB → 2.4MB（50%削減）
   ✅ 量子化完了: models/fx_mtf_20251022_150000_model_fp16.onnx

[ステップ4: レイテンシ検証]
   - 測定サンプル: 1000
   - 平均: 6.2ms
   - p50: 5.8ms
   - p95: 8.1ms ✅（目標: <10ms）
   - p99: 9.7ms

[ステップ5: 精度劣化検証]
   - テストデータ: 5000サンプル
   - PyTorch RMSE: 0.3245
   - ONNX RMSE: 0.3258
   - 劣化: +0.4% ✅（目標: <1%）

💾 最終出力: models/fx_mtf_20251022_150000_model_fp16.onnx
📊 メタデータ保存: models/fx_mtf_20251022_150000_onnx_metadata.json
✅ 第6段階: ONNX変換完了 [2025-10-24 04:18:45 JST]
   変換時間: 3分25秒
```

---

## 📊 メタデータ出力

### onnx_metadata.json

```json
{
  "conversion": {
    "timestamp": "2025-10-22T15:00:00Z",
    "pytorch_model": "models/fx_mtf_20251022_150000_training.pt",
    "onnx_model": "models/fx_mtf_20251022_150000_model_fp16.onnx",
    "quantization": "FP16",
    "opset_version": 17
  },
  "model": {
    "input_shape": [1, 5, 360, 52],
    "output_shape": [1, 36],
    "parameters": 1200000,
    "size_mb": 2.4
  },
  "performance": {
    "latency_ms": {
      "mean": 6.2,
      "p50": 5.8,
      "p95": 8.1,
      "p99": 9.7
    },
    "target_p95_ms": 10.0,
    "achieved": true
  },
  "accuracy": {
    "pytorch_rmse": 0.3245,
    "onnx_rmse": 0.3258,
    "degradation_pct": 0.4,
    "target_degradation_pct": 1.0,
    "achieved": true
  },
  "validation": {
    "test_samples": 5000,
    "latency_samples": 1000,
    "passed": true
  },
  "scaling": {
    "pips_multiplier": 100.0,
    "scaling_applied": false,
    "notes": "USDJPY: 円→pips ×100。グラフ内スケール未適用、Runtime適用推奨"
  }
}
```

### スケーリング契約の明確化

**二重pipsスケーリング防止**: 学習出力とONNX出力のスケール状態を明示的に契約

#### スケール適用パターン

| パターン | グラフ内スケール | metadata.scaling_applied | Runtime適用 | 状態 |
|---------|----------------|-------------------------|------------|------|
| **A: グラフ適用済み** | ✓ | `true` | ✗ | ✅ 安全 |
| **B: Runtime適用** | ✗ | `false` | ✓ | ✅ 安全 |
| **C: 未適用** | ✗ | `false` | ✗ | ⚠️ 警告（スケール忘れ） |
| **D: 二重適用** | ✓ | `true` | ✓ | ❌ エラー（二重スケール） |

#### 推奨方針（Phase 0）
- **学習出力**: 正規化値（pipsスケール未適用）
- **ONNX変換**: グラフ内スケール層なし（`scaling_applied: false`）
- **MT5 Runtime**: `predicted_pips = output[0] * 100.0` で適用
- **理由**: デバッグ容易性、スケール変更の柔軟性

#### メタデータ必須項目
```json
{
  "scaling": {
    "pips_multiplier": 100.0,        // USDJPY用
    "scaling_applied": false,        // グラフ内スケール適用有無
    "notes": "Runtime適用推奨"       // 適用方法の注記
  }
}
```

---

## 🚨 エラー条件

| 条件 | 閾値 | 対応 |
|------|------|------|
| ONNX変換失敗 | オペレータ非互換 | エラー終了（モデル構造確認） |
| レイテンシ超過 | p95 > 15ms | 警告（INT8量子化検討） |
| 精度劣化過大 | > 2% | エラー終了（量子化方法見直し） |
| モデルサイズ超過 | > 10MB | 警告（モデル軽量化検討） |
| ONNX検証失敗 | 形状不一致 | エラー終了（変換設定確認） |

---

## ⚙️ 設定例

```yaml
# config/onnx_conversion.yaml
onnx_conversion:
  # 変換設定
  conversion:
    opset_version: 17  # ONNX Runtime 1.16+
    enable_optimization: true
    dynamic_batch: true
  
  # 量子化
  quantization:
    method: 'FP16'  # FP32 | FP16 | INT8
    calibration_samples: 1000  # INT8のみ
  
  # 検証設定
  validation:
    latency:
      target_p95_ms: 10.0
      num_samples: 1000
      fail_threshold_ms: 15.0  # これを超えたらエラー
    
    accuracy:
      target_degradation_pct: 1.0
      num_test_samples: 5000
      fail_threshold_pct: 2.0  # これを超えたらエラー
  
  # 出力設定
  output:
    save_fp32: false  # FP32版も保存
    save_metadata: true
    save_benchmark: true
```

---

## 🔗 関連仕様書

- **前段階**:
  - 第4段階: [TRAINER_SPEC.md](./TRAINER_SPEC.md) - モデル学習
  - 第5段階: [VALIDATOR_SPEC.md](./VALIDATOR_SPEC.md) - 精度検証
- **参照**:
  - [validator/EXECUTION_LATENCY_SPEC.md](./validator/EXECUTION_LATENCY_SPEC.md) - レイテンシ測定基準
  - [trainer/MULTI_TF_FUSION_SPEC.md](./trainer/MULTI_TF_FUSION_SPEC.md) - モデルアーキテクチャ
- **デプロイ先**: MT5 Expert Advisor（MQL5）

---

## 📌 注意事項

### 1. 量子化戦略の選択

| 方法 | モデルサイズ | 推論速度 | 精度劣化 | 推奨用途 |
|------|------------|---------|---------|---------|
| FP32 | 100% | 1.0x | 0% | 開発・検証 |
| FP16 | 50% | 1.5-2x | <0.5% | **本番推奨** |
| INT8 | 25% | 2-4x | 0.5-2% | 超高速推論 |

**推奨**: FP16（精度とレイテンシのバランス最適）

### 2. レイテンシ目標

```
p95レイテンシ < 10ms

理由:
- MT5 Expert Advisorの1ティック処理時間制約
- マルチTF（5タイムフレーム）の並列処理を考慮
- ネットワーク遅延（2-5ms）を含めても合計 <20ms
```

### 3. ONNX Runtime設定

```python
# GPU推論（推奨）
session = ort.InferenceSession(
    onnx_path,
    providers=[
        ('CUDAExecutionProvider', {
            'device_id': 0,
            'gpu_mem_limit': 2 * 1024 * 1024 * 1024,  # 2GB
        }),
        'CPUExecutionProvider'  # フォールバック
    ]
)

# CPU推論（開発用）
session = ort.InferenceSession(
    onnx_path,
    providers=['CPUExecutionProvider']
)
```

### 4. 未来リーク防止（再確認）

ONNX変換時も**未来リーク**が混入しないよう確認:

```python
# ✅ OK: 過去360本から36本先を予測
input: (batch, 5, 360, 52)  # t-359 ~ t
output: (batch, 36)          # t+1 ~ t+36

# ❌ NG: 未来データが混入
# 第2段階特徴量計算で shift(-n) を使用していないか確認
```

---

## 運用最適化

### INT8校正サンプル選定基準

**目的**: ランダム校正サンプルは極端値を見逃し量子化誤差が増大

**解決策**: ボラティリティregime・価格レンジを網羅する戦略的サンプリング

```python
class CalibrationSampleSelector:
    """INT8校正用サンプル選定"""
    
    def __init__(self, config: dict):
        self.n_samples = config.get("calibration_samples", 500)
        self.stratify_by_volatility = config.get("stratify_volatility", True)
        self.stratify_by_price_level = config.get("stratify_price_level", True)
        self.include_extremes = config.get("include_extremes", True)
    
    def select_samples(
        self,
        features: np.ndarray,  # (N, 5, 360, F)
        metadata: pd.DataFrame  # time, atr_h1, close_h1
    ) -> np.ndarray:
        """
        戦略的校正サンプル選定
        
        Returns:
            selected_indices: shape (n_samples,)
        """
        N = features.shape[0]
        indices = []
        
        # 1. ボラティリティregime層別（50%）
        if self.stratify_by_volatility:
            atr_values = metadata['atr_h1'].values
            atr_quantiles = [0.1, 0.3, 0.5, 0.7, 0.9]
            
            n_per_regime = int(self.n_samples * 0.5 / len(atr_quantiles))
            
            for i in range(len(atr_quantiles) - 1):
                q_low = np.quantile(atr_values, atr_quantiles[i])
                q_high = np.quantile(atr_values, atr_quantiles[i+1])
                
                regime_mask = (atr_values >= q_low) & (atr_values < q_high)
                regime_indices = np.where(regime_mask)[0]
                
                if len(regime_indices) > 0:
                    sampled = np.random.choice(
                        regime_indices,
                        size=min(n_per_regime, len(regime_indices)),
                        replace=False
                    )
                    indices.extend(sampled.tolist())
        
        # 2. 価格レベル層別（30%）
        if self.stratify_by_price_level:
            close_values = metadata['close_h1'].values
            price_quantiles = [0.0, 0.25, 0.5, 0.75, 1.0]
            
            n_per_level = int(self.n_samples * 0.3 / (len(price_quantiles) - 1))
            
            for i in range(len(price_quantiles) - 1):
                q_low = np.quantile(close_values, price_quantiles[i])
                q_high = np.quantile(close_values, price_quantiles[i+1])
                
                level_mask = (close_values >= q_low) & (close_values < q_high)
                level_indices = np.where(level_mask)[0]
                
                if len(level_indices) > 0:
                    sampled = np.random.choice(
                        level_indices,
                        size=min(n_per_level, len(level_indices)),
                        replace=False
                    )
                    indices.extend(sampled.tolist())
        
        # 3. 極端値（20%）
        if self.include_extremes:
            n_extremes = int(self.n_samples * 0.2)
            
            # 各特徴量の極端値を抽出
            feature_means = features.mean(axis=(1, 2, 3))  # (N,)
            extreme_indices = np.argsort(np.abs(feature_means - feature_means.mean()))[-n_extremes:]
            indices.extend(extreme_indices.tolist())
        
        # 重複削除・サンプル数調整
        indices = list(set(indices))
        if len(indices) > self.n_samples:
            indices = np.random.choice(indices, size=self.n_samples, replace=False).tolist()
        elif len(indices) < self.n_samples:
            # 不足分をランダム補充
            remaining = list(set(range(N)) - set(indices))
            additional = np.random.choice(remaining, size=self.n_samples - len(indices), replace=False)
            indices.extend(additional.tolist())
        
        logger.info(f"校正サンプル選定: {len(indices)}件")
        logger.info(f"  - ボラティリティ層別: {int(self.n_samples * 0.5)}件")
        logger.info(f"  - 価格レベル層別: {int(self.n_samples * 0.3)}件")
        logger.info(f"  - 極端値: {int(self.n_samples * 0.2)}件")
        
        return np.array(indices)


# 使用例
selector = CalibrationSampleSelector({
    "calibration_samples": 500,
    "stratify_volatility": True,
    "stratify_price_level": True,
    "include_extremes": True
})

calibration_indices = selector.select_samples(features, metadata)
calibration_data = features[calibration_indices]

# INT8量子化
quantizer.calibrate(calibration_data)
```

**選定基準**:

| 層 | 割合 | 目的 |
|----|------|------|
| ボラティリティregime | 50% | 静穏・通常・激動期を網羅 |
| 価格レベル | 30% | 高値・安値圏の分布再現 |
| 極端値 | 20% | 外れ値の量子化誤差抑制 |

**KPI（項目17）**:
- INT8精度劣化: <1.5%（ランダムサンプリング比較で改善）
- ボラregime網羅率: 5段階すべて≥10%
- 極端値カバー: p99.5以上のサンプル≥20件

---

### INT8 A/B比較手順

**目的**: FP16とINT8の精度差・速度差が不明で導入判断できず

**解決策**: 標準化A/B比較プロトコル

```python
class INT8ABTestProtocol:
    """INT8 vs FP16 A/B比較プロトコル"""
    
    def __init__(self, config: dict):
        self.test_samples = config.get("ab_test_samples", 10000)
        self.latency_iterations = config.get("latency_iterations", 1000)
        self.accuracy_threshold = config.get("accuracy_degradation_threshold", 1.5)  # %
        self.latency_improvement_target = config.get("latency_improvement_target", 30)  # %
    
    def run_ab_test(
        self,
        model_fp16_path: str,
        model_int8_path: str,
        test_data: np.ndarray,
        test_targets: np.ndarray
    ) -> Dict[str, Any]:
        """
        A/B比較実行
        
        Returns:
            {
                "accuracy": {
                    "fp16_mae": float,
                    "int8_mae": float,
                    "degradation_%": float,
                    "pass": bool
                },
                "latency": {
                    "fp16_p95_ms": float,
                    "int8_p95_ms": float,
                    "improvement_%": float,
                    "pass": bool
                },
                "recommendation": "adopt" | "reject"
            }
        """
        import onnxruntime as ort
        
        # セッション初期化
        session_fp16 = ort.InferenceSession(model_fp16_path)
        session_int8 = ort.InferenceSession(model_int8_path)
        
        # 1. 精度比較
        pred_fp16 = []
        pred_int8 = []
        
        for i in range(len(test_data)):
            sample = test_data[i:i+1]
            
            pred_fp16.append(
                session_fp16.run(None, {"input": sample})[0]
            )
            pred_int8.append(
                session_int8.run(None, {"input": sample})[0]
            )
        
        pred_fp16 = np.concatenate(pred_fp16, axis=0)
        pred_int8 = np.concatenate(pred_int8, axis=0)
        
        mae_fp16 = np.abs(pred_fp16 - test_targets).mean()
        mae_int8 = np.abs(pred_int8 - test_targets).mean()
        
        accuracy_degradation = (mae_int8 - mae_fp16) / mae_fp16 * 100
        accuracy_pass = accuracy_degradation < self.accuracy_threshold
        
        # 2. レイテンシ比較
        latency_fp16 = []
        latency_int8 = []
        
        sample = test_data[0:1]  # 単一サンプル
        
        for _ in range(self.latency_iterations):
            start = time.perf_counter()
            session_fp16.run(None, {"input": sample})
            latency_fp16.append((time.perf_counter() - start) * 1000)
        
        for _ in range(self.latency_iterations):
            start = time.perf_counter()
            session_int8.run(None, {"input": sample})
            latency_int8.append((time.perf_counter() - start) * 1000)
        
        fp16_p95 = np.percentile(latency_fp16, 95)
        int8_p95 = np.percentile(latency_int8, 95)
        
        latency_improvement = (fp16_p95 - int8_p95) / fp16_p95 * 100
        latency_pass = latency_improvement >= self.latency_improvement_target
        
        # 3. 判定
        recommendation = "adopt" if (accuracy_pass and latency_pass) else "reject"
        
        result = {
            "accuracy": {
                "fp16_mae": mae_fp16,
                "int8_mae": mae_int8,
                "degradation_%": accuracy_degradation,
                "pass": accuracy_pass
            },
            "latency": {
                "fp16_p95_ms": fp16_p95,
                "int8_p95_ms": int8_p95,
                "improvement_%": latency_improvement,
                "pass": latency_pass
            },
            "recommendation": recommendation
        }
        
        logger.info(f"INT8 A/B比較結果:")
        logger.info(f"  - 精度劣化: {accuracy_degradation:.2f}% (閾値={self.accuracy_threshold}%)")
        logger.info(f"  - レイテンシ改善: {latency_improvement:.2f}% (目標={self.latency_improvement_target}%)")
        logger.info(f"  - 推奨: {recommendation}")
        
        return result


# 使用例
ab_test = INT8ABTestProtocol({
    "ab_test_samples": 10000,
    "latency_iterations": 1000,
    "accuracy_degradation_threshold": 1.5,  # 1.5%まで許容
    "latency_improvement_target": 30  # 30%改善必須
})

result = ab_test.run_ab_test(
    model_fp16_path="models/model_fp16.onnx",
    model_int8_path="models/model_int8.onnx",
    test_data=test_features,
    test_targets=test_targets
)

if result["recommendation"] == "adopt":
    logger.info("INT8モデル採用を推奨")
else:
    logger.warning("INT8モデル不採用: 基準未達")
```

**比較項目**:

| 指標 | FP16 | INT8 | 判定基準 |
|------|------|------|---------|
| MAE精度 | baseline | +X% | X < 1.5% |
| p95レイテンシ | baseline | -Y% | Y ≥ 30% |
| モデルサイズ | 100% | ~25% | - |

**KPI（項目76）**:
- 精度劣化: <1.5%
- レイテンシ改善: ≥30%
- A/B判定の再現性: 5回実行で同一結論

---

## 🔮 実装計画

### Phase 4: ONNX変換実装（1週間）
- [ ] FP32変換実装
- [ ] FP16量子化実装
- [ ] レイテンシ測定実装
- [ ] 精度劣化検証実装

### Phase 4-2: 最適化（1週間）
- [ ] ONNXグラフ最適化
- [ ] INT8量子化実装（オプション）
- [ ] メタデータ出力実装
- [ ] 単体テスト作成

### Phase 4-3: MT5統合準備（1週間）
- [ ] MQL5サンプルコード作成
- [ ] デプロイドキュメント整備
- [ ] ベンチマーク結果公開

---

## 📚 参考資料

### ONNX Runtime
- 公式ドキュメント: https://onnxruntime.ai/docs/
- 量子化ガイド: https://onnxruntime.ai/docs/performance/quantization.html
- GPU実行: https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html

### PyTorch ONNX Export
- 公式ガイド: https://pytorch.org/docs/stable/onnx.html
- ベストプラクティス: https://pytorch.org/tutorials/advanced/super_resolution_with_onnxruntime.html

### MT5 ONNX統合
- MQL5 ONNX関数: https://www.mql5.com/en/docs/integration/onnx

---

**最終更新**: 2025-10-22  
**承認者**: (未承認)  
**ステータス**: ドラフト

### FP16安定性フォールバック検出

**目的**: FP16推論時、数値不安定によるNaN/Inf発生でsilent failure

**解決策**: 自動精度切替機構（FP16 ⇄ FP32）

```python
class FP16StabilityMonitor:
    """FP16安定性監視"""
    
    def __init__(self, config: dict):
        self.consecutive_clean_threshold = config.get("consecutive_clean", 10)
        self.fallback_cooldown = config.get("fallback_cooldown_sec", 60)
        
        self.current_precision = "fp16"
        self.consecutive_clean_count = 0
        self.last_fallback_time = 0
        self.nan_detected_count = 0
    
    def check_output(self, prediction: np.ndarray) -> Tuple[bool, str]:
        """
        推論出力の数値安定性チェック
        
        Returns:
            (is_valid, precision_to_use)
        """
        has_nan = np.isnan(prediction).any()
        has_inf = np.isinf(prediction).any()
        
        if has_nan or has_inf:
            self.nan_detected_count += 1
            self.consecutive_clean_count = 0
            
            # FP32にフォールバック
            if self.current_precision == "fp16":
                logger.warning(f"FP16でNaN/Inf検出 → FP32にフォールバック（検出{self.nan_detected_count}回目）")
                self.current_precision = "fp32"
                self.last_fallback_time = time.time()
            
            return (False, "fp32")
        
        else:
            # Clean出力
            self.consecutive_clean_count += 1
            
            # FP16復帰条件チェック
            if self.current_precision == "fp32":
                cooldown_elapsed = (time.time() - self.last_fallback_time) > self.fallback_cooldown
                
                if self.consecutive_clean_count >= self.consecutive_clean_threshold and cooldown_elapsed:
                    logger.info(f"連続{self.consecutive_clean_count}回clean → FP16復帰")
                    self.current_precision = "fp16"
                    self.consecutive_clean_count = 0
            
            return (True, self.current_precision)
    
    def get_stats(self) -> Dict[str, Any]:
        """統計取得"""
        return {
            "current_precision": self.current_precision,
            "nan_detected_count": self.nan_detected_count,
            "consecutive_clean_count": self.consecutive_clean_count
        }


# 推論ループ統合例
stability_monitor = FP16StabilityMonitor({
    "consecutive_clean": 10,
    "fallback_cooldown_sec": 60
})

# ONNX Runtime セッション（FP16 + FP32両方用意）
session_fp16 = ort.InferenceSession("model_fp16.onnx", providers=["CUDAExecutionProvider"])
session_fp32 = ort.InferenceSession("model_fp32.onnx", providers=["CUDAExecutionProvider"])

while True:
    features = get_latest_features()
    
    # 現在の精度で推論
    if stability_monitor.current_precision == "fp16":
        prediction = session_fp16.run(None, {"input": features})[0]
    else:
        prediction = session_fp32.run(None, {"input": features})[0]
    
    # 安定性チェック
    is_valid, precision_to_use = stability_monitor.check_output(prediction)
    
    if not is_valid:
        # FP32で再実行
        prediction = session_fp32.run(None, {"input": features})[0]
    
    execute_trade(prediction)
```

**フォールバック戦略**:
1. NaN/Inf検出 → 即座にFP32切替
2. 連続10回clean出力 + 60秒経過 → FP16復帰
3. FP32中も監視継続

**KPI（項目28）**: NaN発生率=0（検出後即座にFP32フォールバック）

---
