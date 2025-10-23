# THRESHOLD_METADATA_SPEC.md

**バージョン**: 1.0.0  
**最終更新**: 2025-10-22  
**Author**: System Architect  
**目的**: 閾値類の根拠トレーサビリティ確保

---

## 📋 概要

プロジェクト内で使用される全ての閾値（NaN比率、相関係数、PSI、ECE、レイテンシ等）について、決定根拠を記録・追跡可能にする。運用後の「なぜその値?」問題を解決し、調整時の判断材料を提供。

---

## 🎯 対象閾値カテゴリ

### 1. データ品質閾値
- NaN比率: 5% (phase1), 1% (phase2)
- 低分散閾値: IQR < 1e-6
- 高相関閾値: 0.95

### 2. 学習・評価閾値
- PSI警告: 0.25
- ECE警告: 0.04 (サンプルサイズ依存)
- 期待値バイアス: 5%

### 3. 運用閾値
- レイテンシ p95: 10ms (scalp), 50ms (swing)
- warmup_calls: 32回
- スプレッドジャンプ検出: z > 3.0

### 4. モデルアーキテクチャ
- LSTM hidden_size: 128
- Attention num_heads: 4
- dropout: 0.1

---

## 📝 メタデータフォーマット

### threshold_meta.json 構造

```json
{
  "version": "1.0.0",
  "project": "mt5_multi-timeframe_model",
  "last_updated": "2025-10-22T10:30:00Z",
  
  "thresholds": {
    "nan_ratio_phase1": {
      "value": 0.05,
      "unit": "ratio",
      "category": "data_quality",
      "source": "statistical_analysis",
      "type": "empirical",
      "commit": "abc123def",
      "rationale": "Phase 1（データ収集段階）では5%のNaN許容でデータ量確保。Phase 2で1%に厳格化。",
      "decision_date": "2025-10-15",
      "decision_by": "core-team",
      "related_kpi": "feature_retention_rate >= 80%",
      "validation_method": "expectancy_impact_analysis",
      "references": [
        "docs/FEATURE_CALCULATOR_SPEC.md#nan-threshold-rationale"
      ]
    },
    
    "correlation_threshold": {
      "value": 0.95,
      "unit": "correlation_coefficient",
      "category": "feature_selection",
      "source": "literature",
      "type": "domain_standard",
      "commit": "def456ghi",
      "rationale": "機械学習の標準的な高相関除外閾値。0.95以上で冗長性が高いと判断。",
      "decision_date": "2025-10-10",
      "decision_by": "core-team",
      "related_kpi": "feature_count optimal balance",
      "validation_method": "threshold_sweep (0.90-0.98)",
      "references": [
        "docs/PREPROCESSOR_SPEC.md#correlation-filter"
      ],
      "notes": "threshold sweep実験を推奨（運用フェーズで最適化）"
    },
    
    "psi_warning": {
      "value": 0.25,
      "unit": "psi_score",
      "category": "drift_detection",
      "source": "literature",
      "type": "industry_standard",
      "commit": "ghi789jkl",
      "rationale": "PSI > 0.25は「significant drift」として業界標準。再学習トリガーの閾値。",
      "decision_date": "2025-10-12",
      "decision_by": "core-team",
      "related_kpi": "retrain_frequency optimal",
      "validation_method": "industry_benchmark",
      "references": [
        "docs/validator/DRIFT_CALIBRATION_MONITORING_SPEC.md#psi-calculation",
        "https://www.listendata.com/2015/05/population-stability-index.html"
      ]
    },
    
    "latency_p95_scalp": {
      "value": 10.0,
      "unit": "milliseconds",
      "category": "execution_latency",
      "source": "ab_test",
      "type": "empirical",
      "commit": "jkl012mno",
      "rationale": "M1スキャルピングでは10ms超の遅延でエントリータイミングが悪化し、期待値5%低下を確認。",
      "decision_date": "2025-10-18",
      "decision_by": "core-team",
      "related_kpi": "scalp_expectancy >= baseline",
      "validation_method": "latency_impact_backtest",
      "references": [
        "docs/validator/EXECUTION_LATENCY_SPEC.md#slo-requirements"
      ],
      "ab_test_summary": {
        "baseline_latency": "8.5ms",
        "test_latency": "12.0ms",
        "expectancy_delta": "-5.2%",
        "sample_size": 10000
      }
    },
    
    "warmup_calls": {
      "value": 32,
      "unit": "calls",
      "category": "execution_latency",
      "source": "empirical",
      "type": "experimental",
      "commit": "mno345pqr",
      "rationale": "GPU/ONNXカーネル最適化完了に必要な呼び出し数。32回でp95が安定化を実験的に確認。",
      "decision_date": "2025-10-20",
      "decision_by": "core-team",
      "related_kpi": "warmup_p95_stable_rate >= 95%",
      "validation_method": "convergence_experiment",
      "references": [
        "docs/validator/EXECUTION_LATENCY_SPEC.md#warmup-criteria"
      ],
      "experiment_summary": {
        "tested_values": [8, 16, 32, 64],
        "convergence_at": 32,
        "p95_stability": "32回以降の標準偏差 < 0.5ms"
      }
    }
  }
}
```

---

## 🔧 実装ガイドライン

### 1. 閾値追加時のワークフロー

```bash
# 1. 閾値決定
# - 統計分析 / AB test / 文献調査

# 2. メタデータ記録
cat >> config/threshold_meta.json <<'JSON'
{
  "new_threshold_name": {
    "value": 0.04,
    "unit": "ratio",
    "category": "calibration",
    "source": "ab_test",
    "type": "empirical",
    "commit": "$(git rev-parse --short HEAD)",
    "rationale": "...",
    "decision_date": "$(date -I)",
    ...
  }
}
JSON

# 3. 仕様書参照追加
# docs/*_SPEC.md に threshold_meta.json へのリンク追加

# 4. コミット
git add config/threshold_meta.json docs/*_SPEC.md
git commit -m "閾値追加: new_threshold_name

根拠: AB test結果に基づく
参照: threshold_meta.json"
```

### 2. 実行時ダンプ（resolved_config）

```python
import json
from pathlib import Path

class ThresholdManager:
    """閾値メタデータ管理"""
    
    def __init__(self, meta_path: str = "config/threshold_meta.json"):
        self.meta_path = Path(meta_path)
        self.metadata = self._load_metadata()
    
    def _load_metadata(self) -> dict:
        """メタデータ読み込み"""
        if not self.meta_path.exists():
            logger.warning(f"閾値メタデータ未存在: {self.meta_path}")
            return {}
        
        with open(self.meta_path) as f:
            return json.load(f)
    
    def get_threshold(self, name: str, default: float = None) -> float:
        """閾値取得（メタデータ付き）"""
        if name not in self.metadata.get("thresholds", {}):
            logger.warning(f"閾値メタデータ未登録: {name}")
            return default
        
        threshold = self.metadata["thresholds"][name]
        logger.info(f"閾値使用: {name}={threshold['value']} "
                   f"(根拠: {threshold['rationale'][:50]}...)")
        
        return threshold["value"]
    
    def dump_resolved_config(self, output_path: str = "logs/resolved_config.json"):
        """実行時設定ダンプ（デバッグ用）"""
        resolved = {
            "timestamp": datetime.now().isoformat(),
            "git_commit": subprocess.check_output(
                ["git", "rev-parse", "HEAD"]
            ).decode().strip(),
            "thresholds_used": self.metadata.get("thresholds", {}),
            "override_sources": self._get_override_sources()
        }
        
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(resolved, f, indent=2, ensure_ascii=False)
        
        logger.info(f"実行時設定ダンプ: {output_path}")
    
    def _get_override_sources(self) -> dict:
        """設定優先順位の追跡"""
        return {
            "priority_order": ["env", "runtime_flag", "config_file", "default"],
            "env_overrides": os.environ.get("THRESHOLD_OVERRIDES", "{}"),
            "runtime_flags": sys.argv
        }


# 使用例
threshold_mgr = ThresholdManager()

# 閾値取得（自動ログ出力）
nan_threshold = threshold_mgr.get_threshold("nan_ratio_phase1", default=0.05)

# 実行時設定ダンプ
threshold_mgr.dump_resolved_config("logs/resolved_config.json")
```

---

## 📊 閾値変更履歴

### 変更ログフォーマット

```json
{
  "change_history": [
    {
      "threshold_name": "nan_ratio_phase2",
      "old_value": 0.02,
      "new_value": 0.01,
      "change_date": "2025-10-22",
      "change_reason": "Phase 2厳格化に伴う調整",
      "impact_analysis": "特徴量保持率 85% → 82% (許容範囲内)",
      "commit": "pqr678stu",
      "approved_by": "core-team"
    }
  ]
}
```

---

## 🔍 検証・監査

### 1. メタデータ完全性チェック

```python
def validate_threshold_metadata(meta_path: str) -> bool:
    """必須フィールド検証"""
    required_fields = [
        "value", "unit", "category", "source", "type",
        "commit", "rationale", "decision_date"
    ]
    
    with open(meta_path) as f:
        metadata = json.load(f)
    
    for name, threshold in metadata.get("thresholds", {}).items():
        for field in required_fields:
            if field not in threshold:
                logger.error(f"閾値 {name} に必須フィールド欠如: {field}")
                return False
    
    logger.info("閾値メタデータ検証: OK")
    return True
```

### 2. 未登録閾値検出

```bash
# ソースコード内のハードコード閾値を検出
grep -rn "threshold\|limit\|max\|min" src/ | \
  grep -v "threshold_meta" | \
  awk '{print $0}' > logs/hardcoded_thresholds.txt

# 手動レビュー後、threshold_meta.json に登録
```

---

## 📚 関連仕様書

- `docs/FEATURE_CALCULATOR_SPEC.md` - NaN閾値根拠
- `docs/PREPROCESSOR_SPEC.md` - 相関閾値
- `docs/validator/DRIFT_CALIBRATION_MONITORING_SPEC.md` - PSI/ECE閾値
- `docs/validator/EXECUTION_LATENCY_SPEC.md` - レイテンシ閾値
- `docs/trainer/MULTI_TF_FUSION_SPEC.md` - アーキテクチャパラメータ

---

## 変更履歴

| 日付 | バージョン | 変更内容 |
|------|-----------|----------|
| 2025-10-22 | 1.0.0 | 初版作成 |
