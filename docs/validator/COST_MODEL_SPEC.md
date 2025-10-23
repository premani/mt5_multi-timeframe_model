# COST_MODEL_SPEC.md

**バージョン**: 1.0  
**更新日**: 2025-10-21  
**責任者**: core-team

---

## 📋 目的

FX自動売買における**取引コスト**を現実的にモデル化し、デュアルモード（scalp/swing）戦略のバックテスト・学習・評価で使用する統一的なコスト計算基準を定義する。

---

## 💰 コスト構成要素

### 全体構造

```python
total_cost = spread_cost + slippage_cost + commission + rejection_penalty

# 期待値計算
net_expectancy = E[price_change] - total_cost
```

---

## 📊 各コスト詳細

### 1. スプレッドコスト（Spread Cost）

#### 基本定義

```yaml
spread_cost:
  # 通貨ペア別の典型値（pips）
  EURUSD:
    normal_hours: 0.8 - 1.2    # ロンドン・NY重複時
    quiet_hours: 1.5 - 2.5     # アジア時間・早朝
    news_event: 3.0 - 8.0      # 重要指標発表時
  
  USDJPY:
    normal_hours: 0.6 - 1.0
    quiet_hours: 1.2 - 2.0
    news_event: 2.5 - 6.0
  
  GBPUSD:
    normal_hours: 1.0 - 1.5
    quiet_hours: 2.0 - 3.5
    news_event: 4.0 - 10.0
```

#### モデル実装（デュアルモード対応）

```python
class SpreadModel:
    """
    動的スプレッドモデル
    """
    def __init__(self, pair: str = "EURUSD"):
        self.pair = pair
        self.base_spread = {
            "normal": 1.0,     # pips（ロンドン・NY重複時）
            "quiet": 2.0,      # pips（アジア時間）
            "news": 5.0        # pips（重要指標時）
        }
    
    def get_spread(self, timestamp: datetime, regime: str = "normal") -> float:
        """
        タイムスタンプとレジームに基づきスプレッドを返す
        
        Args:
            timestamp: 取引時刻
            regime: 'normal', 'quiet', 'news'
        
        Returns:
            spread in pips
        """
        hour = timestamp.hour
        
        # 時間帯判定
        if regime == "news":
            return self.base_spread["news"]
        elif 8 <= hour < 10 or 14 <= hour < 16:  # 指標発表が多い時間
            return self.base_spread["normal"] * 1.3
        elif 0 <= hour < 6:  # アジア早朝
            return self.base_spread["quiet"]
        else:  # 通常時間
            return self.base_spread["normal"]
    
    def get_spread_distribution(self) -> dict:
        """
        スプレッド分布（バックテスト用）
        
        Returns:
            {'mean': 1.2, 'std': 0.4, 'p95': 2.0}
        """
        return {
            "mean": 1.2,
            "std": 0.4,
            "p95": 2.0,
            "p99": 3.5
        }
```

---

### 2. スリッページコスト（Slippage Cost）

#### 問題：旧モデルの過小評価

```yaml
# ❌ 旧仕様（非現実的）
slippage: 0.3 pips  # あまりに楽観的

# ✅ 新仕様（現実的）
slippage:
  scalp_mode:    0.8 - 1.5 pips  # 短期・高頻度
  swing_mode:    0.5 - 1.0 pips  # 長期・低頻度
  market_order:  1.0 - 2.0 pips  # 成行注文
  limit_order:   0.3 - 0.8 pips  # 指値注文（約定前提）
```

#### スリッページモデル

```python
class SlippageModel:
    """
    取引モード・注文タイプ・ボラティリティに応じたスリッページ
    """
    def __init__(self):
        self.base_slippage = {
            "scalp_market": 1.2,   # pips（スキャルピング・成行）
            "scalp_limit": 0.6,    # pips（スキャルピング・指値）
            "swing_market": 0.8,   # pips（スイング・成行）
            "swing_limit": 0.4     # pips（スイング・指値）
        }
    
    def get_slippage(
        self,
        mode: str,              # 'scalp' or 'swing'
        order_type: str,        # 'market' or 'limit'
        atr: float,             # Average True Range
        volatility_regime: str  # 'low', 'normal', 'high'
    ) -> float:
        """
        動的スリッページ計算
        
        Returns:
            slippage in pips
        """
        # 基本スリッページ
        key = f"{mode}_{order_type}"
        base = self.base_slippage.get(key, 1.0)
        
        # ボラティリティ調整
        vol_multiplier = {
            "low": 0.7,
            "normal": 1.0,
            "high": 1.5,
            "extreme": 2.5  # スプレッド急拡大時
        }.get(volatility_regime, 1.0)
        
        # ATR比例成分（オプション）
        atr_component = min(atr * 0.05, 0.5)  # ATRの5%、最大0.5 pips
        
        return base * vol_multiplier + atr_component
    
    def get_slippage_distribution(self, mode: str) -> dict:
        """
        モード別スリッページ分布（モンテカルロシミュレーション用）
        """
        if mode == "scalp":
            return {
                "mean": 1.2,
                "std": 0.4,
                "min": 0.5,
                "p50": 1.1,
                "p95": 2.0,
                "p99": 2.8
            }
        else:  # swing
            return {
                "mean": 0.8,
                "std": 0.3,
                "min": 0.3,
                "p50": 0.7,
                "p95": 1.3,
                "p99": 1.8
            }
```

#### 確率的スリッページ（バックテスト用）

```python
def sample_slippage(mode: str, order_type: str, rng: np.random.Generator) -> float:
    """
    確率分布からスリッページをサンプリング
    
    Args:
        mode: 'scalp' or 'swing'
        order_type: 'market' or 'limit'
        rng: numpy random generator
    
    Returns:
        sampled slippage in pips
    """
    if mode == "scalp" and order_type == "market":
        # 対数正規分布（右側に長い裾）
        mu, sigma = 0.0, 0.4
        slip = np.exp(mu + sigma * rng.normal()) * 1.2
        return np.clip(slip, 0.5, 3.0)
    
    elif mode == "swing" and order_type == "market":
        # 正規分布（中央集中）
        slip = rng.normal(0.8, 0.3)
        return np.clip(slip, 0.3, 2.0)
    
    else:  # limit orders
        # 低めの正規分布
        slip = rng.normal(0.5, 0.2)
        return np.clip(slip, 0.1, 1.2)
```

---

### 3. 手数料（Commission）

```yaml
commission:
  # ブローカー別（pips換算）
  standard:
    per_lot: 0.0           # pips（多くのFXブローカーは無料）
    per_trade: 0.0
  
  ecn_broker:
    per_lot: 0.3 - 0.5     # pips（ECNブローカー）
    round_trip: 0.6 - 1.0  # 往復
  
  # 本プロジェクト設定
  default: 0.0             # スプレッドに含まれると仮定
```

**理由**: 多くのFXブローカーは手数料無料でスプレッドに含める形式のため、デフォルト0.0とする。ECNブローカー使用時は適宜設定。

---

### 4. 注文拒否ペナルティ（Rejection Penalty）

#### 新規追加要素

```yaml
order_rejection:
  probability: 0.03 - 0.05   # 3-5%の注文が拒否される
  scenarios:
    - insufficient_liquidity  # 流動性不足
    - price_moved            # 価格スリップ大
    - broker_delay           # ブローカー処理遅延
    - requote               # リクオート
  
  penalty:
    missed_opportunity: E[profit] × rejection_rate
    time_cost: latency_ms × opportunity_cost_factor
```

#### モデル実装

```python
class RejectionModel:
    """
    注文拒否確率と機会損失
    """
    def __init__(self, base_rejection_rate: float = 0.04):
        self.base_rate = base_rejection_rate  # 4%基準
    
    def get_rejection_probability(
        self,
        mode: str,              # 'scalp' or 'swing'
        spread: float,          # current spread in pips
        atr: float,             # volatility measure
        time_of_day: int        # hour (0-23)
    ) -> float:
        """
        注文拒否確率を計算
        
        Returns:
            probability (0.0 - 1.0)
        """
        rate = self.base_rate
        
        # スキャルピングは拒否率高め（流動性消費）
        if mode == "scalp":
            rate *= 1.3
        
        # スプレッド拡大時は拒否率上昇
        if spread > 2.0:
            rate *= 1.5
        elif spread > 3.0:
            rate *= 2.0
        
        # 流動性低下時間帯
        if 0 <= time_of_day < 6:  # アジア早朝
            rate *= 1.4
        
        return min(rate, 0.15)  # 最大15%
    
    def apply_rejection(
        self,
        expected_profit: float,
        rejection_prob: float,
        rng: np.random.Generator
    ) -> tuple[bool, float]:
        """
        注文拒否シミュレーション
        
        Returns:
            (rejected: bool, actual_profit: float)
        """
        rejected = rng.random() < rejection_prob
        
        if rejected:
            # 機会損失
            return True, 0.0
        else:
            return False, expected_profit
```

---

## 🎯 統合コストモデル

### デュアルモード対応

```python
class IntegratedCostModel:
    """
    デュアルモード戦略の統合コストモデル
    """
    def __init__(self, pair: str = "EURUSD"):
        self.spread_model = SpreadModel(pair)
        self.slippage_model = SlippageModel()
        self.rejection_model = RejectionModel()
    
    def calculate_total_cost(
        self,
        mode: str,              # 'scalp' or 'swing'
        order_type: str,        # 'market' or 'limit'
        timestamp: datetime,
        atr: float,
        regime: str = "normal",
        include_rejection: bool = True
    ) -> dict:
        """
        総コスト計算
        
        Returns:
            {
                'spread': float,
                'slippage': float,
                'commission': float,
                'rejection_prob': float,
                'total_cost': float,
                'expected_cost': float  # 拒否率考慮
            }
        """
        # 各コスト計算
        spread = self.spread_model.get_spread(timestamp, regime)
        slippage = self.slippage_model.get_slippage(
            mode, order_type, atr, regime
        )
        commission = 0.0  # デフォルト
        
        total_cost = spread + slippage + commission
        
        # 注文拒否考慮
        if include_rejection:
            rejection_prob = self.rejection_model.get_rejection_probability(
                mode, spread, atr, timestamp.hour
            )
            expected_cost = total_cost / (1 - rejection_prob)
        else:
            rejection_prob = 0.0
            expected_cost = total_cost
        
        return {
            "spread": spread,
            "slippage": slippage,
            "commission": commission,
            "rejection_prob": rejection_prob,
            "total_cost": total_cost,
            "expected_cost": expected_cost
        }
    
    def get_cost_summary(self, mode: str) -> dict:
        """
        モード別コスト統計
        """
        if mode == "scalp":
            return {
                "mean_cost": 2.2,      # pips（spread 1.2 + slippage 1.0）
                "p50_cost": 2.0,
                "p95_cost": 4.0,
                "rejection_rate": 0.05,
                "effective_cost": 2.3   # 拒否率考慮
            }
        else:  # swing
            return {
                "mean_cost": 1.8,      # pips（spread 1.2 + slippage 0.6）
                "p50_cost": 1.7,
                "p95_cost": 3.0,
                "rejection_rate": 0.03,
                "effective_cost": 1.9
            }
```

---

## 📊 設定例

### バックテスト用設定

```yaml
# config/cost_model_config.yaml

cost_model:
  pair: EURUSD
  
  spread:
    mode: dynamic             # 'static' or 'dynamic'
    static_value: 1.2         # pips（static時）
    dynamic_params:
      normal_hours: 1.0
      quiet_hours: 2.0
      news_event: 5.0
  
  slippage:
    mode: probabilistic       # 'static', 'dynamic', 'probabilistic'
    scalp:
      market: 1.2             # pips
      limit: 0.6
    swing:
      market: 0.8
      limit: 0.4
    distribution: lognormal   # 'normal' or 'lognormal'
  
  commission:
    per_trade: 0.0            # pips
    per_lot: 0.0
  
  rejection:
    enabled: true
    base_rate: 0.04           # 4%
    scalp_multiplier: 1.3
    spread_threshold: 2.0     # pips（超えると拒否率上昇）
```

### 学習用設定（期待値計算）

```yaml
# TRAINER_SPEC.mdで使用

training:
  cost_model:
    # 学習時は保守的に見積もる
    spread: 1.5               # pips（p75相当）
    slippage:
      scalp: 1.5
      swing: 1.0
    commission: 0.0
    rejection_penalty: 0.05   # 5%機会損失
    
    # 期待値計算
    net_expectancy_formula: |
      E[price_change] - (spread + slippage) * (1 + rejection_rate)
```

---

## 🎯 旧仕様との比較

| 項目 | 旧仕様 | 新仕様 | 理由 |
|------|--------|--------|------|
| **スプレッド** | 1.2 pips固定 | 0.8-2.5 pips動的 | 時間帯・レジーム考慮 |
| **スリッページ** | 0.3 pips固定 ❌ | 0.8-1.5 pips動的 ✅ | 非現実的→現実的へ |
| **手数料** | 0.0 pips | 0.0 pips（継続） | FXブローカー標準 |
| **注文拒否** | 未考慮 ❌ | 3-5%考慮 ✅ | 機会損失を反映 |
| **モード別** | 未分離 | scalp/swing分離 ✅ | デュアルモード対応 |
| **総コスト** | ~1.5 pips | ~2.2-2.3 pips | **46%増（現実的）** |

---

## 🔄 既存仕様書の更新箇所

### 1. VALIDATOR_SPEC.md

```yaml
# 修正前
cost_model:
  spread: 1.2
  slippage: 0.3  # ❌ 非現実的
  commission: 0.0

# 修正後
cost_model:
  spread: 1.2              # pips（通常時）
  slippage:
    scalp: 1.2             # pips（現実的）
    swing: 0.8
  commission: 0.0
  rejection_rate: 0.04     # 4%注文拒否
```

### 2. TRAINER_SPEC.md

```python
# 期待値計算の更新

# 修正前
NetExpectancy = E[ΔP] - (spread + slippage + commission)

# 修正後
NetExpectancy = E[ΔP] - (spread + slippage) × (1 + rejection_rate)

# スキャルピングモード例
# E[ΔP] = 1.5 pips（予測）
# spread = 1.2 pips
# slippage = 1.2 pips
# rejection_rate = 0.05
# => NetExpectancy = 1.5 - (1.2 + 1.2) × 1.05 = 1.5 - 2.52 = -1.02 pips ❌
# 
# ⚠️ 小さな予測利益では期待値がマイナスになる可能性
# => 信頼度閾値・エントリー条件の厳格化が必要
```

---

## 🚨 影響分析

### 期待値への影響

```python
# 旧コストモデル
old_cost = 1.2 (spread) + 0.3 (slippage) = 1.5 pips

# 新コストモデル（scalp mode）
new_cost = 1.2 (spread) + 1.2 (slippage) = 2.4 pips
new_cost_effective = 2.4 × 1.05 (rejection) = 2.52 pips

# 差分
increase = 2.52 - 1.5 = +1.02 pips (+68%)
```

### 必要な予測精度

```python
# Break-even point（損益分岐点）

# 旧モデル: 1.5 pips以上の予測利益で黒字
required_profit_old = 1.5 pips

# 新モデル: 2.52 pips以上の予測利益で黒字
required_profit_new = 2.52 pips

# 必要精度の上昇
accuracy_increase = (2.52 - 1.5) / 1.5 = +68%
```

**結論**: コストモデルを現実的にすると、**より高い予測精度またはより厳格なエントリー条件**が必要になる。

---

## 🎯 推奨対応策

### 1. エントリー閾値の引き上げ

```yaml
# 旧設定
entry_threshold:
  min_confidence: 0.60
  min_expectancy: 0.0       # pips

# 新設定（コスト反映）
entry_threshold:
  min_confidence: 0.65      # 5%引き上げ
  min_expectancy: 1.0       # pips（最低1 pips利益）
```

### 2. 取引頻度の削減

```python
# コスト増加に対応して勝率の高いトレードに絞る
expected_trade_reduction = 0.3  # 30%減少予測
expected_profitability_increase = 0.5  # 50%改善期待
```

### 3. スイングモード比率の増加

```yaml
# デュアルモード比率の調整

# 基本設計（README.mdに準拠）
scalp_ratio: 0.70 - 0.80    # スキャルプ基本モード 70-80%
swing_ratio: 0.20 - 0.30    # スイング拡張モード 20-30%

# 標準値（バックテスト・学習用）
scalp_ratio: 0.75    # 75%
swing_ratio: 0.25    # 25%

# コスト最適化時の調整例
scalp_ratio: 0.70    # 70%（最小値）
swing_ratio: 0.30    # 30%（最大値）

# 理由: スイングモードはコストが低い（1.9 pips vs 2.5 pips）が、
#       基本設計の70-80%/20-30%の範囲内で最適化する
```

---

## 📝 Phase別実装計画

### 実装フェーズ1: 基盤実装
- ✅ 統合コストモデルクラス実装
- ✅ スプレッド・スリッページ動的計算
- ✅ 注文拒否シミュレーション
- ✅ VALIDATOR_SPEC.md 設定更新

### 実装フェーズ2: バックテスト統合
- ⏳ 確率的スリッページサンプリング
- ⏳ 時間帯別スプレッド適用
- ⏳ 拒否率による期待値補正
- ⏳ コスト分布レポート出力

### 実装フェーズ3: 学習統合
- ⏳ TRAINER_SPEC.md 損失関数更新
- ⏳ 期待値ヘッドへのコスト反映
- ⏳ 閾値最適化（コスト考慮）

---

## 🔗 関連仕様書

- **親仕様**: `docs/VALIDATOR_SPEC.md`
- **バックテスト**: `docs/validator/BACKTEST_EVALUATION_SPEC.md`
- **学習仕様**: `docs/TRAINER_SPEC.md`
- **レイテンシ**: `docs/validator/EXECUTION_LATENCY_SPEC.md`

---

## 📚 参考資料

### FX取引コスト
- "Trading and Exchanges" by Larry Harris - Chapter 3: Trading Costs
- FXCM Research: "Understanding Slippage in Forex Trading"
- Dukascopy: "ECN Trading and Commission Structure"

### スリッページモデル
- Almgren & Chriss (2000): "Optimal Execution of Portfolio Transactions"
- Kissell et al. (2004): "Understanding the Profit and Loss Distribution of Trading Algorithms"

---

**更新履歴**:
- 2025-10-21: 初版作成（デュアルモード対応、現実的コストモデル定義）
