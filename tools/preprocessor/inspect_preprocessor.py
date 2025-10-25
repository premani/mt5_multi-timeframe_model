#!/usr/bin/env python3
"""
前処理結果確認ツール

使用方法:
    bash ./docker_run.sh python3 tools/preprocessor/inspect_preprocessor.py
    bash ./docker_run.sh python3 tools/preprocessor/inspect_preprocessor.py data/preprocessor.h5
"""

import sys
import json
import h5py
import argparse
import numpy as np
from pathlib import Path
from datetime import datetime

# プロジェクトルート設定
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def format_bytes(size_bytes: int) -> str:
    """バイトサイズを人間が読みやすい形式に変換"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} TB"


def inspect_preprocessor(file_path: Path) -> None:
    """前処理済みHDF5ファイルの内容を表示"""
    
    print("=" * 80)
    print("🔍 前処理結果確認ツール")
    print("=" * 80)
    
    # ファイル存在チェック
    if not file_path.exists():
        print(f"❌ エラー: ファイルが見つかりません: {file_path}")
        return
    
    print(f"\n📁 ファイル: {file_path}")
    print(f"   サイズ: {format_bytes(file_path.stat().st_size)}")
    
    try:
        with h5py.File(file_path, 'r') as f:
            # 1. シーケンス情報
            print("\n" + "=" * 80)
            print("📊 シーケンス情報")
            print("=" * 80)
            
            if 'sequences' in f:
                seq_group = f['sequences']
                print(f"\n利用可能なタイムフレーム: {list(seq_group.keys())}\n")
                
                total_sequences = 0
                for tf_name in sorted(seq_group.keys()):
                    seq_data = seq_group[tf_name]
                    shape = seq_data.shape
                    total_sequences += shape[0]
                    
                    print(f"⏱️  {tf_name}:")
                    print(f"   Shape: {shape}")
                    print(f"   - シーケンス数: {shape[0]:,}")
                    print(f"   - ウィンドウサイズ: {shape[1]}")
                    print(f"   - 特徴量数: {shape[2]}")
                    print(f"   - データ型: {seq_data.dtype}")
                    print(f"   - メモリサイズ: {format_bytes(seq_data.size * seq_data.dtype.itemsize)}")
                    print()
                
                print(f"📈 総シーケンス数: {total_sequences:,}")
                
                # NaN/Inf検証
                print("\n" + "=" * 80)
                print("✅ データ品質検証")
                print("=" * 80)
                print("\n【NaN/Inf検査】")
                
                all_clean = True
                for tf_name in sorted(seq_group.keys()):
                    # サンプルチェック（最初の100シーケンス）
                    sample_size = min(100, seq_group[tf_name].shape[0])
                    sample_data = seq_group[tf_name][:sample_size]
                    
                    nan_count = np.isnan(sample_data).sum()
                    inf_count = np.isinf(sample_data).sum()
                    total_elements = sample_data.size
                    
                    if nan_count > 0 or inf_count > 0:
                        all_clean = False
                        print(f"⚠️  {tf_name}: NaN={nan_count}, Inf={inf_count} / {total_elements:,} ({(nan_count+inf_count)/total_elements*100:.2f}%)")
                    else:
                        print(f"✅ {tf_name}: クリーン（先頭{sample_size}サンプル）")
                
                if all_clean:
                    print(f"\n✅ 全タイムフレームでNaN/Inf なし（サンプル検証）")
                else:
                    print(f"\n⚠️  NaN/Inf検出あり - データ品質に問題")
            else:
                print("⚠️  シーケンスデータが見つかりません")
            
            # 2. 正規化パラメータ
            print("\n" + "=" * 80)
            print("🎯 正規化パラメータ")
            print("=" * 80)
            
            if 'scaler_params' in f:
                scaler_params = json.loads(f['scaler_params'][()])
                
                print(f"\n正規化方法: {scaler_params.get('method', 'unknown')}")
                print(f"特徴量数: {len(scaler_params.get('feature_names', []))}")
                
                # パラメータの詳細表示
                if scaler_params.get('method') == 'robust':
                    print(f"\n【RobustScaler パラメータ】")
                    print(f"四分位範囲: {scaler_params.get('quantile_range', [])}")
                    
                    center = scaler_params.get('center_', [])
                    scale = scaler_params.get('scale_', [])
                    
                    if center and scale:
                        print(f"\nCenter（先頭5個）: {center[:5]}")
                        print(f"Scale（先頭5個）: {scale[:5]}")
                        print(f"\nCenter統計:")
                        print(f"  - 最小: {min(center):.6f}")
                        print(f"  - 最大: {max(center):.6f}")
                        print(f"  - 平均: {sum(center)/len(center):.6f}")
                        print(f"\nScale統計:")
                        print(f"  - 最小: {min(scale):.6f}")
                        print(f"  - 最大: {max(scale):.6f}")
                        print(f"  - 平均: {sum(scale)/len(scale):.6f}")
                
                elif scaler_params.get('method') == 'standard':
                    print(f"\n【StandardScaler パラメータ】")
                    
                    mean = scaler_params.get('mean_', [])
                    scale = scaler_params.get('scale_', [])
                    
                    if mean and scale:
                        print(f"\nMean（先頭5個）: {mean[:5]}")
                        print(f"Scale（先頭5個）: {scale[:5]}")
                
                elif scaler_params.get('method') == 'minmax':
                    print(f"\n【MinMaxScaler パラメータ】")
                    
                    data_min = scaler_params.get('data_min_', [])
                    data_max = scaler_params.get('data_max_', [])
                    
                    if data_min and data_max:
                        print(f"\nData Min（先頭5個）: {data_min[:5]}")
                        print(f"Data Max（先頭5個）: {data_max[:5]}")
                
                # 特徴量名リスト
                feature_names = scaler_params.get('feature_names', [])
                if feature_names:
                    print(f"\n【特徴量名リスト】（全{len(feature_names)}個）")
                    for i, name in enumerate(feature_names, 1):
                        print(f"  {i:2d}. {name}")
            else:
                print("\n⚠️  正規化パラメータが見つかりません")
            
            # 3. 特徴量名（scaler_paramsから取得できない場合の予備）
            if 'feature_names' in f and 'scaler_params' not in f:
                print("\n" + "=" * 80)
                print("📋 特徴量名")
                print("=" * 80)
                
                feature_names = [name.decode('utf-8') if isinstance(name, bytes) else name 
                               for name in f['feature_names'][:]]
                print(f"\n特徴量数: {len(feature_names)}")
                print("\n特徴量リスト:")
                for i, name in enumerate(feature_names, 1):
                    print(f"  {i:2d}. {name}")
            
            # 4. メタデータ
            print("\n" + "=" * 80)
            print("📝 メタデータ")
            print("=" * 80)
            
            if 'metadata' in f:
                metadata = json.loads(f['metadata'][()])
                
                print(f"\n生成日時: {metadata.get('processing_timestamp', 'N/A')}")
                print(f"入力ファイル: {metadata.get('input_file', 'N/A')}")
                
                if 'filter_stats' in metadata:
                    stats = metadata['filter_stats']
                    print(f"\nフィルタリング統計:")
                    print(f"  - 初期特徴量数: {stats.get('initial', 'N/A')}")
                    print(f"  - フィルタ後: {stats.get('final', 'N/A')}")
                    print(f"  - 除外数: {stats.get('initial', 0) - stats.get('final', 0)}")
                
                if 'config' in metadata:
                    print(f"\n設定情報:")
                    config = metadata['config']
                    
                    # 品質フィルタ設定
                    if 'quality_filter' in config:
                        qf = config['quality_filter']
                        print(f"  品質フィルタ:")
                        print(f"    - NaN比率上限: {qf.get('max_nan_ratio', 'N/A')}")
                        print(f"    - 最小IQR: {qf.get('min_iqr', 'N/A')}")
                        print(f"    - 相関閾値: {qf.get('max_correlation', 'N/A')}")
                    
                    # 正規化設定
                    if 'normalization' in config:
                        norm = config['normalization']
                        print(f"  正規化:")
                        print(f"    - 方法: {norm.get('method', 'N/A')}")
                        print(f"    - パラメータ保存: {norm.get('save_params', 'N/A')}")
            else:
                print("\n⚠️  メタデータが見つかりません")
            
            # 5. データセット一覧
            print("\n" + "=" * 80)
            print("🗂️  データセット一覧")
            print("=" * 80)
            
            def print_tree(group, prefix=""):
                """HDF5グループをツリー表示"""
                items = list(group.items())
                for i, (name, item) in enumerate(items):
                    is_last = (i == len(items) - 1)
                    connector = "└── " if is_last else "├── "
                    
                    if isinstance(item, h5py.Group):
                        print(f"{prefix}{connector}{name}/ (Group)")
                        extension = "    " if is_last else "│   "
                        print_tree(item, prefix + extension)
                    else:
                        shape_str = f"{item.shape}" if hasattr(item, 'shape') else ""
                        dtype_str = f"[{item.dtype}]" if hasattr(item, 'dtype') else ""
                        print(f"{prefix}{connector}{name} {shape_str} {dtype_str}")
            
            print()
            print_tree(f)
    
    except Exception as e:
        print(f"\n❌ エラー: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 80)


def main():
    """メイン処理"""
    parser = argparse.ArgumentParser(
        description='前処理結果確認ツール',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  bash ./docker_run.sh python3 tools/preprocessor/inspect_preprocessor.py
  bash ./docker_run.sh python3 tools/preprocessor/inspect_preprocessor.py data/preprocessor.h5
  bash ./docker_run.sh python3 tools/preprocessor/inspect_preprocessor.py data/20251023_143045_preprocessor.h5
        """
    )
    
    parser.add_argument(
        'file',
        nargs='?',
        default='data/preprocessor.h5',
        help='確認するHDF5ファイルのパス（デフォルト: data/preprocessor.h5）'
    )
    
    args = parser.parse_args()
    
    # パスをPathオブジェクトに変換
    if Path(args.file).is_absolute():
        file_path = Path(args.file)
    else:
        file_path = PROJECT_ROOT / args.file
    
    inspect_preprocessor(file_path)


if __name__ == "__main__":
    main()
