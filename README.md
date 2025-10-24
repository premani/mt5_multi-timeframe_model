# mt5-multi-timeframe-model

マルチタイムフレーム分析による FX 価格予測モデル

---

## 📊 プロジェクト概要

### 目的
MetaTrader 5 (MT5) の複数タイムフレーム（M1, M5, M15, H1, H4）を同時分析し、**方向（UP/DOWN/NEUTRAL）** と **価格幅（pips）** を予測する深層学習モデルの開発。

### 前プロジェクトからの教訓

#### ❌ 失敗プロジェクト: `mt5_lstm-model`及び`mt5-expert_manias-ai_lstm-model`
1. **方向のみ予測の限界**
   - 方向予測精度80%達成も、価格幅不明で実用不可
   - エントリー判断に必要な情報不足

2. **単一タイムフレームの情報不足**
   - M5のみの分析では大局的なトレンド把握困難
   - 短期ノイズに影響されやすい

3. **固定シーケンス長の問題**
   - 360本入力 → 末尾36本のみ使用
   - パターン認識の柔軟性不足

### ✅ 本プロジェクトの改善点

1. **マルチタスク学習**
   - 方向 + 価格幅を同時予測
   - 実用可能なエントリー判断情報を提供

2. **マルチタイムフレーム分析**

**対象タイムフレーム**: M1, M5, M15, H1, H4（全5種類を常時使用）

**各TFの役割**:
   - **M1** (超短期): エントリータイミング・マイクロ構造分析
   - **M5** (短期): ノイズフィルタ・短期トレンド確認
   - **M15** (中期): 方向性確認・トレンド初期検出
   - **H1** (長期): 大局トレンド方向（スイング展開時）
   - **H4** (超長期): マクロトレンド・レジーム判定（トレール条件）

**デュアルモード戦略**:
   - **基本モード（70-80%）**: M1/M5/M15 重点（1時間以内でエグジット）
   - **拡張モード（20-30%）**: trend_strength > 0.7 で H1/H4 活用（トレール延長）
   - **重要**: 全5TFは常に入力として使用、モードによって重み配分が変化

3. **スケール不変パターン認識**
   - ダブルトップ等のパターンは時間スケールに依存しない
   - 1時間で形成されても4時間で形成されても同じロジック
   - プロフェッショナルトレーダーのアプローチを模倣

---

## 🏗️ アーキテクチャ設計

### モデル構造

```
入力: マルチタイムフレーム × TF別シーケンス長 × 特徴量次元

    ┌─────────────┐
    │ M1 (480本)  │ 8時間  ────→ LSTM ────┐
    ├─────────────┤                        │
    │ M5 (288本)  │ 24時間 ────→ LSTM ────┤
    ├─────────────┤                        │
    │ M15 (192本) │ 48時間 ────→ LSTM ────┤──→ Fusion ──┬→ Direction Head
    ├─────────────┤                        │              ├→ Magnitude_Scalp Head
    │ H1 (96本)   │ 4日    ────→ LSTM ────┤              ├→ Magnitude_Swing Head
    ├─────────────┤                        │              └→ Trend_Strength Head
    │ H4 (48本)   │ 8日    ────→ LSTM ────┘
    └─────────────┘

出力:
- Direction: [UP, DOWN, NEUTRAL] の確率分布
- Magnitude_Scalp: 予測価格幅 (pips, 1時間以内)
- Magnitude_Swing: 拡張価格幅 (pips, トレール時)
- Trend_Strength: トレンド強度 (0-1, H1/H4ベース)
```

**重み付け戦略**:
- スキャル基本モード（70-80%）: M1/M5/M15 重点（weight: 0.35/0.30/0.20）
- スイング拡張モード（20-30%）: trend_strength > 0.7 で H1/H4 活用（weight: 0.10/0.05）

### マルチタスク損失関数

```python
# デュアルモード対応
total_loss = α * L_direction + β * L_magnitude_scalp + γ * L_magnitude_swing + δ * L_trend_strength

# 基本モード（スキャルピング）
α = 0.40  # 方向予測
β = 0.35  # 短期価格幅（1時間以内）

# 拡張モード（スイング展開）
γ = 0.15  # 延長価格幅（トレール時）
δ = 0.10  # トレンド強度（H1/H4ベース）
```

---

## 📊 6段階ワークフロー依存関係

各処理段階の依存関係と実装順序を示すDAG（有向非巡回グラフ）：

```
┌─────────────────────────────────────────────────────────────┐
│                   6段階ワークフロー依存関係                    │
└─────────────────────────────────────────────────────────────┘

第1段階: データ収集
    ↓ (依存: MT5接続、HDF5環境)
    │
    ├─ models/*_raw_data.h5 生成
    │
    ↓
第2段階: 特徴量計算
    ↓ (依存: 第1段階の raw_data.h5)
    │
    ├─ models/*_features.h5 生成
    │
    ↓
第3段階: 前処理（正規化・シーケンス化）
    ↓ (依存: 第2段階の features.h5)
    │
    ├─ models/*_preprocessed.h5 生成
    │
    ↓
第4段階: 学習
    ↓ (依存: 第3段階の preprocessed.h5 + utils/model.py)
    │
    ├─ models/*_training.pt 生成
    │
    ↓
┌───┴────┐
│        │
↓        ↓
第5段階:  第6段階:
検証      ONNX変換
↓        ↓
(依存:    (依存:
 第4段階   第4段階
 training  training
 .pt)      .pt)
│        │
├─ 評価  ├─ models/
│  指標  │  *_model.onnx
│  出力  │  生成
```

**実装上の注意**:
- 各段階は前段階の出力ファイルに依存
- 第5段階と第6段階は並行実行可能
- utils/model.pyは第4-6段階で共通利用

---

## 🚀 技術スタック

- **Deep Learning**: PyTorch 2.8.0
- **GPU**: CUDA 12.8
- **コンテナ**: NVIDIA Docker
- **データ**: MetaTrader 5 API
- **実行環境**: Ubuntu 22.04

---

## 📁 ディレクトリ構造

```
mt5-multi-timeframe-model/
├── src/                      # ソースコード
│   ├── data_collector.py     # 第1段階: データ収集
│   ├── feature_calculator.py # 第2段階: 特徴量計算
│   ├── preprocessor.py       # 第3段階: 前処理
│   ├── trainer.py            # 第4段階: 学習
│   ├── validator.py          # 第5段階: 検証
│   ├── onnx_converter.py     # 第6段階: ONNX変換
│   └── utils/                # 共通モジュール
│       ├── model.py          # LSTMモデル定義
│       ├── hdf5_dataset.py
│       ├── logging_manager.py
│       └── timeframe_aligner.py
├── config/                   # 設定ファイル
│   ├── data_collection.yaml
│   ├── preprocessing.yaml
│   └── training.yaml
├── docs/                     # 仕様書（段階別に整理）
│   ├── common/               # 横断的な共通仕様
│   │   ├── CONFIG_MANAGEMENT_SPEC.md
│   │   ├── MODEL_IO_CONTRACT_SPEC.md
│   │   ├── NAMING_CONVENTION.md
│   │   ├── STORAGE_POLICY_SPEC.md
│   │   ├── THRESHOLD_METADATA_SPEC.md
│   │   └── PHASE_DEPENDENCY_DAG.md
│   ├── data_collector/       # 第1段階: データ収集
│   │   └── DATA_COLLECTOR_SPEC.md (メイン)
│   ├── feature_calculator/   # 第2段階: 特徴量計算
│   │   └── FEATURE_CALCULATOR_SPEC.md (メイン)
│   ├── preprocessor/         # 第3段階: 前処理
│   │   └── PREPROCESSOR_SPEC.md (メイン)
│   ├── trainer/              # 第4段階: 学習
│   │   └── TRAINER_SPEC.md (メイン)
│   ├── validator/            # 第5段階: 検証
│   │   └── VALIDATOR_SPEC.md (メイン)
│   ├── onnx_converter/       # 第6段階: ONNX変換
│   │   └── ONNX_CONVERTER_SPEC.md (メイン)
│   └── utils/                # 共通ユーティリティ仕様
│       └── TRACE_ID_SPEC.md
├── data/                     # 生データ（Git管理外）
├── models/                   # 学習済みモデル（Git管理外）
├── logs/                     # ログファイル（Git管理外）
├── tools/                    # 開発ツール（品質検査・単体テスト）
├── Dockerfile
├── docker_run.sh
├── requirements.txt
├── README.md
├── AGENTS.md                 # AI開発ガイド
└── .github/
    └── copilot-instructions.md
```

---

## 🔧 セットアップ

### 1. リポジトリクローン
```bash
git clone https://github.com/premani/mt5-multi-timeframe-model.git
cd mt5-multi-timeframe-model
```

### 2. 環境設定
```bash
# .env ファイル作成
cp .env.template .env
# MT5 接続情報を編集
nano .env
```

### 3. Docker イメージビルド
```bash
docker build -t mt5-mtf-pytorch .
```

### 4. 実行（6段階ワークフロー）
```bash
# 第1段階: データ収集（マルチTF生データ取得）
bash ./docker_run.sh python3 src/data_collector.py

# 第2段階: 特徴量計算（5-7カテゴリ、50-80特徴量）
bash ./docker_run.sh python3 src/feature_calculator.py

# 第3段階: 前処理（正規化・シーケンス化）
bash ./docker_run.sh python3 src/preprocessor.py

# 第4段階: 学習（マルチタスク学習）
bash ./docker_run.sh python3 src/trainer.py

# 第5段階: 検証（精度評価・バックテスト）
bash ./docker_run.sh python3 src/validator.py

# 第6段階: ONNX変換（推論最適化）
bash ./docker_run.sh python3 src/onnx_converter.py
```

---

## 💾 データ量・ストレージ見積もり

各処理段階で生成されるデータのサイズ見積もり（1ヶ月分のデータを想定）。

| 処理段階 | 出力ファイル | データサイズ（1ヶ月） | 説明 |
|---------|-------------|---------------------|------|
| 第1段階: データ収集 | `models/*_raw_data.h5` | 約500MB | 5TF × 6列(OHLCV+time) × float32 × 約45,000行/TF |
| 第2段階: 特徴量計算 | `models/*_features.h5` | 約1.2GB | 5TF × 50-80列 × float32 × 約45,000行 |
| 第3段階: 前処理 | `models/*_preprocessed.h5` | 約2.5GB | シーケンス化: M1(480)×M5(288)×M15(192)×H1(96)×H4(48) × 50-80特徴 |
| 第4段階: 学習 | `models/*_training.pt` | 約5MB | PyTorchモデルパラメータ（1.2M params × 4 bytes） |
| 第6段階: ONNX変換 | `models/*_model.onnx` | 約2.4MB | FP16量子化後（FP32: 4.8MB → FP16: 2.4MB） |

**合計ストレージ要件（1ヶ月分）**: 約4.2GB
**推奨ディスク容量**: 20GB以上（複数期間の保存、ログ、バックアップを考慮）

**データ保持ポリシー**:
- 生データ（第1段階）: 3ヶ月保持
- 前処理済みデータ（第3段階）: 最新1ヶ月のみ保持
- 学習済みモデル: 全バージョン保持（バージョニング管理）

---

## 📚 ドキュメント構造

プロジェクトの仕様書は **段階別** + **共通仕様** で整理されています。

### ディレクトリ構成

```
docs/
├── DATA_COLLECTOR_SPEC.md           # 第1段階: データ収集 メイン仕様
├── FEATURE_CALCULATOR_SPEC.md       # 第2段階: 特徴量計算 メイン仕様
├── PREPROCESSOR_SPEC.md             # 第3段階: 前処理 メイン仕様
├── TRAINER_SPEC.md                  # 第4段階: 学習 メイン仕様
├── VALIDATOR_SPEC.md                # 第5段階: 検証 メイン仕様
├── ONNX_CONVERTER_SPEC.md           # 第6段階: ONNX変換 メイン仕様
│
├── common/                          # 横断的な共通仕様
│   ├── CONFIG_MANAGEMENT_SPEC.md    # 設定管理規約
│   ├── MODEL_IO_CONTRACT_SPEC.md    # 入力契約定義
│   ├── NAMING_CONVENTION.md         # 命名規約
│   ├── STORAGE_POLICY_SPEC.md       # ストレージポリシー
│   ├── THRESHOLD_METADATA_SPEC.md   # 閾値メタデータ管理
│   ├── PHASE_DEPENDENCY_DAG.md      # 段階間依存関係
│   └── FUTURE_ENHANCEMENTS.md       # 将来拡張仕様（Phase 3-4で検討）
│
├── data_collector/                  # 第1段階: サブ仕様
│   ├── TIMESTAMP_ALIGNMENT_SPEC.md
│   ├── MICROSTRUCTURE_SPEC.md
│   └── STORAGE_POLICY_SPEC.md
│
├── feature_calculator/              # 第2段階: サブ仕様
│   ├── BASIC_MULTI_TF_SPEC.md       # カテゴリ1: 基本マルチTF
│   ├── MOMENTUM_SPEC.md             # カテゴリ2: モメンタム
│   ├── VOLATILITY_REGIME_SPEC.md    # カテゴリ3: ボラティリティレジーム
│   ├── MICROSTRUCTURE_SPEC.md       # カテゴリ4: マイクロ構造
│   └── SESSION_TIME_SPEC.md         # カテゴリ5: セッション・時刻
│
├── preprocessor/                    # 第3段階: サブ仕様
│   ├── INPUT_QUALITY_SPEC.md        # 入力品質管理
│   ├── DATA_INTEGRITY_SPEC.md       # データ整合性検証
│   └── NORMALIZATION_SPEC.md        # 正規化仕様
│
├── trainer/                         # 第4段階: サブ仕様
│   ├── MULTI_TF_FUSION_SPEC.md      # マルチTF融合
│   └── GPU_OPTIMIZATION_SPEC.md     # GPU最適化
│
├── validator/                       # 第5段階: サブ仕様
│   ├── COST_MODEL_SPEC.md
│   ├── DYNAMIC_EXIT_SPEC.md
│   ├── BACKTEST_EVALUATION_SPEC.md
│   ├── DRIFT_CALIBRATION_MONITORING_SPEC.md
│   ├── ERROR_RECOVERY_SPEC.md
│   ├── EXECUTION_LATENCY_SPEC.md
│   ├── FUTURE_LEAK_PREVENTION_SPEC.md
│   ├── INVARIANCE_SPEC.md
│   ├── MULTI_SYMBOL_SPEC.md
│   └── SCALP_THRESHOLD_SPEC.md
│
└── utils/                           # 共通ユーティリティ
    ├── CONFIG_MANAGER_SPEC.md
    └── TRACE_ID_SPEC.md
```

### 仕様書の読み方

1. **各段階のメイン仕様書から開始**:
   - docs直下の6つのメイン仕様書（例: `docs/TRAINER_SPEC.md`）
   - 目的、入力契約、処理フロー、出力を記載

2. **必要に応じてサブ仕様を参照**:
   - 各段階のサブディレクトリ配下（例: `docs/trainer/MULTI_TF_FUSION_SPEC.md`）
   - 詳細な実装手法やアルゴリズムを記載

3. **横断的な仕様は`common/`を参照**:
   - 全段階で共通の規約・ポリシー
   - 命名規約、設定管理、ストレージポリシーなど

### 用語統一

| 用語 | 説明 | 範囲 |
|-----|------|------|
| **第N段階** | 6段階ワークフローの処理段階 | データ収集→特徴量計算→前処理→学習→検証→ONNX変換 |
| **処理ステップN** | 各段階内部の処理順序 | 例: `[ステップ1: HDF5ロード]` |
| **実装フェーズN** | 開発計画の段階 | 基盤構築→最適化→運用監視 |

### 仕様書の構造

各仕様書は以下の構造で統一されています：

```markdown
# [仕様書名]

**処理段階**: 第N段階: [段階名]

## 📋 目的
## 🎯 入力契約
## 🔄 処理フロー
## 📊 出力
## ⚙️ 設定
## 🚨 エラー条件
## 🔗 関連仕様書
```

---

## 📋 開発フェーズ

### 実装フェーズ1: データ収集・特徴量計算（3週間）
- [ ] マルチTFデータ収集機能（M1/M5/M15/H1/H4）
- [ ] タイムスタンプ整合機能
- [ ] 欠損データ補完
- [ ] 特徴量計算（5-7カテゴリ、50-80特徴量）
  - 基本マルチTF（価格変動・TF間差分）
  - マイクロ構造拡張（スプレッド・約定関連）
  - ボラティリティ・レジーム
  - 簡潔勢い指標
  - セッション・時間
- [ ] HDF5 データセット作成

### Phase 2: 前処理・モデル実装（3週間）
- [ ] データ正規化・シーケンス化
- [ ] マルチTF LSTM モデル
- [ ] マルチタスク学習（方向 + 価格幅 + トレンド強度）
- [ ] 学習ループ実装
- [ ] 検証・評価機能

### Phase 3: パターン認識拡張（4週間）
- [ ] スケール不変パターン検出
- [ ] Dynamic Time Warping 統合
- [ ] パターンベースの特徴量追加

### Phase 4: 最適化・ONNX変換（2週間）
- [ ] ハイパーパラメータチューニング
- [ ] ONNX 変換・量子化
- [ ] 推論速度最適化（FP16/INT8）
- [ ] レイテンシ検証（p95 < 10ms目標）

---

## 🎯 重要設計方針

### 1. デュアルモード戦略
- **基本モード**: 1時間以内のエントリー・イグジット（M1/M5/M15）
  - 固定TP/SL: ATR × 0.8 / ATR × 0.5
  - 目標: 0.5-2.0pips の短期利益
- **拡張モード**: トレンド乗り時の延長戦略（H1/H4参照）
  - 条件: trend_strength > 0.7
  - トレール: +0.8pips で発動、0.3pips で追従
  - H1 サポート/レジスタンスでトレール調整

### 2. 時刻管理方針
#### 内部保持形式
- **全データ**: UTC統一で保存
- **HDF5内time列**: UTC UNIXタイムスタンプ(秒)
- **理由**: タイムゾーン変換の複雑性を排除、国際標準との整合性

#### ログ・レポート表示形式
- **ログ出力**: 日本時間(JST, UTC+9)で表示
- **レポート**: 日本時間(JST, UTC+9)で表示
- **フォーマット**: `YYYY-MM-DD HH:MM:SS JST`
- **理由**: 運用者の可読性向上、日本市場との対応関係明確化

#### ブローカータイム変換について
**重要**: MT5ブローカータイム（UTC+3等）からUTC変換の正当性
- MT5が返すタイムスタンプは**実際の市場イベント発生時刻**を表す
- ブローカーのタイムゾーン表示（UTC+3等）は単なる「表示形式」
- UTCに変換しても実際の市場時刻は正しく保持される
- セッション判定（東京/欧州/NY）は変換後のUTCで正しく機能する

例: ブローカー時刻 `10:00 UTC+3` → UTC変換 `07:00 UTC`
- この時刻は実際の世界標準時で7:00（日本時間16:00）
- 東京市場（JST 9:00-15:00 = UTC 0:00-6:00）: 閉場後 ✓
- 欧州市場（UTC 7:00-15:00）: 営業中 ✓

#### タイムスタンプ整合性
- M1, M5, M15, H1, H4 の時刻を正確に揃える
- 欠損時刻の補完方法を明確化

詳細: [docs/utils/TIMEZONE_UTILS_SPEC.md](./docs/utils/TIMEZONE_UTILS_SPEC.md)

### 3. スケール不変性

#### 不変な特徴量（通貨ペア・市場環境に依存しない）
- **相対値**: 価格変化率、リターン率
- **正規化指標**: ATR正規化後の値、RSI、MACD等
- **比率**: spread/ATR、ボリューム比率
- **パターン**: ダブルトップ等の形状（時間スケールに依存しない）

#### 非不変な特徴量（通貨ペア固有のスケールに依存）
- **pips絶対値**: 予測価格幅（USDJPY: 0.01円 = 1pip）
- **TP/SL閾値**: pips単位の固定値（通貨ペアごとに調整必要）

#### Phase 0での扱い
- **対象通貨**: USDJPY単一（スケール固定）
- **pips依存**: 許容（マルチシンボル展開時に再検討）
- **特徴量**: 相対値中心だが、pips予測ヘッドは通貨ペア固有

### 4. マルチタスク学習（デュアルモード）
- 方向と価格幅（短期・延長）は相互に関連
- トレンド強度でモード切替判定
- 共有特徴抽出部で情報を集約
- 個別ヘッドで専門的な予測（scalp / swing / trend）

### 5. エラーハンドリング戦略

各処理段階で統一的なエラーハンドリングを実施：

**基本方針**:
- **Critical（致命的）**: 処理を即座に停止し、エラーログ出力
- **Warning（警告）**: 警告ログを出力して処理続行
- **Recovery（回復可能）**: 自動リトライまたはフォールバック処理

**段階別エラー処理**:

| 処理段階 | エラー種別 | 対応 |
|---------|-----------|------|
| 第1段階: データ収集 | MT5接続失敗 | 3回リトライ後、Critical終了 |
| | データ欠損率 > 30% | Warning（補完処理継続） |
| | タイムスタンプ不整合 | Critical終了（整合性必須） |
| 第2段階: 特徴量計算 | NaN比率 > 5% | Critical終了（計算ロジック確認） |
| | 特徴量数 < 30列 | Warning（カテゴリ有効化確認） |
| | 計算時間 > 300秒 | Warning（最適化検討） |
| 第3段階: 前処理 | メモリ不足 (OOM) | Critical終了（バッチサイズ削減検討） |
| | 正規化失敗 | Critical終了（データ品質確認） |
| 第4段階: 学習 | GPU OOM | 自動的にバッチサイズ削減してリトライ |
| | 勾配爆発 (grad > 1e6) | Warning + 勾配クリッピング適用 |
| | Loss発散 (loss > 1e3) | Critical終了（学習率調整必要） |
| 第5段階: 検証 | 精度異常 (< 0.5) | Warning（モデル性能確認） |
| | バックテスト失敗 | Critical終了（データ整合性確認） |
| 第6段階: ONNX変換 | 変換失敗 | Critical終了（モデル互換性確認） |
| | 精度劣化 > 1% | Warning（量子化パラメータ調整） |

**ログ出力ルール**:
- Critical: `ERROR`レベル + スタックトレース + 終了コード1
- Warning: `WARNING`レベル + 継続メッセージ
- Recovery: `INFO`レベル + リトライ情報

詳細は各段階の仕様書「エラー条件」セクションを参照。

### 6. ログ粒度ポリシー（項目37対応）

段階的ログ出力で分析効率とI/O負荷を最適化：

**ログモード定義**:

| モード | 出力頻度 | 対象内容 | ファイルサイズ目標 |
|--------|---------|---------|------------------|
| **Fast (Core)** | 1秒毎 | コア指標のみ（loss, accuracy, latency） | 10-20 MB/日 |
| **Deep (Extended)** | 60秒毎 | 詳細指標（勾配ノルム、特徴量統計、メモリ使用量） | 50-100 MB/日 |
| **Anomaly (Event-driven)** | イベント発生時 | 異常検出時の詳細ダンプ（スタックトレース、データサンプル） | 可変（通常 <10 MB/日） |

**実装ガイドライン**:
- デフォルトは Fast モード（本番運用時）
- デバッグ時のみ Deep モード有効化
- Anomaly は常時有効（閾値超過時自動出力）
- ログローテーション: 7日間保持、日次圧縮

**KPI**:
- ログサイズ/日: 目標 ±10% 内
- 分析遅延: ログ検索時間 < 5秒（1日分）

---

## 📖 関連ドキュメント

- **開発ガイド**: [AGENTS.md](./AGENTS.md)
- **AI支援指示**: [.github/copilot-instructions.md](./.github/copilot-instructions.md)
- **ツール戦略**: [tools/TOOLS.md](./tools/TOOLS.md)
- **6段階ワークフロー仕様書**:
  - **第1段階: データ収集** - [docs/DATA_COLLECTOR_SPEC.md](./docs/DATA_COLLECTOR_SPEC.md)
    - [マイクロ構造](./docs/data_collector/MICROSTRUCTURE_SPEC.md)
    - [タイムスタンプ整合](./docs/data_collector/TIMESTAMP_ALIGNMENT_SPEC.md)
    - [ストレージポリシー](./docs/data_collector/STORAGE_POLICY_SPEC.md)
  - **第2段階: 特徴量計算** - [docs/FEATURE_CALCULATOR_SPEC.md](./docs/FEATURE_CALCULATOR_SPEC.md)
    - [基本マルチTF特徴量](./docs/feature_calculator/BASIC_MULTI_TF_SPEC.md)
    - [マイクロ構造拡張](./docs/feature_calculator/MICROSTRUCTURE_SPEC.md)
    - [ボラティリティ・レジーム](./docs/feature_calculator/VOLATILITY_REGIME_SPEC.md)
    - [簡潔勢い指標](./docs/feature_calculator/MOMENTUM_SPEC.md)
    - [セッション・時間](./docs/feature_calculator/SESSION_TIME_SPEC.md)
  - **第3段階: 前処理** - [docs/PREPROCESSOR_SPEC.md](./docs/PREPROCESSOR_SPEC.md)
  - **第4段階: 学習** - [docs/TRAINER_SPEC.md](./docs/TRAINER_SPEC.md)
    - [マルチTF融合](./docs/trainer/MULTI_TF_FUSION_SPEC.md)
    - [スカルプ拡張](./docs/trainer/MODEL_ARCHITECTURE_SCALP_EXTENSION_SPEC.md)
    - [GPU最適化](./docs/trainer/GPU_OPTIMIZATION_SPEC.md)
  - **第5段階: 検証・評価** - [docs/VALIDATOR_SPEC.md](./docs/VALIDATOR_SPEC.md)
    - [バックテスト評価](./docs/validator/BACKTEST_EVALUATION_SPEC.md)
    - [ドリフト較正監視](./docs/validator/DRIFT_CALIBRATION_MONITORING_SPEC.md)
    - [動的Exit戦略](./docs/validator/DYNAMIC_EXIT_SPEC.md)
    - [実行レイテンシ](./docs/validator/EXECUTION_LATENCY_SPEC.md)
    - [Future Leak防止](./docs/validator/FUTURE_LEAK_PREVENTION_SPEC.md)
  - **第6段階: ONNX変換** - [docs/ONNX_CONVERTER_SPEC.md](./docs/ONNX_CONVERTER_SPEC.md)
  - **共通モジュール仕様**:
    - [LSTMモデルアーキテクチャ](./docs/utils/MODEL_SPEC.md)
    - [時刻管理ユーティリティ](./docs/utils/TIMEZONE_UTILS_SPEC.md)
    - [設定管理](./docs/utils/CONFIG_MANAGER_SPEC.md)
    - [トレースID管理](./docs/utils/TRACE_ID_SPEC.md)

詳細な手順・閾値・擬似コードは各フェーズ仕様書内「詳細仕様書」セクションを参照してください。

---

## 📘 用語集（Glossary）

プロジェクト全体で頻出する専門用語の簡潔な定義。詳細アルゴリズムや数式は各フェーズ仕様書の該当節を参照してください。

| カテゴリ | 用語 | 定義（概要） |
|---------|------|---------------|
| **基本概念** | タイムフレーム (TF) | チャートの時間単位。本プロジェクトでは**M1, M5, M15, H1, H4の5種類を常時使用**。M1=1分足、M5=5分足、M15=15分足、H1=1時間足、H4=4時間足。 |
| | デュアルモード戦略 | 基本モード（M1/M5/M15重点、70-80%）と拡張モード（H1/H4活用、20-30%）を使い分ける戦略。trend_strength > 0.7で拡張モードに切替。 |
| **アーキテクチャ** | Multi-TF Fusion | 複数タイムフレーム（M1/M5/M15/H1/H4）の情報をLSTM+Attentionで統合する機構。詳細: MULTI_TF_FUSION_SPEC |
| | Cross-TF Attention | TF間の関係を学習するAttention層。例: M1とH1の相関を自動検出。 |
| | Self-Attention Pooling | 各TF内で重要な時刻を動的に抽出するメカニズム。ダブルトップの山を検出等。 |
| **出力ヘッド** | 価格回帰 (Price Regression) | 将来の価格変化幅（pips）を連続値で予測する回帰タスク。方向（UP/DOWN/NEUTRAL）と変動幅（Magnitude）の2段階で構成。 |
| | Magnitude_Scalp | スキャルピング用の短期価格幅予測（0.5-2.0 pips、1時間以内）。 |
| | Magnitude_Swing | スイング用の延長価格幅予測（2.0-5.0 pips、トレール時）。 |
| | Trend_Strength | トレンド強度（0-1）。0.7以上でスイングモードに切替。 |
| **データ処理** | pips | 為替レートの最小変動単位。**USDJPY**: 0.01円 = 1 pip（円→pips: ×100）、**EURUSD**: 0.0001 = 1 pip（ドル→pips: ×10000）。Phase 0ではUSDJPY固定。 |
| | HDF5 | 階層型データフォーマット。大規模数値データの効率的保存・読込に使用。バーデータ + Tickデータ（Ask/Bid時系列）を保存。 |
| | ONNX | Open Neural Network Exchange。PyTorchモデルを推論最適化形式に変換。 |
| | Tickデータ | Ask/Bid価格の時系列データ。マイクロ構造特徴量計算に使用。7年間で約9-10 GB。 |
| **品質保証** | スケール不変性 | 相対値・変化率を使用し、通貨ペア・市場環境に依存しない特徴量設計。**完全不変**: 価格変化率、RSI等。**部分不変**: pips予測ヘッドは通貨ペア固有（Phase 0はUSDJPY固定で許容）。 |
| | direction_flip_rate | 窓内で方向転換（上昇→下降等）が発生した割合。ノイズ過多検知と転換点補助特徴。詳細: MICROSTRUCTURE_SPEC |
| | 未来リーク検査 (Future Leak Prevention) | 特徴量計算がターゲット未来情報を暗黙的に含んでいないかをシフト/マスクで検証。**用語統一**: 「未来リーク」を使用（「リーク」「leak」は略さない）。詳細: FUTURE_LEAK_PREVENTION_SPEC |
| | ドリフト (Drift) | 入力分布やモデル出力分布が過去基準から統計的に乖離する現象。PSIや分位差で検出。詳細: DRIFT_CALIBRATION_MONITORING_SPEC |
| | 校正 (Calibration) | 予測確率と実際的中率の整合度。デシル単位の誤差やECEを測定。詳細: DRIFT_CALIBRATION_MONITORING_SPEC |
| | PSI | Population Stability Index。分布変化度合いの指標。閾値越えで再学習トリガ検討。 |
| **パフォーマンス** | Fast Path | 推論パイプライン中で最小処理（前処理済みテンソル→モデル→出力）の遅延計測対象部分。詳細: EXECUTION_LATENCY_SPEC |
| | Warmup除外 | 初回数バッチ（JIT / キャッシュ生成）のレイテンシ統計からの除外方針。 |
| | レイテンシ計測ポイント | 推論パイプラインの各区間（input_bind, diff_update, forward, postprocess, publish）。 |
| **トレード戦略** | 期待値 (Expectancy) | 1トレードあたり平均損益見込み。勝率・平均利益・平均損失から算出しポジションサイズ決定に利用。詳細: VALIDATOR_SPEC |
| | デュアルモード戦略 | スキャルプ基本モード（70-80%）とスイング拡張モード（20-30%）を動的切替。 |
| | 動的Exit戦略 | 市場環境・予測信頼度・時間帯に応じてTP/SLを調整。固定倍率（ATR×2.0等）を廃止。詳細: DYNAMIC_EXIT_SPEC |
| **運用** | ローリング再学習 | 時系列スライディングウィンドウで定期的にモデルを再学習し新鮮度を維持する運用手法。（Phase 3以降実装予定） |
| | シャドーモデル | 新モデルを本番に昇格させる前に同一入力で並行評価する検証用モデル。（Phase 3以降実装予定） |
| | バージョニング | モデル成果物の命名・昇格/ロールバック条件管理。主要/副次変更の区別。（Phase 3以降実装予定） |
| **最適化** | 閾値フロンティア | 複数評価軸（期待値・安定性・件数など）上で非劣解を形成する閾値セット集合。 |
| | 閾値最適化 | 目的関数と探索（グリッド/早期剪定）で最適閾値を選択する過程。 |
| | dominance pruning | 閾値探索で全指標が他候補に劣る点を除去する手法。 |

---

### 📝 表記統一ルール

#### 単位記法
- **pips**: スペース有り（例: `0.3 pips`、`1.5 pips`）
- **ms**: スペース無し（例: `10ms`、`850ms`）
- **%**: スペース無し（例: `70%`、`0.5%`）

#### 用語統一
- **未来リーク**: 「リーク」「leak」は略さない。英語表記は「Future Leak」
- **pips関連**:
  - **pips絶対値**: 通貨ペア固有の値（例: `0.5 pips`）
  - **pips変換**: 価格→pips変換処理（USDJPY: ×100）
  - **pipsスケール**: pips単位でのスケーリング

#### 階層関係
- **スケール不変性**: 最上位概念
  - **相対値正規化**: 価格変化率、比率
  - **レンジ正規化**: RobustScaler、MinMaxScaler

脚注参照: 詳細式・疑似コードは `docs/` 配下の各仕様書を確認。

---

## 📜 ライセンス

MIT License - 詳細は [LICENSE](./LICENSE) を参照

---

## 🤝 コントリビューション

コントリビューションは歓迎します！詳細は [CONTRIBUTING.md](./CONTRIBUTING.md) を参照してください。

---

## 📞 コンタクト

プロジェクトに関する質問・提案は Issue で受け付けています。

---

**注意**: このプロジェクトは開発中です。本番環境での使用は推奨されません。
