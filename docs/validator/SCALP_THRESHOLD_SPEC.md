# SCALP_THRESHOLD_SPEC.md

**バージョン**: 1.0  
**更新日**: 2025-10-22  
**責任者**: core-team

---

## 📋 目的

スキャルプモード閾値（TP/SL）の最適化と再調整周期を定義する。

---

## 閾値再最適化

### TP/SL再最適化周期

**目的**: 固定TP/SL閾値は市場変化で陳腐化

**解決策**: 定期再最適化トリガ

```python
class TPSLReoptimizer:
    """TP/SL再最適化"""
    
    def __init__(self, config: dict):
        self.reoptimize_interval_days = config.get("reoptimize_interval_days", 7)
        self.performance_threshold = config.get("performance_threshold", 0.9)
        
        self.last_optimize_time = None
        self.baseline_sharpe = None
    
    def should_reoptimize(
        self,
        current_sharpe: float,
        days_since_last: int
    ) -> bool:
        """
        再最適化判定
        
        Returns:
            True: 再最適化必要
        """
        # 条件1: 定期周期
        if days_since_last >= self.reoptimize_interval_days:
            logger.info(f"定期再最適化トリガ: {days_since_last}日経過")
            return True
        
        # 条件2: パフォーマンス劣化
        if self.baseline_sharpe and current_sharpe < self.baseline_sharpe * self.performance_threshold:
            logger.warning(f"パフォーマンス劣化検出: Sharpe={current_sharpe:.2f} < {self.baseline_sharpe:.2f}")
            return True
        
        return False
    
    def optimize_thresholds(
        self,
        backtest_data: pd.DataFrame
    ) -> Dict[str, float]:
        """
        Grid Search最適化
        
        Returns:
            {"tp_pips": float, "sl_pips": float, "best_sharpe": float}
        """
        tp_candidates = [2.0, 3.0, 4.0, 5.0]
        sl_candidates = [1.5, 2.0, 2.5, 3.0]
        
        best_sharpe = -np.inf
        best_params = {}
        
        for tp in tp_candidates:
            for sl in sl_candidates:
                sharpe = simulate_backtest(backtest_data, tp, sl)
                
                if sharpe > best_sharpe:
                    best_sharpe = sharpe
                    best_params = {"tp_pips": tp, "sl_pips": sl}
        
        logger.info(f"最適閾値: TP={best_params['tp_pips']}, SL={best_params['sl_pips']}, Sharpe={best_sharpe:.2f}")
        
        self.baseline_sharpe = best_sharpe
        self.last_optimize_time = time.time()
        
        return {**best_params, "best_sharpe": best_sharpe}


# 使用例
reoptimizer = TPSLReoptimizer({
    "reoptimize_interval_days": 7,
    "performance_threshold": 0.9
})

# 運用監視ループ
while True:
    current_sharpe = calculate_rolling_sharpe(last_7days_trades)
    days_since = (time.time() - reoptimizer.last_optimize_time) / 86400
    
    if reoptimizer.should_reoptimize(current_sharpe, days_since):
        # 再最適化実行
        backtest_data = load_recent_data(days=30)
        new_thresholds = reoptimizer.optimize_thresholds(backtest_data)
        
        # 閾値更新
        update_config("tp_pips", new_thresholds["tp_pips"])
        update_config("sl_pips", new_thresholds["sl_pips"])
```

**再最適化トリガ**:
- 定期: 7日毎
- 性能劣化: Sharpe < baseline × 0.9

**KPI（項目40）**: 再最適化による Sharpe改善≥+10%、最適化頻度週1回
