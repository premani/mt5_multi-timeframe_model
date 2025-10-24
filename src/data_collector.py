#!/usr/bin/env python3
"""
MT5データ収集メインスクリプト

マルチタイムフレーム（M1/M5/M15/H1/H4）のバーデータとTickデータを
MT5 API Server経由で収集し、HDF5形式で保存します。

実行方法:
    bash ./docker_run.sh python3 src/data_collector.py
"""
import sys
from pathlib import Path

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.utils.config_manager import ConfigManager
from src.utils.logging_manager import LoggingManager
from src.data_collector.collector import DataCollector


def main():
    """メイン処理"""
    # 警告を標準エラー出力に表示
    import warnings
    warnings.filterwarnings('default')

    try:
        # 設定読み込み
        config = ConfigManager()

        # ロガー初期化
        logger = LoggingManager(
            name='data_collector',
            log_dir=config.get('logging.log_dir', 'logs'),
            level=config.get('logging.level', 'INFO'),
            timezone_name=config.get('logging.timezone', 'Asia/Tokyo')
        )

        logger.info("=" * 60)
        logger.info("🚀 MT5データ収集開始")
        logger.info("=" * 60)
        
        # データ収集実行
        collector = DataCollector(config, logger)
        collector.collect()
        
        logger.info("=" * 60)
        logger.info("🎉 処理完了")
        logger.info("=" * 60)
        
        return 0
    
    except FileNotFoundError as e:
        print(f"❌ エラー: {e}", file=sys.stderr)
        return 1
    
    except ValueError as e:
        print(f"❌ 設定エラー: {e}", file=sys.stderr)
        return 1
    
    except RuntimeError as e:
        print(f"❌ 実行エラー: {e}", file=sys.stderr)
        return 1
    
    except KeyboardInterrupt:
        print("\n⚠️  処理を中断しました", file=sys.stderr)
        return 130
    
    except Exception as e:
        print(f"❌ 予期しないエラー: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
