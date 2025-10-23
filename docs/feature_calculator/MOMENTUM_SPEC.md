# 簡潔勢い指標仕様書

**カテゴリ**: 4/5
**処理段階**: 第2段階: 特徴量計算
**列数**: 8-12列  
**目的**: トレンド・反転の勢い情報（最小限）

---

## 📋 概要

**旧プロジェクトの反省**を活かし、勢い指標を**8-12列に削減**。RSI、MACD、ボリンジャーバンド、モメンタムの最小構成。

### 旧プロジェクトとの違い

| 項目 | 旧プロジェクト | 本プロジェクト |
|------|--------------|--------------|
| 指標数 | 22指標 | 8-12指標 |
| カテゴリ | ブレイクアウト、チャネル、勢い等 | **簡潔勢い指標に統合** |
| 設計対象 | 方向分類 | **価格回帰** |

### 設計方針
- **最小構成**: RSI/MACD/BB/Momentumのみ
- **価格回帰用に調整**: 値そのものではなく、価格への寄与度を重視
- **マルチTF**: M5とH1のみ（M1は短すぎ、H4は遅すぎ）

---

## 🎯 特徴量詳細

### 1. RSI（Relative Strength Index）（2列）

#### 1-1. M5 RSI（14期間）

```python
def calculate_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """
    RSI計算
    
    RSI = 100 - (100 / (1 + RS))
    RS = 平均上昇幅 / 平均下降幅
    """
    delta = close.diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    
    rs = avg_gain / (avg_loss + 1e-6)
    rsi = 100 - (100 / (1 + rs))
    
    return rsi

features['rsi_m5_14'] = calculate_rsi(close_M5, 14)
```

**値域**: 0-100

**意味**:
- `> 70`: 買われすぎ（反転下落の可能性）
- `30-70`: 中立
- `< 30`: 売られすぎ（反転上昇の可能性）

---

#### 1-2. H1 RSI（14期間）

```python
features['rsi_h1_14'] = calculate_rsi(close_H1, 14)
```

**目的**: 長期トレンドの勢い

---

### 2. MACD（Moving Average Convergence Divergence）（3列）

M5のみで計算（12/26/9パラメータ）。

```python
def calculate_macd(
    close: pd.Series, 
    fast: int = 12, 
    slow: int = 26, 
    signal: int = 9
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    MACD計算
    
    MACD Line = EMA(fast) - EMA(slow)
    Signal Line = EMA(MACD, signal)
    Histogram = MACD - Signal
    """
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    
    return macd_line, signal_line, histogram

macd, signal, hist = calculate_macd(close_M5, 12, 26, 9)

# pips単位に変換
features['macd_m5'] = macd * 10000
features['macd_signal_m5'] = signal * 10000
features['macd_hist_m5'] = hist * 10000
```

**意味**:
- `macd_hist > 0`: 上昇トレンド
- `macd_hist < 0`: 下降トレンド
- `macd_hist` の符号変化: トレンド転換

---

### 3. ボリンジャーバンド位置（2列）

#### 3-1. M5 BB位置（20期間、2σ）

```python
def bb_position(
    close: pd.Series, 
    period: int = 20, 
    std_dev: float = 2.0
) -> pd.Series:
    """
    ボリンジャーバンド内での価格位置
    
    0.0 = 下限バンド
    0.5 = 中央（移動平均）
    1.0 = 上限バンド
    """
    ma = close.rolling(period).mean()
    std = close.rolling(period).std()
    
    upper = ma + std_dev * std
    lower = ma - std_dev * std
    
    position = (close - lower) / (upper - lower + 1e-6)
    
    # クリップ（バンド外の場合）
    return position.clip(0, 1)

features['bb_position_m5'] = bb_position(close_M5, 20, 2.0)
```

**値域**: 0.0 ~ 1.0

**意味**:
- `≈ 1.0`: 上限近く（買われすぎ、反落可能性）
- `≈ 0.5`: 中央（中立）
- `≈ 0.0`: 下限近く（売られすぎ、反発可能性）

---

#### 3-2. H1 BB位置（20期間、2σ）

```python
features['bb_position_h1'] = bb_position(close_H1, 20, 2.0)
```

---

### 4. モメンタム（価格変化の加速度）（2列）

#### 4-1. M5 モメンタム（12期間）

```python
features['momentum_m5_12'] = (
    (close_M5 - close_M5.shift(12)) * 10000
)
```

**目的**: 12本前からの価格変化（pips）

**意味**:
- 正・大: 強い上昇勢い
- 負・大: 強い下降勢い

---

#### 4-2. H1 モメンタム（12期間）

```python
features['momentum_h1_12'] = (
    (close_H1 - close_H1.shift(12)) * 10000
)
```

---

### 5. 複合勢い指標（2列）

#### 5-1. RSI発散（M5 vs H1）

```python
features['rsi_divergence_m5_h1'] = (
    features['rsi_m5_14'] - features['rsi_h1_14']
)
```

**意味**:
- 正・大: M5が買われすぎ、H1は中立（短期過熱）
- 負・大: M5が売られすぎ、H1は中立（短期過冷）

---

#### 5-2. MACD勢い（ヒストグラムの変化率）

```python
features['macd_momentum'] = (
    features['macd_hist_m5'] - features['macd_hist_m5'].shift(1)
)
```

**意味**:
- 正: 勢い加速
- 負: 勢い減速

---

## 🧮 実装クラス

```python
class MomentumCalculator(BaseCalculator):
    """
    簡潔勢い指標計算器
    """
    
    @property
    def name(self) -> str:
        return "momentum"
    
    def compute(
        self, 
        raw_data: Dict[str, pd.DataFrame]
    ) -> pd.DataFrame:
        """
        RSI/MACD/BB/Momentumを計算
        
        Returns:
            features: DataFrame(N, 12)
        """
        features = {}
        
        close_M5 = raw_data['M5']['close']
        close_H1 = raw_data['H1']['close']
        
        # RSI（2列）
        features['rsi_m5_14'] = self._calculate_rsi(close_M5, 14)
        features['rsi_h1_14'] = self._calculate_rsi(close_H1, 14)
        
        # MACD（3列）
        macd, signal, hist = self._calculate_macd(close_M5, 12, 26, 9)
        features['macd_m5'] = macd * 10000
        features['macd_signal_m5'] = signal * 10000
        features['macd_hist_m5'] = hist * 10000
        
        # ボリンジャーバンド位置（2列）
        features['bb_position_m5'] = self._bb_position(close_M5, 20, 2.0)
        features['bb_position_h1'] = self._bb_position(close_H1, 20, 2.0)
        
        # モメンタム（2列）
        features['momentum_m5_12'] = (close_M5 - close_M5.shift(12)) * 10000
        features['momentum_h1_12'] = (close_H1 - close_H1.shift(12)) * 10000
        
        # 複合勢い指標（2列）
        features['rsi_divergence_m5_h1'] = (
            features['rsi_m5_14'] - features['rsi_h1_14']
        )
        features['macd_momentum'] = (
            features['macd_hist_m5'] - features['macd_hist_m5'].shift(1)
        )
        
        return pd.DataFrame(features)
    
    def _calculate_rsi(
        self, 
        close: pd.Series, 
        period: int = 14
    ) -> pd.Series:
        """RSI計算"""
        delta = close.diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        
        avg_gain = gain.rolling(period).mean()
        avg_loss = loss.rolling(period).mean()
        
        rs = avg_gain / (avg_loss + 1e-6)
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
    
    def _calculate_macd(
        self, 
        close: pd.Series, 
        fast: int = 12, 
        slow: int = 26, 
        signal: int = 9
    ) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """MACD計算"""
        ema_fast = close.ewm(span=fast, adjust=False).mean()
        ema_slow = close.ewm(span=slow, adjust=False).mean()
        
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram = macd_line - signal_line
        
        return macd_line, signal_line, histogram
    
    def _bb_position(
        self, 
        close: pd.Series, 
        period: int = 20, 
        std_dev: float = 2.0
    ) -> pd.Series:
        """ボリンジャーバンド位置"""
        ma = close.rolling(period).mean()
        std = close.rolling(period).std()
        
        upper = ma + std_dev * std
        lower = ma - std_dev * std
        
        position = (close - lower) / (upper - lower + 1e-6)
        
        return position.clip(0, 1)
```

---

## ✅ 検証基準

### 1. NaN比率
- **閾値**: < 10%
- **理由**: rolling/ewm計算の初期期間（最大26期間）でNaN発生

### 2. 値の範囲
- `rsi_*_14`: 0 ~ 100
- `macd_*`: -10 ~ +10 pips（通常時）
- `bb_position_*`: 0.0 ~ 1.0
- `momentum_*_12`: -50 ~ +50 pips（通常時）
- `rsi_divergence_m5_h1`: -50 ~ +50
- `macd_momentum`: -5 ~ +5 pips

### 3. 異常値検出
- RSI が 0 または 100 付近で張り付く場合は警告

---

## 📊 出力例

```python
# 出力DataFrame（N, 12）
features = pd.DataFrame({
    # RSI（2列）
    'rsi_m5_14': [45.2, 48.3, 52.1, ...],
    'rsi_h1_14': [38.7, 40.1, 42.5, ...],
    
    # MACD（3列）
    'macd_m5': [0.8, 1.2, 1.5, ...],
    'macd_signal_m5': [0.6, 0.9, 1.1, ...],
    'macd_hist_m5': [0.2, 0.3, 0.4, ...],
    
    # BB位置（2列）
    'bb_position_m5': [0.62, 0.68, 0.71, ...],
    'bb_position_h1': [0.55, 0.58, 0.61, ...],
    
    # モメンタム（2列）
    'momentum_m5_12': [3.2, 4.1, 5.3, ...],
    'momentum_h1_12': [12.5, 13.8, 15.2, ...],
    
    # 複合勢い指標（2列）
    'rsi_divergence_m5_h1': [6.5, 8.2, 9.6, ...],
    'macd_momentum': [0.1, 0.1, 0.1, ...],
})
```

---

## 🚨 注意事項

### 旧プロジェクトとの違い

| 旧プロジェクト | 本プロジェクト |
|-------------|-------------|
| 方向分類用（RSI/MACDのクロスでシグナル） | 価格回帰用（値を特徴量として使用） |
| 22指標（ブレイクアウト、チャネル等含む） | 8-12指標（最小構成） |
| M1/M5/M15/H1/H4 全TFで計算 | M5/H1のみ（効率化） |

### 価格回帰への貢献

- RSI/MACDは**方向転換の予兆**を捉える
- しかし**価格変化量**の予測には直接寄与しにくい
- ボラティリティやトレンド強度と組み合わせて使用

---

## 🔗 関連仕様書

- **メイン仕様**: [FEATURE_CALCULATOR_SPEC.md](../FEATURE_CALCULATOR_SPEC.md)
- **基本特徴量**: [BASIC_MULTI_TF_SPEC.md](./BASIC_MULTI_TF_SPEC.md)
- **ボラティリティ**: [VOLATILITY_REGIME_SPEC.md](./VOLATILITY_REGIME_SPEC.md)

---

**最終更新**: 2025-10-22  
**ステータス**: ドラフト
