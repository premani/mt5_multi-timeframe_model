# TRACE_ID_SPEC.md - トレースID生成・管理仕様

**バージョン**: 1.0  
**更新日**: 2025-01-21

---

## 📋 目的

運用ログと検証ログを一意のトレースIDで紐付け、問題発生時のトレーサビリティを確保する。

---

## 項目120対応: 運用↔検証ログID紐付け

**目的**: 運用環境の異常発生時、検証ログとの対応が不明確で原因調査困難

**解決策**: 一意なトレースIDを生成し、全ログに付与

### トレースID仕様

```python
import hashlib
from datetime import datetime
from typing import Optional

class TraceIDGenerator:
    """トレースID生成器"""
    
    def __init__(self, version: str = "v1"):
        """
        Args:
            version: トレースIDフォーマットバージョン
        """
        self.version = version
    
    def generate(
        self,
        timestamp: Optional[datetime] = None,
        symbol: str = "USDJPY",
        sequence_id: Optional[int] = None,
        additional_data: Optional[dict] = None
    ) -> str:
        """
        トレースID生成
        
        Format: {version}_{timestamp_hash}_{symbol}_{sequence}_{data_hash}
        Example: v1_a3f2b1c8_USDJPY_00042_e7d9f3a1
        
        Args:
            timestamp: タイムスタンプ（デフォルト: 現在時刻）
            symbol: シンボル名
            sequence_id: シーケンスID（オプション）
            additional_data: 追加データ（オプション）
        
        Returns:
            trace_id: 一意なトレースID文字列
        """
        if timestamp is None:
            timestamp = datetime.now()
        
        # タイムスタンプ部分（マイクロ秒精度）
        ts_str = timestamp.strftime("%Y%m%d%H%M%S%f")
        ts_hash = hashlib.md5(ts_str.encode()).hexdigest()[:8]
        
        # シンボル部分（そのまま）
        symbol_part = symbol
        
        # シーケンス部分（5桁ゼロパディング）
        if sequence_id is not None:
            sequence_part = f"{sequence_id:05d}"
        else:
            sequence_part = "00000"
        
        # 追加データ部分（オプション）
        if additional_data:
            data_str = str(sorted(additional_data.items()))
            data_hash = hashlib.md5(data_str.encode()).hexdigest()[:8]
        else:
            data_hash = "00000000"
        
        # 結合
        trace_id = f"{self.version}_{ts_hash}_{symbol_part}_{sequence_part}_{data_hash}"
        
        return trace_id
    
    def parse(self, trace_id: str) -> dict:
        """
        トレースIDをパース
        
        Args:
            trace_id: 生成されたトレースID
        
        Returns:
            parsed: {
                "version": str,
                "timestamp_hash": str,
                "symbol": str,
                "sequence_id": int,
                "data_hash": str
            }
        """
        parts = trace_id.split("_")
        
        if len(parts) != 5:
            raise ValueError(f"Invalid trace_id format: {trace_id}")
        
        return {
            "version": parts[0],
            "timestamp_hash": parts[1],
            "symbol": parts[2],
            "sequence_id": int(parts[3]),
            "data_hash": parts[4]
        }


class TraceIDLogger:
    """トレースID付きロガー"""
    
    def __init__(self, base_logger, trace_id: str):
        """
        Args:
            base_logger: Python標準logger or LogManager
            trace_id: 付与するトレースID
        """
        self.logger = base_logger
        self.trace_id = trace_id
    
    def _add_trace_id(self, msg: str) -> str:
        """ログメッセージにトレースID付与"""
        return f"[trace_id={self.trace_id}] {msg}"
    
    def info(self, msg: str):
        self.logger.info(self._add_trace_id(msg))
    
    def warning(self, msg: str):
        self.logger.warning(self._add_trace_id(msg))
    
    def error(self, msg: str):
        self.logger.error(self._add_trace_id(msg))
    
    def debug(self, msg: str):
        self.logger.debug(self._add_trace_id(msg))


# 使用例: 運用ログ
trace_gen = TraceIDGenerator(version="v1")

# トレードごとにトレースID生成
trace_id = trace_gen.generate(
    timestamp=datetime.now(),
    symbol="USDJPY",
    sequence_id=42,
    additional_data={
        "mode": "scalp",
        "entry_price": 110.25
    }
)

# トレースID付きログ出力
trace_logger = TraceIDLogger(base_logger=logger, trace_id=trace_id)
trace_logger.info("エントリー実行")
trace_logger.info("SL設定: 110.15")

# 出力例:
# [trace_id=v1_a3f2b1c8_USDJPY_00042_e7d9f3a1] エントリー実行
# [trace_id=v1_a3f2b1c8_USDJPY_00042_e7d9f3a1] SL設定: 110.15

# 検証ログでも同じトレースIDを使用
validation_logger = TraceIDLogger(validation_base_logger, trace_id=trace_id)
validation_logger.info("バックテスト実行: 同一エントリー条件")
```

---

## トレースID検索ツール

```python
import re
from pathlib import Path
from typing import List, Dict

class TraceIDSearcher:
    """ログファイルからトレースIDで検索"""
    
    def __init__(self, log_dirs: List[str]):
        """
        Args:
            log_dirs: 検索対象ログディレクトリのリスト
                      例: ["logs/operation/", "logs/validation/"]
        """
        self.log_dirs = log_dirs
    
    def search(
        self,
        trace_id: str,
        log_level: Optional[str] = None
    ) -> Dict[str, List[str]]:
        """
        トレースIDに対応するログ行を全ディレクトリから検索
        
        Args:
            trace_id: 検索するトレースID
            log_level: ログレベルフィルタ（INFO, WARNING, ERROR等）
        
        Returns:
            results: {
                "logs/operation/20250121.log": [行1, 行2, ...],
                "logs/validation/20250121.log": [行1, 行2, ...]
            }
        """
        results = {}
        
        # トレースIDパターン
        pattern = re.compile(rf"\[trace_id={re.escape(trace_id)}\]")
        
        # 各ディレクトリを検索
        for log_dir in self.log_dirs:
            log_path = Path(log_dir)
            
            if not log_path.exists():
                continue
            
            # ログファイルを走査
            for log_file in log_path.glob("*.log"):
                matched_lines = []
                
                with open(log_file, "r", encoding="utf-8") as f:
                    for line_no, line in enumerate(f, start=1):
                        # トレースID一致確認
                        if not pattern.search(line):
                            continue
                        
                        # ログレベルフィルタ
                        if log_level and log_level not in line:
                            continue
                        
                        matched_lines.append(f"[L{line_no}] {line.strip()}")
                
                if matched_lines:
                    results[str(log_file)] = matched_lines
        
        return results
    
    def summarize_trace(self, trace_id: str) -> dict:
        """
        トレースIDの全ログをサマリ表示
        
        Args:
            trace_id: サマリするトレースID
        
        Returns:
            summary: {
                "trace_id": str,
                "total_lines": int,
                "by_level": {"INFO": 10, "WARNING": 2, "ERROR": 0},
                "by_source": {"operation": 8, "validation": 4},
                "first_occurrence": datetime,
                "last_occurrence": datetime
            }
        """
        all_results = self.search(trace_id)
        
        total_lines = sum(len(lines) for lines in all_results.values())
        
        by_level = {"INFO": 0, "WARNING": 0, "ERROR": 0, "DEBUG": 0}
        by_source = {}
        
        for log_file, lines in all_results.items():
            # ソース判定（operation/validation）
            if "operation" in log_file:
                source = "operation"
            elif "validation" in log_file:
                source = "validation"
            else:
                source = "other"
            
            by_source[source] = by_source.get(source, 0) + len(lines)
            
            # ログレベル集計
            for line in lines:
                for level in by_level.keys():
                    if level in line:
                        by_level[level] += 1
                        break
        
        return {
            "trace_id": trace_id,
            "total_lines": total_lines,
            "by_level": by_level,
            "by_source": by_source,
            "log_files": list(all_results.keys())
        }


# 使用例: トレースID検索
searcher = TraceIDSearcher([
    "logs/operation/",
    "logs/validation/"
])

# トレースIDで検索
trace_id = "v1_a3f2b1c8_USDJPY_00042_e7d9f3a1"
results = searcher.search(trace_id)

print(f"トレースID {trace_id} の検索結果:")
for log_file, lines in results.items():
    print(f"\n{log_file}:")
    for line in lines:
        print(f"  {line}")

# サマリ表示
summary = searcher.summarize_trace(trace_id)
print(f"\nサマリ: {summary}")
```

---

## トレースID仕様

| 項目 | 仕様 |
|------|------|
| フォーマット | `{version}_{timestamp_hash}_{symbol}_{sequence}_{data_hash}` |
| バージョン | v1（将来拡張用） |
| タイムスタンプハッシュ | MD5[:8]（マイクロ秒精度） |
| シンボル | そのまま（例: USDJPY） |
| シーケンスID | 5桁ゼロパディング（例: 00042） |
| データハッシュ | MD5[:8]（追加データがある場合） |
| 衝突確率 | < 1e-9（MD5ハッシュ8文字） |

**例**:
```
v1_a3f2b1c8_USDJPY_00042_e7d9f3a1
└──┬──┘ └───┬───┘ └─┬──┘ └─┬──┘ └───┬───┘
   │        │       │      │        │
 version  timestamp symbol seq    data
```

**成功指標**:
- トレースID付与率 = 100%（全運用・検証ログ）
- 検索時間 < 5秒（10万行ログファイル）
- ログファイル間のID一致率 = 100%

**効果**:
- 運用異常発生時の原因特定時間短縮（数時間 → 数分）
- 検証ログとの完全紐付け
- デバッグ時のトレーサビリティ向上

---

## 🔗 関連仕様

- [CONFIG_MANAGEMENT_SPEC.md](../common/CONFIG_MANAGEMENT_SPEC.md) - 設定管理

---

## 🔮 将来拡張

- 分散トレーシング（OpenTelemetry統合）
- トレースIDからグラフィカルログ可視化
- Elasticsearch連携（高速全文検索）
