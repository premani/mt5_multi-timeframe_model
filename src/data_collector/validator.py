"""
データ品質検証モジュール
"""
import numpy as np
from typing import Dict, List, Tuple, Any


class DataValidator:
    """データ品質検証クラス"""
    
    def __init__(self, logger=None):
        """
        初期化
        
        Args:
            logger: ロガーインスタンス
        """
        self.logger = logger
        self.validation_results = {}
    
    def _log(self, level: str, msg: str):
        """ログ出力"""
        if self.logger:
            getattr(self.logger, level)(msg)
    
    def check_monotonic(
        self,
        timestamps: np.ndarray,
        name: str = "data"
    ) -> bool:
        """
        タイムスタンプの単調性をチェック
        
        Args:
            timestamps: タイムスタンプ配列
            name: データ名（ログ用）
        
        Returns:
            単調増加の場合True
        """
        if len(timestamps) == 0:
            self._log('warning', f"⚠️  {name}: データが空です")
            return False
        
        diffs = np.diff(timestamps)
        non_monotonic = np.sum(diffs <= 0)
        
        if non_monotonic > 0:
            self._log('error', f"❌ {name}: 単調性違反 {non_monotonic}件")
            self.validation_results[f'{name}_monotonic'] = False
            return False
        
        self._log('debug', f"✅ {name}: 単調性チェック合格")
        self.validation_results[f'{name}_monotonic'] = True
        return True
    
    def check_duplicates(
        self,
        timestamps: np.ndarray,
        name: str = "data"
    ) -> Tuple[bool, int]:
        """
        重複タイムスタンプをチェック
        
        Args:
            timestamps: タイムスタンプ配列
            name: データ名（ログ用）
        
        Returns:
            (重複なしの場合True, 重複数)
        """
        unique_count = len(np.unique(timestamps))
        total_count = len(timestamps)
        duplicate_count = total_count - unique_count
        
        if duplicate_count > 0:
            self._log('error', f"❌ {name}: 重複 {duplicate_count}件")
            self.validation_results[f'{name}_duplicates'] = duplicate_count
            return False, duplicate_count
        
        self._log('debug', f"✅ {name}: 重複なし")
        self.validation_results[f'{name}_duplicates'] = 0
        return True, 0
    
    def check_gap_ratio(
        self,
        timestamps: np.ndarray,
        expected_interval: int,
        max_ratio: float = 0.005,
        name: str = "data"
    ) -> Tuple[bool, float, int]:
        """
        欠損率をチェック
        
        Args:
            timestamps: タイムスタンプ配列
            expected_interval: 期待される間隔（秒）
            max_ratio: 許容欠損率
            name: データ名（ログ用）
        
        Returns:
            (許容範囲内の場合True, 欠損率, 欠損数)
        """
        if len(timestamps) < 2:
            return True, 0.0, 0
        
        # 期待データ数を計算
        time_range = timestamps[-1] - timestamps[0]
        expected_count = int(time_range / expected_interval) + 1
        actual_count = len(timestamps)
        missing_count = max(0, expected_count - actual_count)
        
        gap_ratio = missing_count / expected_count if expected_count > 0 else 0.0
        
        if gap_ratio > max_ratio:
            self._log('warning', 
                f"⚠️  {name}: 欠損率 {gap_ratio*100:.2f}% "
                f"({missing_count}/{expected_count}件)"
            )
            self.validation_results[f'{name}_gap_ratio'] = gap_ratio
            return False, gap_ratio, missing_count
        
        self._log('debug', 
            f"✅ {name}: 欠損率 {gap_ratio*100:.2f}% "
            f"({missing_count}/{expected_count}件)"
        )
        self.validation_results[f'{name}_gap_ratio'] = gap_ratio
        return True, gap_ratio, missing_count
    
    def check_spread_validity(
        self,
        spreads: np.ndarray,
        name: str = "data"
    ) -> Tuple[bool, int]:
        """
        スプレッドの妥当性をチェック
        
        Args:
            spreads: スプレッド配列
            name: データ名（ログ用）
        
        Returns:
            (全て正の場合True, 負の値の数)
        """
        negative_count = np.sum(spreads < 0)
        
        if negative_count > 0:
            self._log('error', f"❌ {name}: 負のスプレッド {negative_count}件")
            self.validation_results[f'{name}_negative_spread'] = negative_count
            return False, negative_count
        
        self._log('debug', f"✅ {name}: スプレッド妥当性チェック合格")
        self.validation_results[f'{name}_negative_spread'] = 0
        return True, 0
    
    def check_zero_streak(
        self,
        values: np.ndarray,
        max_streak: int = 120,
        name: str = "data"
    ) -> Tuple[bool, int]:
        """
        連続ゼロをチェック
        
        Args:
            values: 値の配列
            max_streak: 許容最大連続数
            name: データ名（ログ用）
        
        Returns:
            (許容範囲内の場合True, 最大連続数)
        """
        if len(values) == 0:
            return True, 0
        
        # 連続ゼロの最大長を計算
        is_zero = (values == 0)
        zero_groups = np.diff(np.concatenate(([0], is_zero.astype(int), [0])))
        zero_starts = np.where(zero_groups == 1)[0]
        zero_ends = np.where(zero_groups == -1)[0]
        
        if len(zero_starts) == 0:
            max_zero_streak = 0
        else:
            zero_lengths = zero_ends - zero_starts
            max_zero_streak = int(np.max(zero_lengths))
        
        if max_zero_streak > max_streak:
            self._log('warning', 
                f"⚠️  {name}: 連続ゼロ {max_zero_streak}本（許容: {max_streak}本）"
            )
            self.validation_results[f'{name}_max_zero_streak'] = max_zero_streak
            return False, max_zero_streak
        
        self._log('debug', f"✅ {name}: 連続ゼロチェック合格（最大{max_zero_streak}本）")
        self.validation_results[f'{name}_max_zero_streak'] = max_zero_streak
        return True, max_zero_streak
    
    def get_results(self) -> Dict[str, Any]:
        """検証結果を取得"""
        return self.validation_results
