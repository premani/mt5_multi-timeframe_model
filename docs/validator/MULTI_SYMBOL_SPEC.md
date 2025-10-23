# MULTI_SYMBOL_SPEC.md

**バージョン**: 1.0  
**更新日**: 2025-10-22  
**責任者**: core-team

---

## 📋 目的

複数シンボル同時運用時の資源優先度管理を定義する。

---

## マルチシンボル資源管理

### 複数シンボル資源優先度

**目的**: GPU/CPU資源制約下で全シンボル同時推論は不可

**解決策**: 動的優先度割当

```python
class MultiSymbolResourceManager:
    """マルチシンボル資源管理"""
    
    def __init__(self, config: dict):
        self.max_concurrent_symbols = config.get("max_concurrent_symbols", 3)
        self.priority_refresh_interval = config.get("priority_refresh_interval", 300)
        
        self.symbol_priorities = {}
        self.last_refresh_time = 0
    
    def calculate_priority(
        self,
        symbol: str,
        recent_volatility: float,
        recent_win_rate: float,
        signal_strength: float
    ) -> float:
        """
        シンボル優先度計算
        
        Returns:
            priority_score: 高いほど優先
        """
        # 重み付きスコア
        score = (
            0.4 * recent_volatility +      # ボラティリティ高=機会大
            0.3 * recent_win_rate +        # 勝率高=優位性
            0.3 * signal_strength          # シグナル強度
        )
        
        return score
    
    def get_active_symbols(
        self,
        all_symbols: List[str],
        market_data: Dict[str, Dict]
    ) -> List[str]:
        """
        アクティブシンボル選定
        
        Returns:
            active_symbols: 推論対象シンボルリスト
        """
        # 優先度再計算（定期）
        if time.time() - self.last_refresh_time > self.priority_refresh_interval:
            for symbol in all_symbols:
                data = market_data[symbol]
                priority = self.calculate_priority(
                    symbol,
                    data["volatility"],
                    data["win_rate"],
                    data["signal_strength"]
                )
                self.symbol_priorities[symbol] = priority
            
            self.last_refresh_time = time.time()
            logger.info(f"優先度更新: {self.symbol_priorities}")
        
        # 上位N件選定
        sorted_symbols = sorted(
            all_symbols,
            key=lambda s: self.symbol_priorities.get(s, 0),
            reverse=True
        )
        
        active = sorted_symbols[:self.max_concurrent_symbols]
        logger.debug(f"アクティブシンボル: {active}")
        
        return active


# 使用例
manager = MultiSymbolResourceManager({
    "max_concurrent_symbols": 3,
    "priority_refresh_interval": 300
})

# 推論ループ
all_symbols = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD"]

while True:
    # 市場データ取得
    market_data = fetch_market_data(all_symbols)
    
    # アクティブシンボル選定
    active_symbols = manager.get_active_symbols(all_symbols, market_data)
    
    # 選定シンボルのみ推論
    for symbol in active_symbols:
        prediction = model.predict(symbol, market_data[symbol])
        execute_if_signal(symbol, prediction)
```

**優先度計算**:
```
priority = 0.4 * volatility + 0.3 * win_rate + 0.3 * signal_strength
```

**KPI（項目41）**: 資源使用率<80%、機会損失<5%
