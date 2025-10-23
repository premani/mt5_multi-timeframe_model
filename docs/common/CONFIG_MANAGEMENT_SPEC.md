# CONFIG_MANAGEMENT_SPEC.md

**バージョン**: 1.0.0  
**最終更新**: 2025-10-22  
**Author**: System Architect  
**目的**: Config override優先順位の明確化

---

## 📋 概要

複数のソース（環境変数、実行時フラグ、設定ファイル、デフォルト値）から設定を読み込む際の優先順位を明確化し、実行時にどの値が適用されたかを追跡可能にする。

---

## 🎯 優先順位ルール

### 確定順序（高 → 低）

```
1. 環境変数 (env)            優先度: 最高
2. 実行時フラグ (runtime)    優先度: 高
3. 設定ファイル (file)       優先度: 中
4. デフォルト値 (default)    優先度: 最低
```

**ルール**:
- 上位のソースが存在する場合、下位は無視される
- 同一優先度内では最後に読み込まれた値が有効
- 明示的な `None` は「未設定」として扱い、下位フォールバック

---

## 🔧 実装ガイドライン

### ConfigLoader クラス

```python
import os
import sys
import yaml
import json
from typing import Any, Dict, Optional
from pathlib import Path
from dataclasses import dataclass, field

@dataclass
class ConfigSource:
    """設定値のソース情報"""
    value: Any
    source: str  # "env", "runtime", "file", "default"
    source_detail: str  # 具体的なソース（ファイルパス、env変数名等）
    priority: int  # 1=env, 2=runtime, 3=file, 4=default


class ConfigLoader:
    """設定優先順位を管理するローダー"""
    
    PRIORITY_ORDER = {
        "env": 1,
        "runtime": 2,
        "file": 3,
        "default": 4
    }
    
    def __init__(self, config_file: Optional[str] = None):
        self.config_file = config_file
        self.resolved = {}  # key -> ConfigSource
        self.defaults = {}
        
    def set_default(self, key: str, value: Any):
        """デフォルト値設定"""
        self.defaults[key] = value
    
    def load(self, key: str, env_var: Optional[str] = None,
             runtime_arg: Optional[str] = None) -> Any:
        """
        優先順位に基づいて設定値を読み込み
        
        Args:
            key: 設定キー名
            env_var: 環境変数名（例: "BATCH_SIZE"）
            runtime_arg: 実行時引数（例: "--batch-size"）
        
        Returns:
            優先順位最高の設定値
        """
        sources = []
        
        # 1. 環境変数チェック
        if env_var and env_var in os.environ:
            value = self._parse_value(os.environ[env_var])
            sources.append(ConfigSource(
                value=value,
                source="env",
                source_detail=f"${env_var}",
                priority=self.PRIORITY_ORDER["env"]
            ))
        
        # 2. 実行時フラグチェック
        if runtime_arg:
            runtime_value = self._get_runtime_arg(runtime_arg)
            if runtime_value is not None:
                sources.append(ConfigSource(
                    value=runtime_value,
                    source="runtime",
                    source_detail=f"arg:{runtime_arg}",
                    priority=self.PRIORITY_ORDER["runtime"]
                ))
        
        # 3. 設定ファイルチェック
        if self.config_file and Path(self.config_file).exists():
            file_value = self._get_from_file(key)
            if file_value is not None:
                sources.append(ConfigSource(
                    value=file_value,
                    source="file",
                    source_detail=self.config_file,
                    priority=self.PRIORITY_ORDER["file"]
                ))
        
        # 4. デフォルト値チェック
        if key in self.defaults:
            sources.append(ConfigSource(
                value=self.defaults[key],
                source="default",
                source_detail="code_default",
                priority=self.PRIORITY_ORDER["default"]
            ))
        
        # 優先順位ソート（priority昇順 = 優先度降順）
        sources.sort(key=lambda s: s.priority)
        
        if not sources:
            raise ValueError(f"設定値未定義: {key}")
        
        # 最高優先度の値を採用
        selected = sources[0]
        self.resolved[key] = selected
        
        logger.info(f"設定読み込み: {key}={selected.value} "
                   f"(source: {selected.source}:{selected.source_detail})")
        
        return selected.value
    
    def _parse_value(self, value: str) -> Any:
        """文字列を適切な型に変換"""
        # bool変換
        if value.lower() in ("true", "1", "yes"):
            return True
        if value.lower() in ("false", "0", "no"):
            return False
        
        # int/float変換
        try:
            if "." in value:
                return float(value)
            return int(value)
        except ValueError:
            pass
        
        # JSON/リスト変換
        if value.startswith("[") or value.startswith("{"):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                pass
        
        return value  # 文字列として扱う
    
    def _get_runtime_arg(self, arg_name: str) -> Optional[Any]:
        """実行時引数から値取得"""
        for i, arg in enumerate(sys.argv):
            if arg == arg_name and i + 1 < len(sys.argv):
                return self._parse_value(sys.argv[i + 1])
            if arg.startswith(f"{arg_name}="):
                return self._parse_value(arg.split("=", 1)[1])
        return None
    
    def _get_from_file(self, key: str) -> Optional[Any]:
        """設定ファイルから値取得"""
        with open(self.config_file) as f:
            config = yaml.safe_load(f)
        
        # ネストしたキーに対応（例: "model.batch_size"）
        keys = key.split(".")
        value = config
        for k in keys:
            if not isinstance(value, dict) or k not in value:
                return None
            value = value[k]
        
        return value
    
    def dump_resolved_config(self, output_path: str = "logs/resolved_config.json"):
        """実行時に適用された設定をダンプ"""
        resolved_dict = {
            "timestamp": datetime.now().isoformat(),
            "git_commit": subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"]
            ).decode().strip(),
            "priority_order": ["env > runtime > file > default"],
            "config_file": self.config_file,
            "resolved_values": {
                key: {
                    "value": source.value,
                    "source": source.source,
                    "source_detail": source.source_detail,
                    "priority": source.priority
                }
                for key, source in self.resolved.items()
            }
        }
        
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(resolved_dict, f, indent=2, ensure_ascii=False)
        
        logger.info(f"実行時設定ダンプ: {output_path}")
        return output_path


# 使用例
config = ConfigLoader(config_file="config/training.yaml")

# デフォルト値設定
config.set_default("batch_size", 128)
config.set_default("learning_rate", 0.001)

# 優先順位に基づいて読み込み
batch_size = config.load(
    key="batch_size",
    env_var="BATCH_SIZE",           # 環境変数: 最優先
    runtime_arg="--batch-size"      # 実行時フラグ: 次点
)

learning_rate = config.load(
    key="learning_rate",
    env_var="LEARNING_RATE",
    runtime_arg="--lr"
)

# 実行時設定ダンプ
config.dump_resolved_config("logs/resolved_config.json")
```

---

## 📊 実行時ダンプ例

### resolved_config.json

```json
{
  "timestamp": "2025-10-22T10:30:00+00:00",
  "git_commit": "abc123d",
  "priority_order": ["env > runtime > file > default"],
  "config_file": "config/training.yaml",
  "resolved_values": {
    "batch_size": {
      "value": 256,
      "source": "env",
      "source_detail": "$BATCH_SIZE",
      "priority": 1
    },
    "learning_rate": {
      "value": 0.0005,
      "source": "runtime",
      "source_detail": "arg:--lr",
      "priority": 2
    },
    "dropout": {
      "value": 0.1,
      "source": "file",
      "source_detail": "config/training.yaml",
      "priority": 3
    },
    "warmup_steps": {
      "value": 1000,
      "source": "default",
      "source_detail": "code_default",
      "priority": 4
    }
  }
}
```

**解釈**:
- `batch_size=256`: 環境変数 `$BATCH_SIZE` で上書き（最優先）
- `learning_rate=0.0005`: 実行時フラグ `--lr` で指定（環境変数なし）
- `dropout=0.1`: 設定ファイルから読み込み（env/runtime指定なし）
- `warmup_steps=1000`: デフォルト値使用（全ソース未指定）

---

## 🔍 デバッグ・トラブルシューティング

### 1. 設定値が期待と異なる場合

```bash
# resolved_config.json を確認
cat logs/resolved_config.json | jq '.resolved_values.batch_size'

# 出力例:
{
  "value": 256,
  "source": "env",
  "source_detail": "$BATCH_SIZE",
  "priority": 1
}

# → 環境変数 $BATCH_SIZE=256 が適用されている
```

### 2. 優先順位の検証

```python
# ConfigLoader のログ出力で確認
# INFO: 設定読み込み: batch_size=256 (source: env:$BATCH_SIZE)
# INFO: 設定読み込み: learning_rate=0.0005 (source: runtime:arg:--lr)
```

### 3. 環境変数の一覧確認

```bash
env | grep -E "(BATCH|LEARNING|DROPOUT)" | sort
```

---

## 📚 優先順位の実用例

### 例1: 本番環境での上書き

```bash
# config/training.yaml: batch_size=128
# 本番環境で一時的に256に変更したい

export BATCH_SIZE=256
python src/train.py

# → batch_size=256 が適用される（環境変数が最優先）
```

### 例2: デバッグ実行

```bash
# 設定ファイルを変更せずにデバッグモードで実行

python src/train.py --batch-size=32 --debug=true

# → batch_size=32, debug=true が適用される
```

### 例3: CI/CD での自動テスト

```yaml
# .github/workflows/test.yml
env:
  BATCH_SIZE: 16        # テスト用に小さく設定
  LEARNING_RATE: 0.01
  NUM_EPOCHS: 2

steps:
  - run: python src/train.py
```

---

## 🚨 注意事項

### 1. 環境変数の持続性

```bash
# ❌ NG: シェルセッション終了で消える
export BATCH_SIZE=256

# ✅ OK: 永続化（本番環境）
echo "export BATCH_SIZE=256" >> ~/.bashrc
source ~/.bashrc
```

### 2. 実行時フラグの記録

```bash
# 実行コマンドをログに記録
echo "$(date): python src/train.py $*" >> logs/command_history.log
python src/train.py --batch-size=256
```

### 3. 設定ファイルのバージョン管理

```bash
# config/*.yaml はGit管理
git add config/training.yaml
git commit -m "バッチサイズ変更: 128 → 256"

# resolved_config.json で実際の適用値を確認
```

---

## 📖 関連仕様書

- `docs/THRESHOLD_METADATA_SPEC.md` - 閾値根拠トレーサビリティ
- `docs/TRAINER_SPEC.md` - 学習設定
- `README.md` - 設定ファイル構造

---

## 変更履歴

| 日付 | バージョン | 変更内容 |
|------|-----------|----------|
| 2025-10-22 | 1.0.0 | 初版作成 |
