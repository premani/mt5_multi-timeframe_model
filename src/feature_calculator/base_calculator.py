"""
特徴量計算器の基底クラス

全カテゴリ計算器の共通インターフェースを定義
"""

from abc import ABC, abstractmethod
from typing import Dict
import pandas as pd


class BaseCalculator(ABC):
    """
    特徴量計算器の基底クラス
    
    各カテゴリ計算器はこのクラスを継承し、
    `compute`メソッドを実装する必要があります。
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """
        カテゴリ名を返す
        
        Returns:
            str: カテゴリ名（例: "basic_multi_tf"）
        """
        pass
    
    @property
    @abstractmethod
    def description(self) -> str:
        """
        カテゴリの説明を返す
        
        Returns:
            str: カテゴリの説明
        """
        pass
    
    @abstractmethod
    def compute(
        self, 
        raw_data: Dict[str, pd.DataFrame]
    ) -> pd.DataFrame:
        """
        特徴量を計算
        
        Args:
            raw_data: マルチTF生データ
                {
                    'M1': DataFrame(N, 6) [time, open, high, low, close, volume],
                    'M5': DataFrame(N, 6),
                    'M15': DataFrame(N, 6),
                    'H1': DataFrame(N, 6),
                    'H4': DataFrame(N, 6),
                }
        
        Returns:
            DataFrame(N, K): K列の特徴量
        """
        pass
    
    def validate(self, features: pd.DataFrame) -> Dict[str, any]:
        """
        計算結果を検証
        
        Args:
            features: 計算した特徴量
        
        Returns:
            dict: 検証結果
                {
                    'valid': bool,
                    'nan_ratio': float,
                    'inf_count': int,
                    'warnings': List[str]
                }
        """
        nan_count = features.isna().sum().sum()
        total_cells = features.size
        nan_ratio = nan_count / total_cells if total_cells > 0 else 0.0
        
        inf_count = 0
        for col in features.columns:
            if features[col].dtype in ['float32', 'float64']:
                inf_count += (features[col] == float('inf')).sum()
                inf_count += (features[col] == float('-inf')).sum()
        
        warnings = []
        if nan_ratio > 0.01:
            warnings.append(f"NaN比率が高い: {nan_ratio:.4f}")
        if inf_count > 0:
            warnings.append(f"無限値を検出: {inf_count}個")
        
        return {
            'valid': nan_ratio <= 0.05 and inf_count == 0,
            'nan_ratio': nan_ratio,
            'inf_count': inf_count,
            'warnings': warnings
        }
