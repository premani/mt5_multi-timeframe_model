# ボラティリティ・レジーム仕様書

**カテゴリ**: 3/5
**処理段階**: 第2段階: 特徴量計算
**列数**: 8-12列  
**目的**: 市場環境の変動性判定

---

## 📋 概要

市場の**ボラティリティレジーム**（変動性環境）を判定する特徴量。ATR（Average True Range）を中心に、複数期間・複数TFでの変動性を測定。

### 設計方針
- マルチTF × 複数期間でのATR測定
- ATR比率による相対評価（絶対値依存を回避）
- レジーム分類（低/通常/高）

---

## 🎯 特徴量詳細

### 1. マルチTF ATR（6列）

各TFで14期間ATRを計算。

```python
def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Average True Range計算
    
    True Range = max(
        high - low,
        |high - close_prev|,
        |low - close_prev|
    )
    
    ATR = True Rangeの移動平均
    """
    high = df['high']
    low = df['low']
    close = df['close']
    
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1) * 10000  # pips
    
    return tr.rolling(period).mean()

# 各TFで計算
for tf in ['M1', 'M5', 'H1']:
    features[f'atr_{tf.lower()}_14'] = calculate_atr(raw_data[tf], 14)

# 追加: M5の複数期間
features['atr_m5_7'] = calculate_atr(raw_data['M5'], 7)   # 短期
features['atr_m5_28'] = calculate_atr(raw_data['M5'], 28)  # 長期
```

**列数**: 5列（M1/M5/H1の14期間 + M5の7/28期間）

**目的**:
- 各TFのボラティリティ測定
- 短期vs長期のボラティリティ変化

---

### 2. ATR比率（3列）

ボラティリティの相対評価。

#### 2-1. M1/M5 ATR比率

```python
features['atr_m1_m5_ratio'] = (
    features['atr_m1_14'] / (features['atr_m5_14'] + 1e-6)
)
```

**意味**:
- `> 1.0`: M1がM5より変動大（短期的な乱高下）
- `≈ 1.0`: 均衡
- `< 1.0`: M5がM1より変動大（長期的な大きな動き）

---

#### 2-2. M5/H1 ATR比率

```python
features['atr_m5_h1_ratio'] = (
    features['atr_m5_14'] / (features['atr_h1_14'] + 1e-6)
)
```

**意味**: 中期vs長期のボラティリティ関係

---

#### 2-3. 短期/長期 ATR比率（M5基準）

```python
features['atr_m5_short_long_ratio'] = (
    features['atr_m5_7'] / (features['atr_m5_28'] + 1e-6)
)
```

**意味**:
- `> 1.2`: 短期ボラティリティ上昇（変動活発化）
- `< 0.8`: 短期ボラティリティ低下（変動沈静化）

---

### 3. ボラティリティレジーム（2列）

市場環境を3段階分類（低/通常/高）。

```python
def classify_regime(
    atr: pd.Series, 
    percentiles: List[int] = [33, 67]
) -> pd.Series:
    """
    ATRをパーセンタイル分割してレジーム判定
    
    Args:
        atr: ATR系列
        percentiles: 分割点 [低境界, 高境界]
    
    Returns:
        regime: 0=低, 1=通常, 2=高
    """
    low_threshold = atr.rolling(100).quantile(percentiles[0] / 100)
    high_threshold = atr.rolling(100).quantile(percentiles[67] / 100)
    
    regime = pd.Series(1, index=atr.index)  # デフォルト: 通常
    regime[atr <= low_threshold] = 0         # 低ボラ
    regime[atr >= high_threshold] = 2        # 高ボラ
    
    return regime

features['vol_regime_m5'] = classify_regime(features['atr_m5_14'])
features['vol_regime_h1'] = classify_regime(features['atr_h1_14'])
```

**値**:
- `0`: 低ボラティリティ（レンジ相場）
- `1`: 通常ボラティリティ
- `2`: 高ボラティリティ（トレンド相場・指標発表）

---

### 4. レンジ圧縮率（1列）

現在のレンジ幅 vs ATR の比率。

```python
features['range_compression'] = (
    (raw_data['M5']['high'] - raw_data['M5']['low']) * 10000 /
    (features['atr_m5_14'] + 1e-6)
)
```

**意味**:
- `> 1.5`: 現在のレンジがATRより大きい（大きな動き）
- `≈ 1.0`: 平常
- `< 0.5`: 現在のレンジがATRより小さい（静か）

---

### 5. ボラティリティ変化率（1列）

ATRの前期間比変化率。

```python
features['atr_change_rate'] = (
    (features['atr_m5_14'] - features['atr_m5_14'].shift(1)) /
    (features['atr_m5_14'].shift(1) + 1e-6)
)
```

**意味**:
- 正・大: ボラティリティ急上昇
- 負・大: ボラティリティ急低下

---

## 🧮 実装クラス

```python
class VolatilityRegimeCalculator(BaseCalculator):
    """
    ボラティリティ・レジーム特徴量計算器
    """
    
    @property
    def name(self) -> str:
        return "volatility_regime"
    
    def compute(
        self, 
        raw_data: Dict[str, pd.DataFrame]
    ) -> pd.DataFrame:
        """
        ATR・レジーム判定を計算
        
        Returns:
            features: DataFrame(N, 12)
        """
        features = {}
        
        # マルチTF ATR（5列）
        features['atr_m1_14'] = self._calculate_atr(raw_data['M1'], 14)
        features['atr_m5_14'] = self._calculate_atr(raw_data['M5'], 14)
        features['atr_h1_14'] = self._calculate_atr(raw_data['H1'], 14)
        features['atr_m5_7'] = self._calculate_atr(raw_data['M5'], 7)
        features['atr_m5_28'] = self._calculate_atr(raw_data['M5'], 28)
        
        # ATR比率（3列）
        features['atr_m1_m5_ratio'] = (
            features['atr_m1_14'] / (features['atr_m5_14'] + 1e-6)
        )
        features['atr_m5_h1_ratio'] = (
            features['atr_m5_14'] / (features['atr_h1_14'] + 1e-6)
        )
        features['atr_m5_short_long_ratio'] = (
            features['atr_m5_7'] / (features['atr_m5_28'] + 1e-6)
        )
        
        # レジーム判定（2列）
        features['vol_regime_m5'] = self._classify_regime(
            features['atr_m5_14']
        )
        features['vol_regime_h1'] = self._classify_regime(
            features['atr_h1_14']
        )
        
        # レンジ圧縮率（1列）
        m5_range = (
            (raw_data['M5']['high'] - raw_data['M5']['low']) * 10000
        )
        features['range_compression'] = (
            m5_range / (features['atr_m5_14'] + 1e-6)
        )
        
        # ボラティリティ変化率（1列）
        features['atr_change_rate'] = (
            (features['atr_m5_14'] - features['atr_m5_14'].shift(1)) /
            (features['atr_m5_14'].shift(1) + 1e-6)
        )
        
        return pd.DataFrame(features)
    
    def _calculate_atr(
        self, 
        df: pd.DataFrame, 
        period: int = 14
    ) -> pd.Series:
        """ATR計算"""
        high = df['high']
        low = df['low']
        close = df['close']
        
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1) * 10000
        
        return tr.rolling(period).mean()
    
    def _classify_regime(
        self, 
        atr: pd.Series, 
        percentiles: List[int] = [33, 67],
        window: int = 100
    ) -> pd.Series:
        """レジーム判定"""
        low_threshold = atr.rolling(window).quantile(percentiles[0] / 100)
        high_threshold = atr.rolling(window).quantile(percentiles[1] / 100)
        
        regime = pd.Series(1, index=atr.index)
        regime[atr <= low_threshold] = 0
        regime[atr >= high_threshold] = 2
        
        return regime
```

---

## ✅ 検証基準

### 1. NaN比率
- **閾値**: < 10%
- **理由**: rolling計算の初期期間（最大100期間）でNaN発生

### 2. 値の範囲
- `atr_*_14`: 1 ~ 50 pips（通常時）
- `atr_*_ratio`: 0.5 ~ 2.0
- `vol_regime_*`: 0, 1, 2（整数）
- `range_compression`: 0.3 ~ 2.0
- `atr_change_rate`: -0.5 ~ +0.5

### 3. レジーム分布
- 理想的には 低:通常:高 = 33:34:33
- 実際は市場環境により変動

---

## 📊 出力例

```python
# 出力DataFrame（N, 12）
features = pd.DataFrame({
    # マルチTF ATR（5列）
    'atr_m1_14': [0.8, 0.9, 0.7, ...],
    'atr_m5_14': [4.5, 4.8, 4.2, ...],
    'atr_h1_14': [18.2, 19.1, 17.5, ...],
    'atr_m5_7': [5.2, 5.5, 4.9, ...],
    'atr_m5_28': [4.1, 4.3, 4.0, ...],
    
    # ATR比率（3列）
    'atr_m1_m5_ratio': [0.18, 0.19, 0.17, ...],
    'atr_m5_h1_ratio': [0.25, 0.25, 0.24, ...],
    'atr_m5_short_long_ratio': [1.27, 1.28, 1.23, ...],
    
    # レジーム判定（2列）
    'vol_regime_m5': [1, 2, 1, ...],  # 0/1/2
    'vol_regime_h1': [1, 1, 0, ...],
    
    # その他（2列）
    'range_compression': [0.95, 1.12, 0.88, ...],
    'atr_change_rate': [0.02, 0.05, -0.03, ...],
})
```

---

## 🚨 注意事項

### ATRの意味
- ATR自体は**方向性を持たない**（上昇/下降を区別しない）
- あくまで**変動幅**の指標
- トレンド判定には別の指標が必要

### 価格回帰への貢献
- ATR単体では価格予測に直結しない
- ボラティリティレジームに応じて**予測の信頼度**を調整する用途
- 例: 高ボラ時は予測幅を広げる

---

## 🔗 関連仕様書

- **メイン仕様**: [FEATURE_CALCULATOR_SPEC.md](../FEATURE_CALCULATOR_SPEC.md)
- **基本特徴量**: [BASIC_MULTI_TF_SPEC.md](./BASIC_MULTI_TF_SPEC.md)
- **マイクロ構造**: [MICROSTRUCTURE_SPEC.md](./MICROSTRUCTURE_SPEC.md)

---

**最終更新**: 2025-10-22  
**ステータス**: ドラフト
