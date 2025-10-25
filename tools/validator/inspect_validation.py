#!/usr/bin/env python3
"""検証レポート確認ツール"""

import sys
from pathlib import Path
import json

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


def main():
    """メイン処理"""
    # レポートファイル（基本名）
    report_path = "models/validator_report.json"
    
    if not Path(report_path).exists():
        print(f"❌ レポートが見つかりません: {report_path}")
        print(f"   検証処理を実行してください: bash ./docker_run.sh python3 src/validator.py")
        return
    
    print(f"📂 検証レポート: {Path(report_path).name}")
    print("=" * 80)
    
    # レポート読み込み
    with open(report_path, 'r', encoding='utf-8') as f:
        report = json.load(f)
    
    # 基本情報
    print(f"\n📝 基本情報")
    print(f"   検証日時: {report['timestamp']}")
    print(f"   モデル: {Path(report['model_file']).name}")
    print(f"   データ: {Path(report['preprocessed_file']).name}")
    print(f"   テストサンプル数: {report['test_samples']:,}")
    
    # クラス分布
    print(f"\n📊 クラス分布")
    class_names = ['DOWN', 'NEUTRAL', 'UP']
    for name in class_names:
        key = name.lower()
        count = report['class_distribution'][key]['count']
        ratio = report['class_distribution'][key]['ratio']
        print(f"   {name:8s}: {count:6,d} ({ratio:6.2%})")
    
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
    
    # 予測信頼度
    print(f"\n🔍 予測信頼度")
    confidence = report['confidence_stats']
    print(f"   平均: {confidence['mean']:.4f}")
    print(f"   中央値: {confidence['median']:.4f}")
    print(f"   標準偏差: {confidence['std']:.4f}")
    print(f"   範囲: [{confidence['min']:.4f}, {confidence['max']:.4f}]")
    
    # 価格幅分布
    print(f"\n📊 価格幅分布")
    mag_dist = report['magnitude_distribution']
    print(f"   実際値 - 平均: {mag_dist['true']['mean']:.4f} pips, 範囲: [{mag_dist['true']['min']:.4f}, {mag_dist['true']['max']:.4f}]")
    print(f"   予測値 - 平均: {mag_dist['pred']['mean']:.4f} pips, 範囲: [{mag_dist['pred']['min']:.4f}, {mag_dist['pred']['max']:.4f}]")
    
    print("\n" + "=" * 80)


if __name__ == "__main__":
    main()
