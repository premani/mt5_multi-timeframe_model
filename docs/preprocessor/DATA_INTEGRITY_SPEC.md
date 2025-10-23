# データ整合性検証仕様 (DATA_INTEGRITY_SPEC)

**バージョン**: 1.0
**更新日**: 2025-10-22
**責任者**: core-team
**カテゴリ**: 前処理サブ仕様

---

## 📋 目的

前処理段階でのデータ整合性を検証し、列順序不一致やTFマッピング失敗に対する処理を定義する。

**対象項目**:
- 列順序ハッシュ検証
- TFマッピング失敗時フォールバック

---

## 項目34対応: 列順序ハッシュ検証

**目的**: 特徴量列順序変更はattention weight誤適用やスケール混在を誘発。Runtime検証でミスマッチ検出する。

**解決策**: ordered_feature_names_hash をメタデータ保存 + Runtime検証

```python
import hashlib
import json
from typing import List

class ColumnOrderValidator:
    """列順序ハッシュ検証"""
    
    def compute_ordered_hash(self, feature_names: List[str]) -> str:
        """
        順序付き特徴量名のハッシュ計算
        
        Args:
            feature_names: 順序を保持した特徴量名リスト
        
        Returns:
            hash: SHA-256の先頭16文字
        """
        # 順序保持のためリストをそのままJSON化
        ordered_str = json.dumps(feature_names, ensure_ascii=False)
        hash_full = hashlib.sha256(ordered_str.encode()).hexdigest()
        return hash_full[:16]
    
    def save_column_order_metadata(
        self,
        h5_file,
        feature_names: List[str]
    ):
        """
        HDF5ファイルに列順序ハッシュ保存
        
        Args:
            h5_file: h5py.File object
            feature_names: 順序付き特徴量名リスト
        """
        metadata_group = h5_file.require_group("metadata")
        
        # 特徴量名保存
        if "feature_names" in metadata_group:
            del metadata_group["feature_names"]
        metadata_group.create_dataset(
            "feature_names",
            data=[name.encode() for name in feature_names]
        )
        
        # 列順序ハッシュ保存
        ordered_hash = self.compute_ordered_hash(feature_names)
        metadata_group.attrs["feature_names_hash"] = ordered_hash
        
        logger.info(f"列順序ハッシュ保存: {ordered_hash}")
    
    def verify_column_order_at_runtime(
        self,
        expected_feature_names: List[str],
        runtime_feature_names: List[str]
    ) -> Dict[str, Any]:
        """
        Runtime時の列順序検証
        
        Args:
            expected_feature_names: 学習時の順序（HDF5から読込）
            runtime_feature_names: 推論時の順序
        
        Returns:
            {
                "valid": bool,
                "expected_hash": str,
                "runtime_hash": str,
                "mismatches": List[Dict],  # ミスマッチ詳細
                "error_message": str
            }
        """
        expected_hash = self.compute_ordered_hash(expected_feature_names)
        runtime_hash = self.compute_ordered_hash(runtime_feature_names)
        
        if expected_hash == runtime_hash:
            return {
                "valid": True,
                "expected_hash": expected_hash,
                "runtime_hash": runtime_hash,
                "mismatches": [],
                "error_message": ""
            }
        
        # ミスマッチ詳細分析
        mismatches = []
        
        # 長さ不一致
        if len(expected_feature_names) != len(runtime_feature_names):
            mismatches.append({
                "type": "length_mismatch",
                "expected": len(expected_feature_names),
                "runtime": len(runtime_feature_names)
            })
        
        # 順序ミスマッチ検出
        max_len = max(len(expected_feature_names), len(runtime_feature_names))
        for i in range(max_len):
            exp_name = expected_feature_names[i] if i < len(expected_feature_names) else "<missing>"
            run_name = runtime_feature_names[i] if i < len(runtime_feature_names) else "<missing>"
            
            if exp_name != run_name:
                mismatches.append({
                    "type": "order_mismatch",
                    "index": i,
                    "expected": exp_name,
                    "runtime": run_name
                })
        
        error_msg = (
            f"列順序ハッシュ不一致: expected={expected_hash}, runtime={runtime_hash}\n"
            f"ミスマッチ数: {len(mismatches)}"
        )
        
        return {
            "valid": False,
            "expected_hash": expected_hash,
            "runtime_hash": runtime_hash,
            "mismatches": mismatches[:10],  # 最初の10件のみ
            "error_message": error_msg
        }


# 使用例: 前処理完了時
validator = ColumnOrderValidator()

with h5py.File("preprocessed.h5", "a") as h5f:
    feature_names = ["rsi_m1", "macd_m1", "atr_m5", ...]  # 順序重要
    validator.save_column_order_metadata(h5f, feature_names)


# 使用例: 推論時
def load_and_validate_features(preprocessed_path: str, runtime_features: pd.DataFrame):
    """
    推論時の列順序検証
    
    Args:
        preprocessed_path: 学習済みHDF5パス
        runtime_features: 推論時の特徴量DataFrame
    
    Raises:
        ValueError: 列順序不一致時
    """
    validator = ColumnOrderValidator()
    
    # 学習時の列順序読込
    with h5py.File(preprocessed_path, "r") as h5f:
        expected_names = [
            name.decode() for name in h5f["metadata/feature_names"][:]
        ]
    
    # Runtime列順序
    runtime_names = list(runtime_features.columns)
    
    # 検証実行
    result = validator.verify_column_order_at_runtime(
        expected_feature_names=expected_names,
        runtime_feature_names=runtime_names
    )
    
    if not result["valid"]:
        logger.error(f"❌ 列順序検証失敗: {result['error_message']}")
        
        # ミスマッチ詳細ログ
        for mismatch in result["mismatches"][:5]:
            logger.error(f"   - {mismatch}")
        
        raise ValueError(
            f"Feature column order mismatch: {result['error_message']}"
        )
    
    logger.info(f"✅ 列順序検証成功: hash={result['expected_hash']}")
    
    return runtime_features[expected_names]  # 正しい順序で返す


# 使用例: バッチ推論
try:
    validated_features = load_and_validate_features(
        "models/fx_mtf_20251022_preprocessed.h5",
        runtime_features
    )
    predictions = model.predict(validated_features)
except ValueError as e:
    logger.error(f"推論失敗: {e}")
    # 列順序修正またはエラー通知
```

**列順序ハッシュ仕様**:
- **アルゴリズム**: SHA-256（先頭16文字使用）
- **保存場所**: `/metadata/feature_names_hash`（HDF5 attribute）
- **検証タイミング**: 
  - 前処理完了時: ハッシュ生成・保存
  - 推論開始時: Runtime列順序とハッシュ比較
  - ONNX変換時: 契約ハッシュとの整合性確認
- **エラー処理**: ミスマッチ時は即座にValueError raise（推論続行禁止）

**成功指標**:
- 列順序ミスマッチ検出率: 100%
- False Positive率: 0%（正しい順序で誤検出なし）
- Runtime検証オーバーヘッド: <10ms

**検証**:
```python
def test_column_order_validation():
    """列順序ハッシュ検証の動作確認"""
    validator = ColumnOrderValidator()
    
    # ケース1: 正しい順序
    expected = ["feat1", "feat2", "feat3"]
    runtime = ["feat1", "feat2", "feat3"]
    result = validator.verify_column_order_at_runtime(expected, runtime)
    assert result["valid"] == True
    
    # ケース2: 順序入れ替わり
    runtime = ["feat1", "feat3", "feat2"]
    result = validator.verify_column_order_at_runtime(expected, runtime)
    assert result["valid"] == False
    assert any(m["type"] == "order_mismatch" for m in result["mismatches"])
    
    # ケース3: 列数不一致
    runtime = ["feat1", "feat2"]
    result = validator.verify_column_order_at_runtime(expected, runtime)
    assert result["valid"] == False
    assert any(m["type"] == "length_mismatch" for m in result["mismatches"])
```

---


---

## 項目46対応: TFマッピング失敗時フォールバック

**目的**: H1/H4開始バー欠損時の処理が未定義 → レイテンシ遅延や未来推定誤り

**解決策**: `fallback="skip"` or `"use_last_closed"` のポリシーフラグ化

```python
class TFMappingFallbackPolicy:
    """TFマッピング失敗時フォールバック"""
    
    def __init__(self, config: dict):
        self.fallback_policy = config.get("tf_mapping_fallback", "skip")  # "skip" | "use_last_closed"
        self.max_lookback_seconds = config.get("max_lookback_seconds", {
            "H1": 3600,   # H1は1時間前まで許容
            "H4": 7200    # H4は2時間前まで許容
        })
    
    def map_lower_to_higher_tf(
        self,
        lower_tf_timestamps: np.ndarray,
        higher_tf_data: pd.DataFrame,
        higher_tf_timestamps: np.ndarray,
        tf_name: str
    ) -> Tuple[np.ndarray, Dict[str, Any]]:
        """
        下位TF → 上位TFマッピング（フォールバック対応）
        
        Args:
            lower_tf_timestamps: M1/M5のタイムスタンプ
            higher_tf_data: H1/H4のデータ
            higher_tf_timestamps: H1/H4のタイムスタンプ
            tf_name: 上位TF名（"H1" or "H4"）
        
        Returns:
            (mapped_indices, mapping_info)
        """
        N = len(lower_tf_timestamps)
        mapped_indices = np.full(N, -1, dtype=int)  # -1=マッピング失敗
        
        fallback_count = 0
        skip_count = 0
        
        for i, ts in enumerate(lower_tf_timestamps):
            # 完全一致検索
            exact_match = np.where(higher_tf_timestamps <= ts)[0]
            
            if len(exact_match) > 0:
                # 最も近い過去のバーを使用
                mapped_indices[i] = exact_match[-1]
            else:
                # マッピング失敗 → フォールバック適用
                if self.fallback_policy == "skip":
                    # スキップ（マスク対象）
                    mapped_indices[i] = -1
                    skip_count += 1
                
                elif self.fallback_policy == "use_last_closed":
                    # 許容時間内の最近過去バーを使用
                    max_lookback = self.max_lookback_seconds.get(tf_name, 3600)
                    
                    # 時間差計算
                    time_diffs = ts - higher_tf_timestamps
                    valid_lookback = (time_diffs > 0) & (time_diffs <= max_lookback)
                    
                    if valid_lookback.any():
                        # 最も近い過去バー
                        valid_indices = np.where(valid_lookback)[0]
                        mapped_indices[i] = valid_indices[-1]
                        fallback_count += 1
                    else:
                        # 許容範囲外 → スキップ
                        mapped_indices[i] = -1
                        skip_count += 1
        
        mapping_info = {
            "policy": self.fallback_policy,
            "total_mappings": N,
            "successful_mappings": int((mapped_indices >= 0).sum()),
            "fallback_used": fallback_count,
            "skipped": skip_count,
            "success_rate": float((mapped_indices >= 0).mean())
        }
        
        logger.info(
            f"{tf_name}マッピング: 成功率={mapping_info['success_rate']:.2%}, "
            f"fallback={fallback_count}, skip={skip_count}"
        )
        
        return mapped_indices, mapping_info


# 使用例: マルチTF統合時
fallback_policy = TFMappingFallbackPolicy({
    "tf_mapping_fallback": "use_last_closed",  # or "skip"
    "max_lookback_seconds": {"H1": 3600, "H4": 7200}
})

# M5 → H1マッピング
h1_indices, mapping_info = fallback_policy.map_lower_to_higher_tf(
    lower_tf_timestamps=timestamps_m5,
    higher_tf_data=features_h1,
    higher_tf_timestamps=timestamps_h1,
    tf_name="H1"
)

# マッピング失敗箇所をマスク
mask = (h1_indices >= 0).astype(float)
```

**KPI（項目46）**:
- マッピング成功率: ≥95%
- fallback使用率: <5%
- skip率: <2%

---



---

## 🔗 関連仕様

- [PREPROCESSOR_SPEC.md](../PREPROCESSOR_SPEC.md) - 前処理メイン仕様
- [MODEL_IO_CONTRACT_SPEC.md](../common/MODEL_IO_CONTRACT_SPEC.md) - 入力契約定義

---

**作成日**: 2025-10-22
