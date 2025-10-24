"""
データ収集メイン処理モジュール
"""
import numpy as np
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Tuple
from pathlib import Path
import json

from .api_client import MT5APIClient
from .validator import DataValidator
from .hdf5_writer import HDF5Writer


class DataCollector:
    """データ収集メインクラス"""
    
    # タイムフレームごとの期待間隔（秒）
    TF_INTERVALS = {
        'M1': 60,
        'M5': 300,
        'M15': 900,
        'H1': 3600,
        'H4': 14400
    }
    
    def __init__(
        self,
        config,
        logger
    ):
        """
        初期化
        
        Args:
            config: ConfigManagerインスタンス
            logger: LoggingManagerインスタンス
        """
        self.config = config
        self.logger = logger
        
        # API設定検証
        config.validate_api_config()
        
        # APIクライアント初期化
        self.api_client = MT5APIClient(
            endpoint=config.get_required('api.endpoint'),
            api_key=config.get_required('api.api_key'),
            timeout=config.get('api.timeout', 60),
            logger=logger
        )
        
        # バリデーター初期化
        self.validator = DataValidator(logger=logger)
        
        # HDF5ライター初期化
        output_dir = config.get('output.data_dir', 'data')
        base_name = config.get('output.base_name', 'data_collector')
        output_path = Path(output_dir) / f"{base_name}.h5"
        
        compression = config.get('output.hdf5.compression')
        self.hdf5_writer = HDF5Writer(
            output_path=str(output_path),
            compression=compression,
            logger=logger
        )
        
        # 統計情報
        self.stats = {
            'timeframes': {},
            'ticks': {},
            'quality': {},
            'performance': {}
        }
    
    def collect(self):
        """データ収集メイン処理"""
        self.logger.info("🔄 データ収集開始")
        
        # 既存ファイルバックアップ
        if self.config.get('output.backup.enabled', True):
            timestamp_format = self.config.get('output.backup.timestamp_format', '%Y%m%d_%H%M%S')
            self.hdf5_writer.backup_existing(timestamp_format)
        
        # 収集設定取得
        symbols = self.config.get_required('data_collection.symbols')
        timeframes = self.config.get_required('data_collection.timeframes')
        period = self.config.get_required('data_collection.period')
        
        # 日時をISO8601形式に変換
        start_dt = datetime.fromisoformat(period['start']).replace(tzinfo=timezone.utc)
        end_dt = datetime.fromisoformat(period['end']).replace(tzinfo=timezone.utc, hour=23, minute=59, second=59)
        
        start_iso = start_dt.isoformat()
        end_iso = end_dt.isoformat()
        
        # 各通貨ペアについて処理
        for symbol in symbols:
            self.logger.info(f"📊 {symbol} データ収集")
            
            # バーデータ収集
            for tf in timeframes:
                self._collect_bars(symbol, tf, start_iso, end_iso)
            
            # Tickデータ収集
            if self.config.get('data_collection.ticks.enabled', False):
                self._collect_ticks(symbol, start_iso, end_iso)
        
        # メタデータ保存
        self._save_metadata(symbols[0], start_iso, end_iso)
        
        # レポート生成
        self._generate_reports()
        
        # API統計出力
        api_stats = self.api_client.get_stats()
        self.logger.info(
            f"⚙️  API統計: リクエスト{api_stats['total_requests']}回, "
            f"平均レスポンス{api_stats['avg_response_time_ms']}ms"
        )
        
        self.logger.info("✅ データ収集完了")
    
    def _collect_bars(
        self,
        symbol: str,
        timeframe: str,
        start: str,
        end: str
    ):
        """
        バーデータ収集
        
        Args:
            symbol: 通貨ペア
            timeframe: タイムフレーム
            start: 開始日時（ISO8601）
            end: 終了日時（ISO8601）
        """
        self.logger.info(f"   📂 {timeframe}バーデータ取得中...")
        
        # APIからデータ取得
        bars = self.api_client.fetch_bars(
            symbol=symbol,
            timeframe=timeframe,
            start=start,
            end=end
        )
        
        if not bars:
            self.logger.warning(f"   ⚠️  {timeframe}: データが取得できませんでした")
            return
        
        # numpy配列に変換
        bar_array = self._convert_bars_to_array(bars)
        
        # タイムスタンプ抽出
        timestamps = bar_array[:, 0].astype(np.int64)
        
        # 品質検証
        self._validate_bars(timeframe, timestamps, bar_array)
        
        # HDF5保存
        self.hdf5_writer.write_bar_data(timeframe, bar_array)
        
        # 統計記録
        self.stats['timeframes'][timeframe] = {
            'bars': len(bars),
            'period': {'start': start, 'end': end}
        }
        
        self.logger.info(f"   ✅ {timeframe}: {len(bars)}件取得・保存完了")
    
    def _collect_ticks(
        self,
        symbol: str,
        start: str,
        end: str
    ):
        """
        Tickデータ収集
        
        Args:
            symbol: 通貨ペア
            start: 開始日時（ISO8601）
            end: 終了日時（ISO8601）
        """
        self.logger.info(f"   📂 Tickデータ取得中...")
        
        # APIからデータ取得
        ticks = self.api_client.fetch_ticks(
            symbol=symbol,
            start=start,
            end=end
        )
        
        if not ticks:
            self.logger.warning(f"   ⚠️  Tickデータが取得できませんでした")
            return
        
        # タイムスタンプ検証
        timestamps = np.array([tick['time'] for tick in ticks])
        self.validator.check_monotonic(timestamps, name="Tick")
        self.validator.check_duplicates(timestamps, name="Tick")
        
        # HDF5保存
        self.hdf5_writer.write_tick_data(ticks)
        
        # 統計記録
        self.stats['ticks'] = {
            'count': len(ticks),
            'period': {'start': start, 'end': end}
        }
        
        self.logger.info(f"   ✅ Tick: {len(ticks)}件取得・保存完了")
    
    def _convert_bars_to_array(self, bars: List[Dict]) -> np.ndarray:
        """
        バーデータをnumpy配列に変換
        
        Args:
            bars: バーデータリスト
        
        Returns:
            numpy配列 (N, 8) [time, open, high, low, close, tick_volume, spread, real_volume]
        """
        # タイムスタンプはint64、価格・出来高はfloat32で保存
        time_col = np.array([bar['time'] for bar in bars], dtype=np.int64).reshape(-1, 1)
        price_cols = np.array([
            [
                bar['open'],
                bar['high'],
                bar['low'],
                bar['close'],
                bar['tick_volume'],
                bar['spread'],
                bar.get('real_volume', 0)
            ]
            for bar in bars
        ], dtype=np.float32)
        
        # 結合 (N, 8)
        return np.hstack([time_col, price_cols])
    
    def _validate_bars(
        self,
        timeframe: str,
        timestamps: np.ndarray,
        bar_array: np.ndarray
    ):
        """
        バーデータの品質検証
        
        Args:
            timeframe: タイムフレーム
            timestamps: タイムスタンプ配列
            bar_array: バーデータ配列
        """
        # 単調性チェック
        if not self.validator.check_monotonic(timestamps, name=timeframe):
            raise RuntimeError(f"{timeframe}: タイムスタンプ単調性違反")
        
        # 重複チェック
        is_valid, dup_count = self.validator.check_duplicates(timestamps, name=timeframe)
        if not is_valid:
            raise RuntimeError(f"{timeframe}: タイムスタンプ重複検出 ({dup_count}件)")
        
        # 欠損率チェック
        expected_interval = self.TF_INTERVALS[timeframe]
        max_gap_ratio = self.config.get('data_collection.quality_thresholds.max_gap_ratio', 0.005)
        
        is_valid, gap_ratio, missing_count = self.validator.check_gap_ratio(
            timestamps,
            expected_interval,
            max_gap_ratio,
            name=timeframe
        )
        
        self.stats['timeframes'][timeframe] = {
            'missing_count': missing_count,
            'missing_rate': gap_ratio
        }
        
        # スプレッドチェック
        spreads = bar_array[:, 6]  # spread列
        is_valid, neg_count = self.validator.check_spread_validity(spreads, name=timeframe)
        if not is_valid:
            raise RuntimeError(f"{timeframe}: 負のスプレッド検出 ({neg_count}件)")
        
        # tick_volume連続ゼロチェック
        tick_volumes = bar_array[:, 5]
        max_zero_streak = self.config.get('data_collection.quality_thresholds.max_zero_streak', 120)
        self.validator.check_zero_streak(tick_volumes, max_zero_streak, name=timeframe)
    
    def _save_metadata(
        self,
        symbol: str,
        start: str,
        end: str
    ):
        """
        メタデータ保存
        
        Args:
            symbol: 通貨ペア
            start: 開始日時
            end: 終了日時
        """
        metadata = {
            'symbol': symbol,
            'start_date': start,
            'end_date': end,
            'api_endpoint': self.config.get('api.endpoint'),
            'collection_time': datetime.now(timezone(timedelta(hours=9))).isoformat(),
            'bar_counts': {
                tf: self.stats['timeframes'].get(tf, {}).get('bars', 0)
                for tf in self.config.get('data_collection.timeframes', [])
            },
            'tick_count': self.stats['ticks'].get('count', 0),
            'file_size_mb': self.hdf5_writer.get_file_size_mb()
        }
        
        self.hdf5_writer.write_metadata(metadata)
    
    def _generate_reports(self):
        """レポート生成"""
        output_dir = Path(self.config.get('output.data_dir', 'data'))
        base_name = self.config.get('output.base_name', 'data_collector')
        
        # JSON レポート
        if self.config.get('output.reports.json', True):
            json_path = output_dir / f"{base_name}_report.json"
            self._generate_json_report(json_path)
        
        # Markdown レポート
        if self.config.get('output.reports.markdown', True):
            md_path = output_dir / f"{base_name}_report.md"
            self._generate_markdown_report(md_path)
    
    def _generate_json_report(self, output_path: Path):
        """JSONレポート生成"""
        report = {
            'timestamp': datetime.now(timezone(timedelta(hours=9))).isoformat(),
            'process': 'data_collector',
            'version': '1.0',
            'timeframes': self.stats['timeframes'],
            'ticks': self.stats['ticks'],
            'quality': self.validator.get_results(),
            'performance': self.api_client.get_stats()
        }
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        
        self.logger.info(f"📄 JSONレポート生成: {output_path.name}")
    
    def _generate_markdown_report(self, output_path: Path):
        """Markdownレポート生成"""
        now_jst = datetime.now(timezone(timedelta(hours=9)))
        
        lines = [
            "# データ収集 実行レポート\n",
            f"**実行日時**: {now_jst.strftime('%Y-%m-%d %H:%M:%S JST')}  \n",
            "**バージョン**: 1.0\n",
            "\n## 📊 タイムフレーム別統計\n",
            "\n| TF | バー数 | 欠損数 | 欠損率 |",
            "\n|----|--------|--------|--------|"
        ]
        
        for tf, stats in self.stats['timeframes'].items():
            bars = stats.get('bars', 0)
            missing = stats.get('missing_count', 0)
            missing_rate = stats.get('missing_rate', 0.0)
            lines.append(
                f"\n| {tf} | {bars:,} | {missing} | {missing_rate*100:.2f}% |"
            )
        
        if self.stats['ticks']:
            lines.extend([
                "\n\n## 📈 Tickデータ統計\n",
                f"\n- **Tick数**: {self.stats['ticks'].get('count', 0):,}"
            ])
        
        lines.append("\n\n## ✅ 検証結果\n")
        for key, value in self.validator.get_results().items():
            lines.append(f"\n- {key}: {value}")
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(''.join(lines))
        
        self.logger.info(f"📄 Markdownレポート生成: {output_path.name}")
