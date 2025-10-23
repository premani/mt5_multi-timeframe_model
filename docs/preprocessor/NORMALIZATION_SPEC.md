# 正規化仕様 (NORMALIZATION_SPEC)

**バージョン**: 1.0
**更新日**: 2025-10-22
**責任者**: core-team
**カテゴリ**: 前処理サブ仕様

---

## 📋 目的

特徴量の正規化処理とパラメータ管理を定義する。

**対象項目**:
- RobustScaler適用
- 正規化パラメータの保存・管理
- 逆変換の仕様

---

## 正規化パラメータ管理

### 正規化パラメータ互換検証

**目的**: 学習時と推論時の正規化パラメータ不一致で予測精度劣化

**解決策**: パラメータdrift検証

```python
class ScalerParamValidator:
    """正規化パラメータ互換検証"""
    
    def __init__(self, config: dict):
        self.drift_threshold = config.get("drift_threshold_percent", 10.0)
    
    def validate_compatibility(
        self,
        train_params: Dict[str, Dict[str, float]],
        inference_params: Dict[str, Dict[str, float]]
    ) -> Dict[str, Any]:
        """学習時と推論時の正規化パラメータ互換性検証"""
        drift_features = []
        common_features = set(train_params.keys()) & set(inference_params.keys())
        
        for feat in common_features:
            train_scale = train_params[feat]["scale"]
            infer_scale = inference_params[feat]["scale"]
            
            if train_scale != 0:
                scale_drift = abs(infer_scale - train_scale) / train_scale * 100
                if scale_drift > self.drift_threshold:
                    drift_features.append(feat)
        
        return {"compatible": len(drift_features) == 0, "drift_features": drift_features}
```

**KPI（項目38）**: drift検出精度100%、誤検出<1%


---

## 🔗 関連仕様

- [PREPROCESSOR_SPEC.md](../PREPROCESSOR_SPEC.md) - 前処理メイン仕様
- [FEATURE_CALCULATOR_SPEC.md](../FEATURE_CALCULATOR_SPEC.md) - 特徴量計算仕様

---

**作成日**: 2025-10-22
