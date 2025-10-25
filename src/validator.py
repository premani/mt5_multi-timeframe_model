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


class SimpleLSTMModel(nn.Module):
    """シンプルLSTMモデル（学習時と同じ構造）"""
    
    def __init__(self, input_size: int, hidden_size: int = 128, num_layers: int = 2):
        super().__init__()
        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=0.2
        )
        
        # Direction head (3クラス: UP/DOWN/NEUTRAL)
        self.direction_head = nn.Sequential(
            nn.Linear(hidden_size, 64),
            nn.ReLU(),
            nn.Dropout(0.3),
            nn.Linear(64, 3)
        )
        
        # Magnitude head (価格幅回帰)
        self.magnitude_head = nn.Sequential(
            nn.Linear(hidden_size, 64),
            nn.ReLU(),
            nn.Dropout(0.3),
            nn.Linear(64, 1)
        )
    
    def forward(self, x: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        """
        Args:
            x: (batch, seq_len, features)
        
        Returns:
            direction_logits: (batch, 3)
            magnitude_pred: (batch, 1)
        """
        # LSTM
        lstm_out, _ = self.lstm(x)
        last_hidden = lstm_out[:, -1, :]
        
        # マルチタスク出力
        direction_logits = self.direction_head(last_hidden)
        magnitude_pred = self.magnitude_head(last_hidden)
        
        return direction_logits, magnitude_pred


class Validator:
    """検証処理クラス"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.logger = LoggingManager.get_logger(__name__)
        self.device = torch.device(config['batch']['device'] if torch.cuda.is_available() else 'cpu')
        
        self.logger.info(f"🎯 検証処理開始")
        self.logger.info(f"   デバイス: {self.device}")
    
    def load_data(self) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """前処理済みデータ読み込み"""
        input_path = Path(self.config['input']['preprocessed_file'])
        
        self.logger.info(f"📂 データ読み込み: {input_path.name}")
        
        with h5py.File(input_path, 'r') as f:
            # テストデータ取得
            test_sequences = f['test/sequences'][:]
            test_direction = f['test/labels/direction'][:]
            test_magnitude = f['test/labels/magnitude'][:]
            
            self.logger.info(f"   テストデータ: {test_sequences.shape}")
            self.logger.info(f"   Direction: {test_direction.shape}")
            self.logger.info(f"   Magnitude: {test_magnitude.shape}")
        
        # Tensorに変換
        test_sequences = torch.from_numpy(test_sequences).float()
        test_direction = torch.from_numpy(test_direction).long()
        test_magnitude = torch.from_numpy(test_magnitude).float()
        
        return test_sequences, test_direction, test_magnitude
    
    def load_model(self, input_size: int) -> SimpleLSTMModel:
        """学習済みモデル読み込み"""
        model_path = Path(self.config['input']['model_file'])
        
        self.logger.info(f"🔧 モデル読み込み: {model_path.name}")
        
        # モデル構築
        model = SimpleLSTMModel(
            input_size=input_size,
            hidden_size=128,
            num_layers=2
        )
        
        # 重み読み込み
        checkpoint = torch.load(model_path, map_location=self.device)
        model.load_state_dict(checkpoint['model_state_dict'])
        model.to(self.device)
        model.eval()
        
        self.logger.info(f"   エポック: {checkpoint['epoch']}")
        self.logger.info(f"   学習精度: {checkpoint.get('train_accuracy', 'N/A')}")
        
        return model
    
    def predict(
        self,
        model: SimpleLSTMModel,
        sequences: torch.Tensor,
        batch_size: int
    ) -> Tuple[np.ndarray, np.ndarray]:
        """推論実行"""
        self.logger.info(f"🔄 推論実行中...")
        
        all_direction_preds = []
        all_magnitude_preds = []
        
        with torch.no_grad():
            for i in range(0, len(sequences), batch_size):
                batch = sequences[i:i+batch_size].to(self.device)
                
                # 推論
                direction_logits, magnitude_pred = model(batch)
                
                # Direction: argmax
                direction_pred = torch.argmax(direction_logits, dim=1).cpu().numpy()
                all_direction_preds.append(direction_pred)
                
                # Magnitude
                magnitude_pred = magnitude_pred.squeeze().cpu().numpy()
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
        """レポート保存"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = output_dir / f"fx_lstm_model_{timestamp}_validation_report.json"
        
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        
        self.logger.info(f"💾 レポート保存: {report_path.name}")
    
    def run(self):
        """検証実行"""
        try:
            # データ読み込み
            test_sequences, test_direction, test_magnitude = self.load_data()
            
            # モデル読み込み
            input_size = test_sequences.shape[2]
            model = self.load_model(input_size)
            
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
            
            # レポート作成
            report = {
                'timestamp': datetime.now().isoformat(),
                'model_file': self.config['input']['model_file'],
                'preprocessed_file': self.config['input']['preprocessed_file'],
                'test_samples': len(test_sequences),
                'direction_metrics': direction_metrics,
                'magnitude_metrics': magnitude_metrics
            }
            
            # 保存
            output_dir = Path(self.config['output']['report_dir'])
            output_dir.mkdir(parents=True, exist_ok=True)
            self.save_report(report, output_dir)
            
            self.logger.info(f"✅ 検証完了")
            
        except Exception as e:
            self.logger.error(f"❌ 検証失敗: {e}", exc_info=True)
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
