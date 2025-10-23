# MICROSTRUCTURE_SPEC.md

**バージョン**: 1.0  
**更新日**: 2025-10-21

---

## 📋 目的

Tickレベルのマイクロ構造原始データを収集段階で保存し、後段の特徴量計算で派生指標を生成できる基盤を提供する。

---

## 🎯 スコープ

### 対象
直近保持Tickシーケンス (`/ticks_recent`) に追加する原始列

### 非対象
- 板情報（Depth）
- 実際の約定aggressor/fill情報（MT5 API制約）

---

## 📊 原始列定義

| 列名 | 型 | 計算 | 目的 |
|------|----|------|------|
| `inter_arrival_ms` | int32 | (t_i - t_{i-1}) × 1000 | 流動性/到着頻度 |
| `direction_flag` | int8 | sign(mid_i - mid_{i-1}) ∈ {-1, 0, 1} | 瞬間方向 |
| `signed_volume` | float32 | direction_flag × volume | フロー方向強度 |
| `spread_recalc` | float32 | ask - bid | 検算/品質 |
| `mid_price` | float64 | (bid + ask) / 2 | 参考価格 |

**注**: 
- 先頭tickの`inter_arrival_ms`は0
- `mid_price` = (bid + ask) / 2

---

## 📈 品質指標

`/metadata/microstructure_stats` に保存:

| 指標 | 説明 |
|------|------|
| `tick_frequency_mean` | ticks / timespan |
| `tick_frequency_p95` | inter_arrival_ms p95の逆数換算 |
| `inter_arrival_ms_p50/p95/p99` | 到着間隔統計 |
| `direction_flip_rate` | flips / (ticks-1) |
| `spread_jump_count` | jump events ≥ threshold |

---

## ✅ 検証条件

| 条件 | 失敗時アクション |
|------|------------------|
| `inter_arrival_ms` < 0 | 当該tick破棄 + カウンタ増加 |
| `inter_arrival_ms_p95` > `max_inter_arrival_ms` | WARNING |
| `direction_flag` ∉ {-1, 0, 1} | ERROR停止 |
| `spread_recalc` < 0 | ERROR停止 |
| `signed_volume` NaN/Inf | 該当行除外 + integrity increment |

---

## 🔄 エッジケース

- **週末明けギャップ**: 最初tickの`inter_arrival_ms`大 → 統計含むが判定除外
- **休場中断片**: `session_flag`でマーク → 後段でマスク
- **スプレッド異常拡大**: jump閾値超過イベントとして記録

---

## 📝 ログ出力

**注記**: ログは日本時間(JST)で表示されます。詳細: [docs/utils/TIMEZONE_UTILS_SPEC.md](../utils/TIMEZONE_UTILS_SPEC.md)

最小限の情報:
```
🧪 マイクロ構造統計
   inter_arrival_ms_p95=850ms
   direction_flip_rate=0.42
   spread_jump_count=8
   
⚠️ 異常検知
   negative_spread=0件
   negative_inter_arrival=0件
   NaN_signed_volume=0件
```

---

## 🔗 前処理での二次利用例

| 指標 | 計算例 |
|------|--------|
| `tick_rate_ema` | EMA(inter_arrival_ms^{-1}) |
| `directional_imbalance` | rolling_sum(signed_volume, w) / rolling_sum(abs(signed_volume), w) |
| `micro_vol_ratio` | std(mid_price_delta, short) / std(mid_price_delta, long) |
| `spread_zscore` | (spread_recalc - rolling_mean) / rolling_std |

---

## 🔗 参照

- **親仕様書**: `docs/DATA_COLLECTOR_SPEC.md`
- **Tick設定**: `config.ticks.microstructure_raw`

---

## 🔮 将来拡張

- aggressor推定（価格変化方向 + spread変化パターン）
- order book depth統合後のqueue imbalance
- dollar_bar / run_bar追加
