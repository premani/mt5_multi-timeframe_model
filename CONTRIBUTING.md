# 開発貢献ガイド

本プロジェクトへの貢献を検討いただきありがとうございます。このガイドに従って開発を進めてください。

## 📋 目次

- [開発環境セットアップ](#開発環境セットアップ)
- [開発フロー](#開発フロー)
- [コミットメッセージ規約](#コミットメッセージ規約)
- [Issue作成ルール](#issue作成ルール)
- [Pull Request作成ルール](#pull-request作成ルール)
- [コードレビュー](#コードレビュー)
- [テスト](#テスト)

---

## 開発環境セットアップ

### 前提条件
- Docker / Docker Compose
- Git
- 推奨: VS Code + GitHub Copilot

### 初期セットアップ
```bash
# リポジトリのクローン
git clone https://github.com/premani/mt5_lstm-model.git
cd mt5_lstm-model

# 設定ファイルのコピー
cp config/data_mt5_collect_config.template.yaml config/data_mt5_collect_config.yaml
cp config/features_calculate_config.template.yaml config/features_calculate_config.yaml
cp config/features_select_config.template.yaml config/features_select_config.yaml
cp config/prepare_sequences_config.template.yaml config/prepare_sequences_config.yaml
cp config/train_config.template.yaml config/train_config.yaml
cp config/train_validate_config.template.yaml config/train_validate_config.yaml

# 設定ファイルを環境に合わせて編集
# （特にMT5接続情報など）

# Dockerイメージのビルド
docker build -t fx-lstm-pytorch .
```

詳細は [`README.md`](README.md) を参照してください。

---

## 開発フロー

### 基本的な流れ
1. **Issue作成**: 実装する機能やバグ修正をIssueで明確化
2. **ブランチ作成**: `feature/`, `fix/`, `docs/` などのプレフィックス
3. **実装**: 小さくコミット、こまめにpush
4. **テスト**: 動作確認・自動テスト実行
5. **PR作成**: レビュー依頼
6. **マージ**: レビュー承認後にマージ

### ブランチ戦略

#### ブランチの種類

| ブランチ | 用途 | 命名規則 | 作成元 | マージ先 |
|---------|------|----------|--------|---------|
| **main** | 本番用コード | `main` | - | - |
| **feature** | 新機能開発 | `feature/<issue番号>-<説明>` | main | main |
| **fix** | バグ修正 | `fix/<issue番号>-<説明>` | main | main |
| **docs** | ドキュメント更新 | `docs/<説明>` | main | main |
| **refactor** | リファクタリング | `refactor/<説明>` | main | main |
| **test** | テスト追加 | `test/<説明>` | main | main |
| **hotfix** | 緊急修正 | `hotfix/<issue番号>-<説明>` | main | main |

#### ブランチ命名規則

**必須ルール**:
- 全て小文字
- 単語の区切りはハイフン `-`
- Issue番号は可能な限り含める
- 英語で簡潔に（日本語禁止）

**✅ 良い例**:
```bash
feature/123-add-momentum-indicator    # 機能追加
fix/456-nan-handling                   # バグ修正
fix/457-preprocessor-memory-leak       # 具体的な問題を記載
docs/update-contributing-guide         # ドキュメント
refactor/feature-calculator-structure  # リファクタリング
test/add-preprocessor-unit-tests       # テスト追加
hotfix/789-critical-data-corruption    # 緊急修正
```

**❌ 悪い例**:
```bash
feature/new-feature              # 何の機能か不明
fix/bug                          # 何のバグか不明
my-branch                        # プレフィックスなし
feature/NaN修正                  # 日本語使用
feature/Add_Momentum_Indicator   # アンダースコア使用
```

#### ブランチ作成手順

**1. mainブランチを最新化**
```bash
git checkout main
git pull origin main
```

**2. Issueから作業ブランチを作成**
```bash
# Issue #123: RSI/MACD指標追加 の場合
git checkout -b feature/123-add-rsi-macd

# Issue #456: 前処理のNaN処理修正 の場合
git checkout -b fix/456-preprocessor-nan-handling
```

**3. 作業開始前の確認**
```bash
# 現在のブランチ確認
git branch

# リモートにpush（トラッキング設定）
git push -u origin feature/123-add-rsi-macd
```

#### ブランチ運用ルール

##### ✅ すべきこと

1. **作業開始前に必ずIssueを作成**
   - Issue番号をブランチ名に含める
   - 作業内容を明確化

2. **こまめにコミット・push**
   ```bash
   # 論理的な単位でコミット
   git add src/feature_calculator.py
   git commit -m "RSI計算ロジック追加"
   git push

   # さらに実装
   git add tests/test_feature_calculator.py
   git commit -m "RSI計算のテスト追加"
   git push
   ```

3. **定期的にmainの変更を取り込む**
   ```bash
   # mainの最新を取得
   git fetch origin main

   # マージまたはリベース
   git merge origin/main
   # または
   git rebase origin/main
   ```

4. **PR作成前の確認**
   ```bash
   # mainとの差分確認
   git diff main

   # コミット履歴確認
   git log main..HEAD --oneline

   # テスト実行
   bash ./docker_run.sh python3 -m pytest tests/
   ```

##### ❌ してはいけないこと

1. **mainブランチで直接作業**
   ```bash
   # NG: mainで直接編集
   git checkout main
   vim src/preprocessor.py
   git commit -m "修正"

   # OK: 作業ブランチで編集
   git checkout -b fix/789-preprocessor-issue
   vim src/preprocessor.py
   git commit -m "前処理のNaN除外ロジック修正"
   ```

2. **複数の独立した機能を1ブランチに**
   ```bash
   # NG: 1ブランチで複数機能
   git checkout -b feature/multiple-features
   # RSI実装
   # MACD実装
   # ドキュメント更新
   # バグ修正

   # OK: 機能ごとにブランチ分離
   git checkout -b feature/123-add-rsi
   git checkout -b feature/124-add-macd
   git checkout -b docs/update-spec
   git checkout -b fix/125-nan-handling
   ```

3. **長期間mainとsyncしない**
   ```bash
   # NG: 1週間以上mainと同期なし
   # → コンフリクト大量発生

   # OK: 毎日または2-3日に1回sync
   git fetch origin main
   git merge origin/main
   ```

4. **テストなしでpush**
   ```bash
   # NG: テストせずpush
   git push

   # OK: テスト実行後push
   bash ./docker_run.sh python3 -m pytest tests/
   git push
   ```

#### ブランチの削除

**マージ後にブランチを削除**（必須）:

```bash
# PR承認・マージ後、ローカルブランチ削除
git checkout main
git pull origin main
git branch -d feature/123-add-rsi-macd

# リモートブランチも削除（GitHub UIで自動削除設定推奨）
git push origin --delete feature/123-add-rsi-macd
```

**削除前の確認**:
```bash
# マージ済みブランチ一覧
git branch --merged main

# 未マージブランチ一覧
git branch --no-merged main
```

#### コンフリクト解決

**コンフリクト発生時の対応**:

```bash
# 1. mainの最新を取得
git fetch origin main

# 2. マージしてコンフリクト確認
git merge origin/main
# または
git rebase origin/main

# 3. コンフリクトファイル確認
git status

# 4. コンフリクト解決
vim <コンフリクトファイル>
# <<<<<<< HEAD
# 自分の変更
# =======
# mainの変更
# >>>>>>> origin/main
# を手動で編集

# 5. 解決後にadd
git add <解決したファイル>

# 6. マージ完了
git commit  # マージの場合
git rebase --continue  # リベースの場合

# 7. push
git push
```

**コンフリクト予防**:
- 小さい単位で頻繁にコミット
- 定期的にmainをマージ
- 同じファイルの同じ箇所を複数人で編集しない

#### ブランチ保護ルール

**main**ブランチの保護設定（推奨）:
- ✅ 直接pushを禁止
- ✅ PRレビュー必須
- ✅ ステータスチェック必須（テスト通過）
- ✅ マージ前に最新化必須
- ✅ 管理者も含めて適用

#### 実践例

**ケース1: 新機能追加（RSI指標）**
```bash
# 1. Issue作成: #130
# 2. ブランチ作成
git checkout main
git pull origin main
git checkout -b feature/130-add-rsi-indicator

# 3. 実装
vim src/feature_calculator.py
git add src/feature_calculator.py
git commit -m "RSI計算ロジック追加

- src/feature_calculator.py: RSI計算関数実装
- 期間14のRSIを計算
- ゼロ除算防止処理追加"

git push -u origin feature/130-add-rsi-indicator

# 4. テスト追加
vim tests/test_feature_calculator.py
git add tests/test_feature_calculator.py
git commit -m "RSI計算のテスト追加

- tests/test_feature_calculator.py: RSIテスト実装
- 正常系・異常系のテストケース追加"

git push

# 5. ドキュメント更新
vim docs/FEATURE_CALCULATOR_SPEC.md
git add docs/FEATURE_CALCULATOR_SPEC.md
git commit -m "FEATURE_CALCULATOR_SPECにRSI仕様追加

- RSI計算の仕様を記載
- パラメータと計算式を明記"

git push

# 6. PR作成
# GitHub上で Pull Request 作成
# タイトル: [Feature] RSI指標追加 (#130)

# 7. レビュー対応後マージ

# 8. ブランチ削除
git checkout main
git pull origin main
git branch -d feature/130-add-rsi-indicator
```

**ケース2: バグ修正（NaN処理）**
```bash
# 1. Issue作成: #145
# 2. ブランチ作成
git checkout main
git pull origin main
git checkout -b fix/145-preprocessor-nan-handling

# 3. バグ修正
vim src/preprocessor.py
git add src/preprocessor.py
git commit -m "前処理のNaN除外ロジック修正

- src/preprocessor.py: NaN判定を主要列のみに限定
- 補助列の欠損は保持してマスク処理
- データ保持率が70%→95%に改善"

git push -u origin fix/145-preprocessor-nan-handling

# 4. テスト実行・PR作成・マージ・削除
# （ケース1と同様）
```

**ケース3: 緊急修正（データ破損）**
```bash
# 1. 緊急Issue作成: #199
# 2. hotfixブランチ作成
git checkout main
git pull origin main
git checkout -b hotfix/199-data-corruption

# 3. 迅速に修正
vim src/data_collector.py
git add src/data_collector.py
git commit -m "データ収集時の破損バグ修正

- タイムスタンプ重複チェック追加
- HDF5書き込み前の検証強化"

git push -u origin hotfix/199-data-corruption

# 4. 緊急PR・即座にマージ
# （テストは最小限、レビューは事後でも可）

# 5. 即座にデプロイ
```

---

## コミットメッセージ規約

### 必須ルール

| 項目 | ルール |
|------|--------|
| **言語** | 日本語のみ |
| **AI署名禁止** | "Claude"、"Copilot" 等の文言は記載しない |
| **数値禁止** | TASK番号、行数、具体的数値は記載しない |
| **誇張語禁止** | "完全"、"絶対"、"完璧" 等は使わない |
| **処理内容明記** | 何のファイル・機能を変更したか具体的に記載 |

### フォーマット
```
<タイトル>（50文字以内）

<本文>
- 変更内容の詳細（どのファイル・機能を変更したか）
- 変更理由（なぜこの変更が必要か）
- 影響範囲（他のファイル・機能への影響）
```

### タイトルの書き方

#### ✅ 良いタイトルの条件
1. **具体的な機能・ファイル名を含む**
2. **動詞で始まる**（追加/修正/削除/更新/リファクタリング）
3. **50文字以内**
4. **1コミット1目的**

#### タイトルのパターン

| パターン | 例 | 説明 |
|---------|---|------|
| **機能追加** | `RSI計算機能追加` | 新機能の実装 |
| **バグ修正** | `前処理のNaN除外ロジック修正` | バグの修正 |
| **リファクタリング** | `特徴量計算器のコード整理` | 動作を変えずに改善 |
| **ドキュメント** | `PREPROCESSOR_SPEC.mdのサブ仕様分離` | 仕様書・README更新 |
| **設定変更** | `Docker設定でGPU対応追加` | 設定ファイル変更 |
| **テスト追加** | `データ収集器の単体テスト追加` | テストコード追加 |
| **依存関係** | `requirements.txtにpandas追加` | ライブラリ追加 |

### 本文の書き方

#### ✅ 具体的に書くべき情報

1. **変更したファイル・モジュール**
   ```
   - src/preprocessor.py: NaN除外ロジック追加
   - src/utils/quality_stats.py: 統計計算関数追加
   - tests/test_preprocessor.py: 単体テスト追加
   ```

2. **変更理由**
   ```
   - 欠損値が残存して学習時にエラーが発生していた
   - 定数列が混入してモデルの収束を妨げていた
   ```

3. **技術的な詳細**
   ```
   - RobustScalerのパラメータをquantile_range=(25, 75)に変更
   - NaN除外閾値を1%から5%に緩和
   - マスク処理を追加して欠損行の学習重みを0に設定
   ```

4. **影響範囲**
   ```
   - 前処理後のデータshapeは変更なし
   - HDF5スキーマは互換性維持
   - 学習フェーズへの影響なし
   ```

### ❌ NG例

```
# 何を変更したか分からない
修正

# 処理内容が不明確
バグ修正

# AI署名・数値・誇張語
Claudeによる修正: 120行変更で完全に解決

# 複数の独立した変更を1コミットに
特徴量計算とテストと仕様書更新
```

### ✅ OK例

#### 例1: 機能追加
```
RSI/MACD計算機能追加

- src/feature_calculator.py: RSI/MACDの計算ロジック実装
- config/features_calculate_config.yaml: パラメータ設定追加
- tests/test_feature_calculator.py: 単体テスト追加

変更理由:
- モメンタム系指標が不足していた
- トレンド判定精度を向上させるため

影響範囲:
- 特徴量数が50→58列に増加
- 計算時間は約10%増加
- 前処理以降への影響なし
```

#### 例2: バグ修正
```
前処理のNaN除外ロジック修正

- src/preprocessor.py: NaN判定を主要列のみに限定
- src/preprocessor.py: 補助列の欠損は保持してマスク処理
- docs/preprocessor/INPUT_QUALITY_SPEC.md: 仕様を更新

変更理由:
- 補助列の欠損で行全体を除外していた
- 過剰なデータ損失（約30%）が発生していた

技術的詳細:
- primary_columns（OHLCV+主要指標）のみNaN判定
- auxiliary_columns（派生特徴）の欠損は学習時マスク
- loss_weight配列で欠損行の重みを0に設定

影響範囲:
- データ保持率が70%→95%に改善
- 学習データ数が約1.4倍に増加
- モデル精度への影響は要検証
```

#### 例3: リファクタリング
```
特徴量計算器のコード整理

- src/feature_calculator.py: クラス構造を整理
- src/feature_calculator.py: 重複コードを共通関数化
- src/utils/technical_indicators.py: 指標計算を分離

変更理由:
- 1ファイル800行で可読性が低下していた
- テストが困難な構造だった

技術的詳細:
- TechnicalIndicatorクラスを分離
- RSI/MACD/ATR計算をutils/に移動
- インターフェースは変更なし

影響範囲:
- 動作変更なし（出力データは同一）
- テストカバレッジが向上
- 後続フェーズへの影響なし
```

#### 例4: ドキュメント更新
```
PREPROCESSOR_SPEC.mdのサブ仕様分離

- docs/PREPROCESSOR_SPEC.md: 1701行→688行に削減
- docs/preprocessor/INPUT_QUALITY_SPEC.md: 新規作成
- docs/preprocessor/DATA_INTEGRITY_SPEC.md: 新規作成
- docs/preprocessor/NORMALIZATION_SPEC.md: 新規作成
- README.md: preprocessor/サブ仕様を追加

変更理由:
- 1ファイル1700行で可読性が低かった
- 他の段階（data_collector/feature_calculator）との一貫性確保

影響範囲:
- 実装コードへの影響なし
- 仕様書の構造のみ変更
```

#### 例5: 設定変更
```
Docker設定でGPU対応追加

- Dockerfile: nvidia/cuda:11.8-base イメージに変更
- docker-compose.yml: GPUリソース設定追加
- requirements.txt: torch==2.0.0+cu118 に変更

変更理由:
- 学習時間を短縮するためGPU利用を有効化
- CPU学習で1エポック3時間→GPU学習で15分に短縮

技術的詳細:
- CUDA 11.8対応
- torch.cuda.is_available()でGPU自動検出
- GPU未搭載環境でもCPUフォールバック動作

影響範囲:
- 学習速度が大幅改善
- GPU必須ではない（CPU動作も維持）
```

### Phase表記ルール

段階的改修時は**何の処理のどの段階か**を明示:

❌ **NG**:
```
phase2 実装
第2段階実装
```

✅ **OK**:
```
NaN除外ロジック実装（phase2: 本格実装）

- phase1で基本実装した機能を拡張
- 補助列の欠損判定ロジック追加
- マスク処理による重み調整実装
```

### コミット粒度のガイドライン

#### ✅ 適切な粒度

1つのコミットには**1つの論理的な変更のみ**を含める

**OK例**:
```
# コミット1: 機能実装
RSI計算機能追加

# コミット2: テスト追加
RSI計算のテスト追加

# コミット3: ドキュメント更新
FEATURE_CALCULATOR_SPEC.mdにRSI仕様追加
```

#### ❌ 不適切な粒度

```
# NG: 複数の独立した変更を1コミットに
RSI追加とNaN修正とドキュメント更新

# NG: 1変更を複数コミットに分割
RSI計算の一部追加
RSI計算の残り追加
```

### コミット前チェックリスト

- [ ] タイトルが50文字以内
- [ ] 何のファイル・機能を変更したか明記
- [ ] 変更理由を記載
- [ ] 技術的詳細を記載（アルゴリズム・パラメータ変更等）
- [ ] 影響範囲を記載
- [ ] AI署名・数値・誇張語を含まない
- [ ] 1コミット1目的
- [ ] `_test_*.py` などの一時ファイルを含まない

### Issue連携

コミットメッセージにIssue番号を含めることで、GitHubで自動的に関連付けられます。

#### 参照のみ（Issue番号をリンク）
```bash
git commit -m "データ収集機能実装 #2

- MT5 API連携
- HDF5保存機能"
```

#### 自動クローズ（Issue完了時）
特定のキーワードでIssueを自動クローズ：

```bash
git commit -m "データ整備機能実装 closes #3

- 異常値検出機能
- 欠損値補完機能
- 品質スコア計算"
```

**クローズキーワード**: `close`, `closes`, `closed`, `fix`, `fixes`, `fixed`, `resolve`, `resolves`, `resolved`

#### ⚠️ closes 使用の判断基準

以下を**全て満たす場合のみ** `closes #N` を使用：

1. ✅ 実装完了（追加のデバッグ不要）
2. ✅ テスト実行成功
3. ✅ ドキュメント更新済み（必要な場合）
4. ✅ もう追加コミット不要と確信

**実装中・デバッグ中は `#N` 参照のみ、完了時に `closes #N`**

```bash
# 実装中・デバッグ中
git commit -m "APIエンドポイント修正 #2"
git commit -m "時刻変換ロジック修正 #2"

# 完全完了時のみ
git commit -m "データ収集機能実装完了 closes #2"
```

**迷ったら**：`#N` だけにして、GitHub上で手動クローズを推奨

**クローズキーワード**: `close`, `closes`, `closed`, `fix`, `fixes`, `fixed`, `resolve`, `resolves`, `resolved`

#### 複数Issue対応
```bash
git commit -m "特徴量計算機能実装 closes #4, relates to #5

- 基本価格特徴量
- テクニカル指標"
```

---

## Issue作成ルール

### Issueタイプ
以下のテンプレートを使用してください:

1. **🐛 バグレポート**: `.github/ISSUE_TEMPLATE/bug_report.md`
2. **✨ 機能追加**: `.github/ISSUE_TEMPLATE/feature_request.md`
3. **📝 ドキュメント改善**: `.github/ISSUE_TEMPLATE/documentation.md`

### Issueタイトル
```
[タイプ] 簡潔な説明

例:
[Bug] 前処理でNaN値が残存する
[Feature] ボリンジャーバンド指標追加
[Docs] 学習フェーズ仕様書更新
```

### 必須記載事項
- **現象/要望**: 何が起きているか、何を実現したいか
- **再現手順** (バグの場合): 問題を再現する手順
- **期待動作**: あるべき動作
- **環境情報**: OS、Dockerバージョン等
- **関連情報**: ログ、スクリーンショット等

---

## Issue管理の運用ルール

### 新規Issue vs 既存Issue追記の判断基準

#### ✅ 新規Issue作成が推奨される場合

1. **実装完了後にバグが発見された場合**
   ```
   Issue #6: 特徴量選抜実装 [完了]
      ↓ (完了後に品質問題発見)
   Issue #14: データ品質問題 [新規] ← 新規Issue作成
   ```
   - 元のIssueは「機能実装」として完了済み
   - 後から品質問題が判明 → **新規Issue作成**
   - 理由: 独立したバグ追跡、影響範囲の明確化

2. **影響範囲が広い場合**
   ```
   Issue #6の問題が Issue #7, #8 に波及
   → 新規Issue作成 + 関連Issue相互リンク
   ```

3. **元のIssueが既にクローズされている場合**
   - クローズ後の再オープンは避ける（履歴が複雑化）
   - **新規Issue作成 + 関連Issue明記**

4. **独立した修正タスクが必要な場合**
   - 複数ファイルの修正、設計変更、再テストが必要
   - 元のIssueとは別のマイルストーンで追跡したい

#### ❌ 既存Issue追記が適切な場合

1. **実装中に発見された問題**
   ```
   Issue #6実装中にバグ発見
   → 同じIssue内でコメント + 修正
   ```

2. **仕様の明確化・補足**
   - 「〇〇の挙動を明確にしてほしい」等のコメント追記
   - 実装者への質問

3. **直接的な修正依頼（Issue未クローズ時）**
   - 「この実装に問題があるので修正してほしい」
   - レビュー指摘事項

### 新規Issue作成時のベストプラクティス

#### 関連Issue明記
```markdown
## 関連Issue
- Issue #6: 特徴量選抜（修正対象）
- Issue #7: シーケンス化・分割（再実行必要）
- Issue #8: LSTM学習（現在停止中）
```

#### ラベル活用
- `bug`: バグ修正
- `regression`: 以前動いていた機能の不具合
- `critical`: 緊急対応必要
- `data-quality`: データ品質問題
- `needs-investigation`: 調査必要

#### 優先度明示
```markdown
## 優先度
🔴 **Critical** - Issue #8の進行を完全ブロック
🟡 **High** - 次マイルストーンで対応必須
🟢 **Medium** - 通常対応
⚪ **Low** - 改善提案
```

### Issue間の参照方法

#### コミットメッセージでの参照
```bash
# 参照のみ
git commit -m "NaN除去ロジック改善 #14"

# 自動クローズ
git commit -m "データ品質問題修正 closes #14"
```

#### Issue本文での相互リンク
```markdown
## 関連
- Related to #6 - 元の実装Issue
- Blocks #7 - このIssueが解決しないと進めない
- Blocks #8
- Fixes #6 - このIssueで根本修正
```

#### Issue完了後のフォローアップ
元のIssueに参照コメントを追加（任意だが推奨）：
```markdown
Issue #6 へのコメント:
「NaN除去ロジックを #14 で改善しました。」
```

### 実例: 今回のケース（Issue #14）

#### 状況
- Issue #6（特徴量選抜）実装完了・コミット済み
- Issue #7, #8実装中にデータ品質問題発見
- NaN残存、値域異常により後続フェーズ停止

#### 判断: ✅ 新規Issue作成
**理由:**
1. ✅ 時間的分離（実装完了後に発見）
2. ✅ 影響範囲が広い（複数Issue波及）
3. ✅ 独立した修正タスク
4. ✅ バグトラッキングの明確化

#### Issue #14構成
```markdown
タイトル: データ品質問題: features_selected.h5にNaN残存と値域異常
ラベル: bug, data-quality, critical
優先度: 🔴 Critical

関連Issue:
- Issue #6: 特徴量選抜（修正対象）
- Issue #7: シーケンス化・分割（再実行必要）
- Issue #8: LSTM学習（現在停止中）

修正タスク:
- [ ] features_select.py のNaN除去改善
- [ ] 値域検証強化
- [ ] 再生成フロー実行
```

### 参考: 主要OSSプロジェクトの実例

**PyTorch, TensorFlow等の大規模プロジェクト:**
- 実装完了後のバグ発見 → 新規Issue作成が主流
- 相互リンク: `Closes #N`, `Related to #N`, `Fixes #N`
- ラベル活用: `regression`, `bug`, `needs-investigation`

**GitHub公式推奨:**
1. 新規Issue優先（追跡性、検索性、統計精度）
2. 相互リンクで関係性明示
3. 再オープンは「同じ機能の未完了部分」のみ

### Issue本文(Description) とコメントの使い分け指針

調査や不具合解析が長期化・段階化するケース向けに、Issue の Description とコメントの役割を明確化します。

| 用途 | Description (本文) | コメント (スレッド) |
|------|--------------------|---------------------|
| 初見で現状把握 | ✅ 最新サマリ / 再現手順 / 暫定 or 確定原因 / 次アクション | - |
| 詳細な調査ログ・試行差分 | ❌ 肥大化させない | ✅ 日付付きで積み上げ |
| 大きな節目（原因確定 / 対策実装 / 検証完了） | ✅ 更新日を明記し反映 | ✅ 背景と計測根拠を詳細記録 |
| 小規模進捗 / 一時メモ | ❌ | ✅ |
| 追加質問・レビュー指摘 | ❌ | ✅ |

#### Description 更新トリガー
1. 原因仮説が高確度となった
2. 対策方針（修正戦略）が合意された
3. 修正 PR がマージされた
4. 検証完了 / 再発防止策完了

#### 推奨 Description 構成テンプレート
```markdown
### 現在のステータス (YYYY-MM-DD 更新)
- 状態: investigating / cause-identified / fix-in-progress / validated / closed
- 暫定/確定原因:
- 影響範囲:
- 次アクション:

### 再現手順 (簡潔)
1. ...
2. ...
3. ...

### 過去の主な節目
- 2025-10-09: 原因特定（例: SequenceDataset 二重定義 + 全量キャッシュ）
```

#### 調査結果コメントテンプレ (日付付き)
```markdown
### 🔍 調査ログ (YYYY-MM-DD)
対象: ...
方法: ...
計測:
- RSS 前: XXX MB
- RSS 後: XXX MB (+YYY MB)
考察:
次ステップ: ...
```

#### 運用ポイント
- Description は常に「最新要約」だけ保持し、詳細履歴はコメントで時系列保管
- 大幅編集前に「Description を更新予定」旨をコメントで予告するとレビュー容易
- 調査が拡散したら次アクションは 3～5 個に再圧縮し優先度を整理

> 目的: 初見コントリビュータが 30 秒以内に状況と必要な次アクションを理解できる状態を保つ。

---

## Pull Request作成ルール

### PRタイトル
Issueと同様の形式:
```
[タイプ] 簡潔な説明 (#Issue番号)

例:
[Feature] モメンタム指標計算器追加 (#123)
[Fix] NaN除外ロジック修正 (#456)
[Docs] CONTRIBUTING.md追加
```

### PR説明テンプレート
`.github/pull_request_template.md` に従って記載:

```markdown
## 変更概要
<!-- 何を変更したか簡潔に -->

## 関連Issue
Closes #<Issue番号>

## 変更内容
- [ ] 変更点1
- [ ] 変更点2

## 影響範囲チェック
- [ ] features/targets shape 差分なし
- [ ] HDF5 スキーマ破壊なし
- [ ] スケーラーJSON構造変更なし
- [ ] ログ語彙・アイコン変更なし
- [ ] 例外握りつぶしなし
- [ ] 計算量・メモリ影響 (該当する場合記載)

## テスト
- [ ] 手動テスト実施
- [ ] 自動テスト追加/修正
- [ ] 動作確認環境: Docker / GPU有無

## レビュー依頼事項
<!-- 特に見てほしい箇所 -->
```

### マージ前チェックリスト
- [ ] コミットメッセージが規約に準拠
- [ ] テストが通過
- [ ] ドキュメント更新 (必要な場合)
- [ ] `_test_*.py` などの一時ファイルを削除
- [ ] レビュー承認済み

---

## コードレビュー

### レビュー観点
1. **仕様準拠**: `docs/*_SPEC.md` との整合性
2. **命名規則**: snake_case / PascalCase
3. **エラー処理**: 握りつぶしていないか
4. **ログ出力**: 既存の語彙・アイコン体系に準拠
5. **パフォーマンス**: 不要な計算・メモリ確保がないか
6. **テスト**: 適切なテストが追加されているか

### レビューコメント例
```markdown
# 承認
LGTM! モメンタム指標の実装が明確で、テストも適切です。

# 要修正
```python
# 提案: エラー握りつぶしを避ける
try:
    result = calculate()
except:
    pass  # NG

# 修正案
try:
    result = calculate()
except ValueError as e:
    logger.error(f"計算失敗: {e}")
    raise
```

# 質問
このNaN除外処理は `quality_stats.py` の既存ロジックと重複していませんか?
```

---

## テスト

### テストファイル命名
- **一時テスト**: `_test_*.py` (プロジェクトルート直下)
- **恒久テスト**: `tests/test_*.py`

### 実行方法
```bash
# 全テスト実行
bash ./docker_run.sh python3 -m pytest tests/

# 特定ファイルのみ
bash ./docker_run.sh python3 -m pytest tests/test_preprocessor.py

# 一時テスト (検証後は削除)
bash ./docker_run.sh python3 _test_momentum.py
rm _test_momentum.py  # 完了後削除
```

### テスト作成ガイドライン
- **単体テスト**: 各計算器・モジュール単位
- **統合テスト**: フェーズ全体の動作
- **エッジケース**: NaN、空配列、極端な値

詳細は [`tests/TESTING.md`](tests/TESTING.md) を参照。

---

## コーディング規約

### 命名規則
- **ファイル**: `snake_case.py`
- **クラス**: `PascalCase`
- **変数/関数**: `snake_case`
- **定数**: `UPPER_SNAKE_CASE`

### 言語使用
- **ログ・コメント**: 日本語
- **変数名・関数名**: 英語

### コード設計原則
1. **簡潔性**: トークン制限を意識した設計
2. **既存活用**: `src/utils/` の共通モジュールを積極利用
3. **事実記述**: 誇張語は使わず事実のみ記述
4. **エラー伝播**: 握りつぶさず適切に `raise`

❌ **NG**:
```python
# NaN問題を完全に解決する絶対的な処理
def remove_nan_completely(df):
    try:
        return df.dropna()
    except:
        pass  # サイレント無視
```

✅ **OK**:
```python
# NaN値を除外
def remove_nan(df: pd.DataFrame) -> pd.DataFrame:
    """
    DataFrame から NaN を含む行を除外
    
    Args:
        df: 入力DataFrame
    
    Returns:
        NaN除外後のDataFrame
    
    Raises:
        ValueError: 入力が空の場合
    """
    if df.empty:
        raise ValueError("入力DataFrameが空です")
    
    return df.dropna()
```

---

## 仕様書規約

### ドキュメント階層構造

プロジェクトの仕様書は以下の階層構造で管理されます：

```
docs/
├── <PHASE>_SPEC.md              # メイン仕様書（4つ）
│   └── 内部で詳細仕様書へリンク
└── <phase>/                      # 詳細仕様書ディレクトリ
    └── <DETAIL>_SPEC.md          # 詳細仕様書
```

### リンクルール

| 参照元 | 参照先 | ルール |
|-------|--------|--------|
| **README.md** | メイン仕様書のみ | ✅ 4つのメイン仕様書へのリンクのみ記載 |
| **メイン仕様書** | 詳細仕様書 | ✅ 関連する詳細仕様書へリンク |
| **README.md** | 詳細仕様書 | ❌ 直接リンクしない |

### 具体例

#### ✅ 正しい参照フロー
```
README.md
  ├─→ DATA_COLLECTOR_SPEC.md
  │     ├─→ data_collector/TIMESTAMP_ALIGNMENT_SPEC.md
  │     └─→ data_collector/MICROSTRUCTURE_SPEC.md
  ├─→ PREPROCESSOR_SPEC.md
  ├─→ TRAINER_SPEC.md
  └─→ VALIDATOR_SPEC.md
        ├─→ validator/BACKTEST_EVALUATION_SPEC.md
        └─→ validator/DRIFT_CALIBRATION_MONITORING_SPEC.md
```

#### ❌ 誤った参照フロー
```
README.md ─→ data_collector/TIMESTAMP_ALIGNMENT_SPEC.md  # NG: 詳細仕様への直接リンク
```

### 仕様書フォーマット

#### メイン仕様書の必須セクション
1. ヘッダー情報（バージョン、更新日、責任者）
2. 📋 概要
3. 📂 入出力
4. ⚙️ 処理フロー
5. 📊 品質基準
6. 🔗 関連仕様書（詳細仕様へのリンク）
7. 📌 注意事項
8. 🔮 将来拡張

#### 詳細仕様書の必須セクション
1. ヘッダー情報（バージョン、更新日、責任者）
2. 📋 概要
3. 詳細仕様（処理アルゴリズム等）
4. 🔗 参照（親仕様書へのリンク）
5. 🔮 将来拡張

### 仕様書更新時のルール

1. **メイン仕様書更新時**
   - 該当する詳細仕様書も確認・更新
   - バージョン番号と更新日を更新

2. **詳細仕様書更新時**
   - 親仕様書への影響を確認
   - 必要に応じて親仕様書も更新

3. **新規詳細仕様書追加時**
   - 親仕様書に参照リンクを追加
   - 「🔗 関連仕様書」セクションを更新

### 仕様書命名規則

| 種別 | 命名規則 | 例 |
|------|----------|-----|
| メイン仕様書 | `<PHASE>_SPEC.md` | `DATA_COLLECTOR_SPEC.md` |
| 詳細仕様書 | `<DETAIL>_SPEC.md` | `TIMESTAMP_ALIGNMENT_SPEC.md` |
| ディレクトリ | `<phase>/` (小文字) | `data_collector/`, `validator/` |

---

## AI開発支援

本プロジェクトはAI（GitHub Copilot等）による開発支援を推奨しています。

### AI向けガイド
- **AGENTS.md**: GitHub Copilot向けの開発ガイド
- **.github/copilot-instructions.md**: 詳細な実装指針

AIを使用する場合も、人間が最終的なレビュー・承認を行ってください。

---

## 参考資料

- **プロジェクト概要**: [`README.md`](README.md)
- **各フェーズ仕様**: `docs/*_SPEC.md`
- **AI開発支援**: [`AGENTS.md`](AGENTS.md)
- **テストガイド**: [`tests/TESTING.md`](tests/TESTING.md)

---

## 質問・サポート

- **Issue**: [GitHub Issues](https://github.com/premani/mt5_lstm-model/issues)
- **Discussions**: [GitHub Discussions](https://github.com/premani/mt5_lstm-model/discussions)

貢献をお待ちしています! 🚀
