# MODEL_IO_CONTRACT_SPEC.md - モデル入出力契約仕様

**バージョン**: 1.0  
**更新日**: 2025-10-22

---

## 📋 目的

モデル入出力の形状・列順・型・セマンティクスを明確に定義し、学習・推論・ONNX変換間の整合性を保証する。

---

## 項目11対応: 入力契約齟齬防止

**目的**: 列順/shape不一致はONNX推論失敗やattention weight無意味化（列シャッフル）を誘発

**解決策**: 入力契約を明示的に定義し、バージョンハッシュで照合

---

## 🔢 入力契約定義

### タイムフレーム別入力形状

```python
INPUT_CONTRACT = {
    "version": "v1.0",
    "schema_hash": "a3f2b1c8e7d9f3a1",  # 契約変更時に更新
    
    "timeframes": {
        "M1": {
            "sequence_length": 480,
            "feature_count": None,  # 実行時決定
            "dtype": "float32",
            "shape": "(batch, 480, F)",
            "semantics": "直近480分（8時間）のM1特徴量"
        },
        "M5": {
            "sequence_length": 288,
            "feature_count": None,
            "dtype": "float32",
            "shape": "(batch, 288, F)",
            "semantics": "直近24時間のM5特徴量"
        },
        "M15": {
            "sequence_length": 192,
            "feature_count": None,
            "dtype": "float32",
            "shape": "(batch, 192, F)",
            "semantics": "直近48時間のM15特徴量"
        },
        "H1": {
            "sequence_length": 96,
            "feature_count": None,
            "dtype": "float32",
            "shape": "(batch, 96, F)",
            "semantics": "直近4日のH1特徴量"
        },
        "H4": {
            "sequence_length": 48,
            "feature_count": None,
            "dtype": "float32",
            "shape": "(batch, 48, F)",
            "semantics": "直近8日のH4特徴量"
        }
    },
    
    "masks": {
        "M1": {
            "shape": "(batch, 480)",
            "dtype": "float32",
            "semantics": "1.0=有効, 0.0=欠損/filled, 0.6=filled減衰"
        },
        "M5": {
            "shape": "(batch, 288)",
            "dtype": "float32",
            "semantics": "1.0=有効, 0.0=欠損/filled, 0.6=filled減衰"
        },
        "M15": {
            "shape": "(batch, 192)",
            "dtype": "float32",
            "semantics": "1.0=有効, 0.0=欠損/filled, 0.6=filled減衰"
        },
        "H1": {
            "shape": "(batch, 96)",
            "dtype": "float32",
            "semantics": "1.0=有効, 0.0=欠損/filled, 0.6=filled減衰"
        },
        "H4": {
            "shape": "(batch, 48)",
            "dtype": "float32",
            "semantics": "1.0=有効, 0.0=欠損/filled, 0.6=filled減衰"
        }
    },
    
    "feature_order": {
        "requirement": "全TFで統一された列順を保持",
        "validation": "feature_names_hash検証必須",
        "persistence": "HDF5 /metadata/feature_names に保存"
    }
}
```

---

## 📤 出力契約定義

### 学習モード出力

```python
OUTPUT_CONTRACT_TRAINING = {
    "version": "v1.0",
    
    "direction": {
        "shape": "(batch, 3)",
        "dtype": "float32",
        "semantics": "方向確率 [UP, DOWN, NEUTRAL]",
        "constraints": "sum=1.0, range=[0,1]"
    },
    
    "magnitude_scalp": {
        "shape": "(batch, 1)",
        "dtype": "float32",
        "semantics": "スカルプ価格幅（pips）",
        "range": "[0.0, 2.0]"
    },
    
    "magnitude_swing": {
        "shape": "(batch, 1)",
        "dtype": "float32",
        "semantics": "スイング価格幅（pips）",
        "range": "[0.0, 5.0]"
    },
    
    "trend_strength": {
        "shape": "(batch, 1)",
        "dtype": "float32",
        "semantics": "トレンド強度スコア",
        "range": "[0.0, 1.0]",
        "interpretation": "<0.3=scalp, >0.7=swing, 0.3-0.7=混合"
    }
}
```

### 推論モード出力

```python
OUTPUT_CONTRACT_INFERENCE = {
    "version": "v1.0",
    
    "predictions": {
        "direction_probs": {
            "shape": "(3,)",
            "dtype": "float32",
            "order": "[UP, DOWN, NEUTRAL]"
        },
        "magnitude_scalp": {
            "value": "float32",
            "unit": "pips"
        },
        "magnitude_swing": {
            "value": "float32",
            "unit": "pips"
        },
        "trend_strength": {
            "value": "float32",
            "range": "[0.0, 1.0]"
        },
        "confidence": {
            "value": "float32",
            "range": "[0.0, 1.0]",
            "computation": "max(direction_probs)"
        }
    },
    
    "metadata": {
        "inference_timestamp": "datetime",
        "model_version": "str",
        "input_quality_score": "float32"
    }
}
```

---

## 🔒 契約検証機構

### 入力契約検証

```python
import hashlib
import json
from typing import Dict, Any

class InputContractValidator:
    """入力契約検証器"""
    
    def __init__(self, contract: dict):
        self.contract = contract
        self.expected_hash = contract["schema_hash"]
    
    def compute_contract_hash(self, feature_names: list, shapes: dict) -> str:
        """
        契約ハッシュ計算
        
        Args:
            feature_names: 特徴量列名リスト（順序重要）
            shapes: TF別形状辞書
        
        Returns:
            contract_hash: MD5ハッシュ（先頭16文字）
        """
        contract_str = json.dumps({
            "feature_names": feature_names,
            "shapes": shapes,
            "version": self.contract["version"]
        }, sort_keys=True)
        
        return hashlib.md5(contract_str.encode()).hexdigest()[:16]
    
    def validate_input(
        self,
        inputs: Dict[str, Any],
        feature_names: list
    ) -> Dict[str, Any]:
        """
        入力データの契約適合性検証
        
        Args:
            inputs: {
                "M1": (batch, 480, F),
                "M5": (batch, 288, F),
                "masks": {"M1": (batch, 480), ...}
            }
            feature_names: 特徴量名リスト
        
        Returns:
            validation_result: {
                "valid": bool,
                "errors": list[str],
                "warnings": list[str]
            }
        """
        errors = []
        warnings = []
        
        # 1. TF形状検証
        for tf, expected in self.contract["timeframes"].items():
            if tf not in inputs:
                errors.append(f"Missing timeframe: {tf}")
                continue
            
            actual_shape = inputs[tf].shape
            expected_seq_len = expected["sequence_length"]
            
            if actual_shape[1] != expected_seq_len:
                errors.append(
                    f"{tf} sequence length mismatch: "
                    f"expected={expected_seq_len}, actual={actual_shape[1]}"
                )
            
            # dtype検証
            if str(inputs[tf].dtype) != expected["dtype"]:
                warnings.append(
                    f"{tf} dtype mismatch: "
                    f"expected={expected['dtype']}, actual={inputs[tf].dtype}"
                )
        
        # 2. マスク形状検証
        if "masks" in inputs:
            for tf, expected in self.contract["masks"].items():
                if tf not in inputs["masks"]:
                    errors.append(f"Missing mask: {tf}")
                    continue
                
                actual_mask_shape = inputs["masks"][tf].shape
                expected_shape_str = expected["shape"]
                # 例: "(batch, 480)" から 480 を抽出
                expected_seq = int(expected_shape_str.split(",")[1].strip().rstrip(")"))
                
                if actual_mask_shape[1] != expected_seq:
                    errors.append(
                        f"{tf} mask shape mismatch: "
                        f"expected seq={expected_seq}, actual={actual_mask_shape[1]}"
                    )
        
        # 3. 特徴量列順ハッシュ検証
        shapes_dict = {
            tf: list(inputs[tf].shape)
            for tf in self.contract["timeframes"].keys()
            if tf in inputs
        }
        
        actual_hash = self.compute_contract_hash(feature_names, shapes_dict)
        
        if actual_hash != self.expected_hash:
            warnings.append(
                f"Contract hash mismatch: "
                f"expected={self.expected_hash}, actual={actual_hash}. "
                f"Feature names or shapes may have changed."
            )
        
        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings
        }


# 使用例: 学習開始時の検証
validator = InputContractValidator(INPUT_CONTRACT)

# データローダーから取得した入力
batch_inputs = {
    "M1": torch.randn(32, 480, 120),
    "M5": torch.randn(32, 288, 120),
    "M15": torch.randn(32, 192, 120),
    "H1": torch.randn(32, 96, 120),
    "H4": torch.randn(32, 48, 120),
    "masks": {
        "M1": torch.ones(32, 480),
        "M5": torch.ones(32, 288),
        "M15": torch.ones(32, 192),
        "H1": torch.ones(32, 96),
        "H4": torch.ones(32, 48),
    }
}

# 特徴量名（HDF5から読み込み）
feature_names = load_feature_names_from_hdf5("preprocessed.h5")

# 検証実行
result = validator.validate_input(batch_inputs, feature_names)

if not result["valid"]:
    logger.error(f"入力契約違反: {result['errors']}")
    raise ValueError("Input contract validation failed")

if result["warnings"]:
    logger.warning(f"入力契約警告: {result['warnings']}")
```

---

## 📋 契約メタデータ保存

### HDF5メタデータ形式

```python
def save_contract_metadata(h5_file, contract: dict, feature_names: list):
    """
    HDF5ファイルに契約メタデータ保存
    
    Args:
        h5_file: h5py.File object
        contract: INPUT_CONTRACT辞書
        feature_names: 特徴量名リスト
    """
    meta_group = h5_file.require_group("metadata/io_contract")
    
    # 契約バージョン
    meta_group.attrs["version"] = contract["version"]
    meta_group.attrs["schema_hash"] = contract["schema_hash"]
    
    # TF別形状
    for tf, spec in contract["timeframes"].items():
        tf_group = meta_group.require_group(f"timeframes/{tf}")
        tf_group.attrs["sequence_length"] = spec["sequence_length"]
        tf_group.attrs["dtype"] = spec["dtype"]
        tf_group.attrs["semantics"] = spec["semantics"]
    
    # 特徴量名（列順保持）
    meta_group.create_dataset(
        "feature_names",
        data=[name.encode() for name in feature_names]
    )
    
    # 契約ハッシュ検証用
    validator = InputContractValidator(contract)
    shapes = {
        tf: [None, spec["sequence_length"], len(feature_names)]
        for tf, spec in contract["timeframes"].items()
    }
    contract_hash = validator.compute_contract_hash(feature_names, shapes)
    meta_group.attrs["computed_hash"] = contract_hash
    
    logger.info(f"契約メタデータ保存完了: version={contract['version']}, hash={contract_hash}")


# 使用例: 前処理完了時
with h5py.File("preprocessed.h5", "a") as h5f:
    save_contract_metadata(h5f, INPUT_CONTRACT, feature_names)
```

---

## 🔄 ONNX変換時の契約検証

```python
def verify_onnx_contract(onnx_model_path: str, contract: dict):
    """
    ONNX変換後の入出力契約検証
    
    Args:
        onnx_model_path: ONNXモデルパス
        contract: INPUT_CONTRACT辞書
    """
    import onnx
    
    model = onnx.load(onnx_model_path)
    
    # 入力形状検証
    for input_tensor in model.graph.input:
        tensor_name = input_tensor.name
        tensor_shape = [
            dim.dim_value if dim.dim_value > 0 else -1
            for dim in input_tensor.type.tensor_type.shape.dim
        ]
        
        # TF名抽出（例: "input_M1" → "M1"）
        tf_name = tensor_name.split("_")[-1]
        
        if tf_name in contract["timeframes"]:
            expected_seq = contract["timeframes"][tf_name]["sequence_length"]
            actual_seq = tensor_shape[1] if len(tensor_shape) > 1 else None
            
            if actual_seq != expected_seq:
                raise ValueError(
                    f"ONNX input shape mismatch for {tf_name}: "
                    f"expected seq={expected_seq}, actual={actual_seq}"
                )
    
    # 出力形状検証
    for output_tensor in model.graph.output:
        tensor_name = output_tensor.name
        tensor_shape = [
            dim.dim_value if dim.dim_value > 0 else -1
            for dim in output_tensor.type.tensor_type.shape.dim
        ]
        
        logger.info(f"ONNX出力検証: {tensor_name}, shape={tensor_shape}")
    
    logger.info("✅ ONNX契約検証: 成功")


# 使用例: ONNX変換後
verify_onnx_contract("model.onnx", INPUT_CONTRACT)
```

---

## 📊 契約変更管理

### バージョン履歴

| バージョン | 日付 | 変更内容 | schema_hash |
|-----------|------|---------|-------------|
| v1.0 | 2025-10-22 | 初版作成 | a3f2b1c8e7d9f3a1 |

### 契約変更時の手順

1. **INPUT_CONTRACT更新**: `version`と`schema_hash`を変更
2. **メタデータ保存**: 前処理時に新契約を保存
3. **検証コード更新**: `InputContractValidator`で新契約検証
4. **ONNX再変換**: 新契約に基づきモデル再変換
5. **テスト実行**: 学習・推論・ONNX推論の全パス検証

---

## 🎯 KPI・成功条件（項目11）

- **推論列整合エラー**: 0件
- **ONNX変換成功率**: 100%
- **契約ハッシュ不一致検出**: 即座にWARNING発火
- **特徴量列順シャッフル検出**: 100%

---

## 🔗 関連仕様

- [PREPROCESSOR_SPEC.md](./PREPROCESSOR_SPEC.md) - 入力データ生成
- [TRAINER_SPEC.md](./TRAINER_SPEC.md) - モデル学習
- [ONNX_CONVERTER_SPEC.md](./ONNX_CONVERTER_SPEC.md) - ONNX変換
- [MULTI_TF_FUSION_SPEC.md](./trainer/MULTI_TF_FUSION_SPEC.md) - マルチTF融合

---

## 🔮 将来拡張

- 動的シーケンス長サポート（可変長入力）
- マルチシンボル対応（通貨ペア別契約）
- カスタムhead追加時の契約自動更新
