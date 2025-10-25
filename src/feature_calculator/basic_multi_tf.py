"""
基本マルチTF特徴量計算器

Phase 1-1: 基本マルチTF (15-20列)
"""

from typing import Dict, Any
import pandas as pd
import numpy as np

from .base_calculator import BaseCalculator


class BasicMultiTFCalculator(BaseCalculator):
    """基本マルチTF特徴量計算器（Phase 1-1必須）"""
    
    def __init__(self, config: Dict[str, Any]):
        """
        Args:
            config: 設定辞書
        """
        self.config = config
    
    @property
    def name(self) -> str:
        return "basic_multi_tf"
    
    @property
    def description(self) -> str:
        return "基本マルチTF特徴量（価格変化・レンジ・TF間差分）"
    
    def compute(
        self, 
        raw_data: Dict[str, pd.DataFrame]
    ) -> pd.DataFrame:
        """
        基本マルチTF特徴量を計算
        
        Args:
            raw_data: マルチTF生データ
        
        Returns:
            DataFrame(N, 15-20): 基本特徴量
        """
        features = {}
        
        # TF内特徴量（各TFで計算）
        for tf in ['M1', 'M5', 'M15', 'H1', 'H4']:
            if tf not in raw_data:
                continue
            
            df = raw_data[tf]
            
            # 価格変化（pips）USDJPY: 0.01円 = 1pip
            features[f'{tf}_price_change_pips'] = (
                (df['close'] - df['close'].shift(1)) * 100
            )
            
            # 価格変化率
            features[f'{tf}_price_change_rate'] = (
                df['close'].pct_change()
            )
            
            # レンジ幅（高値-安値、pips）
            features[f'{tf}_range_pips'] = (
                (df['high'] - df['low']) * 100
            )
            
            # レンジ幅率（高値-安値）/始値
            features[f'{tf}_range_rate'] = (
                (df['high'] - df['low']) / df['open']
            )
        
        # TF間特徴量（M1とM5、M5とM15、M15とH1、H1とH4）
        tf_pairs = [('M1', 'M5'), ('M5', 'M15'), ('M15', 'H1'), ('H1', 'H4')]
        
        for tf1, tf2 in tf_pairs:
            if tf1 not in raw_data or tf2 not in raw_data:
                continue
            
            # 終値差分（pips）
            features[f'{tf1}_{tf2}_close_diff_pips'] = (
                (raw_data[tf1]['close'].values - raw_data[tf2]['close'].values) * 100
            )
            
            # 方向一致度（±符号が同じかどうか）
            tf1_direction = np.sign(
                raw_data[tf1]['close'].values - np.roll(raw_data[tf1]['close'].values, 1)
            )
            tf2_direction = np.sign(
                raw_data[tf2]['close'].values - np.roll(raw_data[tf2]['close'].values, 1)
            )
            features[f'{tf1}_{tf2}_direction_match'] = (
                (tf1_direction == tf2_direction).astype(float)
            )
        
        # DataFrameに変換
        result = pd.DataFrame(features)
        
        return result
