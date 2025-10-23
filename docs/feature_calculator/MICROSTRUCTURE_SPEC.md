# マイクロ構造拡張仕様書

**カテゴリ**: 2/5
**処理段階**: 第2段階: 特徴量計算
**列数**: 10-15列  
**目的**: スプレッド・約定環境の考慮

---

## 📋 概要

マーケット**マイクロ構造**に基づく特徴量。スプレッド動態、ティック到着率、方向転換率など、**約定環境**を反映する情報。

### 設計方針
- スプレッドの変動パターンを捕捉
- ティックレベルの市場活性度を測定
- 短期的な方向転換頻度を検出

### データ要件
- Ask/Bid価格（`docs/data_collector/MICROSTRUCTURE_SPEC.md` 参照）
- ティックカウント情報

---

## 🎯 特徴量詳細

### 1. スプレッド動態（4列）

#### 1-1. 瞬間スプレッド（pips）

```python
features['spread_pips'] = (ask - bid) * 10000
```

**目的**: 現在のスプレッド幅

**例**:
- EUR/USD Ask 1.10050, Bid 1.10040 → `spread_pips = 1.0`

---

#### 1-2. スプレッド移動平均（5期間）

```python
features['spread_ma_5'] = features['spread_pips'].rolling(5).mean()
```

**目的**: スプレッドの平常状態

---

#### 1-3. スプレッドショック

```python
features['spread_shock'] = (
    (features['spread_pips'] - features['spread_ma_5']) / 
    features['spread_ma_5']
)
```

**目的**: 急激なスプレッド拡大を検出

**値**:
- `> 1.0`: スプレッドが平常の2倍以上（流動性低下）
- `≈ 0.0`: 正常
- `< -0.5`: スプレッド異常縮小（稀）

---

#### 1-4. スプレッド・ATR比率

```python
features['spread_atr_ratio'] = (
    features['spread_pips'] / atr_m5_14
)
```

**目的**: ボラティリティ比でのスプレッド評価

**意味**:
- 高: ボラティリティに対してスプレッドが広い（不利な環境）
- 低: ボラティリティに対してスプレッドが狭い（有利な環境）

---

### 2. ティック到着率（3列）

#### 2-1. 1分あたりティック数

```python
# M1基準で計算
features['tick_rate_per_minute'] = tick_count / 60
```

**目的**: 市場活性度の直接指標

**例**:
- 静かな時間帯: 5-10 ticks/min
- 指標発表時: 50-100 ticks/min

---

#### 2-2. ティック到着率移動平均（12期間）

```python
features['tick_rate_ma_12'] = (
    features['tick_rate_per_minute'].rolling(12).mean()
)
```

**目的**: 平常時の活性度

---

#### 2-3. ティック到着率変化

```python
features['tick_rate_change'] = (
    features['tick_rate_per_minute'] - features['tick_rate_ma_12']
)
```

**目的**: 急激な活性度変化を検出

**値**:
- 正・大: 市場が急激に活発化（ニュース・指標）
- 負・大: 市場が沈静化

---

### 3. 方向転換率（2列）

#### 3-1. 12本窓の方向転換回数

```python
def count_direction_changes(close: pd.Series, window: int = 12) -> int:
    """
    指定窓内での方向転換回数
    
    Example:
        close = [1.0, 1.1, 1.2, 1.1, 1.0, 1.1]
        → 方向転換: 2回（上昇→下降、下降→上昇）
    """
    direction = np.sign(close.diff())
    changes = (direction != direction.shift(1)).astype(int)
    return changes.rolling(window).sum()

features['direction_flip_count_12'] = count_direction_changes(
    close_M1, window=12
)
```

**目的**: レンジ相場 vs トレンド相場の判別

**値**:
- 高（>8）: レンジ相場（頻繁な反転）
- 低（<3）: トレンド相場（一方向）

---

#### 3-2. 方向転換率（正規化）

```python
features['direction_flip_rate'] = (
    features['direction_flip_count_12'] / 12
)
```

**目的**: 0-1範囲で転換頻度を表現

**値**:
- `≈ 0.0`: 強いトレンド
- `≈ 0.5`: 中程度
- `≈ 0.8`: レンジ相場

---

### 4. マイクロ構造複合指標（2列）

#### 4-1. 流動性指標

```python
features['liquidity_score'] = (
    features['tick_rate_per_minute'] / (features['spread_pips'] + 1e-6)
)
```

**目的**: 流動性の総合評価

**意味**:
- 高: 多くのティック + 狭いスプレッド（高流動性）
- 低: 少ないティック + 広いスプレッド（低流動性）

---

#### 4-2. マイクロボラティリティ

```python
features['micro_volatility'] = (
    features['M1_range_pips'].rolling(12).std()
)
```

**目的**: M1レベルの微細な変動性

---

## 🧮 実装クラス

```python
class MicrostructureCalculator(BaseCalculator):
    """
    マイクロ構造拡張特徴量計算器
    """
    
    @property
    def name(self) -> str:
        return "microstructure"
    
    def compute(
        self, 
        raw_data: Dict[str, pd.DataFrame]
    ) -> pd.DataFrame:
        """
        スプレッド・ティック・方向転換の特徴量を計算
        
        Args:
            raw_data: {
                'M1': DataFrame(N, 8) [time, open, high, low, close, volume, ask, bid],
                ...
            }
        
        Returns:
            features: DataFrame(N, 12)
        """
        features = {}
        
        # M1データ取得
        df_m1 = raw_data['M1']
        ask = df_m1['ask']
        bid = df_m1['bid']
        close = df_m1['close']
        tick_count = df_m1.get('tick_count', pd.Series([10] * len(df_m1)))
        
        # スプレッド動態（4列）
        spread_pips = (ask - bid) * 10000
        spread_ma_5 = spread_pips.rolling(5).mean()
        
        features['spread_pips'] = spread_pips
        features['spread_ma_5'] = spread_ma_5
        features['spread_shock'] = (
            (spread_pips - spread_ma_5) / (spread_ma_5 + 1e-6)
        )
        
        # ATR計算（簡易版）
        atr_m5_14 = self._calculate_atr(raw_data['M5'], period=14)
        features['spread_atr_ratio'] = spread_pips / (atr_m5_14 + 1e-6)
        
        # ティック到着率（3列）
        tick_rate = tick_count / 60
        tick_rate_ma = tick_rate.rolling(12).mean()
        
        features['tick_rate_per_minute'] = tick_rate
        features['tick_rate_ma_12'] = tick_rate_ma
        features['tick_rate_change'] = tick_rate - tick_rate_ma
        
        # 方向転換率（2列）
        flip_count = self._count_direction_changes(close, window=12)
        features['direction_flip_count_12'] = flip_count
        features['direction_flip_rate'] = flip_count / 12
        
        # 複合指標（2列）
        features['liquidity_score'] = tick_rate / (spread_pips + 1e-6)
        
        m1_range = (df_m1['high'] - df_m1['low']) * 10000
        features['micro_volatility'] = m1_range.rolling(12).std()
        
        return pd.DataFrame(features)
    
    def _calculate_atr(
        self, 
        df: pd.DataFrame, 
        period: int = 14
    ) -> pd.Series:
        """ATR計算（簡易版）"""
        high = df['high']
        low = df['low']
        close = df['close']
        
        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs()
        ], axis=1).max(axis=1) * 10000
        
        return tr.rolling(period).mean()
    
    def _count_direction_changes(
        self, 
        close: pd.Series, 
        window: int = 12
    ) -> pd.Series:
        """方向転換回数カウント"""
        direction = np.sign(close.diff())
        changes = (direction != direction.shift(1)).astype(int)
        return changes.rolling(window).sum()
```

---

## ✅ 検証基準

### 1. データ要件
- Ask/Bid価格が存在すること
- ティックカウント情報が存在すること（なければダミー値10で代用）

### 2. NaN比率
- **閾値**: < 10%
- **理由**: rolling計算の初期期間でNaN発生

### 3. 値の範囲
- `spread_pips`: 0.5 ~ 5.0（通常時）
- `spread_shock`: -0.5 ~ +2.0
- `tick_rate_per_minute`: 5 ~ 100
- `direction_flip_rate`: 0.0 ~ 1.0
- `liquidity_score`: 1 ~ 100

### 4. 異常検出
- スプレッド異常拡大（> 10pips）を警告ログ出力

---

## 📊 出力例

```python
# 出力DataFrame（N, 12）
features = pd.DataFrame({
    # スプレッド動態（4列）
    'spread_pips': [1.2, 1.1, 1.3, ...],
    'spread_ma_5': [1.15, 1.18, 1.20, ...],
    'spread_shock': [0.04, -0.07, 0.08, ...],
    'spread_atr_ratio': [0.25, 0.22, 0.26, ...],
    
    # ティック到着率（3列）
    'tick_rate_per_minute': [12, 15, 18, ...],
    'tick_rate_ma_12': [14, 14.5, 15, ...],
    'tick_rate_change': [-2, 0.5, 3, ...],
    
    # 方向転換率（2列）
    'direction_flip_count_12': [4, 5, 3, ...],
    'direction_flip_rate': [0.33, 0.42, 0.25, ...],
    
    # 複合指標（2列）
    'liquidity_score': [10, 13.6, 13.8, ...],
    'micro_volatility': [0.8, 0.9, 0.7, ...],
})
```

---

## 🚨 注意事項

### Ask/Bid データ取得の重要性
- MT5の `COPY_TICKS_ALL` モードでティックデータ取得必須
- Ask/Bid なしの場合、このカテゴリは無効化される

### 計算コスト
- M1ティックレベルの計算のため、やや重い
- ベクトル化（NumPy）で最適化必須

---

## 🔗 関連仕様書

- **メイン仕様**: [FEATURE_CALCULATOR_SPEC.md](../FEATURE_CALCULATOR_SPEC.md)
- **データ収集**: [data_collector/MICROSTRUCTURE_SPEC.md](../data_collector/MICROSTRUCTURE_SPEC.md)
- **基本特徴量**: [BASIC_MULTI_TF_SPEC.md](./BASIC_MULTI_TF_SPEC.md)

---

**最終更新**: 2025-10-22  
**ステータス**: ドラフト
