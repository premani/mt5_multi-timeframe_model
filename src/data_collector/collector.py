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

    # バーデータのカラムインデックス定義
    # 配列構造: [time, open, high, low, close, tick_volume, spread, real_volume]
    BAR_COLUMNS = {
        'time': 0,
        'open': 1,
        'high': 2,
        'low': 3,
        'close': 4,
        'tick_volume': 5,
        'spread': 6,
        'real_volume': 7
    }

    # バーデータの総カラム数
    BAR_COLUMN_COUNT = 8
    
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

        # 全設定の包括的な検証
        self.logger.info("🔍 設定ファイル検証中...")
        config.validate_all()
        self.logger.info("✅ 設定ファイル検証完了")
        
        # APIクライアント初期化
        self.api_client = MT5APIClient(
            endpoint=config.get_required('api.endpoint'),
            api_key=config.get_required('api.api_key'),
            timeout=config.get('api.timeout'),  # None許可
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
    
    def collect(self) -> None:
        """データ収集メイン処理"""
        self.logger.info("🔄 データ収集開始")
        
        # 既存ファイルバックアップ
        if self.config.get('output.backup.enabled', True):
            timestamp_format = self.config.get('output.backup.timestamp_format', '%Y%m%d_%H%M%S')
            self.hdf5_writer.backup_existing(timestamp_format)
        
        # 既存Tickデータクリーン（バーデータ収集前に実行）
        self.hdf5_writer.clear_tick_data()
        
        # 収集設定取得
        symbols = self.config.get_required('data_collection.symbols')
        timeframes = self.config.get_required('data_collection.timeframes')
        period = self.config.get_required('data_collection.period')
        
        # MT5 API ServerはYYYY-MM-DD形式を期待
        start_date = period['start']
        end_date = period['end']
        
        # 各通貨ペアについて処理
        for symbol in symbols:
            self.logger.info(f"📊 {symbol} データ収集")
            
            # バーデータ収集
            for tf in timeframes:
                self._collect_bars(symbol, tf, start_date, end_date)
            
            # Tickデータ収集
            if self.config.get('data_collection.ticks.enabled', False):
                self._collect_ticks(symbol, start_date, end_date)
        
        # メタデータ保存
        self._save_metadata(symbols[0], start_date, end_date)
        
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
    ) -> None:
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
        timestamps = bar_array[:, self.BAR_COLUMNS['time']].astype(np.int64)
        
        # 品質検証
        self._validate_bars(timeframe, timestamps, bar_array)
        
        # HDF5保存
        self.hdf5_writer.write_bar_data(timeframe, bar_array)
        
        # 統計記録（初回 or 更新）
        if timeframe not in self.stats['timeframes']:
            self.stats['timeframes'][timeframe] = {}
        
        self.stats['timeframes'][timeframe].update({
            'bars': len(bars),
            'period': {'start': start, 'end': end}
        })
        
        self.logger.info(f"   ✅ {timeframe}: {len(bars)}件取得・保存完了")
    
    def _collect_ticks(
        self,
        symbol: str,
        start: str,
        end: str
    ) -> None:
        """
        Tickデータ収集（月単位で分割取得）

        Args:
            symbol: 通貨ペア
            start: 開始日時（ISO8601: YYYY-MM-DD）
            end: 終了日時（ISO8601: YYYY-MM-DD）
        """
        self.logger.info(f"   📂 Tickデータ取得中（月分割）...")
        
        # 月範囲を生成
        month_ranges = self._generate_month_ranges(start, end)
        
        if not month_ranges:
            self.logger.warning(f"   ⚠️  月範囲が生成できませんでした")
            return
        
        self.logger.info(f"   📅 取得対象: {len(month_ranges)}ヶ月分")
        
        total_ticks = 0
        
        # 月ごとに取得・保存
        for i, (month_start, month_end) in enumerate(month_ranges, 1):
            self.logger.info(f"   🔄 [{i}/{len(month_ranges)}] {month_start} ~ {month_end}")
            
            # APIからデータ取得
            ticks = self.api_client.fetch_ticks(
                symbol=symbol,
                start=month_start,
                end=month_end
            )
            
            if not ticks:
                self.logger.warning(f"      ⚠️  データ取得失敗（スキップ）")
                continue
            
            # タイムスタンプ検証（ミリ秒精度）
            timestamps_msc = np.array([tick['time_msc'] for tick in ticks])
            self.validator.check_monotonic(timestamps_msc, name=f"Tick[{month_start}]")
            self.validator.check_duplicates(timestamps_msc, name=f"Tick[{month_start}]")
            
            # HDF5追記保存
            self.hdf5_writer.append_tick_data(ticks)
            
            total_ticks += len(ticks)
            self.logger.info(f"      ✅ {len(ticks):,}件保存（累計: {total_ticks:,}件）")
        
        # 統計記録
        self.stats['ticks'] = {
            'count': total_ticks,
            'months': len(month_ranges),
            'period': {'start': start, 'end': end}
        }
        
        self.logger.info(f"   ✅ Tick: 全{total_ticks:,}件取得・保存完了")
    
    def _generate_month_ranges(
        self,
        start: str,
        end: str
    ) -> List[Tuple[str, str]]:
        """
        月単位の範囲リストを生成
        
        Args:
            start: 開始日（YYYY-MM-DD）
            end: 終了日（YYYY-MM-DD）
        
        Returns:
            [(month_start, month_end), ...] のリスト
        """
        from datetime import datetime, timedelta
        from dateutil.relativedelta import relativedelta
        
        try:
            start_dt = datetime.strptime(start, '%Y-%m-%d')
            end_dt = datetime.strptime(end, '%Y-%m-%d')
        except ValueError as e:
            self.logger.error(f"日付フォーマットエラー: {e}")
            return []
        
        if start_dt > end_dt:
            self.logger.error(f"開始日が終了日より後です: {start} > {end}")
            return []
        
        ranges = []
        current = start_dt
        
        while current <= end_dt:
            # 月初
            month_start = current.replace(day=1)
            
            # 翌月初 - 1日 = 月末
            next_month = month_start + relativedelta(months=1)
            month_end = next_month - timedelta(days=1)
            
            # 最終月は指定終了日でクリップ
            if month_end > end_dt:
                month_end = end_dt
            
            # ISO8601形式に変換
            ranges.append((
                month_start.strftime('%Y-%m-%d'),
                month_end.strftime('%Y-%m-%d')
            ))
            
            # 次の月へ
            current = next_month
        
        return ranges
    
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
    ) -> None:
        """
        バーデータの品質検証

        Args:
            timeframe: タイムフレーム
            timestamps: タイムスタンプ配列
            bar_array: バーデータ配列
        """
        # 単調性チェック
        if not self.validator.check_monotonic(timestamps, name=timeframe):
            # validatorに詳細情報が記録されているため、そのまま例外を投げる
            violation_info = self.validator.validation_results.get(f'{timeframe}_monotonic_violations', {})
            raise RuntimeError(
                f"{timeframe}: タイムスタンプ単調性違反 - "
                f"詳細はログを確認してください (違反数: {violation_info.get('count', '不明')}件)"
            )

        # 重複チェック
        is_valid, dup_count = self.validator.check_duplicates(timestamps, name=timeframe)
        if not is_valid:
            # validatorに詳細情報が記録されているため、そのまま例外を投げる
            dup_info = self.validator.validation_results.get(f'{timeframe}_duplicates', {})
            if isinstance(dup_info, dict):
                raise RuntimeError(
                    f"{timeframe}: タイムスタンプ重複検出 - "
                    f"重複値{dup_info.get('unique_duplicate_values', '?')}個, "
                    f"総重複数{dup_info.get('count', dup_count)}件"
                )
            else:
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
        
        # 統計記録（初回 or 更新）
        if timeframe not in self.stats['timeframes']:
            self.stats['timeframes'][timeframe] = {}
        
        self.stats['timeframes'][timeframe].update({
            'missing_count': missing_count,
            'missing_rate': gap_ratio
        })
        
        # スプレッドチェック
        spreads = bar_array[:, self.BAR_COLUMNS['spread']]
        is_valid, neg_count = self.validator.check_spread_validity(spreads, name=timeframe)
        if not is_valid:
            # validatorに詳細情報が記録されているため、そのまま例外を投げる
            spread_info = self.validator.validation_results.get(f'{timeframe}_negative_spread', {})
            if isinstance(spread_info, dict):
                raise RuntimeError(
                    f"{timeframe}: 負のスプレッド検出 - "
                    f"総数{spread_info.get('count', neg_count)}件, "
                    f"最初の負値index={spread_info.get('first_negative_index', '?')}"
                )
            else:
                raise RuntimeError(f"{timeframe}: 負のスプレッド検出 ({neg_count}件)")

        # tick_volume連続ゼロチェック
        tick_volumes = bar_array[:, self.BAR_COLUMNS['tick_volume']]
        max_zero_streak = self.config.get('data_collection.quality_thresholds.max_zero_streak', 120)
        self.validator.check_zero_streak(tick_volumes, max_zero_streak, name=timeframe)
    
    def _save_metadata(
        self,
        symbol: str,
        start: str,
        end: str
    ) -> None:
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
    
    def _generate_reports(self) -> None:
        """レポート生成"""
        output_dir = Path(self.config.get('output.data_dir', 'data'))
        base_name = self.config.get('output.base_name', 'data_collector')
        
        # バックアップ設定
        backup_enabled = self.config.get('output.backup.enabled', True)
        timestamp_format = self.config.get('output.backup.timestamp_format', '%Y%m%d_%H%M%S')
        
        # JSON レポート
        if self.config.get('output.reports.json', True):
            json_path = output_dir / f"{base_name}_report.json"
            if backup_enabled:
                self._backup_report_file(json_path, timestamp_format)
            self._generate_json_report(json_path)
        
        # Markdown レポート
        if self.config.get('output.reports.markdown', True):
            md_path = output_dir / f"{base_name}_report.md"
            if backup_enabled:
                self._backup_report_file(md_path, timestamp_format)
            self._generate_markdown_report(md_path)
    
    def _backup_report_file(self, file_path: Path, timestamp_format: str) -> None:
        """
        既存レポートファイルをバックアップ

        Args:
            file_path: レポートファイルパス
            timestamp_format: タイムスタンプフォーマット
        """
        if not file_path.exists():
            return
        
        # JST日時プレフィックスを生成
        jst_tz = timezone(timedelta(hours=9))
        mtime = datetime.fromtimestamp(
            file_path.stat().st_mtime,
            tz=jst_tz
        )
        timestamp_str = mtime.strftime(timestamp_format)
        
        # バックアップファイル名生成
        backup_name = f"{timestamp_str}_{file_path.name}"
        backup_path = file_path.parent / backup_name
        
        # リネーム
        file_path.rename(backup_path)
        self.logger.info(f"📦 既存レポートをバックアップ: {backup_name}")
    
    def _generate_json_report(self, output_path: Path) -> None:
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
    
    def _generate_markdown_report(self, output_path: Path) -> None:
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
