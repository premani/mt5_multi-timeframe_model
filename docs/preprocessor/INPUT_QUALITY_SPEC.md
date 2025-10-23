# 入力品質管理仕様 (INPUT_QUALITY_SPEC)

**バージョン**: 1.0
**更新日**: 2025-10-22
**責任者**: core-team
**カテゴリ**: 前処理サブ仕様

---

## 📋 目的

前処理段階での入力データ品質を管理し、欠損・ギャップ・品質劣化に対する適切な処理を定義する。

**対象項目**:
- 入力品質劣化時の信頼度調整
- 欠損判定の列分離
- 長期欠損後のシーケンス分断
- 連続ギャップ除外基準

---

## 項目105対応: 入力品質劣化設計

**目的**: 高頻度欠落バー混入時、揮発性指標（RSI, ATR等）の誤差増大 → 誤シグナル発生

**解決策**: 入力品質スコアで信頼度を調整

```python
class InputQualityScorer:
    """入力品質スコアによる信頼度調整"""
    
    def __init__(self, config: dict):
        self.max_gap_bars = config.get("max_gap_bars", 5)  # 許容欠落バー数
        self.gap_penalty = config.get("gap_penalty", 0.2)  # 1バー欠落で20%減
        self.min_quality_score = config.get("min_quality_score", 0.3)
    
    def calculate_quality_score(self, sequence_timestamps: np.ndarray,
                                expected_interval_seconds: int) -> float:
        """
        入力シーケンスの品質スコア計算
        
        Args:
            sequence_timestamps: シーケンス内のタイムスタンプ配列
            expected_interval_seconds: 期待間隔（M1=60, M5=300, etc.）
        
        Returns:
            quality_score: 0.0（最悪）～ 1.0（完璧）
        """
        # 1. 時間間隔差分計算
        intervals = np.diff(sequence_timestamps)
        expected_interval = expected_interval_seconds
        
        # 2. 欠落バー検出
        gap_bars = (intervals - expected_interval) // expected_interval
        gap_bars = np.clip(gap_bars, 0, None)  # 負値は0に
        
        total_gaps = np.sum(gap_bars)
        max_single_gap = np.max(gap_bars) if len(gap_bars) > 0 else 0
        
        # 3. 品質スコア計算
        quality_score = 1.0
        
        # 総欠落ペナルティ
        quality_score -= total_gaps * self.gap_penalty
        
        # 連続欠落ペナルティ（より重い）
        if max_single_gap > self.max_gap_bars:
            quality_score -= (max_single_gap - self.max_gap_bars) * self.gap_penalty * 2
        
        # 下限クリップ
        quality_score = max(quality_score, self.min_quality_score)
        
        return quality_score
    
    def apply_confidence_scaling(self, predictions: dict, 
                                 quality_score: float) -> dict:
        """
        品質スコアに応じて予測信頼度を調整
        
        Args:
            predictions: {
                "direction_probs": [UP, DOWN, NEUTRAL],
                "magnitude": float,
                "confidence": float
            }
            quality_score: 入力品質スコア
        
        Returns:
            adjusted_predictions: 信頼度調整後の予測
        """
        adjusted = predictions.copy()
        
        # 1. 信頼度スケーリング
        adjusted["confidence"] *= quality_score
        
        # 2. NEUTRAL確率の増加（低品質時は慎重）
        if quality_score < 0.7:
            # NEUTRAL比率を増加（UP/DOWNを抑制）
            neutral_boost = (1.0 - quality_score) * 0.3
            
            direction_probs = adjusted["direction_probs"]
            direction_probs[2] += neutral_boost  # NEUTRAL index=2
            
            # 正規化
            direction_probs = direction_probs / direction_probs.sum()
            adjusted["direction_probs"] = direction_probs
        
        # 3. マグニチュード縮小（低品質時は保守的）
        adjusted["magnitude"] *= quality_score
        
        logger.debug(
            f"信頼度調整: quality={quality_score:.2f}, "
            f"confidence={predictions['confidence']:.2f} → {adjusted['confidence']:.2f}"
        )
        
        return adjusted
    
    def log_quality_statistics(self, quality_scores: list):
        """品質スコア統計ログ出力"""
        stats = {
            "mean": np.mean(quality_scores),
            "std": np.std(quality_scores),
            "min": np.min(quality_scores),
            "p10": np.percentile(quality_scores, 10),
            "median": np.median(quality_scores),
        }
        
        logger.info(f"入力品質統計: {stats}")
        
        # 警告閾値
        if stats["p10"] < 0.5:  # 下位10%が0.5未満
            logger.warning(
                f"入力品質低下: p10={stats['p10']:.2f}, "
                f"データ収集確認推奨"
            )


# 使用例: 推論時の品質チェック
quality_scorer = InputQualityScorer({
    "max_gap_bars": 5,
    "gap_penalty": 0.2,
    "min_quality_score": 0.3
})

# シーケンスから品質スコア計算
sequence_timestamps = preprocessed_data["timestamps"][-480:]  # M1: 直近480本
quality_score = quality_scorer.calculate_quality_score(
    sequence_timestamps,
    expected_interval_seconds=60  # M1
)

# 予測実行
predictions = model.predict(sequence_data)

# 品質スコアで信頼度調整
adjusted_predictions = quality_scorer.apply_confidence_scaling(
    predictions,
    quality_score
)

# 調整後の予測を使用
if adjusted_predictions["confidence"] < 0.5:
    logger.info("信頼度不足、エントリー見送り")
else:
    execute_signal(adjusted_predictions)
```

**入力品質スコア仕様**:
- **max_gap_bars**: 5本（許容欠落バー数）
- **gap_penalty**: 0.2（1バー欠落で20%減点）
- **min_quality_score**: 0.3（最低スコア）
- **信頼度スケーリング**: confidence × quality_score
- **NEUTRAL boost**: quality < 0.7 時に NEUTRAL 確率 +30%
- **成功指標**: 欠落期 NetLoss 減少 >= 20%

**効果**:
- 欠落バー混入時の誤シグナル抑制
- 低品質入力の自動検出
- 推論信頼度の透明性向上

---


---

## 項目44対応: 欠損判定の列分離

**目的**: `df.isna().any(axis=1)` は一部列欠損で行全体を欠損扱い → 過剰なforward fill発生

**解決策**: primary/auxiliary列を分離し、primary列欠損のみfill対象

```python
class MissingDataClassifier:
    """欠損判定の列分離"""
    
    def __init__(self, config: dict):
        # 主要列: OHLCV + 主要テクニカル指標
        self.primary_columns = config.get("primary_columns", [
            "open", "high", "low", "close", "volume",
            "rsi_14", "macd_line", "atr_14"
        ])
        
        # 補助列: その他の派生特徴量
        self.auxiliary_columns = None  # 初期化時に自動判定
        
        self.primary_missing_threshold = config.get("primary_missing_threshold", 0.05)
        self.auxiliary_missing_threshold = config.get("auxiliary_missing_threshold", 0.20)
    
    def classify_missing(
        self,
        df: pd.DataFrame
    ) -> Dict[str, Any]:
        """
        欠損を主要/補助列で分類判定
        
        Args:
            df: 特徴量DataFrame
        
        Returns:
            {
                "primary_missing_mask": np.ndarray,  # 主要列欠損行
                "auxiliary_missing_mask": np.ndarray,  # 補助列のみ欠損行
                "complete_mask": np.ndarray,  # 完全データ行
                "statistics": dict
            }
        """
        # 補助列を自動判定（主要列以外）
        if self.auxiliary_columns is None:
            self.auxiliary_columns = [
                col for col in df.columns 
                if col not in self.primary_columns
            ]
        
        # 主要列欠損判定
        primary_df = df[self.primary_columns]
        primary_missing_mask = primary_df.isna().any(axis=1).values
        
        # 補助列欠損判定
        if len(self.auxiliary_columns) > 0:
            auxiliary_df = df[self.auxiliary_columns]
            auxiliary_missing_mask = auxiliary_df.isna().any(axis=1).values
        else:
            auxiliary_missing_mask = np.zeros(len(df), dtype=bool)
        
        # 完全データ（両方欠損なし）
        complete_mask = ~(primary_missing_mask | auxiliary_missing_mask)
        
        # 補助列のみ欠損（主要列は完全）
        auxiliary_only_missing = auxiliary_missing_mask & ~primary_missing_mask
        
        # 統計計算
        total_rows = len(df)
        stats = {
            "total_rows": total_rows,
            "primary_missing_count": int(primary_missing_mask.sum()),
            "primary_missing_rate": float(primary_missing_mask.mean()),
            "auxiliary_only_missing_count": int(auxiliary_only_missing.sum()),
            "auxiliary_only_missing_rate": float(auxiliary_only_missing.mean()),
            "complete_count": int(complete_mask.sum()),
            "complete_rate": float(complete_mask.mean())
        }
        
        return {
            "primary_missing_mask": primary_missing_mask,
            "auxiliary_missing_mask": auxiliary_missing_mask,
            "auxiliary_only_missing": auxiliary_only_missing,
            "complete_mask": complete_mask,
            "statistics": stats
        }
    
    def apply_selective_fill(
        self,
        df: pd.DataFrame
    ) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        """
        選択的forward fill適用
        
        - 主要列欠損: forward fill適用
        - 補助列のみ欠損: 欠損のまま（学習時マスク対象）
        
        Args:
            df: 特徴量DataFrame
        
        Returns:
            (filled_df, fill_info)
        """
        missing_info = self.classify_missing(df)
        
        df_filled = df.copy()
        
        # 主要列のみforward fill
        primary_mask = missing_info["primary_missing_mask"]
        if primary_mask.sum() > 0:
            df_filled[self.primary_columns] = df_filled[self.primary_columns].fillna(method='ffill')
            logger.info(
                f"主要列forward fill適用: {primary_mask.sum()}行 "
                f"({missing_info['statistics']['primary_missing_rate']:.2%})"
            )
        
        # 補助列は欠損のまま保持
        aux_only_mask = missing_info["auxiliary_only_missing"]
        if aux_only_mask.sum() > 0:
            logger.debug(
                f"補助列欠損保持（fill不要）: {aux_only_mask.sum()}行 "
                f"({missing_info['statistics']['auxiliary_only_missing_rate']:.2%})"
            )
        
        fill_info = {
            "filled_rows": int(primary_mask.sum()),
            "unfilled_auxiliary_rows": int(aux_only_mask.sum()),
            "statistics": missing_info["statistics"]
        }
        
        return df_filled, fill_info


# 使用例: 前処理時
classifier = MissingDataClassifier({
    "primary_columns": ["open", "high", "low", "close", "volume", "rsi_14", "macd_line"],
    "primary_missing_threshold": 0.05,
    "auxiliary_missing_threshold": 0.20
})

# 欠損分類
missing_info = classifier.classify_missing(features_df)
logger.info(f"欠損統計: {missing_info['statistics']}")

# 選択的fill
filled_df, fill_info = classifier.apply_selective_fill(features_df)

# 閾値チェック
if missing_info["statistics"]["primary_missing_rate"] > 0.05:
    logger.warning(
        f"主要列欠損率過大: {missing_info['statistics']['primary_missing_rate']:.2%} > 5%"
    )
```

**KPI（項目44）**:
- 過剰fill削減率: ≥50%（補助列欠損のfill回避）
- 主要列欠損率: <5%
- 学習バイアス軽減: 補助列欠損の平滑化なし

---


---

## 項目45対応: 長期欠損後のシーケンス分断

**目的**: 大きな時間ギャップ後に直続させると「疑似高速変化」を誤学習

**解決策**: `gap_duration > τ` でシーケンス分断 + 先頭warmupバーマスク

```python
class LongGapSequenceSplitter:
    """長期欠損後のシーケンス分断"""
    
    def __init__(self, config: dict):
        self.max_gap_duration_minutes = config.get("max_gap_duration_minutes", {
            "M1": 5,    # M1で5分以上空いたら分断
            "M5": 15,   # M5で15分以上
            "M15": 45,
            "H1": 120,
            "H4": 480
        })
        
        self.warmup_bars_after_gap = config.get("warmup_bars_after_gap", 20)
    
    def detect_long_gaps(
        self,
        timestamps: np.ndarray,
        tf_name: str
    ) -> List[int]:
        """
        長期ギャップ検出
        
        Args:
            timestamps: タイムスタンプ配列（Unix秒）
            tf_name: タイムフレーム名
        
        Returns:
            gap_indices: ギャップ直後のインデックスリスト
        """
        if len(timestamps) < 2:
            return []
        
        # 時間差分（秒）
        time_diffs = np.diff(timestamps)
        
        # 期待間隔（秒）
        expected_interval = {
            "M1": 60,
            "M5": 300,
            "M15": 900,
            "H1": 3600,
            "H4": 14400
        }[tf_name]
        
        # 閾値（分）→秒
        max_gap_seconds = self.max_gap_duration_minutes[tf_name] * 60
        
        # 長期ギャップ検出
        long_gap_mask = time_diffs > max_gap_seconds
        gap_indices = np.where(long_gap_mask)[0] + 1  # ギャップ直後のインデックス
        
        return gap_indices.tolist()
    
    def split_sequences_at_gaps(
        self,
        data: np.ndarray,
        timestamps: np.ndarray,
        tf_name: str,
        window_size: int
    ) -> List[Dict[str, Any]]:
        """
        ギャップでシーケンスを分断
        
        Args:
            data: 特徴量配列 (N, F)
            timestamps: タイムスタンプ配列 (N,)
            tf_name: タイムフレーム名
            window_size: シーケンス長
        
        Returns:
            sequences: 分断されたシーケンスリスト
        """
        gap_indices = self.detect_long_gaps(timestamps, tf_name)
        
        if len(gap_indices) == 0:
            # ギャップなし → 通常シーケンス化
            return self._create_normal_sequences(data, timestamps, window_size)
        
        # ギャップで分断
        segments = []
        start_idx = 0
        
        for gap_idx in gap_indices:
            # ギャップ前のセグメント
            if gap_idx - start_idx >= window_size:
                segment = {
                    "data": data[start_idx:gap_idx],
                    "timestamps": timestamps[start_idx:gap_idx],
                    "start_idx": start_idx,
                    "end_idx": gap_idx,
                    "has_gap_before": False
                }
                segments.append(segment)
            
            # ギャップ後は先頭warmupバーをマスク
            start_idx = gap_idx
        
        # 最後のセグメント
        if len(data) - start_idx >= window_size:
            segment = {
                "data": data[start_idx:],
                "timestamps": timestamps[start_idx:],
                "start_idx": start_idx,
                "end_idx": len(data),
                "has_gap_before": True if start_idx > 0 else False
            }
            segments.append(segment)
        
        # 各セグメントからシーケンス生成
        all_sequences = []
        for seg in segments:
            seqs = self._create_sequences_from_segment(
                seg, window_size
            )
            all_sequences.extend(seqs)
        
        logger.info(
            f"{tf_name}: 長期ギャップ {len(gap_indices)}箇所検出、"
            f"{len(segments)}セグメントに分断、"
            f"{len(all_sequences)}シーケンス生成"
        )
        
        return all_sequences
    
    def _create_sequences_from_segment(
        self,
        segment: Dict[str, Any],
        window_size: int
    ) -> List[Dict[str, Any]]:
        """セグメントからシーケンス生成"""
        data = segment["data"]
        timestamps = segment["timestamps"]
        N = len(data)
        
        sequences = []
        
        for i in range(N - window_size):
            seq_data = data[i:i+window_size]
            seq_timestamps = timestamps[i:i+window_size]
            
            # warmupマスク生成
            warmup_mask = np.ones(window_size, dtype=float)
            
            if segment["has_gap_before"] and i < self.warmup_bars_after_gap:
                # ギャップ直後の先頭warmup期間はマスク
                warmup_bars_in_window = min(
                    self.warmup_bars_after_gap - i,
                    window_size
                )
                warmup_mask[:warmup_bars_in_window] = 0.0
            
            sequences.append({
                "data": seq_data,
                "timestamps": seq_timestamps,
                "mask": warmup_mask,
                "segment_id": segment["start_idx"]
            })
        
        return sequences


# 使用例: シーケンス生成時
splitter = LongGapSequenceSplitter({
    "max_gap_duration_minutes": {"M1": 5, "M5": 15, "H1": 120},
    "warmup_bars_after_gap": 20
})

# M5データのシーケンス生成
sequences = splitter.split_sequences_at_gaps(
    data=features_m5.values,
    timestamps=timestamps_m5,
    tf_name="M5",
    window_size=288
)

# warmupマスクを学習重みに反映
for seq in sequences:
    loss_weight = seq["mask"]  # 0.0=warmup除外, 1.0=通常
```

**KPI（項目45）**:
- ギャップ分断率: 記録（典型的には<2%）
- warmup期間: ギャップ後20バー
- 疑似高速変化誤学習削減: 定性評価

---


---

## 項目106対応: 連続ギャップ除外基準

**目的**: 多数の連続ギャップは異常分布を注入し学習を歪める

**解決策**: `consecutive_gaps > K` でシーケンス除外

```python
class ConsecutiveGapFilter:
    """連続ギャップによるシーケンス除外"""
    
    def __init__(self, config: dict):
        self.max_consecutive_gaps = config.get("max_consecutive_gaps", 3)
        self.gap_detection_window = config.get("gap_detection_window", 10)
    
    def detect_consecutive_gaps(
        self,
        timestamps: np.ndarray,
        tf_name: str
    ) -> np.ndarray:
        """
        連続ギャップ検出
        
        Args:
            timestamps: タイムスタンプ配列
            tf_name: タイムフレーム名
        
        Returns:
            consecutive_gap_mask: True=連続ギャップ多数、False=正常
        """
        if len(timestamps) < 2:
            return np.zeros(len(timestamps), dtype=bool)
        
        # 期待間隔（秒）
        expected_interval = {
            "M1": 60,
            "M5": 300,
            "M15": 900,
            "H1": 3600,
            "H4": 14400
        }[tf_name]
        
        # 時間差分
        time_diffs = np.diff(timestamps)
        
        # ギャップ判定（期待間隔の1.5倍以上）
        is_gap = time_diffs > (expected_interval * 1.5)
        
        # スライディングウィンドウで連続ギャップカウント
        N = len(timestamps)
        consecutive_gap_mask = np.zeros(N, dtype=bool)
        
        for i in range(N - self.gap_detection_window):
            window_gaps = is_gap[i:i+self.gap_detection_window]
            gap_count = window_gaps.sum()
            
            if gap_count > self.max_consecutive_gaps:
                # ウィンドウ内全てをマスク
                consecutive_gap_mask[i:i+self.gap_detection_window+1] = True
        
        return consecutive_gap_mask
    
    def filter_sequences_by_gap_density(
        self,
        sequences: List[Dict[str, Any]],
        tf_name: str
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        連続ギャップ密度でシーケンス除外
        
        Args:
            sequences: シーケンスリスト（各要素に"timestamps"含む）
            tf_name: タイムフレーム名
        
        Returns:
            (filtered_sequences, filter_stats)
        """
        filtered_sequences = []
        discarded_count = 0
        
        for seq in sequences:
            timestamps = seq["timestamps"]
            
            # 連続ギャップ検出
            gap_mask = self.detect_consecutive_gaps(timestamps, tf_name)
            
            # ギャップ比率計算
            gap_ratio = gap_mask.sum() / len(gap_mask)
            
            if gap_ratio > 0.3:  # 30%以上がギャップ影響
                # 除外
                discarded_count += 1
                logger.debug(
                    f"シーケンス除外: ギャップ比率={gap_ratio:.2%} > 30%"
                )
            else:
                # 保持（ギャップマスクを付与）
                seq["gap_mask"] = gap_mask
                seq["gap_ratio"] = gap_ratio
                filtered_sequences.append(seq)
        
        filter_stats = {
            "total_sequences": len(sequences),
            "filtered_sequences": len(filtered_sequences),
            "discarded_sequences": discarded_count,
            "discard_rate": discarded_count / len(sequences) if len(sequences) > 0 else 0
        }
        
        logger.info(
            f"{tf_name} シーケンスフィルタ: "
            f"{len(filtered_sequences)}/{len(sequences)}保持、"
            f"除外率={filter_stats['discard_rate']:.2%}"
        )
        
        return filtered_sequences, filter_stats


# 使用例: シーケンス生成後
gap_filter = ConsecutiveGapFilter({
    "max_consecutive_gaps": 3,
    "gap_detection_window": 10
})

# シーケンスから連続ギャップ多数のものを除外
filtered_sequences, stats = gap_filter.filter_sequences_by_gap_density(
    sequences=all_sequences,
    tf_name="M5"
)

# 除外率チェック
if stats["discard_rate"] > 0.05:
    logger.warning(
        f"連続ギャップによる除外率過大: {stats['discard_rate']:.2%} > 5%。"
        f"データ収集期間またはmax_consecutive_gaps閾値の見直し推奨"
    )
```

**KPI（項目106）**:
- シーケンス除外率: <5%
- ギャップ密度閾値: 30%
- 学習データ品質向上: 異常分布注入率削減

---



---

## 🔗 関連仕様

- [PREPROCESSOR_SPEC.md](../PREPROCESSOR_SPEC.md) - 前処理メイン仕様
- [DATA_COLLECTOR_SPEC.md](../DATA_COLLECTOR_SPEC.md) - データ収集仕様

---

**作成日**: 2025-10-22
