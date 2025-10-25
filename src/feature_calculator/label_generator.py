"""
ラベル生成モジュール

Phase 0: 基本実装
- Direction: 価格変動ベースの3クラス分類（UP/DOWN/NEUTRAL）
- Magnitude: 実測価格幅（pips単位）
"""

import numpy as np
import h5py
from typing import Dict, Tuple
from pathlib import Path


class LabelGenerator:
    """
    マルチタイムフレームデータからラベルを生成
    
    Phase 0実装:
    - Direction: ±NEUTRAL閾値に基づく3クラス分類
    - Magnitude: 実測価格幅（pips）
    """
    
    def __init__(
        self,
        k_spread: float = 1.0,
        k_atr: float = 0.3,
        spread_default: float = 1.2,
        atr_period: int = 14,
        pip_value: float = 0.01  # USDJPY: 0.01, EURUSD: 0.0001
    ):
        """
        Args:
            k_spread: スプレッド倍率（コスト考慮）
            k_atr: ATR倍率（ノイズ除外）
            spread_default: デフォルトスプレッド（pips）
            atr_period: ATR計算期間
            pip_value: 1 pipの値（通貨ペア依存）
        """
        self.k_spread = k_spread
        self.k_atr = k_atr
        self.spread_default = spread_default
        self.atr_period = atr_period
        self.pip_value = pip_value
    
    def generate_labels(
        self,
        preprocessor_path: Path,
        collector_path: Path,
        prediction_horizon: int = 36,
        n_sequences: int = None
    ) -> Dict[str, np.ndarray]:
        """
        前処理データと生データからラベルを生成
        
        Args:
            preprocessor_path: 前処理データパス（preprocessor.h5）、Noneの場合はn_sequencesを使用
            collector_path: 生データパス（data_collector.h5）
            prediction_horizon: 予測時間（シーケンス数）
            n_sequences: シーケンス数（preprocessor_path=Noneの場合に必須）
        
        Returns:
            {
                'direction': (N,) int [0=DOWN, 1=NEUTRAL, 2=UP],
                'magnitude': (N,) float [pips]
            }
        """
        # 1. シーケンス数を取得
        if preprocessor_path is not None:
            with h5py.File(preprocessor_path, 'r') as h5_file:
                m5_sequences = h5_file['sequences/M5'][:]  # (N, seq_len, features)
                N = len(m5_sequences)
        else:
            if n_sequences is None:
                raise ValueError("preprocessor_path=Noneの場合、n_sequencesを指定してください")
            N = n_sequences
        
        # 2. 生データから価格情報を取得
        with h5py.File(collector_path, 'r') as h5_file:
            # M5基準でデータ取得
            m5_data = h5_file['M5/data'][:]  # (total_rows, columns)
            
            # 列名はメタデータまたは標準順序から取得
            # data_collector.h5の列順序: time, open, high, low, close, tick_volume, spread, real_volume
            columns = ['time', 'open', 'high', 'low', 'close', 'tick_volume', 'spread', 'real_volume']
            
            # 必要な列のインデックス
            close_idx = columns.index('close')
            high_idx = columns.index('high')
            low_idx = columns.index('low')
            
            # 価格データ抽出（最新N+prediction_horizon行）
            total_rows = len(m5_data)
            required_rows = N + prediction_horizon
            
            if total_rows < required_rows:
                raise ValueError(f"データ不足: 必要{required_rows}行、実際{total_rows}行")
            
            # 最新データを使用
            prices = m5_data[-required_rows:]
            close_prices = prices[:, close_idx]
            high_prices = prices[:, high_idx]
            low_prices = prices[:, low_idx]
        
        # 3. ラベル生成
        valid_samples = N - prediction_horizon
        
        # 各サンプルの現在価格と未来価格
        current_close = close_prices[:N]
        future_close = np.zeros(N)
        
        for i in range(valid_samples):
            future_close[i] = close_prices[i + prediction_horizon]
        
        # ATR計算（簡易版: 過去14期間のTrue Range平均）
        atr = self._calculate_atr_simple(high_prices, low_prices, close_prices, N)
        
        # NEUTRAL閾値計算
        theta_neutral = np.maximum(
            self.spread_default * self.k_spread,
            atr * self.k_atr
        )
        
        # 価格変動（pips）
        price_change = (future_close - current_close) / self.pip_value
        
        # Directionラベル生成
        direction = np.ones(N, dtype=np.int64) * 1  # デフォルトNEUTRAL
        direction[price_change > theta_neutral] = 2  # UP
        direction[price_change < -theta_neutral] = 0  # DOWN
        
        # Magnitudeラベル生成（絶対値）
        magnitude = np.abs(price_change)
        
        # 未来データなしのサンプルはマスク用にNaNを設定
        direction[valid_samples:] = -1  # 無効マーカー
        magnitude[valid_samples:] = np.nan
        
        return {
            'direction': direction,
            'magnitude': magnitude,
            'valid_mask': np.arange(N) < valid_samples,
            'theta_neutral': theta_neutral
        }
    
    def _calculate_atr_simple(
        self,
        high_prices: np.ndarray,
        low_prices: np.ndarray,
        close_prices: np.ndarray,
        N: int
    ) -> np.ndarray:
        """
        ATR（Average True Range）簡易計算
        
        Args:
            high_prices: 全期間のHigh価格
            low_prices: 全期間のLow価格
            close_prices: 全期間のClose価格
            N: 計算するサンプル数
        
        Returns:
            atr: (N,) ATR値（pips）
        """
        atr = np.zeros(N)
        
        for i in range(N):
            # 過去atr_period期間のTrue Rangeを計算
            start_idx = max(0, i - self.atr_period + 1)
            end_idx = i + 1
            
            high = high_prices[start_idx:end_idx]
            low = low_prices[start_idx:end_idx]
            close_prev = close_prices[start_idx-1:end_idx-1] if start_idx > 0 else close_prices[start_idx:end_idx]
            
            # True Range = max(H-L, |H-C_prev|, |L-C_prev|)
            tr1 = high - low
            if len(close_prev) == len(high):
                tr2 = np.abs(high - close_prev)
                tr3 = np.abs(low - close_prev)
                true_range = np.maximum(tr1, np.maximum(tr2, tr3))
            else:
                true_range = tr1
            
            # ATR = 平均True Range
            atr[i] = np.mean(true_range) / self.pip_value
        
        return atr
    
    def validate_labels(
        self,
        labels: Dict[str, np.ndarray],
        logger
    ) -> None:
        """
        ラベル品質検証
        
        Args:
            labels: generate_labels()の出力
            logger: ロガーインスタンス
        """
        direction = labels['direction']
        magnitude = labels['magnitude']
        valid_mask = labels['valid_mask']
        
        # 有効サンプルのみで統計
        valid_direction = direction[valid_mask]
        valid_magnitude = magnitude[valid_mask]
        
        # Direction分布
        n_up = np.sum(valid_direction == 2)
        n_neutral = np.sum(valid_direction == 1)
        n_down = np.sum(valid_direction == 0)
        total = len(valid_direction)
        
        logger.info("📊 ラベル統計:")
        logger.info(f"   Direction分布:")
        logger.info(f"      UP: {n_up} ({n_up/total*100:.1f}%)")
        logger.info(f"      NEUTRAL: {n_neutral} ({n_neutral/total*100:.1f}%)")
        logger.info(f"      DOWN: {n_down} ({n_down/total*100:.1f}%)")
        
        # Magnitude統計
        mag_mean = np.mean(valid_magnitude)
        mag_std = np.std(valid_magnitude)
        mag_median = np.median(valid_magnitude)
        mag_max = np.max(valid_magnitude)
        
        logger.info(f"   Magnitude統計（pips）:")
        logger.info(f"      平均: {mag_mean:.2f}")
        logger.info(f"      標準偏差: {mag_std:.2f}")
        logger.info(f"      中央値: {mag_median:.2f}")
        logger.info(f"      最大: {mag_max:.2f}")
        
        # バランスチェック
        if n_neutral / total > 0.7:
            logger.warning("⚠️  NEUTRAL比率が高い（閾値調整推奨）")
        
        class_imbalance = max(n_up, n_neutral, n_down) / min(n_up, n_neutral, n_down)
        if class_imbalance > 3.0:
            logger.warning(f"⚠️  クラス不均衡検出（比率: {class_imbalance:.1f}:1）")
