"""
ログ管理モジュール
"""
import logging
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional


class LoggingManager:
    """ログ管理クラス"""
    
    def __init__(
        self,
        name: str = __name__,
        log_dir: str = "logs",
        level: str = "INFO",
        timezone_name: str = "Asia/Tokyo"
    ):
        """
        初期化
        
        Args:
            name: ロガー名
            log_dir: ログディレクトリ
            level: ログレベル
            timezone_name: タイムゾーン名（ログ表示用）
        """
        self.name = name
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # タイムゾーン設定
        if timezone_name == "Asia/Tokyo":
            self.tz = timezone(timedelta(hours=9))
        elif timezone_name == "UTC":
            self.tz = timezone.utc
        else:
            # 他のタイムゾーンは簡易対応（必要に応じて拡張）
            self.tz = timezone.utc
        
        # ロガー設定
        self.logger = logging.getLogger(name)
        self.logger.setLevel(getattr(logging, level.upper()))
        
        # ハンドラーが既に設定されている場合はクリア
        if self.logger.handlers:
            self.logger.handlers.clear()
        
        # コンソールハンドラー
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(getattr(logging, level.upper()))
        console_formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        console_handler.setFormatter(console_formatter)
        self.logger.addHandler(console_handler)
        
        # ファイルハンドラー（タイムスタンプ + 処理名の順序）
        log_file = self.log_dir / f"{self._get_timestamp_str()}_{name}.log"
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(getattr(logging, level.upper()))
        file_formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(file_formatter)
        self.logger.addHandler(file_handler)
    
    def _get_timestamp_str(self) -> str:
        """現在時刻の文字列取得（JST）"""
        now = datetime.now(self.tz)
        return now.strftime('%Y%m%d_%H%M%S')
    
    def format_datetime(self, dt: datetime, include_tz: bool = True) -> str:
        """
        日時を表示用フォーマットに変換
        
        Args:
            dt: 日時オブジェクト
            include_tz: タイムゾーン表記を含めるか
        
        Returns:
            フォーマット済み文字列
        """
        # UTCからJSTに変換
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        
        dt_jst = dt.astimezone(self.tz)
        
        if include_tz:
            return dt_jst.strftime('%Y-%m-%d %H:%M:%S JST')
        else:
            return dt_jst.strftime('%Y-%m-%d %H:%M:%S')
    
    def get_logger(self) -> logging.Logger:
        """ロガーインスタンス取得"""
        return self.logger
    
    def info(self, msg: str) -> None:
        """INFOログ出力"""
        self.logger.info(msg)

    def debug(self, msg: str) -> None:
        """DEBUGログ出力"""
        self.logger.debug(msg)

    def warning(self, msg: str) -> None:
        """WARNINGログ出力"""
        self.logger.warning(msg)

    def error(self, msg: str) -> None:
        """ERRORログ出力"""
        self.logger.error(msg)

    def critical(self, msg: str) -> None:
        """CRITICALログ出力"""
        self.logger.critical(msg)
