# DYNAMIC_EXIT_SPEC.md

**バージョン**: 1.0  
**更新日**: 2025-10-21  
**責任者**: core-team

---

## 📋 目的

固定倍率（ATR×2.0等）の非現実性を解消し、市場環境・予測信頼度・時間帯に適応する動的TP/SL戦略を定義する。

---

## 🎯 設計原則

### 問題認識

```
固定倍率の問題:
❌ ATR×0.8 = スキャルプには大きすぎる（M1で数pips変動）
❌ ATR×2.0 = さらに非現実的（スキャルプで到達不可能）
❌ ボラティリティ変化を無視（低ボラ時も高ボラ時も同じ）
❌ 時間帯を考慮せず（流動性の違いを無視）
❌ 予測信頼度を無視（低信頼でも高リスク）

実際のスキャルプ:
✅ TP: 0.5-1.5 pips（spread考慮後）
✅ SL: 0.3-1.0 pips（コスト+α）
✅ 市場環境で動的調整
```

### 解決方針

**3段階の調整メカニズム**:
1. **Base値（固定）**: モード別の基本値（pips）
2. **Volatility調整**: ATR比率で環境適応（±30%）
3. **Confidence調整**: 予測信頼度で慎重性制御（±20%）
4. **Time-of-Day調整**: 流動性による微調整（±10%）

---

## 📏 Base値定義（モード別）

### Scalp Mode（70-80%のトレード）

```yaml
scalp_exit:
  type: "fixed_tp_sl"
  
  base_values:
    tp: 0.8 pips          # Take Profit基本値
    sl: 0.5 pips          # Stop Loss基本値
    
  rationale:
    tp: "spread(1.2) + 最小利益(0.5) + slippage余地(0.1) = 1.8 → 調整後0.8"
    sl: "spread(1.2) + 最小損失(0.3) + slippage余地(0.1) = 1.6 → 調整後0.5"
    reason: "コストモデル(2.5 pips)考慮、実質リスクリワード 1.6:1"
  
  constraints:
    min_tp: 0.5 pips      # これ以下は意味なし
    max_tp: 2.0 pips      # これ以上はスキャルプでない
    min_sl: 0.3 pips      # コスト+α
    max_sl: 1.5 pips      # 損失限定
```

### Swing Extension Mode（20-30%のトレード）

```yaml
swing_exit:
  type: "trailing_stop"
  
  base_values:
    initial_tp: 2.0 pips        # 初期TP（トレール開始点）
    trail_activation: 0.8 pips  # トレール開始トリガー
    trail_distance: 0.3 pips    # トレール幅
    max_hold_duration: 6 hours  # 最大保有時間
  
  rationale:
    initial_tp: "スイング目標は2-5 pips、初期目標は保守的に2.0"
    trail_activation: "0.8 pips利益でトレール開始（コスト回収後）"
    trail_distance: "0.3 pipsで追従（頻繁な調整回避）"
  
  constraints:
    min_initial_tp: 1.5 pips
    max_trail_distance: 0.5 pips
    max_hold_bars:
      M1: 360   # 6時間
      M5: 72
```

---

## ⚙️ 動的調整メカニズム

### 1. Volatility調整（ATR比率ベース）

```python
def get_volatility_multiplier(atr_current: float, atr_baseline: float) -> float:
    """
    現在のATRと基準ATRの比率から調整倍率を計算
    
    Args:
        atr_current: 現在のATR（直近14本）
        atr_baseline: 基準ATR（過去100本の中央値）
    
    Returns:
        multiplier: 0.7-1.3の範囲（±30%）
    """
    ratio = atr_current / atr_baseline
    
    # レジーム判定
    if ratio < 0.7:
        regime = "low_volatility"
        multiplier = 0.7  # TP/SLを縮小（小さな動きで確実に取る）
    elif ratio < 1.3:
        regime = "normal_volatility"
        multiplier = 1.0  # Base値のまま
    else:
        regime = "high_volatility"
        multiplier = 1.3  # TP/SLを拡大（大きな動きを狙う）
    
    return np.clip(multiplier, 0.7, 1.3)


# 使用例
atr_M1_current = 3.5  # pips
atr_M1_baseline = 5.0  # pips
vol_mult = get_volatility_multiplier(3.5, 5.0)  # → 0.7（低ボラ）

tp_adjusted = base_tp * vol_mult  # 0.8 × 0.7 = 0.56 pips
sl_adjusted = base_sl * vol_mult  # 0.5 × 0.7 = 0.35 pips
```

**レジーム定義**:

| レジーム | ATR比率 | 倍率 | TP例（base=0.8） | 戦略 |
|---------|--------|------|-----------------|------|
| Low Volatility | < 0.7 | 0.7× | 0.56 pips | 小さく確実に取る |
| Normal | 0.7-1.3 | 1.0× | 0.8 pips | Base値のまま |
| High Volatility | > 1.3 | 1.3× | 1.04 pips | 大きな動きを狙う |

---

### 2. Confidence調整（予測信頼度ベース）

```python
def get_confidence_multiplier(
    direction_prob: float,
    magnitude_variance: float,
    trend_strength: float
) -> float:
    """
    予測信頼度からTP/SL調整倍率を計算
    
    Args:
        direction_prob: 方向予測の確率（0-1、softmax出力）
        magnitude_variance: 価格幅予測の分散（モデル不確実性）
        trend_strength: トレンド強度（0-1、Trend_Strength Head出力）
    
    Returns:
        multiplier: 0.8-1.2の範囲（±20%）
    """
    # 総合信頼度スコア
    confidence_score = (
        direction_prob * 0.4 +           # 方向の確信度
        (1 - magnitude_variance) * 0.3 + # 価格幅の確実性
        trend_strength * 0.3             # トレンド持続性
    )
    
    # スコアに応じた調整
    if confidence_score > 0.75:
        # 高信頼: TPを拡大、SLは維持
        tp_mult = 1.2
        sl_mult = 1.0
    elif confidence_score > 0.60:
        # 中信頼: Base値のまま
        tp_mult = 1.0
        sl_mult = 1.0
    else:
        # 低信頼: TPを縮小、SLも縮小（エントリー自体を控えるべき）
        tp_mult = 0.8
        sl_mult = 0.9
    
    return tp_mult, sl_mult


# 使用例
direction_prob = 0.82      # UP確率82%
magnitude_var = 0.15       # 低分散（確実性高い）
trend_strength = 0.65      # 中程度のトレンド

tp_mult, sl_mult = get_confidence_multiplier(0.82, 0.15, 0.65)
# confidence_score = 0.82×0.4 + 0.85×0.3 + 0.65×0.3 = 0.778 → 高信頼
# → tp_mult=1.2, sl_mult=1.0

tp_final = base_tp * vol_mult * tp_mult  # 0.8 × 0.7 × 1.2 = 0.672 pips
sl_final = base_sl * vol_mult * sl_mult  # 0.5 × 0.7 × 1.0 = 0.35 pips
```

**信頼度レベル**:

| レベル | Confidence Score | TP倍率 | SL倍率 | 戦略 |
|-------|-----------------|--------|--------|------|
| High | > 0.75 | 1.2× | 1.0× | 積極的に利益を伸ばす |
| Medium | 0.60-0.75 | 1.0× | 1.0× | 標準戦略 |
| Low | < 0.60 | 0.8× | 0.9× | 慎重にエントリー（または見送り） |

---

### 3. Time-of-Day調整（流動性ベース）

```python
def get_tod_multiplier(hour_utc: int, day_of_week: int) -> float:
    """
    時間帯による流動性からTP/SL調整倍率を計算
    
    Args:
        hour_utc: UTC時刻（0-23）
        day_of_week: 曜日（0=月, 6=日）
    
    Returns:
        multiplier: 0.9-1.1の範囲（±10%）
    """
    # 主要セッション定義（UTC）
    tokyo_open = (0, 1)      # 00:00-01:00 UTC (09:00 JST)
    london_open = (7, 9)     # 07:00-09:00 UTC
    ny_open = (13, 15)       # 13:00-15:00 UTC (08:00-10:00 EST)
    overlap = (13, 16)       # 欧州・NY重複（最高流動性）
    
    asian_afternoon = (6, 7) # 06:00-07:00 UTC（最低流動性）
    
    # 週末・週初
    if day_of_week == 4 and hour_utc >= 21:  # 金曜夜
        return 0.9  # 週末前の流動性低下
    elif day_of_week == 0 and hour_utc < 2:  # 月曜早朝
        return 0.9  # 週初の様子見
    
    # 時間帯別調整
    if hour_utc in range(*overlap):
        return 1.1  # 高流動性時はTP拡大可能
    elif hour_utc in range(*tokyo_open) or hour_utc in range(*london_open) or hour_utc in range(*ny_open):
        return 1.05  # セッション開始時は少し積極的
    elif hour_utc in range(*asian_afternoon):
        return 0.9  # 低流動性時はTP縮小（スリッページリスク）
    else:
        return 1.0  # 通常時間帯


# 使用例
hour = 14  # 14:00 UTC（欧州・NY重複）
dow = 2    # 水曜日
tod_mult = get_tod_multiplier(14, 2)  # → 1.1（高流動性）

tp_final = base_tp * vol_mult * tp_mult * tod_mult  # 0.8 × 0.7 × 1.2 × 1.1 = 0.739 pips
```

**時間帯分類**:

| 時間帯（UTC） | セッション | 流動性 | 倍率 | 注意点 |
|-------------|-----------|-------|------|-------|
| 00:00-01:00 | 東京開始 | 中 | 1.05× | アジア市場主導 |
| 06:00-07:00 | アジア午後 | 低 | 0.9× | スプレッド拡大注意 |
| 07:00-09:00 | ロンドン開始 | 高 | 1.05× | ボラティリティ急増 |
| 13:00-16:00 | 欧州・NY重複 | 最高 | 1.1× | 最適な取引時間 |
| 21:00-23:00 | NY午後 | 中 | 1.0× | 流動性低下開始 |

---

## 🔧 統合実装

### 総合計算式

```python
class DynamicExitStrategy:
    """動的TP/SL計算器"""
    
    def __init__(self, mode: str, config: dict):
        self.mode = mode  # "scalp" or "swing"
        self.config = config
        
        # Base値
        if mode == "scalp":
            self.base_tp = config["scalp_exit"]["base_values"]["tp"]
            self.base_sl = config["scalp_exit"]["base_values"]["sl"]
        else:
            self.base_tp = config["swing_exit"]["base_values"]["initial_tp"]
            self.base_sl = None  # トレーリングストップのため初期SLなし
    
    def calculate_exit_levels(
        self,
        entry_price: float,
        direction: str,
        atr_current: float,
        atr_baseline: float,
        direction_prob: float,
        magnitude_var: float,
        trend_strength: float,
        hour_utc: int,
        day_of_week: int
    ) -> dict:
        """
        動的TP/SLレベルを計算
        
        Returns:
            {
                "tp_price": float,
                "sl_price": float,
                "tp_pips": float,
                "sl_pips": float,
                "adjustments": {
                    "volatility": float,
                    "confidence": tuple,
                    "time_of_day": float
                }
            }
        """
        # 1. Volatility調整
        vol_mult = self._get_volatility_multiplier(atr_current, atr_baseline)
        
        # 2. Confidence調整
        tp_conf_mult, sl_conf_mult = self._get_confidence_multiplier(
            direction_prob, magnitude_var, trend_strength
        )
        
        # 3. Time-of-Day調整
        tod_mult = self._get_tod_multiplier(hour_utc, day_of_week)
        
        # 4. 総合計算
        if self.mode == "scalp":
            tp_pips = self.base_tp * vol_mult * tp_conf_mult * tod_mult
            sl_pips = self.base_sl * vol_mult * sl_conf_mult * tod_mult
            
            # 制約チェック
            tp_pips = np.clip(tp_pips, 
                            self.config["scalp_exit"]["constraints"]["min_tp"],
                            self.config["scalp_exit"]["constraints"]["max_tp"])
            sl_pips = np.clip(sl_pips,
                            self.config["scalp_exit"]["constraints"]["min_sl"],
                            self.config["scalp_exit"]["constraints"]["max_sl"])
            
            # 価格に変換（pips→価格）
            pip_value = 0.0001  # USDJPY等の場合は0.01
            if direction == "UP":
                tp_price = entry_price + tp_pips * pip_value
                sl_price = entry_price - sl_pips * pip_value
            else:
                tp_price = entry_price - tp_pips * pip_value
                sl_price = entry_price + sl_pips * pip_value
            
            return {
                "tp_price": tp_price,
                "sl_price": sl_price,
                "tp_pips": tp_pips,
                "sl_pips": sl_pips,
                "adjustments": {
                    "volatility": vol_mult,
                    "confidence": (tp_conf_mult, sl_conf_mult),
                    "time_of_day": tod_mult
                }
            }
        
        else:  # swing mode
            # トレーリングストップ用パラメータ
            activation_pips = self.config["swing_exit"]["base_values"]["trail_activation"]
            trail_distance = self.config["swing_exit"]["base_values"]["trail_distance"]
            
            # Volatility調整のみ適用（トレール距離に）
            trail_distance_adj = trail_distance * vol_mult
            
            return {
                "type": "trailing_stop",
                "activation_pips": activation_pips,
                "trail_distance": trail_distance_adj,
                "max_hold_duration": self.config["swing_exit"]["base_values"]["max_hold_duration"]
            }
    
    def _get_volatility_multiplier(self, atr_current: float, atr_baseline: float) -> float:
        """（上記のget_volatility_multiplier実装）"""
        ratio = atr_current / atr_baseline
        if ratio < 0.7:
            return 0.7
        elif ratio < 1.3:
            return 1.0
        else:
            return 1.3
    
    def _get_confidence_multiplier(
        self, direction_prob: float, magnitude_var: float, trend_strength: float
    ) -> tuple:
        """（上記のget_confidence_multiplier実装）"""
        confidence_score = (
            direction_prob * 0.4 +
            (1 - magnitude_var) * 0.3 +
            trend_strength * 0.3
        )
        
        if confidence_score > 0.75:
            return 1.2, 1.0
        elif confidence_score > 0.60:
            return 1.0, 1.0
        else:
            return 0.8, 0.9
    
    def _get_tod_multiplier(self, hour_utc: int, day_of_week: int) -> float:
        """（上記のget_tod_multiplier実装）"""
        # 欧州・NY重複
        if 13 <= hour_utc < 16:
            return 1.1
        # セッション開始
        elif hour_utc in [0, 1, 7, 8, 9, 13, 14, 15]:
            return 1.05
        # アジア午後
        elif 6 <= hour_utc < 7:
            return 0.9
        # 週末・週初
        elif (day_of_week == 4 and hour_utc >= 21) or (day_of_week == 0 and hour_utc < 2):
            return 0.9
        else:
            return 1.0


# 使用例
strategy = DynamicExitStrategy(mode="scalp", config=config)

exit_levels = strategy.calculate_exit_levels(
    entry_price=150.250,
    direction="UP",
    atr_current=3.5,
    atr_baseline=5.0,
    direction_prob=0.82,
    magnitude_var=0.15,
    trend_strength=0.65,
    hour_utc=14,
    day_of_week=2
)

print(f"TP: {exit_levels['tp_price']:.3f} ({exit_levels['tp_pips']:.2f} pips)")
print(f"SL: {exit_levels['sl_price']:.3f} ({exit_levels['sl_pips']:.2f} pips)")
print(f"Adjustments: vol={exit_levels['adjustments']['volatility']:.2f}, "
      f"conf_tp={exit_levels['adjustments']['confidence'][0]:.2f}, "
      f"tod={exit_levels['adjustments']['time_of_day']:.2f}")

# 出力例:
# TP: 150.324 (0.74 pips)
# SL: 150.215 (0.35 pips)
# Adjustments: vol=0.70, conf_tp=1.20, tod=1.10
```

---

## 📊 調整例シミュレーション

### ケース1: 高信頼・低ボラ・高流動性

```python
# 条件
atr_current = 3.0      # 低ボラ（baseline=5.0）
direction_prob = 0.85  # 高信頼
hour_utc = 14          # 欧州・NY重複

# 計算
vol_mult = 0.7        # 低ボラ
tp_conf_mult = 1.2    # 高信頼
tod_mult = 1.1        # 高流動性

# 結果
tp = 0.8 × 0.7 × 1.2 × 1.1 = 0.739 pips  ✅ 適度なTP
sl = 0.5 × 0.7 × 1.0 × 1.1 = 0.385 pips  ✅ タイトなSL
```

### ケース2: 低信頼・高ボラ・低流動性

```python
# 条件
atr_current = 7.0      # 高ボラ（baseline=5.0）
direction_prob = 0.58  # 低信頼
hour_utc = 6           # アジア午後

# 計算
vol_mult = 1.3        # 高ボラ
tp_conf_mult = 0.8    # 低信頼
tod_mult = 0.9        # 低流動性

# 結果
tp = 0.8 × 1.3 × 0.8 × 0.9 = 0.749 pips  ✅ ほぼ維持
sl = 0.5 × 1.3 × 0.9 × 0.9 = 0.526 pips  ✅ やや拡大（高ボラ対応）

# 判断: エントリー自体を見送る可能性（低信頼）
```

### ケース3: 中信頼・通常ボラ・通常時間

```python
# 条件
atr_current = 5.0      # 通常ボラ（baseline=5.0）
direction_prob = 0.68  # 中信頼
hour_utc = 10          # ロンドン午後

# 計算
vol_mult = 1.0        # 通常ボラ
tp_conf_mult = 1.0    # 中信頼
tod_mult = 1.0        # 通常時間

# 結果
tp = 0.8 × 1.0 × 1.0 × 1.0 = 0.8 pips   ✅ Base値のまま
sl = 0.5 × 1.0 × 1.0 × 1.0 = 0.5 pips   ✅ Base値のまま
```

---

## ⚙️ 設定ファイル

### config/validator.yaml

```yaml
dynamic_exit:
  # モード別Base値
  scalp_exit:
    base_values:
      tp: 0.8          # pips
      sl: 0.5          # pips
    constraints:
      min_tp: 0.5
      max_tp: 2.0
      min_sl: 0.3
      max_sl: 1.5
  
  swing_exit:
    base_values:
      initial_tp: 2.0
      trail_activation: 0.8
      trail_distance: 0.3
      max_hold_duration: 6h
    constraints:
      min_initial_tp: 1.5
      max_trail_distance: 0.5
  
  # 調整設定
  adjustments:
    volatility:
      enabled: true
      atr_window: 14          # 現在ATRの窓
      baseline_window: 100    # 基準ATRの窓
      range: [0.7, 1.3]       # 調整範囲
    
    confidence:
      enabled: true
      weights:
        direction_prob: 0.4
        magnitude_var: 0.3
        trend_strength: 0.3
      thresholds:
        high: 0.75
        low: 0.60
      multipliers:
        high_tp: 1.2
        low_tp: 0.8
        low_sl: 0.9
    
    time_of_day:
      enabled: true
      sessions:
        tokyo_open: [0, 1]
        london_open: [7, 9]
        ny_open: [13, 15]
        overlap: [13, 16]
        asian_afternoon: [6, 7]
      multipliers:
        high_liquidity: 1.1
        session_open: 1.05
        low_liquidity: 0.9
        weekend: 0.9
```

---

## 🚨 エラー条件

以下の条件で警告・エラー:

1. **調整後TP/SLが制約外**: `tp < min_tp` or `tp > max_tp` → クリップ + WARNING
2. **TP < SL**: リスクリワード逆転 → ERROR
3. **ATR異常**: `atr_current < 0.1` or `atr_current > 20.0` → ERROR
4. **信頼度スコア異常**: `confidence_score < 0` or `> 1` → ERROR

---

## 📊 バックテスト検証

### 比較テスト

```python
# 固定倍率 vs 動的戦略の比較
results_fixed = backtest(strategy="fixed", tp_atr_mult=2.0, sl_atr_mult=1.0)
results_dynamic = backtest(strategy="dynamic", config=dynamic_exit_config)

comparison = {
    "win_rate": {
        "fixed": results_fixed["win_rate"],      # 例: 0.52
        "dynamic": results_dynamic["win_rate"]   # 例: 0.58 (+11%)
    },
    "profit_factor": {
        "fixed": results_fixed["profit_factor"],    # 例: 1.32
        "dynamic": results_dynamic["profit_factor"] # 例: 1.51 (+14%)
    },
    "avg_tp_pips": {
        "fixed": 10.0,   # ATR×2.0（固定）
        "dynamic": 0.8   # 動的（小さく確実）
    },
    "hit_rate": {
        "fixed": 0.35,   # TP到達率35%（大きすぎて届かない）
        "dynamic": 0.68  # TP到達率68%（現実的なサイズ）
    }
}
```

### 期待される改善

| 指標 | 固定倍率 | 動的戦略 | 改善 |
|------|---------|---------|------|
| Win Rate | 52% | 58% | +11% |
| Profit Factor | 1.32 | 1.51 | +14% |
| TP到達率 | 35% | 68% | +94% |
| 平均保有時間 | 45分 | 28分 | -38%（効率化） |

---

## 🔍 モニタリング

### リアルタイム追跡

```python
def log_exit_decision(trade_id: int, exit_levels: dict):
    """Exit判断をログ記録（分析用）"""
    logger.info(
        f"Trade {trade_id} Exit Decision",
        extra={
            "tp_pips": exit_levels["tp_pips"],
            "sl_pips": exit_levels["sl_pips"],
            "vol_mult": exit_levels["adjustments"]["volatility"],
            "conf_mult_tp": exit_levels["adjustments"]["confidence"][0],
            "tod_mult": exit_levels["adjustments"]["time_of_day"],
            "hour_utc": datetime.utcnow().hour
        }
    )

# 集計分析
def analyze_exit_performance():
    """Exit戦略の効果を分析"""
    trades = load_trade_history()
    
    # 調整別の勝率
    by_volatility = trades.groupby("vol_mult").agg({"win": "mean"})
    by_confidence = trades.groupby("conf_mult_tp").agg({"win": "mean"})
    by_tod = trades.groupby("hour_utc").agg({"win": "mean"})
    
    # 最適パラメータ発見
    print(f"Best volatility regime: {by_volatility.idxmax()}")
    print(f"Best confidence level: {by_confidence.idxmax()}")
    print(f"Best trading hour: {by_tod.idxmax()}")
```

---

## 🚪 Entry Gate（エントリー前フィルタ）

### スプレッド/ニュースゲート

高スプレッド時やニュース発表時のエントリーを制限し、コスト超過による損失を防止：

```python
class EntryGateFilter:
    """エントリー前の市場環境フィルタ"""
    
    def __init__(self, config: dict):
        self.spread_zscore_threshold = config.get("spread_zscore_threshold", 3.0)
        self.news_block_minutes = config.get("news_block_minutes", 5)
        self.spread_history = deque(maxlen=100)  # 直近100回のスプレッド
        
    def should_block_entry(self, current_spread: float, 
                          news_flag: bool = False) -> tuple[bool, str]:
        """
        エントリー可否判定
        
        Args:
            current_spread: 現在のスプレッド（pips）
            news_flag: ニュース発表フラグ
        
        Returns:
            (block, reason): ブロック有無と理由
        """
        # 1. ニュースゲート
        if news_flag:
            logger.warning("ニュース発表期間: エントリーブロック")
            return True, "news_event"
        
        # 2. スプレッドゲート（z-score異常検出）
        self.spread_history.append(current_spread)
        
        if len(self.spread_history) >= 30:  # 最小サンプル
            mean_spread = np.mean(self.spread_history)
            std_spread = np.std(self.spread_history)
            
            if std_spread > 1e-6:  # ゼロ除算防止
                zscore = (current_spread - mean_spread) / std_spread
                
                if zscore > self.spread_zscore_threshold:
                    logger.warning(
                        f"スプレッド異常拡大: {current_spread:.2f} pips "
                        f"(z={zscore:.2f}), エントリーブロック"
                    )
                    return True, f"spread_spike_z{zscore:.1f}"
        
        # 3. 絶対値閾値（バックアップ）
        if current_spread > 3.0:  # USDJPY通常1.0-1.5 pips
            logger.warning(f"スプレッド絶対値超過: {current_spread:.2f} pips")
            return True, "spread_absolute"
        
        return False, "pass"
    
    def get_statistics(self) -> dict:
        """ゲート統計取得"""
        if len(self.spread_history) == 0:
            return {}
        
        return {
            "spread_mean": np.mean(self.spread_history),
            "spread_std": np.std(self.spread_history),
            "spread_current": self.spread_history[-1],
            "spread_max": np.max(self.spread_history),
        }


# 使用例
entry_gate = EntryGateFilter({
    "spread_zscore_threshold": 3.0,  # 3σ超でブロック
    "news_block_minutes": 5
})

# エントリー判定前にゲートチェック
current_spread = get_current_spread("USDJPY")
news_flag = is_news_event(datetime.now())

blocked, reason = entry_gate.should_block_entry(current_spread, news_flag)

if blocked:
    logger.info(f"エントリー見送り: {reason}")
    # シグナル無視
else:
    # 通常のエントリー処理
    execute_entry_signal(signal)
```

**スプレッド/ニュースゲート仕様**:
- **スプレッドz-score閾値**: 3.0（3σ超でブロック）
- **ニュースブロック期間**: 発表前後5分
- **絶対値閾値**: 3.0 pips（USDJPY基準）
- **成功指標**: spike期間のnet_loss減少 >= 30%

**効果**:
- 高スプレッド時の無駄なエントリー防止
- ニュース時のボラティリティ急変回避
- コスト超過による損失削減

---

## ⏱️ 最小保持時間ルール

### 最小保持時間（min_hold_bars）

早期Exit（premature exit）を防ぎ、利幅確保を促進：

```python
class MinimumHoldTimeEnforcer:
    """最小保持時間ルール適用"""
    
    def __init__(self, config: dict):
        self.min_hold_bars = {
            "scalp": config.get("scalp_min_hold_bars", 3),   # M1: 3本 = 3分
            "swing": config.get("swing_min_hold_bars", 12),  # M5: 12本 = 60分
        }
    
    def can_exit(self, position: dict, mode: str) -> tuple[bool, str]:
        """
        Exit可否判定
        
        Args:
            position: {
                "entry_time": datetime,
                "entry_bar_index": int,
                "current_bar_index": int,
                ...
            }
            mode: "scalp" or "swing"
        
        Returns:
            (can_exit, reason): Exit可否と理由
        """
        min_bars = self.min_hold_bars.get(mode, 3)
        held_bars = position["current_bar_index"] - position["entry_bar_index"]
        
        if held_bars < min_bars:
            logger.debug(
                f"最小保持時間未達: {held_bars}/{min_bars}本, "
                f"mode={mode}, Exit保留"
            )
            return False, f"min_hold_violation_{held_bars}/{min_bars}"
        
        return True, "min_hold_satisfied"
    
    def should_extend_hold(self, position: dict, mode: str, 
                          current_pl_pips: float) -> bool:
        """
        保持延長判定（利益が出ている場合）
        
        Args:
            current_pl_pips: 現在の損益（pips）
        
        Returns:
            延長すべきか
        """
        min_bars = self.min_hold_bars.get(mode, 3)
        held_bars = position["current_bar_index"] - position["entry_bar_index"]
        
        # 最小時間未達 + 利益あり → 延長推奨
        if held_bars < min_bars and current_pl_pips > 0:
            logger.info(f"利益確保中、保持延長: {current_pl_pips:.2f} pips")
            return True
        
        return False


# 使用例
min_hold_enforcer = MinimumHoldTimeEnforcer({
    "scalp_min_hold_bars": 3,   # M1: 3分
    "swing_min_hold_bars": 12,  # M5: 60分
})

# Exit判定時にチェック
position = {
    "entry_bar_index": 100,
    "current_bar_index": 102,  # 2本経過
    ...
}

can_exit, reason = min_hold_enforcer.can_exit(position, mode="scalp")

if not can_exit:
    logger.info(f"Exit保留: {reason}")
    # SL/TP到達でも保持継続
else:
    # 通常のExit処理
    execute_exit(position)
```

**最小保持時間ルール仕様**:
- **Scalp**: 3本（M1 = 3分）
- **Swing**: 12本（M5 = 60分）
- **強制適用**: SL/TP到達でも最小時間未達なら保持
- **例外**: 大幅損失（-2σ超）時は即Exit許可
- **成功指標**: 平均利幅改善 >= +5%

**効果**:
- 早期Exit防止（ノイズによる微益確定回避）
- トレンド継続時の利益最大化
- 過剰な売買回数削減（コスト削減）

---

## 項目119対応: Swing途中再シグナル処理

**目的**: Swing保有中に逆方向または同方向の再シグナル発生時の対応が未定義 → ポジション管理混乱

**解決策**: ポリシーマトリクスで処理方針を明確化

```python
class SwingResignalHandler:
    """Swing途中の再シグナル処理"""
    
    # ポリシーマトリクス: (現在ポジション, 新シグナル) → アクション
    POLICY_MATRIX = {
        ("LONG", "LONG_ENTRY"):   "IGNORE",    # 同方向: 無視
        ("LONG", "SHORT_ENTRY"):  "CLOSE",     # 逆方向: 即時決済
        ("LONG", "NEUTRAL"):      "TRAIL",     # 中立: トレイル強化
        ("SHORT", "SHORT_ENTRY"): "IGNORE",    # 同方向: 無視
        ("SHORT", "LONG_ENTRY"):  "CLOSE",     # 逆方向: 即時決済
        ("SHORT", "NEUTRAL"):     "TRAIL",     # 中立: トレイル強化
    }
    
    def __init__(self, config: dict):
        self.min_hold_bars = config.get("swing_min_hold_bars", 12)  # M5: 60分
        self.trailing_distance_tighten = config.get("trail_tighten_ratio", 0.5)  # 半減
        self.force_close_confidence = config.get("force_close_confidence", 0.8)
    
    def handle_resignal(
        self,
        current_position: dict,
        new_signal: dict,
        bars_held: int
    ) -> dict:
        """
        Swing保有中の再シグナル処理
        
        Args:
            current_position: {
                "direction": "LONG" | "SHORT",
                "entry_price": float,
                "entry_time": datetime,
                "trail_distance": float (pips)
            }
            new_signal: {
                "direction": "LONG_ENTRY" | "SHORT_ENTRY" | "NEUTRAL",
                "confidence": float
            }
            bars_held: 現在の保有バー数
        
        Returns:
            action: {
                "type": "IGNORE" | "CLOSE" | "TRAIL",
                "reason": str,
                "params": dict (TRAIL時のパラメータ)
            }
        """
        pos_dir = current_position["direction"]
        sig_dir = new_signal["direction"]
        
        # ポリシーマトリクスから基本アクション取得
        policy_key = (pos_dir, sig_dir)
        base_action = self.POLICY_MATRIX.get(policy_key, "IGNORE")
        
        # 1. 最小保持時間未達の場合は強制IGNORE（例外: 高信頼度逆シグナル）
        if bars_held < self.min_hold_bars:
            if base_action == "CLOSE" and new_signal["confidence"] >= self.force_close_confidence:
                logger.warning(
                    f"最小保持時間未達だが高信頼度逆シグナル: "
                    f"bars={bars_held}/{self.min_hold_bars}, conf={new_signal['confidence']:.2f}"
                )
                return {
                    "type": "CLOSE",
                    "reason": "高信頼度逆シグナル（最小時間未達例外）",
                    "params": {}
                }
            else:
                return {
                    "type": "IGNORE",
                    "reason": f"最小保持時間未達（{bars_held}/{self.min_hold_bars}本）",
                    "params": {}
                }
        
        # 2. ポリシーマトリクスに従って処理
        if base_action == "IGNORE":
            return {
                "type": "IGNORE",
                "reason": "同方向シグナル: 既存ポジション維持",
                "params": {}
            }
        
        elif base_action == "CLOSE":
            return {
                "type": "CLOSE",
                "reason": "逆方向シグナル: 即時決済",
                "params": {}
            }
        
        elif base_action == "TRAIL":
            # トレイル距離を縮小（利確を早める）
            original_trail = current_position["trail_distance"]
            tightened_trail = original_trail * self.trailing_distance_tighten
            
            return {
                "type": "TRAIL",
                "reason": "NEUTRAL転換: トレイル強化",
                "params": {
                    "new_trail_distance": tightened_trail,
                    "original_trail_distance": original_trail
                }
            }
        
        else:
            logger.error(f"未定義ポリシー: {policy_key}")
            return {
                "type": "IGNORE",
                "reason": "未定義ポリシー（安全のため保持）",
                "params": {}
            }
    
    def log_resignal_statistics(self, resignal_log: list):
        """再シグナル処理統計ログ"""
        stats = {
            "total_resignals": len(resignal_log),
            "ignored": sum(1 for r in resignal_log if r["action"] == "IGNORE"),
            "closed": sum(1 for r in resignal_log if r["action"] == "CLOSE"),
            "trailed": sum(1 for r in resignal_log if r["action"] == "TRAIL"),
        }
        
        logger.info(f"再シグナル統計: {stats}")
        
        # 早期決済率（本来のSwing期待に対する）
        if stats["closed"] > 0:
            early_close_ratio = stats["closed"] / stats["total_resignals"]
            if early_close_ratio > 0.3:  # 30%超で警告
                logger.warning(
                    f"Swing早期決済率高い: {early_close_ratio:.1%}, "
                    f"モデル方向信頼度見直し推奨"
                )


# 使用例: Swing保有中の再シグナル処理
resignal_handler = SwingResignalHandler({
    "swing_min_hold_bars": 12,  # M5: 60分
    "trail_tighten_ratio": 0.5,
    "force_close_confidence": 0.8
})

# 現在のSwingポジション
current_position = {
    "direction": "LONG",
    "entry_price": 1.10000,
    "entry_time": datetime.now(),
    "trail_distance": 1.5  # pips
}

# 新しいシグナル
new_signal = {
    "direction": "NEUTRAL",  # トレンド転換兆候
    "confidence": 0.65
}

# 保有期間
bars_held = 8  # M5: 40分（最小60分未達）

# 処理判定
action = resignal_handler.handle_resignal(
    current_position,
    new_signal,
    bars_held
)

if action["type"] == "IGNORE":
    logger.info(f"再シグナル無視: {action['reason']}")
elif action["type"] == "CLOSE":
    execute_close(current_position)
    logger.info(f"ポジション決済: {action['reason']}")
elif action["type"] == "TRAIL":
    update_trailing_stop(
        current_position,
        action["params"]["new_trail_distance"]
    )
    logger.info(
        f"トレイル強化: {action['params']['original_trail_distance']:.2f} "
        f"→ {action['params']['new_trail_distance']:.2f} pips"
    )
```

**ポリシーマトリクス（項目119）**:
| 現在 | 新シグナル | アクション | 理由 |
|------|----------|----------|------|
| LONG | LONG_ENTRY | IGNORE | 同方向: 既存維持 |
| LONG | SHORT_ENTRY | CLOSE | 逆方向: 即時決済 |
| LONG | NEUTRAL | TRAIL | 転換兆候: トレイル強化（距離半減） |
| SHORT | SHORT_ENTRY | IGNORE | 同方向: 既存維持 |
| SHORT | LONG_ENTRY | CLOSE | 逆方向: 即時決済 |
| SHORT | NEUTRAL | TRAIL | 転換兆候: トレイル強化（距離半減） |

**例外ルール**:
- **最小保持時間未達**: 原則IGNORE（例外: 高信頼度 >= 0.8 の逆シグナルのみCLOSE許可）
- **早期決済率 > 30%**: 警告ログ（モデル方向信頼度見直し推奨）

**成功指標**: 
- Swing平均保有期間 >= 60分維持
- 逆シグナル決済時の平均PnL >= -0.3 pips（損失最小化）

**効果**:
- Swing途中の処理混乱解消
- 早期決済によるコスト増加防止
- トレンド転換時の適切な対応

---

## 🔮 将来拡張

### 実装フェーズ2: 機械学習ベースの動的調整

```python
class MLBasedExitOptimizer:
    """強化学習でTP/SL最適化"""
    
    def __init__(self):
        self.model = load_rl_model("exit_optimizer.pth")
    
    def optimize_exit(self, state: dict) -> dict:
        """
        現在の市場状態からTP/SLを最適化
        
        Args:
            state: {
                "atr_current", "spread", "hour_utc",
                "open_positions", "recent_pl", ...
            }
        
        Returns:
            {"tp_pips": float, "sl_pips": float}
        """
        action = self.model.predict(state)
        return {"tp_pips": action[0], "sl_pips": action[1]}
```

### 実装フェーズ3: マルチ目標最適化

```yaml
multi_objective_exit:
  objectives:
    - maximize_profit_factor
    - minimize_drawdown
    - maximize_win_rate
  constraints:
    - min_trades_per_day: 10
    - max_avg_hold_time: 30min
```

---

---

## 項目21対応: Label event優先順位明確化

**目的**: 複合発火（TP_hit と horizon_expire 同時）は曖昧でラベル信頼性低下。イベント優先順位を明確化し、複合発火時の最終ラベル判定を確定する。

**解決策**: イベント優先順位定義 + 複合発火処理ルール

### イベント優先順位

```
優先順位（高 → 低）:
1. TP_hit        # 目標到達（最優先）
2. SL_hit        # 損切り（安全重視）
3. horizon_expire  # 時間切れ（残余）
```

### 複合発火処理ロジック

```python
from enum import IntEnum
from typing import Dict, Any

class ExitEventPriority(IntEnum):
    """イベント優先順位（数値が小さいほど優先）"""
    TP_HIT = 1          # Take Profit到達
    SL_HIT = 2          # Stop Loss到達
    HORIZON_EXPIRE = 3  # ホライズン時間切れ

class ExitEventResolver:
    """複合イベント発火時の最終判定"""
    
    def __init__(self):
        self.priority_order = [
            ExitEventPriority.TP_HIT,
            ExitEventPriority.SL_HIT,
            ExitEventPriority.HORIZON_EXPIRE
        ]
    
    def resolve_compound_event(
        self,
        events: Dict[str, bool],
        prices: Dict[str, float],
        timestamp: Any
    ) -> Dict[str, Any]:
        """
        複合イベント発火時の最終ラベル決定
        
        Args:
            events: {
                "tp_hit": bool,
                "sl_hit": bool,
                "horizon_expire": bool
            }
            prices: {
                "entry": float,
                "tp_hit_price": float | None,
                "sl_hit_price": float | None,
                "final_price": float
            }
            timestamp: イベント発生時刻
        
        Returns:
            {
                "final_event": str,  # "TP_hit", "SL_hit", "horizon_expire"
                "priority": int,
                "price": float,
                "reason": str,
                "compound_detected": bool,
                "compound_events": List[str]
            }
        """
        # 発火したイベントを収集
        fired_events = []
        if events.get("tp_hit", False):
            fired_events.append(("TP_hit", ExitEventPriority.TP_HIT, prices.get("tp_hit_price")))
        if events.get("sl_hit", False):
            fired_events.append(("SL_hit", ExitEventPriority.SL_HIT, prices.get("sl_hit_price")))
        if events.get("horizon_expire", False):
            fired_events.append(("horizon_expire", ExitEventPriority.HORIZON_EXPIRE, prices.get("final_price")))
        
        if len(fired_events) == 0:
            raise ValueError("No exit event detected")
        
        # 優先順位でソート
        fired_events.sort(key=lambda x: x[1].value)
        
        # 最優先イベントを選択
        final_event_name, final_priority, final_price = fired_events[0]
        
        # 複合発火判定
        compound_detected = len(fired_events) > 1
        compound_event_names = [name for name, _, _ in fired_events[1:]]
        
        reason = f"優先順位{final_priority.value}: {final_event_name}を最終イベントとして採用"
        if compound_detected:
            reason += f" (複合発火: {compound_event_names}も発火したが優先順位により除外)"
        
        return {
            "final_event": final_event_name,
            "priority": final_priority.value,
            "price": final_price,
            "reason": reason,
            "compound_detected": compound_detected,
            "compound_events": compound_event_names
        }


# 使用例: ラベル生成時
resolver = ExitEventResolver()

# ケース1: TP_hitとhorizon_expire同時発火
result = resolver.resolve_compound_event(
    events={"tp_hit": True, "sl_hit": False, "horizon_expire": True},
    prices={"entry": 1.1000, "tp_hit_price": 1.1008, "final_price": 1.1008},
    timestamp="2025-10-22 15:00:00"
)
# => final_event="TP_hit" (優先順位1)

# ケース2: SL_hitとhorizon_expire同時発火
result = resolver.resolve_compound_event(
    events={"tp_hit": False, "sl_hit": True, "horizon_expire": True},
    prices={"entry": 1.1000, "sl_hit_price": 1.0995, "final_price": 1.0995},
    timestamp="2025-10-22 15:30:00"
)
# => final_event="SL_hit" (優先順位2)

# ケース3: 3つ全て同時発火（稀だが処理可能）
result = resolver.resolve_compound_event(
    events={"tp_hit": True, "sl_hit": True, "horizon_expire": True},
    prices={"entry": 1.1000, "tp_hit_price": 1.1008, "sl_hit_price": 1.0995, "final_price": 1.1008},
    timestamp="2025-10-22 16:00:00"
)
# => final_event="TP_hit" (優先順位1が最優先)
```

### ラベル生成への統合

```python
def generate_exit_label_with_priority(
    price_series: np.ndarray,
    entry_idx: int,
    tp_level: float,
    sl_level: float,
    horizon: int,
    direction: int  # 1=long, -1=short
) -> Dict[str, Any]:
    """
    優先順位考慮したラベル生成
    
    Args:
        price_series: 価格系列
        entry_idx: エントリーインデックス
        tp_level: TP価格
        sl_level: SL価格
        horizon: 最大保有期間
        direction: ポジション方向
    
    Returns:
        {
            "exit_event": str,
            "exit_bar": int,
            "exit_price": float,
            "pnl_pips": float,
            "compound_detected": bool
        }
    """
    resolver = ExitEventResolver()
    
    # 各イベントの発生を検出
    events = {"tp_hit": False, "sl_hit": False, "horizon_expire": False}
    prices = {"entry": price_series[entry_idx]}
    
    for i in range(entry_idx + 1, min(entry_idx + horizon + 1, len(price_series))):
        current_price = price_series[i]
        
        # TP判定
        if direction == 1 and current_price >= tp_level:
            events["tp_hit"] = True
            prices["tp_hit_price"] = tp_level
            prices["tp_hit_bar"] = i
        elif direction == -1 and current_price <= tp_level:
            events["tp_hit"] = True
            prices["tp_hit_price"] = tp_level
            prices["tp_hit_bar"] = i
        
        # SL判定
        if direction == 1 and current_price <= sl_level:
            events["sl_hit"] = True
            prices["sl_hit_price"] = sl_level
            prices["sl_hit_bar"] = i
        elif direction == -1 and current_price >= sl_level:
            events["sl_hit"] = True
            prices["sl_hit_price"] = sl_level
            prices["sl_hit_bar"] = i
        
        # ホライズン判定
        if i == entry_idx + horizon:
            events["horizon_expire"] = True
            prices["final_price"] = current_price
            prices["horizon_bar"] = i
        
        # いずれかのイベントが発火したら終了
        if any(events.values()):
            break
    
    # 複合イベント解決
    result = resolver.resolve_compound_event(events, prices, timestamp=None)
    
    # PnL計算
    exit_price = result["price"]
    pnl_pips = (exit_price - prices["entry"]) * direction * 10000
    
    return {
        "exit_event": result["final_event"],
        "exit_bar": prices.get(f"{result['final_event']}_bar", entry_idx + horizon),
        "exit_price": exit_price,
        "pnl_pips": pnl_pips,
        "compound_detected": result["compound_detected"],
        "compound_events": result.get("compound_events", []),
        "resolution_reason": result["reason"]
    }
```

**成功指標**:
- 複合発火検出率: 記録（典型的には1-3%）
- 複合発火時の優先順位適用率: 100%
- ラベル曖昧性: 0件（全て確定）

**検証**:
```python
def test_event_priority():
    """イベント優先順位の動作確認"""
    resolver = ExitEventResolver()
    
    # テスト1: TP優先
    result = resolver.resolve_compound_event(
        {"tp_hit": True, "horizon_expire": True, "sl_hit": False},
        {"tp_hit_price": 1.1008, "final_price": 1.1008},
        None
    )
    assert result["final_event"] == "TP_hit"
    assert result["compound_detected"] == True
    
    # テスト2: SL > horizon
    result = resolver.resolve_compound_event(
        {"tp_hit": False, "sl_hit": True, "horizon_expire": True},
        {"sl_hit_price": 1.0995, "final_price": 1.0995},
        None
    )
    assert result["final_event"] == "SL_hit"
    
    # テスト3: 単一イベント
    result = resolver.resolve_compound_event(
        {"tp_hit": True, "sl_hit": False, "horizon_expire": False},
        {"tp_hit_price": 1.1008},
        None
    )
    assert result["compound_detected"] == False
```

---

## 📚 関連仕様

- [VALIDATOR_SPEC.md](../VALIDATOR_SPEC.md) - 検証全体仕様
- [BACKTEST_EVALUATION_SPEC.md](./BACKTEST_EVALUATION_SPEC.md) - バックテスト詳細
- [COST_MODEL_SPEC.md](./COST_MODEL_SPEC.md) - コストモデル（TP/SL設定に影響）
- [TRAINER_SPEC.md](../TRAINER_SPEC.md) - モード切替ロジック

---

## 📝 変更履歴

- **2025-10-22**: 項目21対応追加
  - イベント優先順位定義（TP_hit > SL_hit > horizon_expire）
  - ExitEventResolver実装（複合発火解決）
  - ラベル生成統合例

- **2025-10-21**: 初版作成
  - 固定倍率（ATR×2.0）を廃止
  - Base値定義（Scalp: 0.8/0.5 pips、Swing: 2.0/trailing）
  - 3段階調整メカニズム（Volatility/Confidence/Time-of-Day）
  - 統合実装クラス（DynamicExitStrategy）
  - バックテスト検証計画
