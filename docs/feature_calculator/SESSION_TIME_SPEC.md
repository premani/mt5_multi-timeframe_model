# セッション・時間仕様書

**カテゴリ**: 5/5
**処理段階**: 第2段階: 特徴量計算
**列数**: 5-8列  
**目的**: 時間帯による市場特性反映

---

## 📋 概要

時刻とセッション（東京/欧州/NY）による市場特性を特徴量化。時刻の周期性をsin/cos変換で表現し、モデルが**時間帯固有のパターン**を学習できるようにする。

### 設計方針
- **時刻の周期性**: sin/cos変換（線形な値ではなく周期的な値）
- **セッション判定**: 東京/欧州/NYの3セッション
- **曜日効果**: 週初/週末の特性

### 時刻管理方針
- **特徴量計算**: UTC時刻で処理
- **セッション定義**: UTC基準で定義（コメントにJST参考情報を併記）
- **ログ出力**: 日本時間(JST)で表示
- 詳細: [docs/utils/TIMEZONE_UTILS_SPEC.md](../utils/TIMEZONE_UTILS_SPEC.md)

---

## 🎯 特徴量詳細

### 1. 時刻エンコード（4列）

時刻（hour/minute）を周期的な値に変換。

#### 1-1. 時刻sin/cos（24時間周期）

```python
import numpy as np

# UTC時刻を取得
time = raw_data['M5']['time']
hour = time.dt.hour
minute = time.dt.minute

# 24時間周期のsin/cos変換
features['hour_sin'] = np.sin(2 * np.pi * hour / 24)
features['hour_cos'] = np.cos(2 * np.pi * hour / 24)

# 60分周期のsin/cos変換
features['minute_sin'] = np.sin(2 * np.pi * minute / 60)
features['minute_cos'] = np.cos(2 * np.pi * minute / 60)
```

**なぜsin/cos変換？**
- 時刻は周期的（23時→0時は連続）
- 単純な整数値だと、0時と23時が遠い値になる
- sin/cosを使うことで、0時と23時が近い値になる

**値域**: 各列とも -1.0 ~ +1.0

**例**:
```python
# 0時（UTC）
hour_sin = sin(2π * 0 / 24) = 0.0
hour_cos = cos(2π * 0 / 24) = 1.0

# 6時（UTC）
hour_sin = sin(2π * 6 / 24) = 1.0
hour_cos = cos(2π * 6 / 24) = 0.0

# 12時（UTC）
hour_sin = sin(2π * 12 / 24) = 0.0
hour_cos = cos(2π * 12 / 24) = -1.0

# 18時（UTC）
hour_sin = sin(2π * 18 / 24) = -1.0
hour_cos = cos(2π * 18 / 24) = 0.0
```

---

### 2. セッション判定（3列）

#### 2-1. 東京セッション（UTC 0:00-6:00）

```python
# UTC時刻基準
# 東京セッション: JST 9:00-15:00 = UTC 0:00-6:00
features['session_tokyo'] = (
    (hour >= 0) & (hour < 6)
).astype(int)
```

**値**: 0 or 1

---

#### 2-2. 欧州セッション（UTC 7:00-15:00）

```python
# 欧州セッション: GMT 8:00-16:00 = UTC 7:00-15:00（夏時間考慮）
features['session_europe'] = (
    (hour >= 7) & (hour < 15)
).astype(int)
```

---

#### 2-3. NYセッション（UTC 13:00-21:00）

```python
# NYセッション: EST 8:00-16:00 = UTC 13:00-21:00（夏時間考慮）
features['session_ny'] = (
    (hour >= 13) & (hour < 21)
).astype(int)
```

**注意**: 欧州とNYは重複時間帯あり（UTC 13:00-15:00）

---

### 3. 曜日効果（2列）

#### 3-1. 週初（月曜）

```python
day_of_week = time.dt.dayofweek  # 0=月曜, 6=日曜

features['is_monday'] = (day_of_week == 0).astype(int)
```

**意味**: 週初の価格跳ね（週末ギャップ）

---

#### 3-2. 週末（金曜）

```python
features['is_friday'] = (day_of_week == 4).astype(int)
```

**意味**: 週末前のポジション調整

---

### 4. セッション重複判定（1列、オプション）

```python
features['session_overlap'] = (
    features['session_europe'] & features['session_ny']
).astype(int)
```

**意味**: 欧州とNYの重複時間帯（最も流動性が高い）

**値**: 0 or 1

---

## 🧮 実装クラス

```python
class SessionTimeCalculator(BaseCalculator):
    """
    セッション・時間特徴量計算器
    """
    
    @property
    def name(self) -> str:
        return "session_time"
    
    def compute(
        self, 
        raw_data: Dict[str, pd.DataFrame]
    ) -> pd.DataFrame:
        """
        時刻・セッション特徴量を計算
        
        Returns:
            features: DataFrame(N, 8)
        """
        features = {}
        
        # M5の時刻を取得（全TF共通）
        time = raw_data['M5']['time']
        hour = time.dt.hour
        minute = time.dt.minute
        day_of_week = time.dt.dayofweek
        
        # 時刻エンコード（4列）
        features['hour_sin'] = np.sin(2 * np.pi * hour / 24)
        features['hour_cos'] = np.cos(2 * np.pi * hour / 24)
        features['minute_sin'] = np.sin(2 * np.pi * minute / 60)
        features['minute_cos'] = np.cos(2 * np.pi * minute / 60)
        
        # セッション判定（3列）
        features['session_tokyo'] = (
            (hour >= 0) & (hour < 6)
        ).astype(int)
        
        features['session_europe'] = (
            (hour >= 7) & (hour < 15)
        ).astype(int)
        
        features['session_ny'] = (
            (hour >= 13) & (hour < 21)
        ).astype(int)
        
        # 曜日効果（2列）
        features['is_monday'] = (day_of_week == 0).astype(int)
        features['is_friday'] = (day_of_week == 4).astype(int)
        
        # セッション重複（1列、オプション）
        features['session_overlap'] = (
            features['session_tokyo'] & features['session_ny']
        ).astype(int)
        
        return pd.DataFrame(features)
```

---

## ✅ 検証基準

### 1. NaN比率
- **閾値**: 0%
- **理由**: 時刻情報は必ず存在、NaN発生なし

### 2. 値の範囲
- `hour_sin`, `hour_cos`: -1.0 ~ +1.0
- `minute_sin`, `minute_cos`: -1.0 ~ +1.0
- `session_*`: 0 or 1
- `is_monday`, `is_friday`: 0 or 1
- `session_overlap`: 0 or 1

### 3. セッション分布
- 各セッションが適切な比率で出現すること
  - 東京: ≈ 25%（6時間/24時間）
  - 欧州: ≈ 33%（8時間/24時間）
  - NY: ≈ 33%（8時間/24時間）
  - 重複: ≈ 8%（2時間/24時間）

---

## 📊 出力例

```python
# 出力DataFrame（N, 8）
features = pd.DataFrame({
    # 時刻エンコード（4列）
    'hour_sin': [0.0, 0.26, 0.5, ...],       # UTC 0時, 1時, 2時
    'hour_cos': [1.0, 0.97, 0.87, ...],
    'minute_sin': [0.0, 0.1, 0.2, ...],      # 0分, 6分, 12分
    'minute_cos': [1.0, 0.99, 0.98, ...],
    
    # セッション判定（3列）
    'session_tokyo': [1, 1, 1, 0, 0, ...],   # UTC 0-5時は1
    'session_europe': [0, 0, 0, 1, 1, ...],  # UTC 7-14時は1
    'session_ny': [0, 0, 0, 1, 1, ...],      # UTC 13-20時は1
    
    # 曜日効果（2列）
    'is_monday': [1, 0, 0, 0, 0, ...],       # 月曜のみ1
    'is_friday': [0, 0, 0, 0, 1, ...],       # 金曜のみ1
    
    # セッション重複（1列）
    'session_overlap': [0, 0, 0, 1, 0, ...], # UTC 13-14時のみ1
})
```

---

## 🌍 タイムゾーン設定

### UTC基準の理由
- MT5サーバー時刻は通常UTC+2/+3（夏時間）
- しかし取引戦略は**グローバルな時刻**に依存
- UTC統一で一貫性を保つ

### タイムゾーン変換（参考）

```python
# MT5サーバー時刻（UTC+2）をUTCに変換
import pytz

mt5_time = pd.to_datetime('2025-10-22 10:00:00')  # MT5サーバー時刻
mt5_tz = pytz.timezone('Europe/Helsinki')  # UTC+2/+3
utc_tz = pytz.UTC

# UTCに変換
time_utc = mt5_tz.localize(mt5_time).astimezone(utc_tz)
```

---

## 🚨 注意事項

### 夏時間の扱い
- 欧州/NYは夏時間と冬時間で1時間ずれる
- 本プロジェクトでは**夏時間を標準**とする
- 冬時間の対応は将来拡張

### セッション重複の意義
- 欧州とNYの重複時間帯（UTC 13:00-15:00）は最も流動性が高い
- 価格変動が大きくなる傾向
- この時間帯を特別に扱うことで精度向上の可能性

### 曜日効果の限定的使用
- 週初（月曜）と週末（金曜）のみ特徴化
- 火/水/木は中立として扱う
- 過度な曜日依存を避ける

---

## 🔗 関連仕様書

- **メイン仕様**: [FEATURE_CALCULATOR_SPEC.md](../FEATURE_CALCULATOR_SPEC.md)
- **基本特徴量**: [BASIC_MULTI_TF_SPEC.md](./BASIC_MULTI_TF_SPEC.md)
- **データ収集**: [DATA_COLLECTOR_SPEC.md](../DATA_COLLECTOR_SPEC.md)

---

## 📚 参考資料

### セッション時間帯（UTC基準）

| セッション | 現地時刻 | UTC時刻 | 特徴 |
|----------|---------|---------|------|
| **東京** | JST 9:00-15:00 | UTC 0:00-6:00 | アジア通貨活発 |
| **欧州** | GMT 8:00-16:00 | UTC 7:00-15:00 | EUR/GBP活発 |
| **NY** | EST 8:00-16:00 | UTC 13:00-21:00 | USD活発 |
| **重複** | - | UTC 13:00-15:00 | 最高流動性 |

### 時刻エンコード参考文献
- Circular Features in Machine Learning: https://ianlondon.github.io/blog/encoding-cyclical-features-24hour-time/

---

**最終更新**: 2025-10-22  
**ステータス**: ドラフト
