"""
MT5 API Server クライアントモジュール
"""
import requests
from datetime import datetime
from typing import Dict, List, Any, Optional
import time


class MT5APIClient:
    """MT5 API Server通信クライアント"""
    
    def __init__(
        self,
        endpoint: str,
        api_key: str,
        timeout: int = 60,
        logger=None
    ):
        """
        初期化
        
        Args:
            endpoint: API ServerのエンドポイントURL
            api_key: 認証用APIキー
            timeout: リクエストタイムアウト（秒）
            logger: ロガーインスタンス
        """
        self.endpoint = endpoint.rstrip('/')
        self.api_key = api_key
        self.timeout = timeout
        self.logger = logger
        
        # リクエスト統計
        self.stats = {
            'total_requests': 0,
            'successful_requests': 0,
            'failed_requests': 0,
            'total_response_time': 0.0
        }
    
    def _get_headers(self) -> Dict[str, str]:
        """認証ヘッダーを取得"""
        return {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }
    
    def _log(self, level: str, msg: str):
        """ログ出力"""
        if self.logger:
            getattr(self.logger, level)(msg)
    
    def fetch_bars(
        self,
        symbol: str,
        timeframe: str,
        start: str,
        end: str,
        limit: int = 0
    ) -> List[Dict[str, Any]]:
        """
        バーデータを取得
        
        Args:
            symbol: 通貨ペア（例: "USDJPY"）
            timeframe: タイムフレーム（例: "M5"）
            start: 開始日時（ISO8601形式）
            end: 終了日時（ISO8601形式）
            limit: 取得上限（0=無制限）
        
        Returns:
            バーデータのリスト
        
        Raises:
            RuntimeError: API呼び出しに失敗した場合
        """
        url = f"{self.endpoint}/historical"
        payload = {
            'symbol': symbol,
            'timeframe': timeframe,
            'start': start,
            'end': end
        }
        
        # limitは0以外の場合のみ追加（0=無制限はAPIが受け付けない）
        if limit > 0:
            payload['limit'] = limit
        
        self._log('debug', f"📡 バーデータ取得: {symbol} {timeframe} {start} ～ {end}")
        
        start_time = time.time()
        self.stats['total_requests'] += 1
        
        try:
            response = requests.post(
                url,
                json=payload,
                headers=self._get_headers(),
                timeout=self.timeout
            )
            response.raise_for_status()
            
            elapsed = time.time() - start_time
            self.stats['total_response_time'] += elapsed
            self.stats['successful_requests'] += 1
            
            data = response.json()
            bar_count = data.get('count', 0)
            
            self._log('debug', f"   ✅ 取得成功: {bar_count}件 ({elapsed:.2f}秒)")
            
            return data.get('data', [])
        
        except requests.exceptions.RequestException as e:
            elapsed = time.time() - start_time
            self.stats['failed_requests'] += 1
            
            self._log('error', f"   ❌ 取得失敗: {str(e)} ({elapsed:.2f}秒)")
            raise RuntimeError(f"バーデータ取得失敗: {symbol} {timeframe}") from e
    
    def fetch_ticks(
        self,
        symbol: str,
        start: str,
        end: str,
        tick_type: str = "INFO",
        limit: int = 0
    ) -> List[Dict[str, Any]]:
        """
        Tickデータを取得
        
        Args:
            symbol: 通貨ペア（例: "USDJPY"）
            start: 開始日時（ISO8601形式）
            end: 終了日時（ISO8601形式）
            tick_type: Tickタイプ（INFO/TRADE等）
            limit: 取得上限（0=無制限）
        
        Returns:
            Tickデータのリスト
        
        Raises:
            RuntimeError: API呼び出しに失敗した場合
        """
        url = f"{self.endpoint}/ticks"
        payload = {
            'symbol': symbol,
            'start': start,
            'end': end,
            'tick_type': tick_type,
            'limit': limit
        }
        
        self._log('debug', f"📡 Tickデータ取得: {symbol} {start} ～ {end}")
        
        start_time = time.time()
        self.stats['total_requests'] += 1
        
        try:
            response = requests.post(
                url,
                json=payload,
                headers=self._get_headers(),
                timeout=self.timeout
            )
            response.raise_for_status()
            
            elapsed = time.time() - start_time
            self.stats['total_response_time'] += elapsed
            self.stats['successful_requests'] += 1
            
            data = response.json()
            tick_count = data.get('count', 0)
            
            self._log('debug', f"   ✅ 取得成功: {tick_count}件 ({elapsed:.2f}秒)")
            
            return data.get('data', [])
        
        except requests.exceptions.RequestException as e:
            elapsed = time.time() - start_time
            self.stats['failed_requests'] += 1
            
            self._log('error', f"   ❌ 取得失敗: {str(e)} ({elapsed:.2f}秒)")
            raise RuntimeError(f"Tickデータ取得失敗: {symbol}") from e
    
    def get_stats(self) -> Dict[str, Any]:
        """
        統計情報を取得
        
        Returns:
            統計情報の辞書
        """
        avg_response_time = 0.0
        if self.stats['successful_requests'] > 0:
            avg_response_time = (
                self.stats['total_response_time'] / 
                self.stats['successful_requests']
            )
        
        return {
            'total_requests': self.stats['total_requests'],
            'successful_requests': self.stats['successful_requests'],
            'failed_requests': self.stats['failed_requests'],
            'avg_response_time_ms': int(avg_response_time * 1000)
        }
