"""
HDF5データ保存モジュール
"""
import h5py
import numpy as np
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional
import json


class HDF5Writer:
    """HDF5データ書き込みクラス"""

    # Tickデータのフィールド定義
    TICK_DTYPE = [
        ('time', 'i8'),
        ('time_msc', 'i8'),
        ('bid', 'f4'),
        ('ask', 'f4'),
        ('last', 'f4'),
        ('volume', 'i4'),
        ('flags', 'i4')
    ]

    # Tickデータのフィールド名リスト
    TICK_FIELDS = ['time', 'time_msc', 'bid', 'ask', 'last', 'volume', 'flags']

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
    
    def _log(self, level: str, msg: str) -> None:
        """ログ出力"""
        if self.logger:
            getattr(self.logger, level)(msg)
    
    def backup_existing(self, timestamp_format: str = "%Y%m%d_%H%M%S") -> None:
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
    ) -> None:
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
    ) -> None:
        """
        Tickデータを書き込み（上書きモード）

        Args:
            data: Tickデータのリスト
        """
        if not data:
            self._log('warning', "⚠️  Tickデータが空です")
            return
        
        # 構造化配列に変換
        tick_array = self._convert_ticks_to_array(data)
        
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
    
    def clear_tick_data(self) -> None:
        """
        既存のTickデータを削除（月分割取得の初回クリーン用）
        """
        if not self.output_path.exists():
            self._log('debug', "🗑️  clear_tick_data: ファイル未存在")
            return
        
        with h5py.File(self.output_path, 'a') as f:
            dataset_path = "ticks/data"
            
            self._log('debug', f"🗑️  clear_tick_data: '{dataset_path}' in f = {dataset_path in f}")
            self._log('debug', f"🗑️  clear_tick_data: 現在のキー = {list(f.keys())}")
            
            if dataset_path in f:
                del f[dataset_path]
                self._log('debug', f"🗑️  既存Tickデータ削除完了")
                self._log('debug', f"🗑️  削除後のキー = {list(f.keys())}")
            else:
                self._log('debug', "🗑️  clear_tick_data: '{dataset_path}' 存在せず")
    
    def append_tick_data(
        self,
        data: List[Dict[str, Any]]
    ) -> None:
        """
        Tickデータを追記（月分割用）

        Args:
            data: Tickデータのリスト
        """
        if not data:
            self._log('warning', "⚠️  Tickデータが空です")
            return
        
        # 構造化配列に変換
        new_array = self._convert_ticks_to_array(data)
        
        with h5py.File(self.output_path, 'a') as f:
            dataset_path = "ticks/data"
            
            self._log('debug', f"💾 append_tick_data: '{dataset_path}' in f = {dataset_path in f}")
            self._log('debug', f"💾 append_tick_data: 現在のキー = {list(f.keys())}")
            
            if dataset_path not in f:
                # 初回: 新規作成
                self._log('debug', f"💾 Tick初回作成: {len(new_array)}件")
                f.create_dataset(
                    dataset_path,
                    data=new_array,
                    maxshape=(None,),
                    compression=self.compression
                )
            else:
                # 追記: リサイズして追加
                dataset = f[dataset_path]
                old_size = dataset.shape[0]
                new_size = old_size + len(new_array)
                
                self._log('debug', f"💾 Tick追記: {old_size:,} → {new_size:,}件 (+{len(new_array):,})")
                
                dataset.resize((new_size,))
                dataset[old_size:new_size] = new_array
    
    def _convert_ticks_to_array(
        self,
        data: List[Dict[str, Any]]
    ) -> np.ndarray:
        """
        TickデータをNumPy構造化配列に変換

        Args:
            data: Tickデータのリスト

        Returns:
            構造化配列
        """
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
        ], dtype=self.TICK_DTYPE)

        return tick_array
    
    def write_metadata(
        self,
        metadata: Dict[str, Any]
    ) -> None:
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
