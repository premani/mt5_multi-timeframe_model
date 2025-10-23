# BACKTEST_EVALUATION_SPEC.md# BACKTEST_EVALUATION_SPEC.md



**バージョン**: 1.0  ## 目的

**更新日**: 2025-10-21期待値・リスク指標を簡易シミュレーションで算出しモデル有効性を検証。



---## 入力

- 推論結果: direction_probs[h], magnitude_dist, hazard_prob, net_expectancy

## 📋 目的- 価格系列: close/high/low



期待値・リスク指標を簡易シミュレーションで算出し、モデルの有効性を検証する。## シミュレーションルール

1. エントリー判定: `net_expectancy > 0` AND `max(direction_prob) > τ_dir`

---2. TP/SL 設定: TP=ATR*k_tp, SL=ATR*k_sl

3. 期間: 対応 horizon h

## 📥 入力4. 到達判定順序: TP → SL → horizon終値

5. リターン記録: +TP / -SL / (close_{t+h}-close_t)

- **推論結果**: direction_probs[h], magnitude_dist, hazard_prob, net_expectancy

- **価格系列**: close/high/low## 指標算出

- WinRate = wins / trades

---- ProfitFactor = sum_positive / |sum_negative|

- PayoffRatio = avg_positive / |avg_negative|

## 🔄 シミュレーションルール- CostAdjustedExpectancy = mean(net_expectancy)

- MAE/MFE: 各トレード最大逆行/最大順行平均

### 1. エントリー判定- DrawdownMax: 累積損失ピーク

```python

if net_expectancy > 0 and max(direction_prob) > θ_dir:## JSON フォーマット

    entry = True```

```{

  "trades": N,

### 2. TP/SL設定  "win_rate": 0.56,

```python  "profit_factor": 1.45,

TP = ATR × k_tp  # 例: 2.0  "payoff_ratio": 1.32,

SL = ATR × k_sl  # 例: 1.0  "mae": 0.8,

```  "mfe": 1.6,

  "drawdown_max": -2.4,

### 3. 到達判定順序  "cost_adjusted_expectancy": 0.12,

TP → SL → horizon終値  "direction_accuracy": {"r_025":0.71,...},

  "config_hash": "...",

### 4. リターン記録  "commit_hash": "..."

- TP到達: +TP}

- SL到達: -SL```

- タイムアウト: close_{t+h} - close_t

## エラー条件

---- trades < min_trades → 統計信頼性不足

- profit_factor NaN (無トレード) → 0 で埋め + 警告

## 📊 算出指標

## 拡張

| 指標 | 計算式 | 目的 |- 滑りモデル: ボラティリティ閾値で動的 spread 増分

|------|--------|------|- 複数 horizon 同時ポートフォリオ評価

| Win Rate | wins / trades | 勝率 |- Monte Carlo ランダム化 (エントリー時刻シフト)

| Profit Factor | sum_positive / abs(sum_negative) | 収益性 |
| Payoff Ratio | avg_positive / abs(avg_negative) | リスクリワード |
| Cost-Adjusted Expectancy | mean(net_expectancy) | コスト考慮期待値 |
| MAE | mean(max_adverse_excursion) | 最大逆行平均 |
| MFE | mean(max_favorable_excursion) | 最大順行平均 |
| Max Drawdown | 累積損失ピーク | 最大ドローダウン |

---

## 📄 JSON出力フォーマット

```json
{
  "trades": 1250,
  "win_rate": 0.56,
  "profit_factor": 1.45,
  "payoff_ratio": 1.32,
  "mae": 0.8,
  "mfe": 1.6,
  "drawdown_max": -2.4,
  "cost_adjusted_expectancy": 0.12,
  "direction_accuracy": {
    "r_025": 0.71,
    "r_050": 0.68,
    "r_100": 0.63
  },
  "config_hash": "abc123...",
  "commit_hash": "def456..."
}
```

---

## 🚨 エラー条件

- `trades < min_trades` → 統計信頼性不足（WARNING）
- `profit_factor` NaN（無トレード） → 0で埋め + 警告

---

## 項目116対応: Fill模擬決定性検証

**目的**: 並列実行時にランダム性（hash順序、浮動小数誤差蓄積）で約定タイミング・順序がズレる → バックテスト結果が不定

**解決策**: 並列実行とシリアル実行の結果を完全一致検証

```python
class BacktestDeterminismValidator:
    """Fill模擬決定性検証"""
    
    def __init__(self, config: dict):
        self.seed = config.get("seed", 42)
        self.parallel_workers = config.get("parallel_workers", 4)
        self.tolerance = config.get("float_tolerance", 1e-9)
    
    def validate_determinism(self, backtest_engine, test_data: dict) -> bool:
        """
        並列/シリアル実行の結果一致性検証
        
        Args:
            backtest_engine: バックテストエンジンインスタンス
            test_data: テストデータ（price, signals）
        
        Returns:
            is_deterministic: True=一致、False=不一致
        """
        import multiprocessing as mp
        
        # 1. シリアル実行（シード固定）
        np.random.seed(self.seed)
        torch.manual_seed(self.seed)
        
        serial_results = backtest_engine.run(
            test_data,
            parallel=False
        )
        
        # 2. 並列実行（シード固定）
        np.random.seed(self.seed)
        torch.manual_seed(self.seed)
        
        # ワーカープロセスごとにシード設定
        def init_worker(seed):
            np.random.seed(seed)
            torch.manual_seed(seed)
        
        with mp.Pool(
            processes=self.parallel_workers,
            initializer=init_worker,
            initargs=(self.seed,)
        ) as pool:
            parallel_results = backtest_engine.run(
                test_data,
                parallel=True,
                pool=pool
            )
        
        # 3. 結果比較
        is_deterministic = self._compare_results(
            serial_results,
            parallel_results
        )
        
        return is_deterministic
    
    def _compare_results(self, serial: dict, parallel: dict) -> bool:
        """
        結果詳細比較
        
        Args:
            serial: シリアル実行結果
            parallel: 並列実行結果
        
        Returns:
            is_equal: 完全一致ならTrue
        """
        # トレード数一致
        if serial["trades"] != parallel["trades"]:
            logger.error(
                f"トレード数不一致: serial={serial['trades']}, "
                f"parallel={parallel['trades']}"
            )
            return False
        
        # 指標値一致（浮動小数許容範囲内）
        metrics = ["win_rate", "profit_factor", "payoff_ratio", 
                  "drawdown_max", "cost_adjusted_expectancy"]
        
        for metric in metrics:
            diff = abs(serial[metric] - parallel[metric])
            if diff > self.tolerance:
                logger.error(
                    f"{metric}不一致: serial={serial[metric]:.6f}, "
                    f"parallel={parallel[metric]:.6f}, diff={diff:.2e}"
                )
                return False
        
        # トレードログ一致
        if "trade_log" in serial and "trade_log" in parallel:
            serial_log = serial["trade_log"]
            parallel_log = parallel["trade_log"]
            
            if len(serial_log) != len(parallel_log):
                logger.error(
                    f"トレードログ長不一致: serial={len(serial_log)}, "
                    f"parallel={len(parallel_log)}"
                )
                return False
            
            # 各トレード詳細比較
            for i, (s_trade, p_trade) in enumerate(zip(serial_log, parallel_log)):
                if s_trade["entry_time"] != p_trade["entry_time"]:
                    logger.error(
                        f"Trade#{i} エントリー時刻不一致: "
                        f"serial={s_trade['entry_time']}, "
                        f"parallel={p_trade['entry_time']}"
                    )
                    return False
                
                if abs(s_trade["pnl"] - p_trade["pnl"]) > self.tolerance:
                    logger.error(
                        f"Trade#{i} PnL不一致: serial={s_trade['pnl']:.4f}, "
                        f"parallel={p_trade['pnl']:.4f}"
                    )
                    return False
        
        logger.info("✅ 決定性検証: 並列/シリアル完全一致")
        return True


# 使用例: バックテスト実行前の検証
validator = BacktestDeterminismValidator({
    "seed": 42,
    "parallel_workers": 4,
    "float_tolerance": 1e-9
})

# サンプルデータで検証
is_deterministic = validator.validate_determinism(
    backtest_engine=my_backtest_engine,
    test_data=sample_test_data
)

if not is_deterministic:
    raise RuntimeError("バックテスト決定性検証失敗: 並列実行結果が不定")

# 検証成功後に本番バックテスト実行
final_results = my_backtest_engine.run(
    production_data,
    parallel=True
)
```

**決定性検証仕様**:
- **seed固定**: np.random + torch シード固定
- **並列/シリアル比較**: トレード数、指標値、トレードログ完全一致
- **float_tolerance**: 1e-9（浮動小数誤差許容範囲）
- **成功指標**: 決定性検証失敗率 = 0%

**効果**:
- 並列実行時の再現性保証
- デバッグ時の予測可能性向上
- CI/CDでの自動検証可能

---

## 🔗 参照

- **親仕様書**: `docs/VALIDATOR_SPEC.md`

---

## 🔮 将来拡張

- スリッページモデル: ボラティリティ閾値で動的spread増分
- 複数horizon同時ポートフォリオ評価
- Monte Carloランダム化（エントリー時刻シフト）

---

## スリッページモデル

### スリッページ循環依存モデル化

**目的**: 固定slippage（0.3 pips）は市場影響・流動性無視

**解決策**: 注文サイズ・ボラティリティ依存モデル

```python
class SlippageModel:
    """スリッページモデル"""
    
    def __init__(self, config: dict):
        self.base_slippage_pips = config.get("base_slippage_pips", 0.3)
        self.volatility_multiplier = config.get("volatility_multiplier", 0.5)
        self.size_multiplier = config.get("size_multiplier", 0.1)
    
    def estimate_slippage(
        self,
        order_size_lots: float,
        atr_current: float,
        atr_baseline: float
    ) -> float:
        """
        スリッページ推定
        
        Args:
            order_size_lots: 注文サイズ（ロット）
            atr_current: 現在ATR
            atr_baseline: 通常時ATR
        
        Returns:
            slippage_pips: 推定スリッページ
        """
        # ベーススリッページ
        slip = self.base_slippage_pips
        
        # ボラティリティ補正
        vol_ratio = atr_current / atr_baseline if atr_baseline > 0 else 1.0
        slip += self.volatility_multiplier * (vol_ratio - 1.0)
        
        # サイズ補正（0.1ロット超で増加）
        if order_size_lots > 0.1:
            slip += self.size_multiplier * (order_size_lots - 0.1)
        
        return max(slip, 0.1)  # 最小0.1 pips


# 使用例
slip_model = SlippageModel({
    "base_slippage_pips": 0.3,
    "volatility_multiplier": 0.5,
    "size_multiplier": 0.1
})

# バックテスト内
for trade in backtest_trades:
    slip = slip_model.estimate_slippage(
        order_size_lots=trade.size,
        atr_current=trade.atr,
        atr_baseline=historical_atr_median
    )
    
    # コスト計算
    total_cost = spread + slip + commission
    net_pips = trade.magnitude - total_cost
```

**スリッページ推定式**:
```
slip = base + volatility_factor * (ATR_ratio - 1) + size_factor * (size - 0.1)
```

**KPI（項目30）**: スリッページ推定誤差<0.2 pips、実測比較R²>0.5
