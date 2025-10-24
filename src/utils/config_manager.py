"""
設定管理モジュール
"""
import os
from pathlib import Path
from typing import Any, Dict, Optional
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
    
    def validate_api_config(self):
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
    
    def get_all(self) -> Dict[str, Any]:
        """全設定を取得"""
        return self.config
