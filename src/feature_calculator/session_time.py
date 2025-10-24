"""
セッション・時間特徴量計算器

Phase 1-1: セッション時間（5-8列）
"""

from typing import Dict, Any
import pandas as pd
import numpy as np

from .base_calculator import BaseCalculator


class SessionTimeCalculator(BaseCalculator):
    """セッション・時間特徴量計算器（Phase 1-1必須）"""
    
    def __init__(self, config: Dict[str, Any]):
        """
        Args:
            config: 設定辞書
        """
        self.config = config
        
        # セッション時刻設定（UTC）
        self.sessions = config.get('sessions', {
            'tokyo': {'start': '00:00', 'end': '06:00'},
            'london': {'start': '07:00', 'end': '15:00'},
            'newyork': {'start': '12:00', 'end': '20:00'}
        })
    
    @property
    def name(self) -> str:
        return "session_time"
    
    @property
    def description(self) -> str:
        return "セッション・時間特徴量（時刻エンコード・セッション判定）"
    
    def compute(self, raw_data: Dict[str, pd.DataFrame]) -> pd.DataFrame:
        """
        セッション・時間特徴量を計算
        
        Args:
            raw_data: {TF: DataFrame} の辞書（M1のtime列を使用）
        
        Returns:
            特徴量DataFrame（5-8列）
        """
        # M1の時刻データを使用（最も粒度が細かい）
        m1_data = raw_data.get('M1')
        if m1_data is None or 'time' not in m1_data.columns:
            raise ValueError("M1データまたはtime列が見つかりません")
        
        timestamps = m1_data['time']
        
        # 特徴量辞書
        features = {}
        
        # 時刻エンコード（24時間周期）
        hours = timestamps.dt.hour + timestamps.dt.minute / 60.0
        features['hour_sin'] = np.sin(2 * np.pi * hours / 24.0)
        features['hour_cos'] = np.cos(2 * np.pi * hours / 24.0)
        
        # 分エンコード（60分周期）
        minutes = timestamps.dt.minute
        features['minute_sin'] = np.sin(2 * np.pi * minutes / 60.0)
        features['minute_cos'] = np.cos(2 * np.pi * minutes / 60.0)
        
        # 曜日（0=月曜, 6=日曜）
        features['weekday'] = timestamps.dt.weekday.astype(float)
        
        # セッション判定（UTC時刻ベース）
        hour = timestamps.dt.hour
        for session_name, session_info in self.sessions.items():
            start_hour = int(session_info['start'].split(':')[0])
            end_hour = int(session_info['end'].split(':')[0])
            
            if start_hour < end_hour:
                # 通常の範囲（例: 00:00-06:00）
                features[f'{session_name}_session'] = ((hour >= start_hour) & (hour < end_hour)).astype(float)
            else:
                # 日付をまたぐ範囲（例: 22:00-02:00）
                features[f'{session_name}_session'] = ((hour >= start_hour) | (hour < end_hour)).astype(float)
        
        return pd.DataFrame(features)
