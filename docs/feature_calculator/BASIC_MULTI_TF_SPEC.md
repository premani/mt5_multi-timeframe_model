# 基本マルチTF特徴量仕様書

**カテゴリ**: 1/5
**処理段階**: 第2段階: 特徴量計算
**列数**: 15-20列  
**目的**: TF内変化とTF間関係の基本情報

---

## 📋 概要

マルチタイムフレーム分析の**基盤となる特徴量**。各TFの価格変動情報と、TF間の関係性を表現する。

### 設計方針
- **TF内特徴**: 各TF独立の価格変化・レンジ幅
- **TF間特徴**: 複数TFの相互関係（乖離・一致度・相関）
- **価格回帰重視**: pips絶対値を保持

---

## 🎯 TF内特徴量（15列）

各TF（M1/M5/M15/H1/H4）で同じ計算を実施。

### 1. 価格変化（pips絶対値）

```python
# 各TFで計算
for tf in ['M1', 'M5', 'M15', 'H1', 'H4']:
    features[f'{tf}_price_change_pips'] = (
        (close[tf] - close[tf].shift(1)) * 10000
    )
```

**目的**: 価格変化の絶対量を保持（価格回帰に必須）

**例**:
- M5で+5pips上昇 → `M5_price_change_pips = 5.0`
- H1で-12pips下落 → `H1_price_change_pips = -12.0`

---

### 2. 価格変化率

```python
for tf in ['M1', 'M5', 'M15', 'H1', 'H4']:
    features[f'{tf}_price_change_rate'] = (
        (close[tf] - close[tf].shift(1)) / close[tf]
    )
```

**目的**: スケール正規化された変化情報

**例**:
- EUR/USD 1.1000 → 1.1010（+10pips） → `rate = 0.0009`（0.09%）

---

### 3. レンジ幅（pips）

```python
for tf in ['M1', 'M5', 'M15', 'H1', 'H4']:
    features[f'{tf}_range_pips'] = (
        (high[tf] - low[tf]) * 10000
    )
```

**目的**: ボラティリティの直接指標

**例**:
- M5のレンジ 3pips → `M5_range_pips = 3.0`
- H1のレンジ 25pips → `H1_range_pips = 25.0`

---

## 🔗 TF間特徴量（5列）

### 1. M5とM1の価格乖離（pips）

```python
features['M5_M1_divergence_pips'] = (
    (close_M5 - close_M1) * 10000
)
```

**目的**: 短期TF間の価格ズレを検出

**意味**:
- 正: M5がM1より高い（M1が遅れて追従する可能性）
- 負: M1がM5より高い（M5が追いつく可能性）

---

### 2. M15とM5の方向一致度

```python
features['M15_M5_direction_agreement'] = (
    np.sign(close_M15 - close_M15.shift(1)) == 
    np.sign(close_M5 - close_M5.shift(1))
).astype(int)
```

**目的**: 中期トレンドと短期トレンドの整合性

**値**:
- `1`: 同じ方向（トレンド継続の可能性）
- `0`: 逆方向（トレンド転換の可能性）

---

### 3. H1とM15の変化率差

```python
features['H1_M15_momentum_diff'] = (
    ((close_H1 - close_H1.shift(1)) / close_H1) -
    ((close_M15 - close_M15.shift(1)) / close_M15)
)
```

**目的**: 長期vs中期のモメンタム差

**意味**:
- 正: H1の勢いがM15より強い
- 負: M15の勢いがH1より強い

---

### 4. H4とH1のトレンド強度差

```python
def trend_strength(close, window=20):
    """トレンド強度: 移動平均からの乖離率"""
    ma = close.rolling(window).mean()
    return (close - ma) / ma

features['H4_H1_trend_strength_diff'] = (
    trend_strength(close_H4, 20) - trend_strength(close_H1, 20)
)
```

**目的**: 長期トレンドと中期トレンドの乖離

---

### 5. マルチTF相関（M5-M15-H1）

```python
def multi_tf_correlation(close_m5, close_m15, close_h1, window=20):
    """3つのTFの平均相関係数"""
    corr_m5_m15 = close_m5.rolling(window).corr(close_m15)
    corr_m15_h1 = close_m15.rolling(window).corr(close_h1)
    corr_m5_h1 = close_m5.rolling(window).corr(close_h1)
    
    return (corr_m5_m15 + corr_m15_h1 + corr_m5_h1) / 3

features['multi_tf_correlation'] = multi_tf_correlation(
    close_M5, close_M15, close_H1
)
```

**目的**: TF間の同調度合い

**値**:
- `≈ 1.0`: 全TFが同じ方向に動いている（強いトレンド）
- `≈ 0.5`: 部分的に同調（レンジ相場）
- `< 0.0`: 逆相関（稀）

---

## 🧮 実装クラス

```python
class BasicMultiTFCalculator(BaseCalculator):
    """
    基本マルチTF特徴量計算器
    """
    
    @property
    def name(self) -> str:
        return "basic_multi_tf"
    
    def compute(
        self, 
        raw_data: Dict[str, pd.DataFrame]
    ) -> pd.DataFrame:
        """
        TF内・TF間特徴量を計算
        
        Args:
            raw_data: {
                'M1': DataFrame(N, 6) [time, open, high, low, close, volume],
                'M5': DataFrame(N, 6),
                ...
            }
        
        Returns:
            features: DataFrame(N, 20)
        """
        features = {}
        
        # TF内特徴（15列）
        for tf in ['M1', 'M5', 'M15', 'H1', 'H4']:
            df = raw_data[tf]
            close = df['close']
            high = df['high']
            low = df['low']
            
            # 価格変化（pips）
            features[f'{tf}_price_change_pips'] = (
                (close - close.shift(1)) * 10000
            )
            
            # 価格変化率
            features[f'{tf}_price_change_rate'] = (
                (close - close.shift(1)) / close
            )
            
            # レンジ幅（pips）
            features[f'{tf}_range_pips'] = (high - low) * 10000
        
        # TF間特徴（5列）
        close_M1 = raw_data['M1']['close']
        close_M5 = raw_data['M5']['close']
        close_M15 = raw_data['M15']['close']
        close_H1 = raw_data['H1']['close']
        close_H4 = raw_data['H4']['close']
        
        # M5-M1乖離
        features['M5_M1_divergence_pips'] = (
            (close_M5 - close_M1) * 10000
        )
        
        # M15-M5方向一致度
        features['M15_M5_direction_agreement'] = (
            np.sign(close_M15 - close_M15.shift(1)) ==
            np.sign(close_M5 - close_M5.shift(1))
        ).astype(int)
        
        # H1-M15変化率差
        features['H1_M15_momentum_diff'] = (
            ((close_H1 - close_H1.shift(1)) / close_H1) -
            ((close_M15 - close_M15.shift(1)) / close_M15)
        )
        
        # H4-H1トレンド強度差
        ma_H4 = close_H4.rolling(20).mean()
        ma_H1 = close_H1.rolling(20).mean()
        features['H4_H1_trend_strength_diff'] = (
            (close_H4 - ma_H4) / ma_H4 -
            (close_H1 - ma_H1) / ma_H1
        )
        
        # マルチTF相関
        features['multi_tf_correlation'] = self._multi_tf_corr(
            close_M5, close_M15, close_H1
        )
        
        return pd.DataFrame(features)
    
    def _multi_tf_corr(
        self,
        close_m5: pd.Series,
        close_m15: pd.Series,
        close_h1: pd.Series,
        window: int = 20
    ) -> pd.Series:
        """3TFの平均相関"""
        corr_m5_m15 = close_m5.rolling(window).corr(close_m15)
        corr_m15_h1 = close_m15.rolling(window).corr(close_h1)
        corr_m5_h1 = close_m5.rolling(window).corr(close_h1)
        
        return (corr_m5_m15 + corr_m15_h1 + corr_m5_h1) / 3
```

---

## ✅ 検証基準

### 1. NaN比率
- **閾値**: < 5%
- **理由**: 最初の1本（shift(1)）以外はNaNなし

### 2. 値の範囲
- `price_change_pips`: -100 ~ +100（通常時）
- `price_change_rate`: -0.01 ~ +0.01（1%以内）
- `range_pips`: 0 ~ 50（通常時）
- `direction_agreement`: 0 or 1
- `multi_tf_correlation`: -1.0 ~ +1.0

### 3. スケール不変性（部分的）
- `price_change_rate`, `correlation` はスケール不変
- `price_change_pips`, `range_pips` は価格回帰用に**意図的に非不変**

---

## 📊 出力例

```python
# 出力DataFrame（N, 20）
features = pd.DataFrame({
    # M1特徴（3列）
    'M1_price_change_pips': [0.5, -0.3, 0.8, ...],
    'M1_price_change_rate': [0.00005, -0.00003, 0.00008, ...],
    'M1_range_pips': [2.1, 1.8, 2.5, ...],
    
    # M5特徴（3列）
    'M5_price_change_pips': [2.3, -1.5, 3.2, ...],
    'M5_price_change_rate': [0.00023, -0.00015, 0.00032, ...],
    'M5_range_pips': [5.4, 4.2, 6.1, ...],
    
    # ... M15, H1, H4 同様 ...
    
    # TF間特徴（5列）
    'M5_M1_divergence_pips': [0.2, 0.5, -0.3, ...],
    'M15_M5_direction_agreement': [1, 1, 0, ...],
    'H1_M15_momentum_diff': [0.0002, -0.0001, 0.0003, ...],
    'H4_H1_trend_strength_diff': [0.015, 0.012, 0.018, ...],
    'multi_tf_correlation': [0.85, 0.78, 0.92, ...],
})
```

---

## 🔗 関連仕様書

- **メイン仕様**: [FEATURE_CALCULATOR_SPEC.md](../FEATURE_CALCULATOR_SPEC.md)
- **データ収集**: [DATA_COLLECTOR_SPEC.md](../DATA_COLLECTOR_SPEC.md)
- **次工程**: [PREPROCESSOR_SPEC.md](../PREPROCESSOR_SPEC.md)

---

**最終更新**: 2025-10-22  
**ステータス**: ドラフト
