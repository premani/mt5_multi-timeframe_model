"""
タイムスタンプ整合モジュール

全タイムフレームをM1基準（1分間隔）に整合
"""

from typing import Dict
import pandas as pd
import numpy as np
from datetime import timezone


class TimestampAligner:
    """タイムスタンプ整合クラス"""
    
    # バーデータのカラムインデックス定義（collector.pyと同じ）
    BAR_COLUMNS = {
        'time': 0,
        'open': 1,
        'high': 2,
        'low': 3,
        'close': 4,
        'tick_volume': 5,
        'spread': 6,
        'real_volume': 7
    }
    
    def __init__(self, logger):
        """
        Args:
            logger: ロガーインスタンス
        """
        self.logger = logger
    
    def align_to_m1(self, raw_data: Dict[str, np.ndarray]) -> Dict[str, np.ndarray]:
        """
        全TFをM1基準に整合
        
        Args:
            raw_data: {TF: numpy配列(N, 8)} の辞書
        
        Returns:
            整合後の {TF: numpy配列(M, 8)} 辞書（全て同じ行数）
        """
        self.logger.info("🔄 タイムスタンプ整合開始")
        
        # M1の時刻インデックスを基準とする
        if 'M1' not in raw_data:
            raise ValueError("M1データが必要です")
        
        m1_array = raw_data['M1']
        m1_times = pd.to_datetime(
            m1_array[:, self.BAR_COLUMNS['time']].astype(np.int64), 
            unit='s', 
            utc=True
        )
        
        self.logger.info(f"   基準時刻: M1 ({len(m1_times):,}行)")
        self.logger.info(f"   期間: {m1_times.min()} ～ {m1_times.max()}")
        
        # 整合後データ
        aligned_data = {}
        
        # M1はそのまま
        aligned_data['M1'] = m1_array.copy()
        
        # 他のTFを整合
        for tf in ['M5', 'M15', 'H1', 'H4']:
            if tf not in raw_data:
                self.logger.warning(f"   ⚠️ {tf}データが見つかりません")
                continue
            
            aligned_data[tf] = self._align_single_tf(
                raw_data[tf], 
                m1_times,
                tf
            )
        
        self.logger.info("✅ タイムスタンプ整合完了")
        
        # 整合結果サマリ
        for tf, arr in aligned_data.items():
            self.logger.info(f"   {tf}: {len(arr):,}行（整合後）")
        
        return aligned_data
    
    def _align_single_tf(
        self, 
        tf_array: np.ndarray, 
        m1_times: pd.Series,
        tf_name: str
    ) -> np.ndarray:
        """
        単一TFをM1時刻に整合
        
        Args:
            tf_array: 整合対象のnumpy配列 (N, 8)
            m1_times: M1の時刻Series
            tf_name: TF名（ログ用）
        
        Returns:
            整合後のnumpy配列 (M, 8)
        """
        # TFのタイムスタンプをdatetimeに変換
        tf_times = pd.to_datetime(
            tf_array[:, self.BAR_COLUMNS['time']].astype(np.int64),
            unit='s', 
            utc=True
        )
        
        # DataFrameに変換（reindexのため）
        tf_df = pd.DataFrame(
            tf_array,
            columns=['time', 'open', 'high', 'low', 'close', 
                    'tick_volume', 'spread', 'real_volume']
        )
        tf_df.index = tf_times
        
        # M1の時刻に再インデックス（前方補完）
        aligned_df = tf_df.reindex(m1_times, method='ffill')
        
        # timeカラムをM1基準に更新（UNIX秒に戻す）
        aligned_df['time'] = m1_times.astype(np.int64) // 10**9
        
        # numpy配列に戻す
        aligned_array = aligned_df.values.astype(np.float64)
        
        # 補完統計
        original_rows = len(tf_array)
        aligned_rows = len(aligned_array)
        filled_ratio = (aligned_rows - original_rows) / aligned_rows * 100
        
        self.logger.info(
            f"   {tf_name}: {original_rows:,}行 → {aligned_rows:,}行 "
            f"(補完率: {filled_ratio:.1f}%)"
        )
        
        return aligned_array
