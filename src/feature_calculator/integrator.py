"""
特徴量計算統合クラス

各カテゴリ計算器を管理し、特徴量計算を統合的に実行
"""

from typing import Dict, List
import pandas as pd
import numpy as np
from pathlib import Path
import logging
import time
import h5py
import json

from .base_calculator import BaseCalculator

logger = logging.getLogger(__name__)


class FeatureCalculatorIntegrator:
    """
    特徴量計算の統合クラス
    
    役割:
    - 各カテゴリ計算器の実行管理
    - カテゴリ別ファイル管理（キャッシュ・増分更新）
    - 段階的検証の実施
    - 統合HDF5出力
    """
    
    def __init__(self, config: dict, project_root: Path = None):
        """
        初期化
        
        Args:
            config: 設定辞書
            project_root: プロジェクトルートパス
        """
        self.config = config
        self.calculators: List[BaseCalculator] = []
        self.category_results = {}
        
        # プロジェクトルート設定
        if project_root is None:
            project_root = Path(__file__).resolve().parent.parent.parent
        self.project_root = project_root
        
        # カテゴリ別ファイル保存ディレクトリ
        self.category_dir = self.project_root / "data" / "feature_calculator"
        self.category_dir.mkdir(parents=True, exist_ok=True)
    
    def register_calculator(self, calculator: BaseCalculator):
        """
        計算器を登録
        
        Args:
            calculator: 計算器インスタンス
        """
        category_name = calculator.name
        
        # カテゴリが有効化されているか確認
        if not self.config['enable_categories'].get(category_name, False):
            logger.info(f"⏭️  {category_name}: 無効化されているためスキップ")
            return
        
        self.calculators.append(calculator)
        logger.info(f"✅ {category_name} を登録")
    
    def calculate(
        self, 
        raw_data: Dict[str, pd.DataFrame]
    ) -> pd.DataFrame:
        """
        全カテゴリの特徴量を計算
        
        フロー:
        1. 各カテゴリをキャッシュ確認
        2. キャッシュあり → 読み込み
        3. キャッシュなし → 計算 → カテゴリ別ファイル保存
        4. 全カテゴリを統合
        
        Args:
            raw_data: マルチTF生データ
                {
                    'M1': DataFrame(N, 6),
                    'M5': DataFrame(N, 6),
                    'M15': DataFrame(N, 6),
                    'H1': DataFrame(N, 6),
                    'H4': DataFrame(N, 6),
                }
        
        Returns:
            DataFrame(N, K): K列の統合特徴量
        """
        all_features = []
        
        # 再計算対象カテゴリ（設定で指定、なければ全て再計算）
        recalculate_categories = self.config.get('recalculate_categories', None)
        
        for calculator in self.calculators:
            category_name = calculator.name
            category_file = self.category_dir / f"{category_name}.h5"
            
            # 既存ファイルがあればリネーム（仕様書: 既存ファイルがある場合、JST日時プレフィックス付きでリネーム退避）
            if category_file.exists():
                from datetime import datetime, timezone, timedelta
                # 既存ファイルの作成日時を取得
                file_mtime = category_file.stat().st_mtime
                file_dt = datetime.fromtimestamp(file_mtime, tz=timezone(timedelta(hours=9)))
                timestamp_str = file_dt.strftime('%Y%m%d_%H%M%S')
                backup_file = self.category_dir / f"{timestamp_str}_{category_name}.h5"
                category_file.rename(backup_file)
                logger.info(f"💾 {category_name} 既存キャッシュリネーム: {backup_file.name}")
                
                # キャッシュ利用判定
                use_cache = recalculate_categories is not None and category_name not in recalculate_categories
                
                if use_cache:
                    # キャッシュから読み込み
                    logger.info(f"💾 {category_name} キャッシュ使用")
                    
                    start_time = time.time()
                    
                    try:
                        with h5py.File(backup_file, 'r') as f:
                            data_array = f['features'][:]
                            feature_names_bytes = f['feature_names'][:]
                            feature_names = [name.decode('utf-8') for name in feature_names_bytes]
                            cat_features = pd.DataFrame(data_array, columns=feature_names)
                            metadata = json.loads(f['metadata'][()].decode('utf-8'))
                        
                        calc_time = time.time() - start_time
                        self.category_results[category_name] = {
                            'count': len(cat_features.columns),
                            'calculation_time_sec': round(calc_time, 2),
                            'columns': cat_features.columns.tolist(),
                            'nan_ratio': metadata.get('nan_ratio', 0.0),
                            'inf_count': metadata.get('inf_count', 0),
                            'cached': True
                        }
                        
                        all_features.append(cat_features)
                        logger.info(f"   → {len(cat_features.columns)}列読み込み ({calc_time:.1f}秒)")
                        continue
                        
                    except Exception as e:
                        logger.warning(f"⚠️  {category_name} キャッシュ読み込み失敗: {e}\n   → 再計算します")
            
            # 計算実行
            logger.info(f"🧮 {category_name} 計算開始")
            
            start_time = time.time()
            
            try:
                # カテゴリ特徴量計算
                cat_features = calculator.compute(raw_data)
                
                # 検証
                validation = calculator.validate(cat_features)
                
                if not validation['valid']:
                    logger.warning(
                        f"⚠️  {category_name} 検証失敗: "
                        f"{', '.join(validation['warnings'])}"
                    )
                
                # 結果を記録
                calc_time = time.time() - start_time
                self.category_results[category_name] = {
                    'count': len(cat_features.columns),
                    'calculation_time_sec': round(calc_time, 2),
                    'columns': cat_features.columns.tolist(),
                    'nan_ratio': validation['nan_ratio'],
                    'inf_count': validation['inf_count'],
                    'cached': False
                }
                
                # カテゴリ別HDF5保存
                self._save_category_features(
                    category_name,
                    cat_features,
                    validation
                )
                
                all_features.append(cat_features)
                
                logger.info(
                    f"   → {len(cat_features.columns)}列生成 "
                    f"({calc_time:.1f}秒)"
                )
                
            except Exception as e:
                logger.error(f"❌ {category_name} 計算失敗: {e}")
                raise
        
        # 全特徴量を結合
        if not all_features:
            raise ValueError("計算された特徴量がありません")
        
        features = pd.concat(all_features, axis=1)
        
        logger.info(f"✅ 特徴量計算完了: {len(features.columns)}列")
        
        return features
    
    def get_category_info(self) -> Dict:
        """
        カテゴリ別情報を取得
        
        Returns:
            dict: カテゴリ別統計情報
        """
        return self.category_results
    
    def _save_category_features(
        self,
        category_name: str,
        features: pd.DataFrame,
        validation: Dict
    ):
        """
        カテゴリ特徴量を個別HDF5ファイルに保存
        
        Args:
            category_name: カテゴリ名
            features: 特徴量DataFrame
            validation: 検証結果
        """
        category_file = self.category_dir / f"{category_name}.h5"
        
        # リネームは calculate() で実行済み
        try:
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
            
            # HDF5保存（h5py形式）
            with h5py.File(category_file, 'w') as f:
                # 特徴量データ
                f.create_dataset(
                    'features',
                    data=features.values,
                    dtype='float32',
                    compression='gzip',
                    compression_opts=5
                )
                
                # 特徴量名
                feature_names = [name.encode('utf-8') for name in features.columns]
                f.create_dataset('feature_names', data=feature_names)
                
                # メタデータ
                metadata = {
                    'category_name': category_name,
                    'num_features': len(features.columns),
                    'num_samples': len(features),
                    'nan_ratio': validation['nan_ratio'],
                    'inf_count': validation['inf_count'],
                    'feature_names': features.columns.tolist()
                }
                metadata_serializable = convert_to_serializable(metadata)
                metadata_json = json.dumps(metadata_serializable, ensure_ascii=False).encode('utf-8')
                f.create_dataset('metadata', data=metadata_json)
            
            logger.info(f"   💾 保存: {category_file.name}")
            
        except Exception as e:
            logger.warning(f"⚠️  {category_name} 保存失敗: {e}")
            # 保存失敗しても続行（キャッシュなしで次回再計算）
