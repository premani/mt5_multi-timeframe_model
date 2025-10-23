# AGENTS.md - GitHub Copilot 向け開発ガイド

> **対象**: VS Code GitHub Copilot（毎回自動読み込み）  
> **目的**: プロジェクト固有のルール・制約をAIに明示

プロジェクト全体概要は `README.md` を参照

---

## 🚨 最優先ルール

### 1. カレントディレクトリ指定は不要

**常にプロジェクトルート (`/home/mania/github.com/premani/mt5-multi-timeframe-model`) で実行中**

❌ **絶対にNG**:
```bash
cd /home/mania/github.com/premani/mt5-multi-timeframe-model && git add README.md
```

✅ **正しい形式**:
```bash
git add README.md
bash ./docker_run.sh python3 src/training.py
ls -lh models/
```

### 2. エラーは握りつぶさない

❌ **NG**: サイレント無視
```python
try:
    risky_operation()
except:
    pass  # 何も起きなかったことにする → 禁止
```

✅ **OK**: エラー伝播
```python
try:
    risky_operation()
except ValueError as e:
    logger.error(f"処理失敗: {e}")
    raise  # 上位に伝播させる
```

**理由**: フォールバックで隠蔽せず、根本原因を修正する

### 3. 実装前に必ず提案

❌ **NG**: いきなりコード修正  
✅ **OK**: 「〇〇を修正します」→ 承認待ち → 実装

---

## コミットメッセージ規約

### 必須ルール
| 項目 | ルール |
|------|--------|
| 言語 | 日本語のみ |
| AI署名 | "Claude"、"Copilot" 等の文言**禁止** |
| 数値 | TASK番号・行数・具体的数値**禁止** |
| 誇張語 | "完全"、"絶対"、"完璧" 等**禁止** |

### 例

❌ **NG**:
```
完全にNaN問題を解決 (TASK-123)
Claudeによる修正: 120行変更
```

✅ **OK**:
```
NaN除外ロジック修正

- 計算器でのゼロ除算防止
- 定数列の自動検出と除外
```

### Issue連携

コミットメッセージにIssue番号を含めることで自動リンク・クローズが可能：

```bash
# Issue参照のみ（実装中・デバッグ中）
git commit -m "データ収集機能実装 #2"

# Issue自動クローズ（完全完了時のみ）
git commit -m "データ整備機能実装 closes #3

- 異常値検出機能
- 欠損値補完機能"
```

**closes使用条件**: 実装完了 + テスト成功 + 追加コミット不要  
**迷ったら**: `#N` 参照のみにして手動クローズ

**クローズキーワード**: `closes`, `fixes`, `resolves` (+ `#Issue番号`)

**複数Issue同時クローズ時の注意**:
- ❌ **NG**: `closes #37 #168` （#168が認識されない）
- ✅ **OK**: 各Issueを改行で分離
  ```bash
  git commit -m "機能実装

  closes #37
  closes #168

  - 詳細説明..."
  ```

---

## Phase表記ルール

段階的改修時は**内容を明示**すること

❌ **NG**: 
```python
# phase2 実装
# phase3 対応
```

✅ **OK**:
```python
# NaN除外ロジック phase2
# 相関フィルタリング phase3
```

**理由**: 後から追跡可能にするため

---

## ファイル・ディレクトリ構造

### テストファイル
- **命名**: `_test_*.py`（例: `_test_preprocessor.py`）
- **配置**: プロジェクトルート直下
- **削除**: 検証完了後は**必ず削除**（一時ログも同様）

### モジュール配置原則
```
src/
├── preprocessor_data.py          # メインスクリプト
└── preprocessor_data/            # 同名ディレクトリに固有モジュール
    ├── processor.py
    └── validator.py

src/utils/                        # 汎用モジュール
├── hdf5_dataset.py
└── logging_manager.py
```

**ルール**:
- メインスクリプトと同名ディレクトリに固有モジュール配置
- 汎用モジュールは `src/utils/` へ
- 仕様書も実行ファイル名に揃える（`docs/<name>_SPEC.md`）

### 共通モジュール編集時

`src/utils/` 配下を編集したら、対応仕様書を**同時更新**:

| モジュール | 仕様書 |
|-----------|--------|
| `src/utils/hdf5_inspector.py` | `docs/utils/HDF5_INSPECTOR_SPEC.md` |
| `src/utils/alignment_verifier.py` | `docs/utils/ALIGNMENT_VERIFIER_SPEC.md` |

---

## コーディング規約

### 命名規則
- **ファイル**: `snake_case.py`
- **クラス**: `PascalCase`
- **変数/関数**: `snake_case`

### 言語使用
- **ログ・コメント**: 日本語
- **変数名・関数名**: 英語

### コード設計原則
1. **簡潔性**: トークン制限25000を意識（冗長コード禁止）
2. **既存活用**: `src/utils/` の共通モジュールを積極利用
3. **誇張禁止**: "完全解決"等の表現は使わず事実のみ記述

❌ **NG**:
```python
# NaN問題を完全に解決する絶対的な処理
def remove_nan_completely(df):
    ...
```

✅ **OK**:
```python
# NaN値を除外
def remove_nan(df):
    ...
```

---

## 実装時の必須確認事項

コード生成・修正前に以下を確認:

1. ❌ `cd /home/mania/.../` を使っていないか
2. ❌ `except: pass` でエラー握りつぶしていないか
3. ✅ 提案→承認→実装の順で進めているか
4. ✅ コミットメッセージに誇張語・数値が入っていないか
5. ✅ Phase表記に内容説明があるか
6. ✅ テストファイル削除したか
7. ✅ `src/utils/` 編集時に仕様書更新したか

---

## 参考資料

- **プロジェクト概要**: `README.md`
- **AI開発支援詳細**: `.github/copilot-instructions.md`
- **各フェーズ仕様**: `docs/*_SPEC.md`

## エラー処理とフォールバック

### ❌ NG: エラーを隠蔽・回避する
```python
try:
    risky_operation()
except:
    pass  # サイレントに無視 → NG
```

### ✅ OK: エラーは適切に伝播させる
```python
try:
    risky_operation()
except ValueError as e:
    logger.error(f"処理失敗: {e}")
    raise  # エラーを上位に伝播
```

**方針**: 
- エラーを回避するのではなく、根本原因を修正する
- フォールバックで誤魔化さず、エラーはエラーとして出力して停止させる

## 実装フロー

### 必須ステップ
1. **提案**: 実装前に変更内容を簡潔に説明
2. **確認**: ユーザーの合意を得る
3. **実装**: 承認後にコード修正を実行
4. **検証**: 変更内容を表示・確認

❌ **NG**: いきなりコード修正
✅ **OK**: 「〇〇を修正します」→ 承認後 → 実装

## コミットメッセージ規約

### 基本ルール
- **言語**: 日本語のみ
- **AI署名禁止**: "Claude"、"Copilot" 等の文言不要
- **具体的数値禁止**: TASK番号、行数、具体的な数値は記載しない
- **誇張表現禁止**: "完全"、"絶対" 等は使わない

### 例

❌ **NG**:
```
完全にNaN問題を解決 (TASK-123)
Claudeによる修正: 120行変更
```

✅ **OK**:
```
NaN除外ロジック修正

- 計算器でのゼロ除算防止
- 定数列の自動検出と除外
```

## 段階的改修（Phase表記）

### ❌ NG: 曖昧な Phase 表記
```
# phase2 実装
# phase3 対応
```

### ✅ OK: 内容を明示した Phase 表記
```
# NaN除外ロジック phase2
# 相関フィルタリング phase3
```

**理由**: 何の phase2/3 なのか後から追跡できるように

## ファイル・ディレクトリ構造

### テストファイル
- **命名**: `_test_*.py` で開始（例: `_test_preprocessor.py`）
- **配置**: プロジェクトルート直下
- **削除**: 検証完了後は必ず削除（一時ログファイルも同様）

### モジュール配置ルール
```
src/
├── preprocessor_data.py          # メインスクリプト
└── preprocessor_data/            # 同名ディレクトリに固有モジュール
    ├── processor.py
    └── validator.py

src/utils/                        # 汎用モジュール
├── hdf5_dataset.py
└── logging_manager.py
```

**原則**: 
- メインスクリプトと同名ディレクトリに固有モジュール
- 汎用モジュールは `utils/` へ
- 仕様書も実行ファイル名に揃える

### 共通モジュール編集時の注意
`src/utils/` 配下のモジュール編集時は、対応する仕様書も同時更新:
- モジュール: `src/utils/hdf5_inspector.py`
- 仕様書: `docs/utils/HDF5_INSPECTOR_SPEC.md`

## コード設計

### 日本語表記
- ログメッセージ、コメント、処理説明は日本語で記述
- 変数名・関数名は英語（snake_case / PascalCase）

### コード設計
- **冗長化回避**: トークン制限（25000）を意識した簡潔な設計
- **既存モジュール活用**: `src/utils/` の共通モジュールを積極利用
- **シンプルな表現**: 「完全解決」等の誇張語は使わず、事実のみ記述

### 例

❌ **NG**:
```python
# NaN問題を完全に解決する絶対的な処理
def remove_nan_completely(df):
    ...
```

✅ **OK**:
```python
# NaN値を除外
def remove_nan(df):
    ...
```

---

## まとめ: AI実装時の必須確認事項

このファイルはGitHub Copilotが毎回読み込むAI向け指示書です。以下を常に遵守してください:

1. **カレントディレクトリ**: `cd /path/to/project &&` は不要（常にプロジェクトルート）
2. **エラー処理**: サイレントに握りつぶさず、必ず raise して伝播
3. **実装フロー**: 提案 → 確認 → 実装 → 検証の順守
4. **コミットメッセージ**: 日本語、AI署名禁止、誇張語禁止、具体的数値禁止
5. **Phase表記**: 必ず内容を明示（例: `NaN除外ロジック修正対応 Phase2`）
6. **テストファイル**: `_test_*.py` は検証後必ず削除
7. **共通モジュール**: `src/utils/` 編集時は `docs/utils/` の仕様書も同時更新
8. **ディレクトリ構造**: メインスクリプトと同名ディレクトリに固有モジュール配置