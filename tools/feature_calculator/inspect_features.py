#!/usr/bin/env python3
"""
特徴量計算結果確認ツール

feature_calculator.h5の内容を表示
"""
import sys
import h5py
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

def main():
    file_path = PROJECT_ROOT / "data" / "feature_calculator.h5"
    
    if not file_path.exists():
        print(f"❌ ファイルが見つかりません: {file_path}")
        return
    
    print("=" * 80)
    print(f"📂 ファイル: {file_path.name}")
    print("=" * 80)
    
    with h5py.File(file_path, 'r') as f:
        # データセット一覧
        print("\n🗂️  データセット一覧")
        def print_structure(name, obj):
            if isinstance(obj, h5py.Dataset):
                print(f"   ├── {name} {obj.shape} [{obj.dtype}]")
            elif isinstance(obj, h5py.Group):
                print(f"   ├── {name}/ (Group)")
        
        f.visititems(print_structure)
        
        # 特徴量情報
        if 'features' in f:
            features = f['features']
            print(f"\n📊 特徴量データ")
            print(f"   形状: {features.shape}")
            print(f"   サンプル数: {features.shape[0]:,}")
            print(f"   特徴量数: {features.shape[1]}")
        
        # 特徴量名
        if 'feature_names' in f:
            feature_names = [name.decode('utf-8') for name in f['feature_names'][:]]
            print(f"\n🏷️  特徴量名（最初10個）")
            for i, name in enumerate(feature_names[:10], 1):
                print(f"   {i:2d}. {name}")
            if len(feature_names) > 10:
                print(f"   ... 他 {len(feature_names) - 10} 個")
        
        # ラベル情報
        if 'labels' in f:
            print(f"\n🏷️  ラベル")
            labels_group = f['labels']
            
            if 'direction' in labels_group:
                direction = labels_group['direction'][:]
                print(f"   Direction: {direction.shape}")
                
                # 分布
                import numpy as np
                counts = np.bincount(direction)
                total = len(direction)
                if len(counts) >= 3:
                    print(f"      DOWN: {counts[0]} ({counts[0]/total*100:.1f}%)")
                    print(f"      NEUTRAL: {counts[1]} ({counts[1]/total*100:.1f}%)")
                    print(f"      UP: {counts[2]} ({counts[2]/total*100:.1f}%)")
            
            if 'magnitude' in labels_group:
                magnitude = labels_group['magnitude'][:]
                print(f"   Magnitude: {magnitude.shape}")
                print(f"      平均: {magnitude.mean():.2f} pips")
                print(f"      中央値: {np.median(magnitude):.2f} pips")
                print(f"      最大: {magnitude.max():.2f} pips")
        
        # メタデータ
        if 'metadata' in f:
            metadata = json.loads(f['metadata'][()].decode('utf-8'))
            print(f"\n📝 メタデータ")
            print(f"   作成日時: {metadata.get('created_at', 'N/A')}")
            print(f"   サンプル数: {metadata.get('num_samples', 'N/A'):,}")
            print(f"   特徴量数: {metadata.get('num_features', 'N/A')}")
            print(f"   フェーズ: {metadata.get('phase', 'N/A')}")
    
    print("\n" + "=" * 80)
    print("✅ 確認完了")
    print("=" * 80)

if __name__ == "__main__":
    main()
