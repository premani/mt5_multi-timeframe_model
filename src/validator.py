#!/usr/bin/env python3
"""
検証処理（第5段階）

目的:
    学習済みモデルの性能評価

入力:
    - preprocessed.h5: 前処理済みデータ（テストセット）
    - training.pt: 学習済みモデル

出力:
    - validation_report.json: 評価指標レポート
    - confusion_matrix.png: 混同行列（オプション）

実行:
    bash ./docker_run.sh python3 src/validator.py
"""

import sys
from pathlib import Path
import yaml
import h5py
import torch
import torch.nn as nn
import numpy as np
import json
from datetime import datetime
from typing import Dict, Tuple, Any
from sklearn.metrics import (
    accuracy_score, precision_score, recall_score, f1_score,
    mean_absolute_error, mean_squared_error, r2_score,
    confusion_matrix, classification_report
)

# プロジェクトルート追加
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.utils.logging_manager import LoggingManager

# trainer.pyからモデル定義をインポート
import importlib.util
trainer_spec = importlib.util.spec_from_file_location("trainer_module", Path(__file__).parent / "trainer.py")
trainer_module = importlib.util.module_from_spec(trainer_spec)
trainer_spec.loader.exec_module(trainer_module)
MultiTFModel = trainer_module.MultiTFModel
TFEncoder = trainer_module.TFEncoder


class Validator:
    """検証処理クラス"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        
        # ロガー初期化
        self.logger = LoggingManager(
            name="validator",
            log_dir="logs",
            level=config.get("logging", {}).get("level", "INFO")
        )
        
        self.device = torch.device(config['batch']['device'] if torch.cuda.is_available() else 'cpu')
        
        self.logger.info(f"🎯 検証処理開始")
        self.logger.info(f"   デバイス: {self.device}")
    
    def load_data(self) -> Tuple[Dict[str, torch.Tensor], torch.Tensor, torch.Tensor]:
        """前処理済みデータ読み込み（全データから検証用を抽出）"""
        input_path = Path(self.config['input']['preprocessed_file'])
        
        self.logger.info(f"📂 データ読み込み: {input_path.name}")
        
        sequences = {}
        with h5py.File(input_path, 'r') as f:
            # 全シーケンス読み込み（マルチTF）
            for tf in f['sequences'].keys():
                sequences[tf] = f[f'sequences/{tf}'][:]
                self.logger.info(f"   {tf}: {sequences[tf].shape}")
            
            # ラベル読み込み
            all_direction = f['labels/direction'][:]
            all_magnitude = f['labels/magnitude'][:]
            
            self.logger.info(f"   Direction: {all_direction.shape}")
            self.logger.info(f"   Magnitude: {all_magnitude.shape}")
        
        # 最小サンプル数でアライメント（全TFで共通の長さ）
        min_samples = min(len(all_direction), len(all_magnitude), 
                         min(seq.shape[0] for seq in sequences.values()))
        
        # 検証用データ分割（後半20%を使用）
        test_size = int(min_samples * 0.2)
        test_start = min_samples - test_size
        
        self.logger.info(f"   アライメント後: {min_samples} サンプル")
        self.logger.info(f"   検証データ: {test_start}〜{min_samples} ({test_size} サンプル)")
        
        # テストデータ抽出
        test_sequences = {
            tf: torch.from_numpy(seq[test_start:min_samples]).float()
            for tf, seq in sequences.items()
        }
        test_direction = torch.from_numpy(all_direction[test_start:min_samples]).long()
        test_magnitude = torch.from_numpy(all_magnitude[test_start:min_samples]).float()
        
        return test_sequences, test_direction, test_magnitude
    
    def load_model(self) -> MultiTFModel:
        """学習済みモデル読み込み"""
        model_path = Path(self.config['input']['model_file'])
        
        self.logger.info(f"🔧 モデル読み込み: {model_path.name}")
        
        # チェックポイント読み込み（PyTorch 2.8対応）
        checkpoint = torch.load(model_path, map_location=self.device, weights_only=False)
        
        # モデル構築（設定から復元）
        model_config = checkpoint.get('config', self.config)
        model = MultiTFModel(model_config)
        
        # エンコーダを動的追加（チェックポイントから構造を復元）
        state_dict = checkpoint['model_state_dict']
        for key in state_dict.keys():
            if key.startswith('encoders.'):
                tf_name = key.split('.')[1]
                # 最初の重みからinput_sizeを推定
                weight_key = f'encoders.{tf_name}.lstm.weight_ih_l0'
                if weight_key in state_dict:
                    input_size = state_dict[weight_key].shape[1]
                    if tf_name not in model.encoders:
                        model.add_encoder(tf_name, input_size)
        
        # 重み読み込み
        model.load_state_dict(state_dict)
        model.to(self.device)
        model.eval()
        
        self.logger.info(f"   エポック: {checkpoint['epoch']}")
        self.logger.info(f"   学習精度: {checkpoint.get('train_accuracy', 'N/A')}")
        
        return model
    
    def predict(
        self,
        model: MultiTFModel,
        sequences: Dict[str, torch.Tensor],
        batch_size: int
    ) -> Tuple[np.ndarray, np.ndarray]:
        """推論実行"""
        self.logger.info(f"🔄 推論実行中...")
        
        # サンプル数取得（全TF共通）
        n_samples = len(next(iter(sequences.values())))
        
        all_direction_preds = []
        all_magnitude_preds = []
        
        with torch.no_grad():
            for i in range(0, n_samples, batch_size):
                # バッチ作成
                batch = {
                    tf: seq[i:i+batch_size].to(self.device)
                    for tf, seq in sequences.items()
                }
                
                # 推論
                output = model(batch)
                direction_logits = output["direction"]
                magnitude_pred = output["magnitude"]
                
                # Direction: argmax
                direction_pred = torch.argmax(direction_logits, dim=1).cpu().numpy()
                all_direction_preds.append(direction_pred)
                
                # Magnitude
                magnitude_pred = magnitude_pred.cpu().numpy()
                all_magnitude_preds.append(magnitude_pred)
        
        # 結合
        direction_preds = np.concatenate(all_direction_preds)
        magnitude_preds = np.concatenate(all_magnitude_preds)
        
        self.logger.info(f"   推論完了: {len(direction_preds)} サンプル")
        
        return direction_preds, magnitude_preds
    
    def evaluate_direction(
        self,
        y_true: np.ndarray,
        y_pred: np.ndarray
    ) -> Dict[str, Any]:
        """方向予測評価"""
        self.logger.info(f"📊 方向予測評価")
        
        # 全体精度
        accuracy = accuracy_score(y_true, y_pred)
        self.logger.info(f"   Accuracy: {accuracy:.4f}")
        
        # クラス別指標
        precision = precision_score(y_true, y_pred, average=None, zero_division=0)
        recall = recall_score(y_true, y_pred, average=None, zero_division=0)
        f1 = f1_score(y_true, y_pred, average=None, zero_division=0)
        
        class_names = ['DOWN', 'NEUTRAL', 'UP']
        for i, name in enumerate(class_names):
            self.logger.info(f"   {name:8s}: Precision={precision[i]:.4f}, Recall={recall[i]:.4f}, F1={f1[i]:.4f}")
        
        # 混同行列
        cm = confusion_matrix(y_true, y_pred)
        self.logger.info(f"   混同行列:\n{cm}")
        
        # 分類レポート
        report = classification_report(y_true, y_pred, target_names=class_names, zero_division=0)
        
        return {
            'accuracy': float(accuracy),
            'precision': precision.tolist(),
            'recall': recall.tolist(),
            'f1_score': f1.tolist(),
            'confusion_matrix': cm.tolist(),
            'classification_report': report
        }
    
    def evaluate_magnitude(
        self,
        y_true: np.ndarray,
        y_pred: np.ndarray
    ) -> Dict[str, float]:
        """価格幅予測評価"""
        self.logger.info(f"📊 価格幅予測評価")
        
        # MAE
        mae = mean_absolute_error(y_true, y_pred)
        self.logger.info(f"   MAE: {mae:.4f} pips")
        
        # RMSE
        rmse = np.sqrt(mean_squared_error(y_true, y_pred))
        self.logger.info(f"   RMSE: {rmse:.4f} pips")
        
        # R²
        r2 = r2_score(y_true, y_pred)
        self.logger.info(f"   R²: {r2:.4f}")
        
        return {
            'mae': float(mae),
            'rmse': float(rmse),
            'r2': float(r2)
        }
    
    def save_report(self, report: Dict[str, Any], output_dir: Path):
        """レポート保存（JSON + Markdown）
        
        命名規約:
        - 基本: validator_report.json / validator_report.md
        - 既存ファイルがある場合: 既存ファイルを validator_YYYYMMDD_HHMMSS_report.* にリネーム
        """
        import os
        
        # 基本ファイル名（タイムスタンプなし）
        json_path = output_dir / "validator_report.json"
        md_path = output_dir / "validator_report.md"
        
        # 既存ファイルのバックアップ
        for path in [json_path, md_path]:
            if path.exists():
                # 既存ファイルの変更時刻を取得
                mtime = os.path.getmtime(path)
                timestamp = datetime.fromtimestamp(mtime).strftime("%Y%m%d_%H%M%S")
                
                # リネーム先
                backup_name = f"validator_{timestamp}_report{path.suffix}"
                backup_path = path.parent / backup_name
                
                # リネーム
                path.rename(backup_path)
                self.logger.info(f"📦 既存ファイルをバックアップ: {backup_name}")
        
        # JSONレポート保存
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        self.logger.info(f"💾 JSONレポート保存: {json_path.name}")
        
        # Markdownレポート保存
        self._save_markdown_report(report, md_path)
        self.logger.info(f"💾 Markdownレポート保存: {md_path.name}")
    
    def _save_markdown_report(self, report: Dict[str, Any], md_path: Path):
        """Markdownレポート生成"""
        lines = [
            "# 検証レポート",
            "",
            f"**検証日時**: {report['timestamp']}",
            f"**モデル**: {Path(report['model_file']).name}",
            f"**データ**: {Path(report['preprocessed_file']).name}",
            f"**テストサンプル数**: {report['test_samples']:,}",
            "",
            "---",
            "",
            "## 📊 クラス分布",
            "",
            "| クラス | サンプル数 | 割合 |",
            "|--------|-----------|------|"
        ]
        
        # クラス分布
        class_names = ['DOWN', 'NEUTRAL', 'UP']
        for name in class_names:
            key = name.lower()
            count = report['class_distribution'][key]['count']
            ratio = report['class_distribution'][key]['ratio']
            lines.append(f"| {name:8s} | {count:6,d} | {ratio:6.2%} |")
        
        lines.extend([
            "",
            "---",
            "",
            "## 🎯 方向予測評価",
            "",
            f"**Accuracy**: {report['direction_metrics']['accuracy']:.4f}",
            "",
            "### クラス別指標",
            "",
            "| クラス | Precision | Recall | F1-Score |",
            "|--------|-----------|--------|----------|"
        ])
        
        for i, name in enumerate(class_names):
            precision = report['direction_metrics']['precision'][i]
            recall = report['direction_metrics']['recall'][i]
            f1 = report['direction_metrics']['f1_score'][i]
            lines.append(f"| {name:8s} | {precision:.4f} | {recall:.4f} | {f1:.4f} |")
        
        lines.extend([
            "",
            "### 混同行列",
            "",
            "|         | DOWN | NEUTRAL | UP   |",
            "|---------|------|---------|------|"
        ])
        
        cm = report['direction_metrics']['confusion_matrix']
        for i, name in enumerate(class_names):
            lines.append(f"| {name:7s} | {cm[i][0]:4d} | {cm[i][1]:7d} | {cm[i][2]:4d} |")
        
        lines.extend([
            "",
            "---",
            "",
            "## 🔍 予測信頼度",
            "",
            f"- **平均信頼度**: {report['confidence_stats']['mean']:.4f}",
            f"- **中央値**: {report['confidence_stats']['median']:.4f}",
            f"- **標準偏差**: {report['confidence_stats']['std']:.4f}",
            f"- **範囲**: [{report['confidence_stats']['min']:.4f}, {report['confidence_stats']['max']:.4f}]",
            f"- **四分位範囲**: [{report['confidence_stats']['q25']:.4f}, {report['confidence_stats']['q75']:.4f}]",
            "",
            "---",
            "",
            "## 📊 価格幅予測評価",
            "",
            f"### 誤差指標",
            "",
            f"- **MAE**: {report['magnitude_metrics']['mae']:.4f} pips",
            f"- **RMSE**: {report['magnitude_metrics']['rmse']:.4f} pips",
            f"- **R²**: {report['magnitude_metrics']['r2']:.4f}",
            "",
            "### 実際値の分布",
            "",
            f"- **平均**: {report['magnitude_distribution']['true']['mean']:.4f} pips",
            f"- **中央値**: {report['magnitude_distribution']['true']['median']:.4f} pips",
            f"- **標準偏差**: {report['magnitude_distribution']['true']['std']:.4f} pips",
            f"- **範囲**: [{report['magnitude_distribution']['true']['min']:.4f}, {report['magnitude_distribution']['true']['max']:.4f}] pips",
            "",
            "### 予測値の分布",
            "",
            f"- **平均**: {report['magnitude_distribution']['pred']['mean']:.4f} pips",
            f"- **中央値**: {report['magnitude_distribution']['pred']['median']:.4f} pips",
            f"- **標準偏差**: {report['magnitude_distribution']['pred']['std']:.4f} pips",
            f"- **範囲**: [{report['magnitude_distribution']['pred']['min']:.4f}, {report['magnitude_distribution']['pred']['max']:.4f}] pips",
            ""
        ])
        
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
    
    def analyze_class_distribution(self, y_true: np.ndarray) -> Dict[str, Any]:
        """クラス分布分析"""
        self.logger.info(f"📊 クラス分布分析")
        
        class_names = ['DOWN', 'NEUTRAL', 'UP']
        total = len(y_true)
        distribution = {}
        
        for i, name in enumerate(class_names):
            count = np.sum(y_true == i)
            ratio = count / total
            distribution[name.lower()] = {
                'count': int(count),
                'ratio': float(ratio)
            }
            self.logger.info(f"   {name:8s}: {count:5d} ({ratio:6.2%})")
        
        return distribution
    
    def analyze_prediction_confidence(
        self,
        model: MultiTFModel,
        sequences: Dict[str, torch.Tensor],
        batch_size: int
    ) -> Dict[str, Any]:
        """予測信頼度分析"""
        self.logger.info(f"🔍 予測信頼度分析")
        
        n_samples = len(next(iter(sequences.values())))
        all_probs = []
        
        with torch.no_grad():
            for i in range(0, n_samples, batch_size):
                batch = {
                    tf: seq[i:i+batch_size].to(self.device)
                    for tf, seq in sequences.items()
                }
                
                output = model(batch)
                direction_logits = output["direction"]
                probs = torch.softmax(direction_logits, dim=1)
                all_probs.append(probs.cpu().numpy())
        
        all_probs = np.concatenate(all_probs)
        max_probs = np.max(all_probs, axis=1)
        
        confidence_stats = {
            'mean': float(np.mean(max_probs)),
            'median': float(np.median(max_probs)),
            'std': float(np.std(max_probs)),
            'min': float(np.min(max_probs)),
            'max': float(np.max(max_probs)),
            'q25': float(np.percentile(max_probs, 25)),
            'q75': float(np.percentile(max_probs, 75))
        }
        
        self.logger.info(f"   平均信頼度: {confidence_stats['mean']:.4f}")
        self.logger.info(f"   中央値: {confidence_stats['median']:.4f}")
        self.logger.info(f"   標準偏差: {confidence_stats['std']:.4f}")
        
        return confidence_stats
    
    def analyze_magnitude_distribution(
        self,
        y_true: np.ndarray,
        y_pred: np.ndarray
    ) -> Dict[str, Any]:
        """価格幅分布分析"""
        self.logger.info(f"📊 価格幅分布分析")
        
        true_stats = {
            'mean': float(np.mean(y_true)),
            'median': float(np.median(y_true)),
            'std': float(np.std(y_true)),
            'min': float(np.min(y_true)),
            'max': float(np.max(y_true)),
            'q25': float(np.percentile(y_true, 25)),
            'q75': float(np.percentile(y_true, 75))
        }
        
        pred_stats = {
            'mean': float(np.mean(y_pred)),
            'median': float(np.median(y_pred)),
            'std': float(np.std(y_pred)),
            'min': float(np.min(y_pred)),
            'max': float(np.max(y_pred)),
            'q25': float(np.percentile(y_pred, 25)),
            'q75': float(np.percentile(y_pred, 75))
        }
        
        self.logger.info(f"   実際値 - 平均: {true_stats['mean']:.4f} pips, 範囲: [{true_stats['min']:.4f}, {true_stats['max']:.4f}]")
        self.logger.info(f"   予測値 - 平均: {pred_stats['mean']:.4f} pips, 範囲: [{pred_stats['min']:.4f}, {pred_stats['max']:.4f}]")
        
        return {
            'true': true_stats,
            'pred': pred_stats
        }
    
    def run(self):
        """検証実行"""
        try:
            # データ読み込み
            test_sequences, test_direction, test_magnitude = self.load_data()
            
            # サンプル数取得（マルチTF対応）
            n_samples = len(test_direction)
            
            # モデル読み込み
            model = self.load_model()
            
            # 推論
            batch_size = self.config['batch']['size']
            direction_preds, magnitude_preds = self.predict(model, test_sequences, batch_size)
            
            # 評価
            direction_metrics = self.evaluate_direction(
                test_direction.numpy(),
                direction_preds
            )
            
            magnitude_metrics = self.evaluate_magnitude(
                test_magnitude.numpy(),
                magnitude_preds
            )
            
            # 追加分析
            class_distribution = self.analyze_class_distribution(test_direction.numpy())
            confidence_stats = self.analyze_prediction_confidence(model, test_sequences, batch_size)
            magnitude_distribution = self.analyze_magnitude_distribution(
                test_magnitude.numpy(),
                magnitude_preds
            )
            
            # レポート作成
            report = {
                'timestamp': datetime.now().isoformat(),
                'model_file': self.config['input']['model_file'],
                'preprocessed_file': self.config['input']['preprocessed_file'],
                'test_samples': n_samples,
                'class_distribution': class_distribution,
                'direction_metrics': direction_metrics,
                'magnitude_metrics': magnitude_metrics,
                'confidence_stats': confidence_stats,
                'magnitude_distribution': magnitude_distribution
            }
            
            # 保存
            output_dir = Path(self.config['output']['report_dir'])
            output_dir.mkdir(parents=True, exist_ok=True)
            self.save_report(report, output_dir)
            
            self.logger.info(f"✅ 検証完了")
            
        except Exception as e:
            self.logger.error(f"❌ 検証失敗: {e}")
            raise


def main():
    """メイン処理"""
    # 設定読み込み
    config_path = Path("config/validator.yaml")
    if not config_path.exists():
        print(f"❌ 設定ファイルが見つかりません: {config_path}")
        print(f"   テンプレートをコピーしてください:")
        print(f"   cp config/validator.template.yaml config/validator.yaml")
        sys.exit(1)
    
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    # 検証実行
    validator = Validator(config)
    validator.run()


if __name__ == "__main__":
    main()
