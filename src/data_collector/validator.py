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
    
    def _log(self, level: str, msg: str) -> None:
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
        violation_indices = np.where(diffs <= 0)[0]
        non_monotonic = len(violation_indices)

        if non_monotonic > 0:
            # 最初の違反箇所の詳細を出力
            first_violation_idx = violation_indices[0]
            first_violation_detail = (
                f"index={first_violation_idx}, "
                f"timestamp[{first_violation_idx}]={timestamps[first_violation_idx]}, "
                f"timestamp[{first_violation_idx+1}]={timestamps[first_violation_idx+1]}, "
                f"diff={diffs[first_violation_idx]}"
            )

            self._log('error',
                f"❌ {name}: 単調性違反 {non_monotonic}件\n"
                f"   最初の違反箇所: {first_violation_detail}"
            )
            self.validation_results[f'{name}_monotonic'] = False
            self.validation_results[f'{name}_monotonic_violations'] = {
                'count': non_monotonic,
                'first_violation_index': int(first_violation_idx),
                'first_violation_diff': float(diffs[first_violation_idx])
            }
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
        unique_values, counts = np.unique(timestamps, return_counts=True)
        duplicate_mask = counts > 1
        duplicate_values = unique_values[duplicate_mask]
        duplicate_counts = counts[duplicate_mask]
        total_count = len(timestamps)
        duplicate_count = total_count - len(unique_values)

        if duplicate_count > 0:
            # 最初の重複値の詳細を出力
            first_dup_value = duplicate_values[0]
            first_dup_count = duplicate_counts[0]
            first_dup_indices = np.where(timestamps == first_dup_value)[0]

            self._log('error',
                f"❌ {name}: 重複 {duplicate_count}件（{len(duplicate_values)}個の重複値）\n"
                f"   最初の重複: timestamp={first_dup_value}, "
                f"出現{first_dup_count}回, indices={first_dup_indices[:5].tolist()}"
                f"{'...' if len(first_dup_indices) > 5 else ''}"
            )
            self.validation_results[f'{name}_duplicates'] = {
                'count': duplicate_count,
                'unique_duplicate_values': len(duplicate_values),
                'first_duplicate_value': int(first_dup_value),
                'first_duplicate_count': int(first_dup_count)
            }
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
        negative_indices = np.where(spreads < 0)[0]
        negative_count = len(negative_indices)

        if negative_count > 0:
            # 最初の負のスプレッドの詳細を出力
            first_neg_idx = negative_indices[0]
            first_neg_value = spreads[first_neg_idx]

            self._log('error',
                f"❌ {name}: 負のスプレッド {negative_count}件\n"
                f"   最初の負値: index={first_neg_idx}, spread={first_neg_value}"
            )
            self.validation_results[f'{name}_negative_spread'] = {
                'count': negative_count,
                'first_negative_index': int(first_neg_idx),
                'first_negative_value': float(first_neg_value)
            }
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
            # 最長の連続ゼロ箇所を特定
            max_streak_idx = np.argmax(zero_lengths)
            max_streak_start = zero_starts[max_streak_idx]
            max_streak_end = zero_ends[max_streak_idx]

            self._log('warning',
                f"⚠️  {name}: 連続ゼロ {max_zero_streak}本（許容: {max_streak}本）\n"
                f"   最長箇所: index {max_streak_start}～{max_streak_end-1}"
            )
            self.validation_results[f'{name}_max_zero_streak'] = {
                'max_streak': max_zero_streak,
                'max_streak_start_index': int(max_streak_start),
                'max_streak_end_index': int(max_streak_end - 1),
                'threshold': max_streak
            }
            return False, max_zero_streak
        
        self._log('debug', f"✅ {name}: 連続ゼロチェック合格（最大{max_zero_streak}本）")
        self.validation_results[f'{name}_max_zero_streak'] = max_zero_streak
        return True, max_zero_streak
    
    def get_results(self) -> Dict[str, Any]:
        """検証結果を取得"""
        return self.validation_results
