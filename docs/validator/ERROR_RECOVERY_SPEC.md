# ERROR_RECOVERY_SPEC.md

**バージョン**: 1.0  
**更新日**: 2025-10-22  
**責任者**: core-team

---

## 📋 目的

重大エラー発生時のfallback戦略とhealth gate機構を定義する。

---

## エラー回復

### 重大エラーfallback

**目的**: 予期せぬエラーでトレード停止は機会損失

**解決策**: Health Gate + Fallback戦略

```python
class HealthGateController:
    """Health Gate制御"""
    
    def __init__(self, config: dict):
        self.error_threshold = config.get("error_threshold", 5)
        self.recovery_cooldown = config.get("recovery_cooldown_minutes", 10)
        
        self.error_count = 0
        self.last_error_time = 0
        self.health_status = "healthy"  # healthy | degraded | blocked
    
    def record_error(self, error: Exception, severity: str):
        """
        エラー記録
        
        Args:
            error: 例外オブジェクト
            severity: "warning" | "critical"
        """
        self.error_count += 1
        self.last_error_time = time.time()
        
        if severity == "critical":
            self.error_count += 2  # 重大エラーは2カウント
        
        # Health状態更新
        if self.error_count >= self.error_threshold:
            self.health_status = "blocked"
            logger.error(f"Health Gate: BLOCKED（エラー{self.error_count}回）")
        elif self.error_count >= self.error_threshold * 0.5:
            self.health_status = "degraded"
            logger.warning(f"Health Gate: DEGRADED（エラー{self.error_count}回）")
    
    def can_trade(self) -> bool:
        """トレード許可判定"""
        # 回復チェック
        if self.health_status == "blocked":
            elapsed_minutes = (time.time() - self.last_error_time) / 60
            
            if elapsed_minutes > self.recovery_cooldown:
                logger.info("Health Gate: 回復期間経過、リセット")
                self.error_count = 0
                self.health_status = "healthy"
        
        return self.health_status != "blocked"
    
    def get_fallback_strategy(self) -> Dict[str, Any]:
        """Fallback戦略取得"""
        if self.health_status == "healthy":
            return {"mode": "normal", "position_size_multiplier": 1.0}
        
        elif self.health_status == "degraded":
            return {
                "mode": "conservative",
                "position_size_multiplier": 0.5,  # ポジションサイズ半減
                "use_simplified_features": True
            }
        
        else:  # blocked
            return {
                "mode": "blocked",
                "position_size_multiplier": 0.0,
                "message": "トレード停止中"
            }


# 使用例
health_gate = HealthGateController({
    "error_threshold": 5,
    "recovery_cooldown_minutes": 10
})

# トレードループ
while True:
    try:
        # Health Gate チェック
        if not health_gate.can_trade():
            logger.warning("トレード停止中: Health Gate BLOCKED")
            time.sleep(60)
            continue
        
        # Fallback戦略取得
        strategy = health_gate.get_fallback_strategy()
        
        # 推論実行
        prediction = model.predict(features)
        
        # ポジションサイズ調整
        position_size = base_size * strategy["position_size_multiplier"]
        
        if position_size > 0:
            execute_trade(prediction, position_size)
    
    except ValueError as e:
        health_gate.record_error(e, severity="warning")
    
    except RuntimeError as e:
        health_gate.record_error(e, severity="critical")
```

**Health状態遷移**:
- healthy: エラー<3回
- degraded: エラー3-4回（ポジションサイズ50%）
- blocked: エラー≥5回（トレード停止）

**KPI（項目42）**: 回復成功率≥90%、block発生<1回/月
