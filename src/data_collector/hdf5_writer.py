"""
HDF5データ保存モジュール
"""
import h5py
import numpy as np
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
import json


class HDF5Writer:
    """HDF5データ書き込みクラス"""
    
    def __init__(
        self,
        output_path: str,
        compression: Optional[str] = None,
        logger=None
    ):
        """
        初期化
        
        Args:
            output_path: 出力ファイルパス
            compression: 圧縮方式（None/"gzip"/"lzf"）
            logger: ロガーインスタンス
        """
        self.output_path = Path(output_path)
        self.compression = compression
        self.logger = logger
        
        # 出力ディレクトリ作成
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
    
    def _log(self, level: str, msg: str):
        """ログ出力"""
        if self.logger:
            getattr(self.logger, level)(msg)
    
    def backup_existing(self, timestamp_format: str = "%Y%m%d_%H%M%S"):
        """
        既存ファイルをバックアップ
        
        Args:
            timestamp_format: タイムスタンプフォーマット
        """
        if not self.output_path.exists():
            return
        
        # JST日時プレフィックスを生成
        jst_tz = timezone(timedelta(hours=9))
        mtime = datetime.fromtimestamp(
            self.output_path.stat().st_mtime,
            tz=jst_tz
        )
        timestamp_str = mtime.strftime(timestamp_format)
        
        # バックアップファイル名生成
        backup_name = f"{timestamp_str}_{self.output_path.name}"
        backup_path = self.output_path.parent / backup_name
        
        # リネーム
        self.output_path.rename(backup_path)
        self._log('info', f"📦 既存ファイルをバックアップ: {backup_name}")
    
    def write_bar_data(
        self,
        timeframe: str,
        data: np.ndarray
    ):
        """
        バーデータを書き込み
        
        Args:
            timeframe: タイムフレーム（例: "M5"）
            data: バーデータ（N, 8）[time, open, high, low, close, tick_volume, spread, real_volume]
        """
        with h5py.File(self.output_path, 'a') as f:
            dataset_path = f"{timeframe}/data"
            
            if dataset_path in f:
                del f[dataset_path]
            
            # dtypeを指定せず、入力データの型を保持
            f.create_dataset(
                dataset_path,
                data=data,
                compression=self.compression
            )
            
            self._log('debug', f"💾 {timeframe}バーデータ保存: {data.shape}")
    
    def write_tick_data(
        self,
        data: List[Dict[str, Any]]
    ):
        """
        Tickデータを書き込み
        
        Args:
            data: Tickデータのリスト
        """
        if not data:
            self._log('warning', "⚠️  Tickデータが空です")
            return
        
        # 構造化配列に変換
        dtype = [
            ('time', 'i8'),
            ('time_msc', 'i8'),
            ('bid', 'f4'),
            ('ask', 'f4'),
            ('last', 'f4'),
            ('volume', 'i4'),
            ('flags', 'i4')
        ]
        
        tick_array = np.array([
            (
                tick['time'],
                tick['time_msc'],
                tick['bid'],
                tick['ask'],
                tick.get('last', 0.0),
                tick.get('volume', 0),
                tick.get('flags', 0)
            )
            for tick in data
        ], dtype=dtype)
        
        with h5py.File(self.output_path, 'a') as f:
            dataset_path = "ticks/data"
            
            if dataset_path in f:
                del f[dataset_path]
            
            f.create_dataset(
                dataset_path,
                data=tick_array,
                compression=self.compression
            )
            
            self._log('debug', f"💾 Tickデータ保存: {len(data)}件")
    
    def write_metadata(
        self,
        metadata: Dict[str, Any]
    ):
        """
        メタデータを書き込み
        
        Args:
            metadata: メタデータ辞書
        """
        with h5py.File(self.output_path, 'a') as f:
            # JSON文字列として保存
            metadata_json = json.dumps(metadata, ensure_ascii=False, indent=2)
            
            if 'metadata' in f:
                del f['metadata']
            
            f.create_dataset(
                'metadata',
                data=metadata_json.encode('utf-8')
            )
            
            self._log('debug', "💾 メタデータ保存完了")
    
    def get_file_size_mb(self) -> float:
        """
        ファイルサイズ取得
        
        Returns:
            ファイルサイズ（MB）
        """
        if not self.output_path.exists():
            return 0.0
        
        size_bytes = self.output_path.stat().st_size
        return size_bytes / (1024 * 1024)


# timedeltaのインポート追加
from datetime import timedelta
