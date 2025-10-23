# GitHub Copilot カスタム指示

## 📚 必須参照ファイル（回答前に必ず確認）

**すべての回答・コード生成前に以下のファイル内容を参照してください**:

### 1. 最優先参照（必須）
- **README.md** - プロジェクト全体概要・マルチタイムフレーム設計
- **AGENTS.md** - コーディング規約・禁止事項・実装フロー

---

## 🎯 プロジェクト概要（README.mdより）

**目的**: マルチタイムフレーム分析による FX 価格予測モデル  
**技術スタック**: NVIDIA Docker + PyTorch 2.8.0 + CUDA 12.8  
**実行環境**: プロジェクトルート (`/home/mania/github.com/premani/mt5-multi-timeframe-model`)

### 核心設計
1. **マルチタイムフレーム分析**: M5, M15, H1 を同時処理
2. **マルチタスク学習**: 方向（UP/DOWN/NEUTRAL） + 価格幅（pips）を同時予測
3. **スケール不変パターン認識**: ダブルトップ等の時間スケール非依存パターン

### 前プロジェクトからの教訓
- ❌ 方向のみ予測 → 価格幅不明で実用性なし
- ❌ 単一タイムフレーム → 情報不足
- ❌ 固定シーケンス長 → パターン認識の柔軟性不足

**実行方法**: すべて `bash ./docker_run.sh python3 src/<script>.py` で実行

---

## 🚨 絶対禁止事項（AGENTS.mdより）

### 1. カレントディレクトリ指定禁止
❌ **NG**: `cd /home/mania/github.com/premani/mt5-multi-timeframe-model &&`  
✅ **OK**: `git add README.md` (直接実行)

**理由**: 常にプロジェクトルートで実行中

### 2. エラー握りつぶし禁止
❌ **NG**: `except: pass`  
✅ **OK**: `except ValueError as e: logger.error(f"エラー: {e}"); raise`

**理由**: フォールバックで隠蔽せず、根本原因を修正

### 3. 事前提案なし実装禁止
❌ **NG**: いきなりコード修正  
✅ **OK**: 提案 → 承認 → 実装

---

## 📝 コミットメッセージ規約（AGENTS.mdより）

| 項目 | ルール |
|------|--------|
| 言語 | 日本語のみ |
| AI署名 | 禁止 ("Copilot"等の文言不要) |
| 数値 | 禁止 (TASK番号・行数等) |
| 誇張語 | 禁止 ("完全"、"絶対"等) |

**例**:
```bash
# ❌ NG
git commit -m "完全にタイムスタンプ問題を解決 (TASK-123) Copilotによる修正"

# ✅ OK
git commit -m "マルチTFタイムスタンプ整合機能実装

- M5/M15/H1 の時刻揃え
- 欠損時刻の補完ロジック"
```

### Issue連携
- **参照のみ**: `git commit -m "データ収集機能実装 #2"`
- **自動クローズ**: `git commit -m "データ収集機能実装 closes #3"`
- **条件**: 実装完了 + テスト成功 + 追加コミット不要時のみ `closes` 使用

---

## 🏗️ ファイル・ディレクトリ構造（AGENTS.mdより）

### モジュール配置原則
```
src/
├── <script_name>.py          # メインスクリプト
└── <script_name>/            # 同名ディレクトリに固有モジュール
    ├── module1.py
    └── module2.py

docs/
├── <SCRIPT_NAME>_SPEC.md     # 処理全体仕様書
└── <script_name>/            # モジュール別詳細仕様
    ├── MODULE1_SPEC.md
    └── MODULE2_SPEC.md
```

### テストファイル
- **命名**: `_test_*.py`
- **配置**: プロジェクトルート直下
- **削除**: 検証完了後は必ず削除

---

## 💻 コーディング規約（AGENTS.mdより）

### 命名規則
- ファイル: `snake_case.py`
- クラス: `PascalCase`
- 変数/関数: `snake_case`

### 言語使用
- ログ・コメント: 日本語
- 変数名・関数名: 英語

### 設計原則
1. トークン制限25000を意識した簡潔な設計
2. `src/utils/` の共通モジュールを積極利用
3. 誇張語禁止（"完全解決"等は使わず事実のみ）

### Phase表記ルール
❌ **NG**: `# phase2 実装`  
✅ **OK**: `# マルチTF統合 phase2`

---

## 🔧 実装時の必須確認チェックリスト（AGENTS.mdより）

- [ ] README.md でプロジェクト全体像を把握したか
- [ ] AGENTS.md で禁止事項を確認したか
- [ ] 該当する `docs/*_SPEC.md` を参照したか
- [ ] `cd /home/mania/.../` を使っていないか
- [ ] `except: pass` でエラー握りつぶしていないか
- [ ] 提案→承認→実装の順で進めているか
- [ ] コミットメッセージに誇張語・数値が入っていないか
- [ ] Phase表記に内容説明があるか
- [ ] テストファイル削除したか
- [ ] `src/utils/` 編集時に `docs/utils/` の仕様書も同時更新したか
- [ ] マルチTF のタイムスタンプ整合性を確認したか

---

## 🎯 マルチタイムフレーム設計の重要ポイント

### タイムスタンプ整合性
- M5, M15, H1 の時刻を正確に揃える
- 欠損時刻の補完方法を明確化
- タイムゾーン統一

### スケール不変性
- 価格の絶対値ではなく相対値・変化率を使用
- パターン認識は時間スケールに依存しない設計
- ダブルトップ等のパターンは1時間でも4時間でも同じロジック

### マルチタスク学習
- 方向予測（分類）: UP/DOWN/NEUTRAL
- 価格幅予測（回帰）: pips
- 損失関数: 重み付き合計（例: 0.5 * 方向 + 0.5 * 価格幅）

---

## 📖 詳細仕様参照先（README.mdより）

### データ処理
- `docs/DATA_COLLECTION_SPEC.md` - マルチTFデータ収集
- `docs/DATA_ALIGNMENT_SPEC.md` - タイムスタンプ整合

### モデル
- `docs/TRAINER_SPEC.md` - 学習全体仕様
- `docs/trainer/MULTI_TF_FUSION_SPEC.md` - マルチTF融合アーキテクチャ
- `docs/trainer/MODEL_ARCHITECTURE_SCALP_EXTENSION_SPEC.md` - スカルプ拡張

### 共通モジュール
- `docs/UTILS_COMMON_MODULES_SPEC.md` - 全モジュール概要
- `docs/utils/HDF5_DATASET_SPEC.md` - HDF5読み書き
- `docs/utils/LOGGING_MANAGER_SPEC.md` - ログ管理

---

## 🎯 実装フロー（AGENTS.mdより）

1. **参照**: README.md・AGENTS.md・該当仕様書を確認
2. **提案**: 変更内容を簡潔に説明
3. **確認**: ユーザーの合意を得る
4. **実装**: 承認後にコード修正
5. **検証**: 変更内容を表示・確認

---

**重要**: 
- **すべての回答は README.md と AGENTS.md の内容に準拠してください**
- **コード生成時は該当する `docs/*_SPEC.md` を必ず参照してください**
- **不明点がある場合は実装前に確認してください**
- **マルチタイムフレームのタイムスタンプ整合性は最優先課題です**
