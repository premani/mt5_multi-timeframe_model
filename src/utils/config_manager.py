"""
設定管理モジュール
"""
import os
from pathlib import Path
from typing import Any, Dict, Optional, List
from datetime import datetime
import yaml


class ConfigManager:
    """設定管理クラス"""
    
    def __init__(self, config_path: Optional[str] = None):
        """
        初期化
        
        Args:
            config_path: 設定ファイルパス（省略時は環境変数から検索）
        """
        self.config_path = self._find_config(config_path)
        self.config = self._load_config()
        self._apply_env_overrides()
    
    def _find_config(self, config_path: Optional[str]) -> Path:
        """
        設定ファイルを検索
        
        Args:
            config_path: 指定された設定ファイルパス
        
        Returns:
            設定ファイルのPath
        
        Raises:
            FileNotFoundError: 設定ファイルが見つからない場合
        """
        if config_path:
            path = Path(config_path)
            if path.exists():
                return path
            raise FileNotFoundError(f"設定ファイルが見つかりません: {config_path}")
        
        # デフォルトパスを検索
        default_paths = [
            Path("config/data_collector.yaml"),
            Path("config/data_collector.template.yaml"),
        ]
        
        for path in default_paths:
            if path.exists():
                if "template" in path.name:
                    print(f"⚠️  テンプレートファイルを使用しています: {path}")
                    print(f"   本番運用前に config/data_collector.yaml を作成してください")
                return path
        
        raise FileNotFoundError(
            "設定ファイルが見つかりません。\n"
            "config/data_collector.template.yaml をコピーして\n"
            "config/data_collector.yaml を作成してください。"
        )
    
    def _load_config(self) -> Dict[str, Any]:
        """
        設定ファイルを読み込み
        
        Returns:
            設定辞書
        """
        with open(self.config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    
    def _apply_env_overrides(self):
        """環境変数で設定を上書き"""
        # MT5 API設定
        if 'MT5_API_ENDPOINT' in os.environ:
            if 'api' not in self.config:
                self.config['api'] = {}
            self.config['api']['endpoint'] = os.environ['MT5_API_ENDPOINT']
        
        if 'MT5_API_KEY' in os.environ:
            if 'api' not in self.config:
                self.config['api'] = {}
            self.config['api']['api_key'] = os.environ['MT5_API_KEY']
        
        if 'MT5_API_TIMEOUT' in os.environ:
            if 'api' not in self.config:
                self.config['api'] = {}
            self.config['api']['timeout'] = int(os.environ['MT5_API_TIMEOUT'])
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        設定値を取得（ドット記法対応）
        
        Args:
            key: 設定キー（例: "data_collection.symbols"）
            default: デフォルト値
        
        Returns:
            設定値
        """
        keys = key.split('.')
        value = self.config
        
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        
        return value
    
    def get_required(self, key: str) -> Any:
        """
        必須設定値を取得
        
        Args:
            key: 設定キー
        
        Returns:
            設定値
        
        Raises:
            ValueError: 設定が存在しない場合
        """
        value = self.get(key)
        if value is None:
            raise ValueError(f"必須設定が見つかりません: {key}")
        return value
    
    def validate_api_config(self) -> None:
        """
        API設定の検証

        Raises:
            ValueError: 必須設定が不足している場合
        """
        required_keys = ['api.endpoint', 'api.api_key']

        for key in required_keys:
            if self.get(key) is None:
                raise ValueError(
                    f"必須設定が不足しています: {key}\n"
                    f"環境変数 {key.replace('.', '_').upper()} を設定してください。"
                )

    def validate_data_collection_config(self) -> None:
        """
        データ収集設定の検証

        Raises:
            ValueError: 設定が不正な場合
        """
        # タイムフレーム検証
        self._validate_timeframes()

        # 通貨ペア検証
        self._validate_symbols()

        # 期間検証
        self._validate_period()

        # 品質閾値検証
        self._validate_quality_thresholds()

    def _validate_timeframes(self) -> None:
        """タイムフレーム設定の検証"""
        valid_tfs = ['M1', 'M5', 'M15', 'H1', 'H4']
        tfs = self.get('data_collection.timeframes', [])

        if not tfs:
            raise ValueError(
                "data_collection.timeframes が設定されていません。\n"
                f"有効な値: {', '.join(valid_tfs)}"
            )

        if not isinstance(tfs, list):
            raise ValueError(
                f"data_collection.timeframes はリスト形式である必要があります。\n"
                f"現在の型: {type(tfs).__name__}"
            )

        invalid_tfs = [tf for tf in tfs if tf not in valid_tfs]
        if invalid_tfs:
            raise ValueError(
                f"無効なタイムフレーム: {', '.join(invalid_tfs)}\n"
                f"有効な値: {', '.join(valid_tfs)}"
            )

    def _validate_symbols(self) -> None:
        """通貨ペア設定の検証"""
        symbols = self.get('data_collection.symbols', [])

        if not symbols:
            raise ValueError("data_collection.symbols が設定されていません。")

        if not isinstance(symbols, list):
            raise ValueError(
                f"data_collection.symbols はリスト形式である必要があります。\n"
                f"現在の型: {type(symbols).__name__}"
            )

        # 通貨ペア名の基本検証（大文字、6文字）
        for symbol in symbols:
            if not isinstance(symbol, str):
                raise ValueError(f"無効な通貨ペア: {symbol} (文字列である必要があります)")

            if len(symbol) < 6 or len(symbol) > 10:
                raise ValueError(
                    f"無効な通貨ペア: {symbol} (長さは6-10文字である必要があります)"
                )

            if not symbol.isupper():
                raise ValueError(
                    f"無効な通貨ペア: {symbol} (大文字である必要があります)"
                )

    def _validate_period(self) -> None:
        """期間設定の検証"""
        period = self.get('data_collection.period')

        if not period:
            raise ValueError("data_collection.period が設定されていません。")

        if not isinstance(period, dict):
            raise ValueError(
                f"data_collection.period は辞書形式である必要があります。\n"
                f"現在の型: {type(period).__name__}"
            )

        # 開始日・終了日の存在チェック
        if 'start' not in period:
            raise ValueError("data_collection.period.start が設定されていません。")

        if 'end' not in period:
            raise ValueError("data_collection.period.end が設定されていません。")

        # 日付フォーマット検証
        date_format = '%Y-%m-%d'
        try:
            start_date = datetime.strptime(period['start'], date_format)
        except ValueError as e:
            raise ValueError(
                f"data_collection.period.start の形式が不正です: {period['start']}\n"
                f"正しい形式: YYYY-MM-DD (例: 2018-01-01)\n"
                f"エラー: {e}"
            )

        try:
            end_date = datetime.strptime(period['end'], date_format)
        except ValueError as e:
            raise ValueError(
                f"data_collection.period.end の形式が不正です: {period['end']}\n"
                f"正しい形式: YYYY-MM-DD (例: 2025-10-23)\n"
                f"エラー: {e}"
            )

        # 開始日 < 終了日 の検証
        if start_date >= end_date:
            raise ValueError(
                f"開始日が終了日以降になっています。\n"
                f"開始日: {period['start']}, 終了日: {period['end']}"
            )

        # 未来日チェック（終了日が今日より後の場合は警告）
        today = datetime.now().date()
        if end_date.date() > today:
            import warnings
            warnings.warn(
                f"終了日が未来日です: {period['end']}\n"
                f"データ取得時にエラーが発生する可能性があります。",
                UserWarning
            )

    def _validate_quality_thresholds(self) -> None:
        """品質閾値設定の検証"""
        thresholds = self.get('data_collection.quality_thresholds', {})

        if not thresholds:
            # デフォルト値が使用されるため警告のみ
            import warnings
            warnings.warn(
                "data_collection.quality_thresholds が設定されていません。\n"
                "デフォルト値が使用されます。",
                UserWarning
            )
            return

        # max_gap_ratio の検証
        max_gap_ratio = thresholds.get('max_gap_ratio')
        if max_gap_ratio is not None:
            if not isinstance(max_gap_ratio, (int, float)):
                raise ValueError(
                    f"max_gap_ratio は数値である必要があります。\n"
                    f"現在の値: {max_gap_ratio} (型: {type(max_gap_ratio).__name__})"
                )

            if not (0.0 <= max_gap_ratio <= 1.0):
                raise ValueError(
                    f"max_gap_ratio は 0.0～1.0 の範囲である必要があります。\n"
                    f"現在の値: {max_gap_ratio}"
                )

        # max_gap_fill の検証
        max_gap_fill = thresholds.get('max_gap_fill')
        if max_gap_fill is not None:
            if not isinstance(max_gap_fill, int):
                raise ValueError(
                    f"max_gap_fill は整数である必要があります。\n"
                    f"現在の値: {max_gap_fill} (型: {type(max_gap_fill).__name__})"
                )

            if max_gap_fill < 1:
                raise ValueError(
                    f"max_gap_fill は 1 以上である必要があります。\n"
                    f"現在の値: {max_gap_fill}"
                )

        # max_zero_streak の検証
        max_zero_streak = thresholds.get('max_zero_streak')
        if max_zero_streak is not None:
            if not isinstance(max_zero_streak, int):
                raise ValueError(
                    f"max_zero_streak は整数である必要があります。\n"
                    f"現在の値: {max_zero_streak} (型: {type(max_zero_streak).__name__})"
                )

            if max_zero_streak < 1:
                raise ValueError(
                    f"max_zero_streak は 1 以上である必要があります。\n"
                    f"現在の値: {max_zero_streak}"
                )

    def validate_all(self) -> None:
        """
        全設定の包括的な検証

        Raises:
            ValueError: 設定が不正な場合
        """
        # API設定検証
        self.validate_api_config()

        # データ収集設定検証
        self.validate_data_collection_config()

    def get_all(self) -> Dict[str, Any]:
        """全設定を取得"""
        return self.config
