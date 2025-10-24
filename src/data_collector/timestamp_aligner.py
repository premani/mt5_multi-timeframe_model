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
    
    def __init__(self, logger):
        """
        Args:
            logger: ロガーインスタンス
        """
        self.logger = logger
    
    def align_to_m1(self, raw_data: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
        """
        全TFをM1基準に整合
        
        Args:
            raw_data: {TF: DataFrame} の辞書
        
        Returns:
            整合後の {TF: DataFrame} 辞書（全て同じ行数）
        """
        self.logger.info("🔄 タイムスタンプ整合開始")
        
        # M1の時刻インデックスを基準とする
        if 'M1' not in raw_data:
            raise ValueError("M1データが必要です")
        
        m1_data = raw_data['M1']
        m1_times = pd.to_datetime(m1_data['time'], unit='s', utc=True)
        
        self.logger.info(f"   基準時刻: M1 ({len(m1_times):,}行)")
        self.logger.info(f"   期間: {m1_times.min()} ～ {m1_times.max()}")
        
        # 整合後データ
        aligned_data = {}
        
        # M1はそのまま
        aligned_data['M1'] = m1_data.copy()
        aligned_data['M1']['time'] = m1_times
        
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
        for tf, df in aligned_data.items():
            self.logger.info(f"   {tf}: {len(df):,}行（整合後）")
        
        return aligned_data
    
    def _align_single_tf(
        self, 
        tf_data: pd.DataFrame, 
        m1_times: pd.Series,
        tf_name: str
    ) -> pd.DataFrame:
        """
        単一TFをM1時刻に整合
        
        Args:
            tf_data: 整合対象のDataFrame
            m1_times: M1の時刻Series
            tf_name: TF名（ログ用）
        
        Returns:
            整合後のDataFrame
        """
        # TFのタイムスタンプをdatetimeに変換
        tf_times = pd.to_datetime(tf_data['time'], unit='s', utc=True)
        
        # timeをインデックスに設定
        tf_indexed = tf_data.copy()
        tf_indexed.index = tf_times
        
        # M1の時刻に再インデックス（前方補完）
        aligned = tf_indexed.reindex(m1_times, method='ffill')
        
        # timeカラムをM1基準に更新
        aligned['time'] = m1_times
        aligned = aligned.reset_index(drop=True)
        
        # 補完統計
        original_rows = len(tf_data)
        aligned_rows = len(aligned)
        filled_ratio = (aligned_rows - original_rows) / aligned_rows * 100
        
        self.logger.info(
            f"   {tf_name}: {original_rows:,}行 → {aligned_rows:,}行 "
            f"(補完率: {filled_ratio:.1f}%)"
        )
        
        return aligned
