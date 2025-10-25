#!/usr/bin/env python3
"""
特徴量計算メインスクリプト

第2段階: 特徴量計算
- 入力: data/data_collector.h5（マルチTF生データ）
- 出力: data/feature_calculator.h5（50-80特徴量）
- レポート: data/feature_calculator_report.{json,md}
"""

import sys
import time
import json
import h5py
import yaml
import hashlib
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, List

import pandas as pd
import numpy as np

# プロジェクトルート設定
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from feature_calculator import BaseCalculator, BasicMultiTFCalculator, SessionTimeCalculator, LabelGenerator
from feature_calculator.integrator import FeatureCalculatorIntegrator


def setup_logging() -> logging.Logger:
    """ログ設定（JST表示）"""
    # JST用のログフォーマッター
    class JSTFormatter(logging.Formatter):
        def formatTime(self, record, datefmt=None):
            dt = datetime.fromtimestamp(record.created, tz=timezone.utc)
            jst = dt.astimezone(timezone(timedelta(hours=9)))
            if datefmt:
                return jst.strftime(datefmt)
            return jst.strftime('%Y-%m-%d %H:%M:%S JST')
    
    # ログディレクトリ作成
    log_dir = PROJECT_ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    
    # ログファイル名（JST）
    jst_now = datetime.now(timezone(timedelta(hours=9)))
    log_file = log_dir / f"{jst_now.strftime('%Y%m%d_%H%M%S')}_feature_calculator.log"
    
    # ロガー設定
    logger = logging.getLogger("feature_calculator")
    logger.setLevel(logging.INFO)
    
    # ファイルハンドラ
    fh = logging.FileHandler(log_file, encoding='utf-8')
    fh.setLevel(logging.INFO)
    fh.setFormatter(JSTFormatter('%(asctime)s [%(levelname)s] %(message)s'))
    
    # コンソールハンドラ
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(JSTFormatter('%(asctime)s [%(levelname)s] %(message)s'))
    
    logger.addHandler(fh)
    logger.addHandler(ch)
    
    return logger


from datetime import timedelta, timezone


def load_config() -> Dict[str, Any]:
    """設定ファイル読み込み"""
    config_path = PROJECT_ROOT / "config" / "feature_calculator.yaml"
    template_path = PROJECT_ROOT / "config" / "feature_calculator.template.yaml"
    
    if not config_path.exists():
        if template_path.exists():
            raise FileNotFoundError(
                f"設定ファイルが見つかりません: {config_path}\n"
                f"テンプレートをコピーして作成してください:\n"
                f"  cp {template_path} {config_path}"
            )
        else:
            raise FileNotFoundError(f"設定ファイルとテンプレートが見つかりません: {config_path}")
    
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def load_raw_data(logger: logging.Logger) -> Dict[str, pd.DataFrame]:
    """
    生データ読み込み（第1段階: data_collector.h5）
    
    HDF5構造: /M1/data, /M5/data, ..., /ticks/data, /metadata
    
    Returns:
        Dict[str, pd.DataFrame]: {TF: DataFrame} の辞書
    """
    logger.info("🔄 第1段階データ読み込み開始")
    
    data_path = PROJECT_ROOT / "data" / "data_collector.h5"
    if not data_path.exists():
        raise FileNotFoundError(f"生データファイルが見つかりません: {data_path}")
    
    raw_data = {}
    with h5py.File(data_path, 'r') as f:
        # メタデータ確認
        if 'metadata' in f:
            metadata = json.loads(f['metadata'][()])
            logger.info(f"   入力ファイル: {data_path.name}")
            logger.info(f"   収集期間: {metadata.get('start_date')} ～ {metadata.get('end_date')}")
            logger.info(f"   通貨ペア: {metadata.get('symbol')}")
        
        # 各TFのバーデータ読み込み
        timeframes = ['M1', 'M5', 'M15', 'H1', 'H4']
        for tf in timeframes:
            if tf in f and 'data' in f[tf]:
                # データセットを読み込み
                data_array = f[tf]['data'][:]
                
                # カラム名定義（DATA_COLLECTOR_SPEC.mdに準拠）
                columns = ['time', 'open', 'high', 'low', 'close', 'tick_volume', 'spread', 'real_volume']
                
                # DataFrameに変換
                df = pd.DataFrame(data_array, columns=columns)
                
                # タイムスタンプをint64として取得し、datetime64に変換
                df['time'] = pd.to_datetime(df['time'].astype('int64'), unit='s', utc=True)
                
                raw_data[tf] = df
                logger.info(f"   {tf}: {len(df):,} 行読み込み完了")
            else:
                logger.warning(f"   {tf}: データが見つかりません（スキップ）")
    
    if not raw_data:
        raise ValueError("有効なタイムフレームデータが見つかりません")
    
    logger.info("✅ 生データ読み込み完了")
    return raw_data


def register_calculators(config: Dict[str, Any], logger: logging.Logger) -> FeatureCalculatorIntegrator:
    """計算器登録"""
    logger.info("🔄 計算器登録開始")
    
    integrator = FeatureCalculatorIntegrator(config)
    
    # Phase 1-1: 必須カテゴリ
    integrator.register_calculator(BasicMultiTFCalculator(config))
    integrator.register_calculator(SessionTimeCalculator(config))
    
    logger.info(f"   登録済み計算器: {len(integrator.calculators)} 個")
    for calc in integrator.calculators:
        logger.info(f"      - {calc.name}")
    
    logger.info("✅ 計算器登録完了")
    return integrator


def calculate_features(
    integrator: FeatureCalculatorIntegrator,
    raw_data: Dict[str, pd.DataFrame],
    logger: logging.Logger
) -> pd.DataFrame:
    """特徴量計算実行"""
    logger.info("🔄 特徴量計算開始")
    start_time = time.time()
    
    try:
        features = integrator.calculate(raw_data)
        
        elapsed = time.time() - start_time
        logger.info(f"   計算時間: {elapsed:.2f} 秒")
        logger.info(f"   出力shape: {features.shape}")
        logger.info(f"   特徴量数: {len(features.columns)} 列")
        
        # カテゴリ別統計
        category_info = integrator.get_category_info()
        logger.info("   カテゴリ別統計:")
        for cat_name, info in category_info.items():
            logger.info(f"      - {cat_name}: {info['count']} 列, "
                       f"{info['calculation_time_sec']:.2f}秒, "
                       f"NaN比率={info['nan_ratio']:.4f}")
        
        logger.info("✅ 特徴量計算完了")
        return features
    
    except Exception as e:
        logger.error(f"❌ 特徴量計算失敗: {e}", exc_info=True)
        raise


def save_features(
    features: pd.DataFrame,
    category_info: Dict[str, Any],
    config: Dict[str, Any],
    logger: logging.Logger,
    integrator: 'FeatureCalculatorIntegrator',
    labels: Dict[str, np.ndarray] = None
) -> Path:
    """特徴量をHDF5形式で保存（ラベルオプション）"""
    logger.info("🔄 特徴量保存開始")
    
    # 出力ファイルパス（既存時のみリネーム）
    base_output_file = PROJECT_ROOT / "data" / "feature_calculator.h5"
    
    if base_output_file.exists():
        # 既存ファイルの作成日時を取得してリネーム
        file_mtime = base_output_file.stat().st_mtime
        file_dt = datetime.fromtimestamp(file_mtime, tz=timezone(timedelta(hours=9)))
        timestamp_str = file_dt.strftime('%Y%m%d_%H%M%S')
        backup_file = PROJECT_ROOT / "data" / f"{timestamp_str}_feature_calculator.h5"
        base_output_file.rename(backup_file)
        logger.info(f"   既存ファイルリネーム: {backup_file.name}")
    
    # 新しいファイルは常にbase_output_fileパスで保存
    output_file = base_output_file
    
    # 現在時刻（メタデータ用）
    jst_now = datetime.now(timezone(timedelta(hours=9)))
    
    # numpy型をPython標準型に変換
    def convert_to_serializable(obj):
        """numpy型をJSON互換型に変換"""
        if isinstance(obj, (np.int64, np.int32, np.int16, np.int8)):
            return int(obj)
        elif isinstance(obj, (np.float64, np.float32, np.float16)):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, dict):
            return {k: convert_to_serializable(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [convert_to_serializable(item) for item in obj]
        return obj
    
    category_info_serializable = convert_to_serializable(category_info)
    config_serializable = convert_to_serializable(config)
    
    with h5py.File(output_file, 'w') as f:
        # 特徴量データ
        f.create_dataset('features', data=features.values, dtype='float32', compression='gzip')
        
        # 特徴量名
        feature_names = [name.encode('utf-8') for name in features.columns]
        f.create_dataset('feature_names', data=feature_names)
        
        # カテゴリ情報
        category_info_json = json.dumps(category_info_serializable, ensure_ascii=False).encode('utf-8')
        f.create_dataset('category_info', data=category_info_json)
        
        # メタデータ
        metadata = {
            'created_at': jst_now.isoformat(),
            'num_samples': int(len(features)),
            'num_features': int(len(features.columns)),
            'phase': 'feature_calculator',
            'config_hash': hashlib.sha256(json.dumps(config_serializable, sort_keys=True).encode()).hexdigest()[:8]
        }
        metadata_json = json.dumps(metadata, ensure_ascii=False).encode('utf-8')
        f.create_dataset('metadata', data=metadata_json)
        
        # ラベル保存（オプション）
        if labels is not None:
            logger.info("   📊 ラベル保存")
            labels_group = f.create_group('labels')
            labels_group.create_dataset('direction', data=labels['direction'], dtype='int64')
            labels_group.create_dataset('magnitude', data=labels['magnitude'], dtype='float32')
            logger.info(f"      Direction: {labels['direction'].shape}")
            logger.info(f"      Magnitude: {labels['magnitude'].shape}")
    
    logger.info(f"   出力ファイル: {output_file.name}")
    logger.info(f"   ファイルサイズ: {output_file.stat().st_size / 1024 / 1024:.2f} MB")
    logger.info("✅ 特徴量保存完了")
    
    return output_file


def generate_report(
    features: pd.DataFrame,
    category_info: Dict[str, Any],
    config: Dict[str, Any],
    output_file: Path,
    integrator: FeatureCalculatorIntegrator,
    logger: logging.Logger
):
    """レポート生成（JSON + Markdown）"""
    logger.info("🔄 レポート生成開始")
    
    jst_now = datetime.now(timezone(timedelta(hours=9)))
    
    # numpy型をPython標準型に変換
    def convert_to_serializable(obj):
        """numpy型をJSON互換型に変換"""
        if isinstance(obj, (np.int64, np.int32, np.int16, np.int8)):
            return int(obj)
        elif isinstance(obj, (np.float64, np.float32, np.float16)):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, dict):
            return {k: convert_to_serializable(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [convert_to_serializable(item) for item in obj]
        return obj
    
    category_info_serializable = convert_to_serializable(category_info)
    
    # カテゴリ別ファイルパス情報
    category_files = {}
    for cat_name in category_info.keys():
        cat_file = integrator.category_dir / f"{cat_name}.h5"
        if cat_file.exists():
            category_files[cat_name] = str(cat_file.relative_to(PROJECT_ROOT))
    
    # JSON レポート（既存時のみリネーム）
    base_json_path = PROJECT_ROOT / "data" / "feature_calculator_report.json"
    if base_json_path.exists():
        # 既存ファイルの作成日時を取得してリネーム
        json_mtime = base_json_path.stat().st_mtime
        json_dt = datetime.fromtimestamp(json_mtime, tz=timezone(timedelta(hours=9)))
        backup_json = PROJECT_ROOT / "data" / f"{json_dt.strftime('%Y%m%d_%H%M%S')}_feature_calculator_report.json"
        base_json_path.rename(backup_json)
        logger.info(f"   既存JSONレポートリネーム: {backup_json.name}")
    
    json_path = base_json_path
    
    report = {
        'created_at': jst_now.isoformat(),
        'phase': 'feature_calculator',
        'summary': {
            'num_samples': int(len(features)),
            'num_features': int(len(features.columns)),
            'output_file': output_file.name,
            'file_size_mb': round(output_file.stat().st_size / 1024 / 1024, 2)
        },
        'category_files': category_files,
        'categories': category_info_serializable,
        'feature_names': features.columns.tolist()
    }
    
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    logger.info(f"   JSONレポート: {json_path.name}")
    
    # Markdown レポート（既存時のみリネーム）
    base_md_path = PROJECT_ROOT / "data" / "feature_calculator_report.md"
    if base_md_path.exists():
        # 既存ファイルの作成日時を取得してリネーム
        md_mtime = base_md_path.stat().st_mtime
        md_dt = datetime.fromtimestamp(md_mtime, tz=timezone(timedelta(hours=9)))
        backup_md = PROJECT_ROOT / "data" / f"{md_dt.strftime('%Y%m%d_%H%M%S')}_feature_calculator_report.md"
        base_md_path.rename(backup_md)
        logger.info(f"   既存MDレポートリネーム: {backup_md.name}")
    
    md_path = base_md_path
    
    md_content = f"""# 特徴量計算レポート

## 概要
- **作成日時**: {jst_now.strftime('%Y-%m-%d %H:%M:%S JST')}
- **処理段階**: 第2段階: 特徴量計算
- **サンプル数**: {len(features):,}
- **特徴量数**: {len(features.columns)} 列
- **出力ファイル**: `{output_file.name}`
- **ファイルサイズ**: {output_file.stat().st_size / 1024 / 1024:.2f} MB

## カテゴリ別ファイル

"""
    
    for cat_name, cat_path in category_files.items():
        md_content += f"- **{cat_name}**: `{cat_path}`\n"
    
    md_content += """
## カテゴリ別統計

| カテゴリ | 特徴量数 | 計算時間 (秒) | NaN比率 | 状態 |
|---------|---------|--------------|---------|------|
"""
    
    for cat_name, info in category_info.items():
        status = "💾 キャッシュ" if info.get('cached', False) else "✅ 計算"
        md_content += f"| {cat_name} | {info['count']} | {info['calculation_time_sec']:.2f} | {info['nan_ratio']:.4f} | {status} |\n"
    
    md_content += f"""
## 特徴量一覧

合計 {len(features.columns)} 列:

"""
    
    for i, col in enumerate(features.columns, 1):
        md_content += f"{i}. `{col}`\n"
    
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(md_content)
    logger.info(f"   Markdownレポート: {md_path.name}")
    
    logger.info("✅ レポート生成完了")


def main():
    """メイン処理"""
    logger = setup_logging()
    logger.info("=" * 80)
    logger.info("🚀 特徴量計算開始")
    logger.info("=" * 80)
    
    try:
        # 設定読み込み
        config = load_config()
        logger.info("✅ 設定ファイル読み込み完了")
        
        # 生データ読み込み
        raw_data = load_raw_data(logger)
        
        # 計算器登録
        integrator = register_calculators(config, logger)
        
        # 特徴量計算
        features = calculate_features(integrator, raw_data, logger)
        
        # カテゴリ情報取得
        category_info = integrator.get_category_info()
        
        # ラベル生成（有効な場合）
        labels = None
        if config.get('label_generation', {}).get('enabled', False):
            logger.info("=" * 80)
            logger.info("🏷️  ラベル生成開始")
            logger.info("=" * 80)
            
            label_gen_config = config['label_generation']
            
            # キャッシュファイルパス
            cache_dir = PROJECT_ROOT / "data" / "feature_calculator"
            cache_dir.mkdir(exist_ok=True)
            cache_file = cache_dir / "labels.h5"
            
            # 再計算判定
            recalculate_categories = config.get('recalculate_categories')
            should_recalculate = recalculate_categories is None or 'labels' in recalculate_categories
            
            # キャッシュ確認
            if cache_file.exists() and not should_recalculate:
                # キャッシュ使用
                logger.info(f"💾 labels キャッシュ使用")
                
                try:
                    with h5py.File(cache_file, 'r') as f:
                        labels = {
                            'direction': f['direction'][:],
                            'magnitude': f['magnitude'][:]
                        }
                        metadata = json.loads(f['metadata'][()].decode('utf-8'))
                        
                        logger.info(f"   → Direction: {labels['direction'].shape}")
                        logger.info(f"   → Magnitude: {labels['magnitude'].shape}")
                        logger.info(f"   → 生成日時: {metadata.get('created_at', 'N/A')}")
                        
                except Exception as e:
                    logger.warning(f"⚠️  labels キャッシュ読み込み失敗: {e}")
                    logger.warning("   → 再計算します")
                    labels = None
            
            # キャッシュがない、または再計算が必要な場合
            if labels is None:
                # 既存キャッシュをリネーム
                if cache_file.exists():
                    from datetime import datetime, timezone, timedelta
                    file_mtime = cache_file.stat().st_mtime
                    file_dt = datetime.fromtimestamp(file_mtime, tz=timezone(timedelta(hours=9)))
                    timestamp_str = file_dt.strftime('%Y%m%d_%H%M%S')
                    backup_file = cache_dir / f"{timestamp_str}_labels.h5"
                    cache_file.rename(backup_file)
                    logger.info(f"💾 labels 既存キャッシュリネーム: {backup_file.name}")
                
                # ラベル生成
                label_generator = LabelGenerator(
                    k_spread=label_gen_config.get('k_spread', 1.0),
                    k_atr=label_gen_config.get('k_atr', 0.3),
                    spread_default=label_gen_config.get('spread_default', 1.2),
                    atr_period=label_gen_config.get('atr_period', 14),
                    pip_value=label_gen_config.get('pip_value', 0.01)
                )
                
                # 生データパス
                collector_path = PROJECT_ROOT / "data" / "data_collector.h5"
                
                # シーケンス数計算（prediction_horizon分引く）
                n_sequences = len(features) - label_gen_config.get('prediction_horizon', 36)
                if n_sequences <= 0:
                    logger.warning(f"⚠️  データ不足: features={len(features)}, horizon={label_gen_config.get('prediction_horizon', 36)}")
                    logger.warning("   ラベル生成をスキップします")
                else:
                    # ラベル生成
                    logger.info(f"🧮 labels 計算開始")
                    label_result = label_generator.generate_labels(
                        preprocessor_path=None,  # 未保存なのでNone
                        collector_path=collector_path,
                        prediction_horizon=label_gen_config.get('prediction_horizon', 36),
                        n_sequences=n_sequences
                    )
                    
                    # ラベル品質検証
                    label_generator.validate_labels(label_result, logger)
                    
                    # 有効サンプル確認
                    n_valid = np.sum(label_result['valid_mask'])
                    valid_ratio = n_valid / len(label_result['valid_mask'])
                    
                    min_valid_ratio = label_gen_config.get('min_valid_samples_ratio', 0.9)
                    if valid_ratio < min_valid_ratio:
                        logger.warning(f"⚠️  有効サンプル比率が低すぎます: {valid_ratio:.2%} < {min_valid_ratio:.0%}")
                        logger.warning("   ラベル生成をスキップします")
                    else:
                        # 有効サンプルのみ抽出
                        valid_mask = label_result['valid_mask']
                        labels = {
                            'direction': label_result['direction'][valid_mask],
                            'magnitude': label_result['magnitude'][valid_mask]
                        }
                        
                        # キャッシュ保存
                        try:
                            from datetime import datetime, timezone, timedelta
                            jst_now = datetime.now(timezone(timedelta(hours=9)))
                            
                            with h5py.File(cache_file, 'w') as f:
                                f.create_dataset('direction', data=labels['direction'], dtype='int64')
                                f.create_dataset('magnitude', data=labels['magnitude'], dtype='float32')
                                
                                # メタデータ
                                metadata = {
                                    'created_at': jst_now.isoformat(),
                                    'n_samples': len(labels['direction']),
                                    'prediction_horizon': label_gen_config.get('prediction_horizon', 36),
                                    'k_spread': label_gen_config.get('k_spread', 1.0),
                                    'k_atr': label_gen_config.get('k_atr', 0.3)
                                }
                                metadata_json = json.dumps(metadata, ensure_ascii=False).encode('utf-8')
                                f.create_dataset('metadata', data=metadata_json)
                            
                            logger.info(f"   💾 保存: labels.h5")
                        except Exception as e:
                            logger.warning(f"⚠️  labels キャッシュ保存失敗: {e}")
                        
                        # 特徴量も同様にフィルタ（最初のn_sequences行を使用）
                        features = features.iloc[:n_sequences][valid_mask].reset_index(drop=True)
                        
                        logger.info(f"   → {len(labels['direction'])}列生成")
                        logger.info(f"✅ ラベル生成完了: {len(labels['direction'])} サンプル")
        
        # 特徴量保存（ラベル含む）
        output_file = save_features(features, category_info, config, logger, integrator, labels)
        
        # レポート生成
        generate_report(features, category_info, config, output_file, integrator, logger)
        
        logger.info("=" * 80)
        logger.info("✅ 特徴量計算が正常に完了しました")
        logger.info("=" * 80)
        
    except Exception as e:
        logger.error("=" * 80)
        logger.error(f"❌ 特徴量計算が失敗しました: {e}")
        logger.error("=" * 80)
        raise


if __name__ == "__main__":
    main()
