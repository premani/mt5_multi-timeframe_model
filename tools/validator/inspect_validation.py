#!/usr/bin/env python3
"""検証レポート確認ツール"""

import sys
from pathlib import Path
import json
import glob

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


def main():
    """メイン処理"""
    # 最新のレポート取得
    report_pattern = "data/*_validation_report.json"
    reports = sorted(glob.glob(report_pattern))
    
    if not reports:
        print(f"❌ レポートが見つかりません: {report_pattern}")
        return
    
    latest_report = reports[-1]
    print(f"📂 検証レポート: {Path(latest_report).name}")
    print("=" * 80)
    
    # レポート読み込み
    with open(latest_report, 'r', encoding='utf-8') as f:
        report = json.load(f)
    
    # 基本情報
    print(f"\n📝 基本情報")
    print(f"   検証日時: {report['timestamp']}")
    print(f"   モデル: {Path(report['model_file']).name}")
    print(f"   データ: {Path(report['preprocessed_file']).name}")
    print(f"   テストサンプル数: {report['test_samples']:,}")
    
    # 方向予測評価
    print(f"\n🎯 方向予測評価")
    direction = report['direction_metrics']
    print(f"   Accuracy: {direction['accuracy']:.4f}")
    
    class_names = ['DOWN', 'NEUTRAL', 'UP']
    for i, name in enumerate(class_names):
        precision = direction['precision'][i]
        recall = direction['recall'][i]
        f1 = direction['f1_score'][i]
        print(f"   {name:8s}: Precision={precision:.4f}, Recall={recall:.4f}, F1={f1:.4f}")
    
    # 混同行列
    print(f"\n   混同行列:")
    cm = direction['confusion_matrix']
    print(f"              予測")
    print(f"          DOWN  NEUTRAL  UP")
    for i, name in enumerate(class_names):
        print(f"   {name:8s} {cm[i][0]:5d}  {cm[i][1]:7d}  {cm[i][2]:4d}")
    
    # 価格幅予測評価
    print(f"\n📊 価格幅予測評価")
    magnitude = report['magnitude_metrics']
    print(f"   MAE: {magnitude['mae']:.4f} pips")
    print(f"   RMSE: {magnitude['rmse']:.4f} pips")
    print(f"   R²: {magnitude['r2']:.4f}")
    
    print("\n" + "=" * 80)


if __name__ == "__main__":
    main()
