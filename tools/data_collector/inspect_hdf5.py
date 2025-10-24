#!/usr/bin/env python3
"""
HDF5データ検査ツール
data_collector.h5の内容を詳細表示
"""
import sys
import argparse
from pathlib import Path
import h5py
import numpy as np
import json
from datetime import datetime, timezone

def format_timestamp(ts: float) -> str:
    """UNIX時刻をISO8601形式に変換（UTC+9 JST）"""
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()

def inspect_structure(file_path: Path):
    """HDF5ファイルの構造を表示"""
    print("=" * 80)
    print(f"📁 ファイル: {file_path}")
    print(f"📦 サイズ: {file_path.stat().st_size / 1024 / 1024:.2f} MB")
    print("=" * 80)
    
    with h5py.File(file_path, 'r') as f:
        print("\n📊 HDF5構造:")
        print("-" * 80)
        
        for key in f.keys():
            item = f[key]
            if isinstance(item, h5py.Dataset):
                print(f"  {key}: shape={item.shape}, dtype={item.dtype}")
            else:
                print(f"  {key}/ (group)")
                for subkey in item.keys():
                    ds = item[subkey]
                    print(f"    {subkey}: shape={ds.shape}, dtype={ds.dtype}")

def inspect_metadata(file_path: Path):
    """メタデータを表示"""
    with h5py.File(file_path, 'r') as f:
        if 'metadata' not in f:
            print("\n⚠️  メタデータなし")
            return
        
        print("\n📋 メタデータ:")
        print("-" * 80)
        meta = json.loads(f['metadata'][()].decode('utf-8'))
        for key, value in meta.items():
            print(f"  {key}: {value}")

def inspect_timeframe(file_path: Path, tf: str, sample_size: int = 5):
    """タイムフレームデータを表示"""
    with h5py.File(file_path, 'r') as f:
        if tf not in f or 'data' not in f[tf]:
            print(f"\n❌ {tf}データなし")
            return
        
        data = f[tf]['data']
        print(f"\n📊 {tf}データ: shape={data.shape}")
        print("-" * 80)
        
        # 統計情報
        timestamps = data[:, 0]
        print(f"  件数: {len(data):,}件")
        print(f"  期間: {format_timestamp(timestamps[0])} ~ {format_timestamp(timestamps[-1])}")
        
        # 単調性チェック
        diffs = np.diff(timestamps)
        non_monotonic = np.sum(diffs <= 0)
        if non_monotonic > 0:
            print(f"  ⚠️  単調性違反: {non_monotonic}件")
        else:
            print(f"  ✅ 単調性: OK")
        
        # 重複チェック
        duplicates = len(timestamps) - len(np.unique(timestamps))
        if duplicates > 0:
            print(f"  ⚠️  重複: {duplicates}件")
        else:
            print(f"  ✅ 重複: なし")
        
        # サンプルデータ表示
        print(f"\n  最初の{sample_size}件:")
        for i in range(min(sample_size, len(data))):
            row = data[i]
            ts = format_timestamp(row[0])
            print(f"    [{i}] {ts} | O={row[1]:.3f} H={row[2]:.3f} L={row[3]:.3f} C={row[4]:.3f}")

def inspect_ticks(file_path: Path, sample_size: int = 5):
    """Tickデータを表示"""
    with h5py.File(file_path, 'r') as f:
        if 'ticks' not in f or 'data' not in f['ticks']:
            print(f"\n❌ Tickデータなし")
            return
        
        data = f['ticks']['data']
        print(f"\n🎯 Tickデータ: shape={data.shape}, dtype={data.dtype}")
        print("-" * 80)
        
        print(f"  件数: {len(data):,}件")
        
        # 最初と最後のサンプル
        print(f"\n  最初の{sample_size}件:")
        for i in range(min(sample_size, len(data))):
            print(f"    [{i}] {data[i]}")
        
        if len(data) > sample_size * 2:
            print(f"\n  最後の{sample_size}件:")
            for i in range(len(data) - sample_size, len(data)):
                print(f"    [{i}] {data[i]}")

def main():
    parser = argparse.ArgumentParser(description='HDF5データ検査ツール')
    parser.add_argument(
        'file',
        nargs='?',
        default='data/data_collector.h5',
        help='検査するHDF5ファイルパス（デフォルト: data/data_collector.h5）'
    )
    parser.add_argument(
        '--timeframe', '-t',
        choices=['M1', 'M5', 'M15', 'H1', 'H4'],
        help='特定のタイムフレームのみ表示'
    )
    parser.add_argument(
        '--ticks',
        action='store_true',
        help='Tickデータを表示'
    )
    parser.add_argument(
        '--sample-size', '-n',
        type=int,
        default=5,
        help='サンプル表示件数（デフォルト: 5）'
    )
    parser.add_argument(
        '--all',
        action='store_true',
        help='全タイムフレーム表示'
    )
    
    args = parser.parse_args()
    
    file_path = Path(args.file)
    if not file_path.exists():
        print(f"❌ ファイルが見つかりません: {file_path}")
        sys.exit(1)
    
    # 構造とメタデータは常に表示
    inspect_structure(file_path)
    inspect_metadata(file_path)
    
    # タイムフレームデータ表示
    if args.timeframe:
        inspect_timeframe(file_path, args.timeframe, args.sample_size)
    elif args.all:
        for tf in ['M1', 'M5', 'M15', 'H1', 'H4']:
            inspect_timeframe(file_path, tf, args.sample_size)
    
    # Tickデータ表示
    if args.ticks:
        inspect_ticks(file_path, args.sample_size)
    
    print("\n" + "=" * 80)

if __name__ == '__main__':
    main()
