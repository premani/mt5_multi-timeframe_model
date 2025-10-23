# MULTI_TF_FUSION_SPEC.md

**バージョン**: 1.0  
**更新日**: 2025-10-21  
**責任者**: core-team

---

## 📋 目的

マルチタイムフレーム（M1/M5/M15/H1/H4）の特徴量を統合し、スケール不変なパターン認識を実現するための融合機構の詳細仕様を定義する。

---

## 🎯 設計原則

### 1. パターン中心アプローチ

人間トレーダーのチャート判断を模倣:
- **ダブルトップ**: 2つの山の形状（時間幅は可変）
- **レンジブレイク**: 高値/安値の突破（何本前かは不問）
- **トレンド転換**: 上昇→下降のリズム（期間は結果的に決まる）

### 2. 最大公約数的な固定窓

```yaml
設計思想:
- 固定窓 = 「パターン検出に十分な最大長」
- Attention = 「窓内で動的にパターン抽出」
- 結果 = 同一窓内で50本のパターンも200本のパターンも認識可能
```

### 3. スケール不変性

各タイムフレームは**同じ時間範囲を異なる解像度で観測**:
- M1: 詳細な波形（ノイズ多、エントリー精度高）
- H4: 大局的トレンド（滑らか、レジーム判定用）

---

## 📏 シーケンス長定義

### 各TFの固定窓サイズ

| TF | 本数 | カバー時間 | 主な用途 | 想定パターン例 |
|----|------|-----------|---------|---------------|
| **M1** | 480 | 8時間 | 短期エントリー、マイクロパターン | スキャルプ用ダブルトップ（30-60本） |
| **M5** | 288 | 24時間 | 短期トレンド、スキャルプセットアップ | デイトレ用レンジ（50-150本） |
| **M15** | 192 | 48時間 | 中期トレンド、スイングセットアップ | スイング用三角持ち合い（80-120本） |
| **H1** | 96 | 96時間（4日） | 主要トレンド、日足構造 | 週足レベルのトレンド転換（40-80本） |
| **H4** | 48 | 192時間（8日） | レジーム検出、マクロバイアス | 月足レベルの大局観（20-40本） |

### 設計根拠

1. **M1 (480本 = 8時間)**
   - スキャルプ用パターンは通常30-120分で完結
   - 8時間窓で複数パターンを学習可能
   
2. **M5 (288本 = 24時間)**
   - デイトレ用の小波動は4-12時間
   - 1日窓で朝・昼・夕の複数セットアップをカバー
   
3. **M15 (192本 = 48時間)**
   - スイング用セットアップは12-36時間
   - 2日窓で週初・週央のパターン変化を捉える
   
4. **H1 (96本 = 4日)**
   - 週足レベルのトレンドは2-5日で形成
   - 4日窓で週全体の流れを把握
   
5. **H4 (48本 = 8日)**
   - 月足レベルの大局は1-3週間
   - 8日窓でレジーム変化（トレンド/レンジ切替）を検出

### 動的パターン抽出の例

```python
# M5足288本の窓内で異なる長さのパターンを検出

# 例1: 短いダブルトップ（50本 ≈ 4時間）
# [0]---[238]---[288(現在)]
#       ↑山1 ↑山2
# Attention weights: 直近50本に集中 (weight > 0.6)

# 例2: 長いレンジ（200本 ≈ 17時間）
# [0]---[88]---[288(現在)]
#       ↑レンジ開始
# Attention weights: 広範囲に分散 (weight = 0.3-0.5)

# 例3: 複数パターン同時検出
# [0]---[100]---[200]---[288(現在)]
#       ↑三角持合  ↑ブレイク
# Attention weights: 2つのピーク (multi-head対応)
```

---

## 🏗️ アーキテクチャ詳細

### 全体構造

```
入力: マルチTF特徴量
├─ X_M1:  [batch, 480, features]
├─ X_M5:  [batch, 288, features]
├─ X_M15: [batch, 192, features]
├─ X_H1:  [batch, 96, features]
└─ X_H4:  [batch, 48, features]

↓ 各TF独立エンコード

TFエンコーダ層（LSTM）
├─ LSTM_M1:  [batch, 480, features] → [batch, 480, d_model]
├─ LSTM_M5:  [batch, 288, features] → [batch, 288, d_model]
├─ LSTM_M15: [batch, 192, features] → [batch, 192, d_model]
├─ LSTM_H1:  [batch, 96, features] → [batch, 96, d_model]
└─ LSTM_H4:  [batch, 48, features] → [batch, 48, d_model]

↓ Self-Attention（各TF内でパターン抽出）

Self-Attention層
├─ SelfAttn_M1:  [batch, 480, d_model] → [batch, d_model]
├─ SelfAttn_M5:  [batch, 288, d_model] → [batch, d_model]
├─ SelfAttn_M15: [batch, 192, d_model] → [batch, d_model]
├─ SelfAttn_H1:  [batch, 96, d_model] → [batch, d_model]
└─ SelfAttn_H4:  [batch, 48, d_model] → [batch, d_model]

↓ TFサマリーベクトル統合

Cross-TF Fusion
└─ H_all: [batch, 5, d_model]  # 5 TFs

↓ TF間の関係学習

Cross-TF Attention
└─ fused: [batch, d_model]

↓ モード別重み付け（オプション）

Mode-Specific Weighting
├─ Scalp Mode:  [0.35, 0.30, 0.20, 0.10, 0.05]
└─ Swing Mode:  [0.20, 0.20, 0.25, 0.20, 0.15]

↓ 最終出力

Multi-Head Output
├─ Direction Head:      [batch, 3]  # UP/DOWN/NEUTRAL
├─ Magnitude_Scalp Head: [batch, 1]  # 0.5-2.0 pips
├─ Magnitude_Swing Head: [batch, 1]  # 2.0-5.0 pips
└─ Trend_Strength Head:  [batch, 1]  # 0-1
```

---

## 🔧 実装詳細

### 1. TFエンコーダ（LSTM）

```python
class TimeframeEncoder(nn.Module):
    """各タイムフレーム用のLSTMエンコーダ"""
    
    def __init__(self, input_dim: int, d_model: int = 128, num_layers: int = 2):
        super().__init__()
        self.lstm = nn.LSTM(
            input_size=input_dim,
            hidden_size=d_model,
            num_layers=num_layers,
            batch_first=True,
            dropout=0.1,
            bidirectional=False  # 未来リーク防止
        )
        self.layer_norm = nn.LayerNorm(d_model)
    
    def forward(self, x: Tensor) -> Tensor:
        """
        Args:
            x: [batch, seq_len, input_dim]
        Returns:
            h: [batch, seq_len, d_model]  # 全時刻の隠れ状態
        """
        h, (h_n, c_n) = self.lstm(x)
        h = self.layer_norm(h)
        return h  # 全時刻を返す（Self-Attention用）


# 各TF用にインスタンス化
encoders = {
    "M1":  TimeframeEncoder(input_dim=features_M1, d_model=128),
    "M5":  TimeframeEncoder(input_dim=features_M5, d_model=128),
    "M15": TimeframeEncoder(input_dim=features_M15, d_model=128),
    "H1":  TimeframeEncoder(input_dim=features_H1, d_model=128),
    "H4":  TimeframeEncoder(input_dim=features_H4, d_model=128),
}
```

**設計ポイント**:
- **全時刻の隠れ状態を保持**: Self-Attentionで動的にパターン抽出するため
- **Bidirectional=False**: 未来リークを防止（推論時に未来データを使えない）
- **LayerNorm**: 各TFのスケールを揃える

---

### 2. Self-Attention（TF内パターン抽出）

```python
class SelfAttentionPooling(nn.Module):
    """各TF内で重要な時刻を動的に抽出"""
    
    def __init__(self, d_model: int = 128, num_heads: int = 4):
        super().__init__()
        self.attention = nn.MultiheadAttention(
            embed_dim=d_model,
            num_heads=num_heads,
            dropout=0.1,
            batch_first=True
        )
        self.query_token = nn.Parameter(torch.randn(1, 1, d_model))  # 学習可能
        self.layer_norm = nn.LayerNorm(d_model)
    
    def forward(self, h: Tensor) -> Tuple[Tensor, Tensor]:
        """
        Args:
            h: [batch, seq_len, d_model]  # LSTMの全時刻出力
        Returns:
            summary: [batch, d_model]     # TFサマリーベクトル
            weights: [batch, seq_len]     # Attention weights（可視化用）
        """
        batch_size = h.size(0)
        query = self.query_token.expand(batch_size, -1, -1)  # [batch, 1, d_model]
        
        # Attention: Query=学習トークン, Key/Value=全時刻
        attn_output, attn_weights = self.attention(
            query=query,
            key=h,
            value=h,
            need_weights=True
        )
        
        summary = self.layer_norm(attn_output.squeeze(1))  # [batch, d_model]
        weights = attn_weights.squeeze(1)  # [batch, seq_len]
        
        return summary, weights


# 使用例
self_attn_M5 = SelfAttentionPooling(d_model=128, num_heads=4)
h_M5 = encoders["M5"](X_M5)  # [batch, 288, 128]
summary_M5, weights_M5 = self_attn_M5(h_M5)  # summary: [batch, 128]

# weights_M5 の可視化でダブルトップの2つの山が高weightになる
```

**設計ポイント**:
- **学習可能なクエリトークン**: 「どの時刻が重要か」をデータから学習
- **Multi-Head (4 heads)**: 複数パターン同時検出（例: 山1、山2、現在価格）
- **Attention weights保存**: デバッグ・解釈性向上のため

---

### 3. Cross-TF Attention（TF間融合）

```python
class CrossTimeframeFusion(nn.Module):
    """複数TFのサマリーベクトルを統合"""
    
    def __init__(self, d_model: int = 128, num_heads: int = 4):
        super().__init__()
        self.cross_attention = nn.MultiheadAttention(
            embed_dim=d_model,
            num_heads=num_heads,
            dropout=0.1,
            batch_first=True
        )
        self.feed_forward = nn.Sequential(
            nn.Linear(d_model, d_model * 4),
            nn.GELU(),
            nn.Dropout(0.1),
            nn.Linear(d_model * 4, d_model),
        )
        self.layer_norm1 = nn.LayerNorm(d_model)
        self.layer_norm2 = nn.LayerNorm(d_model)
    
    def forward(self, tf_summaries: Tensor) -> Tensor:
        """
        Args:
            tf_summaries: [batch, 5, d_model]  # [M1, M5, M15, H1, H4]
        Returns:
            fused: [batch, d_model]  # 統合ベクトル
        """
        # Self-Attention: TF間の関係を学習
        attn_output, _ = self.cross_attention(
            query=tf_summaries,
            key=tf_summaries,
            value=tf_summaries
        )
        attn_output = self.layer_norm1(attn_output + tf_summaries)  # Residual
        
        # Feed Forward
        ff_output = self.feed_forward(attn_output)
        output = self.layer_norm2(ff_output + attn_output)  # Residual
        
        # Global pooling: 5 TFs → 1 vector
        fused = output.mean(dim=1)  # [batch, d_model]
        
        return fused


# 使用例
tf_summaries = torch.stack([
    summary_M1,   # [batch, 128]
    summary_M5,   # [batch, 128]
    summary_M15,  # [batch, 128]
    summary_H1,   # [batch, 128]
    summary_H4,   # [batch, 128]
], dim=1)  # [batch, 5, 128]

fusion = CrossTimeframeFusion(d_model=128, num_heads=4)
fused = fusion(tf_summaries)  # [batch, 128]
```

**設計ポイント**:
- **Self-Attention on TFs**: M1とH1の相関など、TF間の関係を学習
- **Residual + LayerNorm**: 学習安定化
- **Mean pooling**: 全TFの情報を均等に統合（モード別重み付けは後段）

**項目64対応: Cross-TF Attention後の静的モード重み適用時の二重重み化防止**:

Cross-TF Attentionでは、各TFに対して動的な重み（attention weights）が学習される。その後、ModeSpecificWeightingで静的な重みを適用すると、同じTFに対して二重に重みがかかる可能性がある。

**二重重み化リスク**:
```python
# NG例: 二重重み化
attn_fused = cross_tf_attention(tf_summaries)  # 動的重みA
weighted = mode_weighting(tf_summaries, attn_fused)  # 静的重みB
# → M1に対して: A_M1 * B_M1 （積が大きすぎる）
```

**解決策: 後段重みの正規化**:
```python
class ModeSpecificWeighting(nn.Module):
    def forward(self, tf_summaries: Tensor, fused: Tensor) -> Tensor:
        # ... (モード判定・重み計算) ...
        
        # 【重要】Cross-TF Attentionの影響を考慮した正規化
        # Option 1: Gating（推奨）
        gate = torch.sigmoid(self.gate_proj(fused))  # [batch, 1]
        weighted = gate * fused + (1 - gate) * weighted_static
        
        # Option 2: 温度パラメータで重み緩和
        temperature = 2.0  # 静的重みを平滑化
        weights_soft = torch.softmax(weights / temperature, dim=-1)
        
        # Option 3: 完全にAttention優先（静的重みは補助）
        # 静的重みは学習初期のみ使用、後は無効化
        
        return weighted
```

**実装ガイドライン（項目64）**:
1. **Phase 1**: Cross-TF Attention のみ（静的重みなし）
2. **Phase 2評価時**: Gating方式で静的重みを補助的に使用
3. **温度パラメータ**: 2.0以上で重み集中を緩和
4. **成功指標**: M1への重み集中度 < 0.5（全体の50%未満）

---

### 4. モード別重み付け（オプション）

```python
class ModeSpecificWeighting(nn.Module):
    """デュアルモード別のTF重み適用（項目59対応: Age-weight正規化）"""
    
    def __init__(self, d_model: int = 128):
        super().__init__()
        # 静的重み（学習しない）- 正規化済み（sum=1.0）
        self.scalp_weights = torch.tensor([0.35, 0.30, 0.20, 0.10, 0.05])
        self.swing_weights = torch.tensor([0.20, 0.20, 0.25, 0.20, 0.15])
        
        # 正規化検証
        assert abs(self.scalp_weights.sum() - 1.0) < 1e-6, "Scalp weights must sum to 1.0"
        assert abs(self.swing_weights.sum() - 1.0) < 1e-6, "Swing weights must sum to 1.0"
        
        # モード判定用（trend_strengthから）
        self.mode_gate = nn.Linear(d_model, 1)
    
    def forward(self, tf_summaries: Tensor, fused: Tensor) -> Tensor:
        """
        Args:
            tf_summaries: [batch, 5, d_model]  # [M1, M5, M15, H1, H4]
            fused: [batch, d_model]  # Cross-TF Attention出力
        Returns:
            weighted: [batch, d_model]  # モード別重み適用後
        """
        # モード判定（trend_strengthの代理）
        mode_score = torch.sigmoid(self.mode_gate(fused))  # [batch, 1]
        # mode_score < 0.3 → Scalp, > 0.7 → Swing, 0.3-0.7 → Mix
        
        # 重み補間
        weights = (
            (1 - mode_score) * self.scalp_weights.to(fused.device) +
            mode_score * self.swing_weights.to(fused.device)
        )  # [batch, 5]
        
        # 正規化保証（補間後も sum=1.0）
        weights = weights / weights.sum(dim=-1, keepdim=True)
        
        # Age-weight KPI計算（最新TF = M1の最小重み保証）
        min_fresh_ratio = weights[:, 0].min().item()  # M1重み最小値
        if min_fresh_ratio < 0.15:  # 閾値: Scalp最低15%, Swing最低10%
            logging.warning(f"M1 weight too low: {min_fresh_ratio:.3f}")
        
        # 加重平均
        weights_expanded = weights.unsqueeze(-1)  # [batch, 5, 1]
        weighted = (tf_summaries * weights_expanded).sum(dim=1)  # [batch, d_model]
        
        return weighted


# 使用例（オプション機能）
mode_weighting = ModeSpecificWeighting(d_model=128)
weighted_fused = mode_weighting(tf_summaries, fused)
```

**設計ポイント**:
- **静的重み正規化**: 初期化時に sum=1.0 を assert で検証
- **補間後正規化**: 動的重みも必ず正規化（他の注意機構と干渉防止）
- **min_fresh_ratio KPI**: M1重みの最小値を監視
  - Scalp: min_fresh_ratio >= 0.15（短期重視）
  - Swing: min_fresh_ratio >= 0.10（中長期重視）
- **警告ログ**: 閾値未満時に自動検出

**Age-weight正規化の効果**:
- 重み過大による勾配偏りを防止
- 他のAttention層との重み競合を回避
- モード切替時の安定性向上

---

## 📊 Attention可視化例

### パターン検出の確認

```python
# M5足でダブルトップ検出時のAttention weights
# X軸: 本数（0-288）、Y軸: Attention weight

weights_M5: [0.001, 0.001, ..., 0.15(山1), ..., 0.20(山2), ..., 0.35(現在)]
                              ↑188本目      ↑238本目        ↑288本目

# 解釈:
# - 山1 (188本目 = 約16時間前): weight=0.15 → 1つ目のピーク検出
# - 山2 (238本目 = 約4時間前):  weight=0.20 → 2つ目のピーク検出
# - 現在 (288本目):             weight=0.35 → エントリー判断の基準点

# → モデルは「50本間隔のダブルトップ」を自動検出
```

### TF間の協調

```python
# Cross-TF Attentionでの各TFの寄与度

TF Attention weights (Scalp Mode):
M1:  0.32  # エントリータイミング重視
M5:  0.28  # 短期トレンド
M15: 0.22  # 中期バイアス
H1:  0.12  # 大局確認
H4:  0.06  # レジーム参考

TF Attention weights (Swing Mode):
M1:  0.18  # タイミング重要度低下
M5:  0.20
M15: 0.26  # 中期トレンド重視
H1:  0.22  # 大局重要度上昇
H4:  0.14  # レジーム影響増加

# → モードに応じてAttentionが自動調整される可能性
#    （静的重みよりも柔軟）
```

---

## ⚙️ ハイパーパラメータ

### 推奨設定

```yaml
model:
  tf_encoder:
    d_model: 128           # LSTM隠れ層次元
    num_layers: 2          # LSTM層数
    dropout: 0.1
    
  self_attention:
    num_heads: 4           # Multi-head数
    dropout: 0.1
    
  cross_tf_fusion:
    num_heads: 4
    dropout: 0.1
    ff_dim: 512            # Feed Forward中間層 (d_model * 4)
    
  mode_weighting:
    enabled: false         # Phase 1では無効
    static_weights:
      scalp: [0.35, 0.30, 0.20, 0.10, 0.05]
      swing: [0.20, 0.20, 0.25, 0.20, 0.15]

sequence_lengths:
  M1:  480   # 8時間
  M5:  288   # 24時間
  M15: 192   # 48時間
  H1:  96    # 96時間
  H4:  48    # 192時間
```

### チューニング指針

| パラメータ | 小さい値の効果 | 大きい値の効果 | 推奨範囲 |
|----------|--------------|--------------|---------|
| `d_model` | 学習速度↑、表現力↓ | 表現力↑、過学習リスク↑ | 64-256 |
| `num_heads` | 単純パターン重視 | 複雑パターン検出 | 2-8 |
| `num_layers` (LSTM) | 浅い特徴抽出 | 深い抽象化 | 1-3 |
| `dropout` | 過学習しやすい | 汎化性能↑、学習遅延 | 0.1-0.3 |

---

## 🔍 デバッグ・検証

### 1. Attention weights保存

```python
# 学習時にAttention weightsをログ保存
def log_attention_weights(batch_idx: int, weights: Dict[str, Tensor]):
    """
    Args:
        weights: {
            "M1": [batch, 480],
            "M5": [batch, 288],
            ...
        }
    """
    if batch_idx % 100 == 0:  # 100バッチごと
        for tf_name, w in weights.items():
            # サンプル0のweightsをプロット
            plt.figure(figsize=(12, 3))
            plt.plot(w[0].cpu().numpy())
            plt.title(f"{tf_name} Attention Weights (batch {batch_idx})")
            plt.xlabel("Time Step")
            plt.ylabel("Weight")
            plt.savefig(f"logs/attention_{tf_name}_batch{batch_idx}.png")
            plt.close()
```

### 2. パターン検出精度

```python
# ダブルトップが存在するサンプルでAttentionが正しく山を検出できているか
def evaluate_pattern_detection(
    model: nn.Module,
    test_data: Dataset,
    pattern_labels: Dict[int, List[int]]  # {sample_id: [peak1_idx, peak2_idx]}
):
    """
    Args:
        pattern_labels: 人間が手動でラベル付けした山の位置
    """
    for sample_id, peak_indices in pattern_labels.items():
        x = test_data[sample_id]
        _, attention_weights = model.forward_with_attention(x)
        
        # Attention weightsの上位K個の位置
        top_k_indices = attention_weights.topk(k=5).indices
        
        # 山の位置とどれだけ一致するか
        hit_count = sum(1 for idx in peak_indices if idx in top_k_indices)
        precision = hit_count / len(peak_indices)
        
        print(f"Sample {sample_id}: Precision={precision:.2f}")
```

### 3. TF寄与度分析

```python
# 各TFがどれだけ予測に寄与しているか（Ablation Study）
def tf_ablation_study(model: nn.Module, test_loader: DataLoader):
    """各TFを無効化した時の性能変化"""
    baseline_acc = evaluate(model, test_loader)
    
    for tf_name in ["M1", "M5", "M15", "H1", "H4"]:
        # 特定TFをゼロマスク
        model.mask_tf(tf_name)
        masked_acc = evaluate(model, test_loader)
        impact = baseline_acc - masked_acc
        
        print(f"TF={tf_name} removed: Accuracy drop = {impact:.3f}")
        model.unmask_tf(tf_name)
    
    # 出力例:
    # TF=M1 removed: Accuracy drop = 0.082  # M1が最重要
    # TF=H4 removed: Accuracy drop = 0.015  # H4は補助的
```

---

## 🚀 実装フェーズ

### 実装フェーズ1: 基本実装

1. **TFエンコーダ + Self-Attention**
   - 各TFを独立にエンコード
   - Self-Attentionでサマリー抽出
   
2. **Cross-TF Fusion（Simple版）**
   - Mean poolingのみ（モード別重み付けなし）
   
3. **検証**
   - Attention weights可視化
   - パターン検出精度評価

### 実装フェーズ2: 高度化

1. **モード別重み付け**
   - trend_strengthベースの動的重み
   
2. **Hierarchical Attention**
   - TF内 → TF間の2段階Attention
   
3. **Positional Encoding**
   - 時刻情報の明示的エンコード

### 実装フェーズ3: 最適化

1. **ONNX変換対応**
   - Attention演算の最適化

2. **推論レイテンシ削減**
   - Incremental update（新規1本のみ処理）

3. **Multi-GPU学習**
   - データ並列化

---

## Cross-TF Attention後の重み正規化

**目的**: 同一TFへ注意重み+静的モード重みの集中により勾配偏重・過学習（特定TF過剰強調）リスク。

**問題詳細**:
```python
# 二重重み化の例
# Step 1: Cross-TF Attention
attention_weights = softmax(Q @ K.T)  # [0.4, 0.3, 0.2, 0.05, 0.05] (M1優位)

# Step 2: モード別静的重み適用
mode_weights = [0.35, 0.30, 0.20, 0.10, 0.05]  # M1優先 (Scalp mode)

# 結果: M1が二重に強調される
# M1への実効重み ≈ 0.4 × 0.35 = 0.14
# M5への実効重み ≈ 0.3 × 0.30 = 0.09
# → M1の勾配が過剰に大きくなる
```

**対応策**: 後段重み正規化または gating

### オプション1: 後段正規化（推奨）

```python
class CrossTFFusionWithNormalization(nn.Module):
    """
    Cross-TF Attention + 後段重み正規化
    """

    def __init__(self, d_model=128, mode='scalp'):
        super().__init__()
        self.attention = CrossTFAttention(d_model)
        self.mode = mode

        # モード別静的重み（初期値）
        self.register_buffer('static_weights', torch.tensor([
            0.35, 0.30, 0.20, 0.10, 0.05  # Scalp mode
        ]))

    def forward(self, tf_embeddings: List[torch.Tensor]) -> torch.Tensor:
        """
        Args:
            tf_embeddings: [M1, M5, M15, H1, H4] embeddings

        Returns:
            融合embedding
        """
        # Step 1: Cross-TF Attention（動的重み）
        attended, attn_weights = self.attention(tf_embeddings)
        # attn_weights.shape = [batch, 5]

        # Step 2: 静的重み適用
        static_w = self.static_weights.unsqueeze(0)  # [1, 5]

        # オプション1a: 重み積の正規化
        combined_weights = attn_weights * static_w
        combined_weights = combined_weights / combined_weights.sum(dim=1, keepdim=True)
        # 正規化により Σw = 1.0 を保証

        # Step 3: 融合
        fused = torch.stack(attended, dim=1)  # [batch, 5, d_model]
        output = (fused * combined_weights.unsqueeze(-1)).sum(dim=1)

        return output, combined_weights


# トレーニング時の検証
def validate_weight_distribution(combined_weights):
    """重み分布の健全性チェック"""
    # 1. 合計が1.0
    assert torch.allclose(combined_weights.sum(dim=1), torch.ones(len(combined_weights)))

    # 2. 単一TFへの過剰集中防止（最大重み < 0.6）
    max_weights, _ = combined_weights.max(dim=1)
    if (max_weights > 0.6).any():
        logger.warning(f"TF weight concentration detected: max={max_weights.max():.3f}")

    # 3. 実効重みの多様性（Entropy）
    entropy = -(combined_weights * torch.log(combined_weights + 1e-9)).sum(dim=1)
    min_entropy = torch.log(torch.tensor(5.0)) * 0.5  # 最小エントロピー閾値
    if (entropy < min_entropy).any():
        logger.warning(f"Low weight diversity: entropy={entropy.min():.3f}")
```

### オプション2: Gating機構

```python
class GatedCrossTFFusion(nn.Module):
    """
    Gating による動的・静的重みの統合
    """

    def __init__(self, d_model=128):
        super().__init__()
        self.attention = CrossTFAttention(d_model)

        # Gate network: 動的重みと静的重みのバランスを学習
        self.gate_net = nn.Sequential(
            nn.Linear(d_model, 64),
            nn.ReLU(),
            nn.Linear(64, 1),
            nn.Sigmoid()  # [0, 1]
        )

    def forward(self, tf_embeddings, static_weights):
        """
        Args:
            tf_embeddings: [M1, M5, M15, H1, H4]
            static_weights: [0.35, 0.30, 0.20, 0.10, 0.05]
        """
        # Attention重み
        attended, attn_weights = self.attention(tf_embeddings)

        # Gating値計算（バッチ平均embedding から）
        avg_emb = torch.stack(attended, dim=1).mean(dim=1)  # [batch, d_model]
        gate = self.gate_net(avg_emb)  # [batch, 1]

        # 動的・静的のブレンド
        static_w = static_weights.unsqueeze(0).expand(len(attn_weights), -1)
        blended_weights = gate * attn_weights + (1 - gate) * static_w

        # 正規化
        blended_weights = blended_weights / blended_weights.sum(dim=1, keepdim=True)

        # 融合
        fused = torch.stack(attended, dim=1)
        output = (fused * blended_weights.unsqueeze(-1)).sum(dim=1)

        return output, blended_weights, gate
```

**成功指標**:
- 最大TF重み < 0.6（過剰集中防止）
- 重みエントロピー > log(5) × 0.5（多様性保証）
- 勾配ノルム分散: TF間で CV < 0.5

**検証**:
```python
def test_weight_normalization():
    """重み正規化の検証"""
    model = CrossTFFusionWithNormalization(d_model=128, mode='scalp')

    # ダミー入力
    tf_embs = [torch.randn(32, 128) for _ in range(5)]

    output, combined_weights = model(tf_embs)

    # 検証1: 重み合計=1.0
    assert torch.allclose(combined_weights.sum(dim=1), torch.ones(32))

    # 検証2: 過剰集中なし
    max_w = combined_weights.max(dim=1)[0]
    assert (max_w < 0.6).all(), f"過剰集中検出: {max_w.max():.3f}"

    # 検証3: エントロピー確認
    entropy = -(combined_weights * torch.log(combined_weights + 1e-9)).sum(dim=1)
    assert (entropy > torch.log(torch.tensor(5.0)) * 0.5).all()
```

**実装推奨**: Phase 1ではオプション1（後段正規化）を採用、Phase 2でオプション2（Gating）を評価。

---

## LSTM最適化

### 長窓鮮度減衰（Freshness Decay）

**目的**: 480本（M1）や288本（M5）の古い情報が新しいパターンを押し潰す

**解決策**: 時間減衰による位置埋め込み拡張

```python
class FreshnessDecayEmbedding(nn.Module):
    """鮮度減衰位置埋め込み"""
    
    def __init__(self, d_model: int, max_len: int = 500, decay_mode: str = "exponential"):
        super().__init__()
        self.d_model = d_model
        self.decay_mode = decay_mode
        
        # 標準位置埋め込み
        self.pos_embedding = nn.Parameter(torch.randn(max_len, d_model))
        
        # 減衰係数（学習可能）
        self.decay_alpha = nn.Parameter(torch.tensor(0.995))  # 初期値: 480本で~0.1倍
    
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        鮮度減衰適用
        
        Args:
            x: 入力系列 (batch, seq_len, d_model)
        
        Returns:
            x_decayed: 減衰適用後 (batch, seq_len, d_model)
        """
        batch, seq_len, d_model = x.shape
        
        # 位置インデックス（古い=0, 新しい=seq_len-1）
        positions = torch.arange(seq_len, device=x.device)
        
        # 減衰係数計算
        if self.decay_mode == "exponential":
            # α^(seq_len - 1 - pos)
            decay_weights = self.decay_alpha ** (seq_len - 1 - positions)
        elif self.decay_mode == "linear":
            # (pos + 1) / seq_len
            decay_weights = (positions + 1) / seq_len
        else:
            raise ValueError(f"Unknown decay_mode: {self.decay_mode}")
        
        decay_weights = decay_weights.view(1, seq_len, 1)  # (1, seq_len, 1)
        
        # 位置埋め込み追加
        pos_emb = self.pos_embedding[:seq_len]  # (seq_len, d_model)
        x = x + pos_emb.unsqueeze(0)
        
        # 減衰適用
        x_decayed = x * decay_weights
        
        return x_decayed


class MultiTFLSTMWithFreshness(nn.Module):
    """鮮度減衰対応マルチTF LSTM"""
    
    def __init__(self, config: dict):
        super().__init__()
        
        d_model = config['d_model']
        
        # 各TF用鮮度減衰
        self.freshness_m1 = FreshnessDecayEmbedding(d_model, max_len=480)
        self.freshness_m5 = FreshnessDecayEmbedding(d_model, max_len=288)
        self.freshness_m15 = FreshnessDecayEmbedding(d_model, max_len=192)
        self.freshness_h1 = FreshnessDecayEmbedding(d_model, max_len=96)
        self.freshness_h4 = FreshnessDecayEmbedding(d_model, max_len=48)
        
        # LSTM層
        self.lstm_m1 = nn.LSTM(d_model, d_model, batch_first=True)
        self.lstm_m5 = nn.LSTM(d_model, d_model, batch_first=True)
        # ... 他のTF
    
    def forward(self, multi_tf_features: Dict[str, torch.Tensor]) -> torch.Tensor:
        """
        鮮度減衰適用後にLSTM処理
        
        Args:
            multi_tf_features: {
                "m1": (batch, 480, d_model),
                "m5": (batch, 288, d_model),
                ...
            }
        
        Returns:
            fused_output: (batch, d_model)
        """
        # 鮮度減衰適用
        m1_decayed = self.freshness_m1(multi_tf_features["m1"])
        m5_decayed = self.freshness_m5(multi_tf_features["m5"])
        # ...
        
        # LSTM処理
        m1_out, _ = self.lstm_m1(m1_decayed)
        m5_out, _ = self.lstm_m5(m5_decayed)
        # ...
        
        # 最終状態取得
        m1_final = m1_out[:, -1, :]  # (batch, d_model)
        m5_final = m5_out[:, -1, :]
        # ...
        
        # Fusion（既存のCrossTFFusion使用）
        fused = self.fusion([m1_final, m5_final, ...])
        
        return fused


# 減衰曲線の可視化
def visualize_freshness_decay():
    """減衰係数の可視化"""
    seq_len = 480
    alpha = 0.995
    
    positions = np.arange(seq_len)
    decay = alpha ** (seq_len - 1 - positions)
    
    plt.figure(figsize=(10, 4))
    plt.plot(positions, decay)
    plt.xlabel("Position (0=oldest, 479=newest)")
    plt.ylabel("Weight Multiplier")
    plt.title(f"Freshness Decay (α={alpha})")
    plt.grid(True)
    plt.savefig("freshness_decay.png")
```

**減衰パターン比較**:

| Mode | 式 | 480本での減衰 | 用途 |
|------|---|--------------|------|
| exponential | α^(N-1-t) | 0.995^479 ≈ 0.09 | 古い情報を大幅減衰 |
| linear | (t+1)/N | 1/480 ≈ 0.002 | 線形減少 |

**KPI（項目19）**:
- 新しい50本vs古い50本の重み比: ≥10:1
- 学習済みα値: 0.99～0.999範囲
- 精度改善: ≥+1%（減衰なし比較）

---

### 項目65・81対応: Incremental LSTM推論

**目的**: 毎回全窓再計算は遅延増大の原因

**解決策**: LSTM隠れ状態キャッシュによる差分更新

```python
class IncrementalLSTMInference:
    """差分更新LSTM推論（項目65・81対応）"""
    
    def __init__(self, lstm_model: nn.LSTM, max_cache_size: int = 500):
        self.lstm = lstm_model
        self.max_cache_size = max_cache_size
        
        # キャッシュ（TF別）
        self.hidden_cache = {}  # {tf: (h, c)}
        self.feature_cache = {}  # {tf: deque of features}
    
    def initialize_cache(self, tf: str, initial_sequence: torch.Tensor):
        """
        キャッシュ初期化（起動時・リセット時）
        
        Args:
            tf: タイムフレーム名（"m1", "m5", ...）
            initial_sequence: 初期系列 (1, seq_len, d_model)
        """
        # 全窓処理して最終状態を保存
        output, (h_n, c_n) = self.lstm(initial_sequence)
        
        self.hidden_cache[tf] = (h_n, c_n)
        
        # 特徴量履歴（deque）
        self.feature_cache[tf] = deque(
            initial_sequence[0].cpu().numpy(),
            maxlen=self.max_cache_size
        )
        
        logger.info(f"{tf} キャッシュ初期化: hidden_shape={h_n.shape}")
    
    def update_incremental(
        self,
        tf: str,
        new_feature: torch.Tensor  # (1, 1, d_model) 新着1本
    ) -> torch.Tensor:
        """
        差分更新（新着1本のみ処理）
        
        Args:
            tf: タイムフレーム名
            new_feature: 新着特徴量 (1, 1, d_model)
        
        Returns:
            new_output: 更新後の出力 (1, d_model)
        """
        if tf not in self.hidden_cache:
            raise ValueError(f"{tf} キャッシュ未初期化")
        
        # 前回の隠れ状態取得
        h_prev, c_prev = self.hidden_cache[tf]
        
        # 新着1本のみLSTM処理
        output, (h_new, c_new) = self.lstm(new_feature, (h_prev, c_prev))
        
        # キャッシュ更新
        self.hidden_cache[tf] = (h_new, c_new)
        self.feature_cache[tf].append(new_feature[0, 0].cpu().numpy())
        
        return output[:, -1, :]  # (1, d_model)
    
    def reset_if_stale(self, tf: str, threshold_seconds: int = 300):
        """
        古すぎるキャッシュをリセット（接続断後など）
        
        Args:
            tf: タイムフレーム名
            threshold_seconds: リセット閾値（秒）
        """
        # 実装時は最終更新時刻を保存してチェック
        pass


# 使用例
incremental_lstm = IncrementalLSTMInference(
    lstm_model=model.lstm_m1,
    max_cache_size=500
)

# 初期化（起動時）
initial_seq = load_initial_480_bars("m1")  # (1, 480, d_model)
incremental_lstm.initialize_cache("m1", initial_seq)

# 推論ループ（新着tick毎）
while True:
    new_tick = get_new_tick_feature("m1")  # (1, 1, d_model)
    
    # 差分更新（O(1)計算量）
    output = incremental_lstm.update_incremental("m1", new_tick)
    
    # 予測実行
    prediction = model.direction_head(output)
```

**API仕様**:

| メソッド | 計算量 | 用途 |
|---------|-------|------|
| `initialize_cache()` | O(N) | 起動時・リセット時 |
| `update_incremental()` | O(1) | 通常推論（新着1本） |
| `reset_if_stale()` | O(N) | 接続断復帰時 |

**実装詳細（項目81）**:

```python
# 隠れ状態の形状
h_n: (num_layers, batch, hidden_size)
c_n: (num_layers, batch, hidden_size)

# キャッシュサイズ見積
hidden_cache_size = num_layers * hidden_size * 2 (h+c) * 4 bytes (float32)
例: 2層×128次元×2×4 = 2KB / TF

# メモリ効率化
- CPU保存: 推論中のみGPUへ転送
- FP16化: メモリ半減（精度劣化<0.1%）
```

**KPI（項目65・81）**:
- レイテンシ削減: ≥50%（全窓再計算比較）
- メモリ使用量: <10KB / TF（5TF合計<50KB）
- リセット頻度: <1回/日（接続安定時）

---

## 📚 関連仕様

- [TRAINER_SPEC.md](../TRAINER_SPEC.md) - 全体アーキテクチャ
- [PREPROCESSOR_SPEC.md](../PREPROCESSOR_SPEC.md) - 入力特徴量形式
- [EXECUTION_LATENCY_SPEC.md](../validator/EXECUTION_LATENCY_SPEC.md) - 推論レイテンシ要件

---

## 📝 変更履歴

- **2025-10-21**: 初版作成
  - シーケンス長定義（最大公約数的固定窓）
  - LSTM + Self-Attention設計
  - Cross-TF Fusion詳細
  - Attention可視化・検証方法
