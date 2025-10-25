"""
trainer.py
Phase 0: 学習処理（最小構成）

目的: マルチタイムフレーム特徴量から価格予測モデルを学習
入力: data/preprocessor.h5（前処理済みシーケンス）
出力: models/trainer_model.pth（学習済みモデル）
"""

import os
import sys
import time
import json
import yaml
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Dict, Tuple, List

import numpy as np
import h5py
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
from sklearn.metrics import accuracy_score, precision_recall_fscore_support, mean_absolute_error, mean_squared_error, r2_score

# 相対インポート
sys.path.append(str(Path(__file__).parent))
from utils.logging_manager import LoggingManager


class MultiTFDataset(Dataset):
    """マルチタイムフレームデータセット"""
    
    def __init__(self, sequences: Dict[str, np.ndarray], labels: Dict[str, np.ndarray]):
        """
        Args:
            sequences: {TF名: (N, seq_len, features)}
            labels: {"direction": (N,), "magnitude": (N,)}
        """
        self.sequences = sequences
        self.labels = labels
        self.n_samples = len(labels["direction"])
        
    def __len__(self) -> int:
        return self.n_samples
    
    def __getitem__(self, idx: int) -> Tuple[Dict[str, torch.Tensor], Dict[str, torch.Tensor]]:
        # シーケンス取得
        seq_dict = {
            tf: torch.FloatTensor(seq[idx])
            for tf, seq in self.sequences.items()
        }
        
        # ラベル取得
        label_dict = {
            "direction": torch.LongTensor([self.labels["direction"][idx]])[0],
            "magnitude": torch.FloatTensor([self.labels["magnitude"][idx]])[0]
        }
        
        return seq_dict, label_dict


class TFEncoder(nn.Module):
    """タイムフレーム別エンコーダ（LSTM）"""
    
    def __init__(self, input_size: int, hidden_size: int, num_layers: int, dropout: float):
        super().__init__()
        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            dropout=dropout if num_layers > 1 else 0,
            batch_first=True
        )
        
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Args:
            x: (batch, seq_len, features)
        Returns:
            output: (batch, seq_len, hidden_size)
        """
        output, _ = self.lstm(x)
        return output


class AttentionFusion(nn.Module):
    """アテンション融合層"""
    
    def __init__(self, hidden_size: int, num_heads: int, dropout: float):
        super().__init__()
        self.attention = nn.MultiheadAttention(
            embed_dim=hidden_size,
            num_heads=num_heads,
            dropout=dropout,
            batch_first=True
        )
        self.norm = nn.LayerNorm(hidden_size)
        
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Args:
            x: (batch, seq_len, hidden_size)
        Returns:
            output: (batch, hidden_size)
        """
        # Self-attention
        attn_out, _ = self.attention(x, x, x)
        x = self.norm(x + attn_out)
        
        # 最終状態を取得（最後のタイムステップ）
        return x[:, -1, :]


class MultiTFModel(nn.Module):
    """マルチタイムフレームLSTMモデル（Phase 0: 超簡略版）"""
    
    def __init__(self, config: Dict):
        super().__init__()
        
        # 設定
        lstm_cfg = config["model"]["lstm"]
        
        hidden_size = lstm_cfg["hidden_size"]
        num_layers = lstm_cfg["num_layers"]
        dropout = lstm_cfg["dropout"]
        
        # TF別エンコーダ（特徴量数は動的に設定）
        self.encoders = nn.ModuleDict()
        
        # TF重み（Phase 0: 均等）
        self.tf_weights = nn.Parameter(torch.ones(5) / 5, requires_grad=False)
        
        # 出力ヘッド（シンプル化）
        self.direction_head = nn.Sequential(
            nn.Linear(hidden_size, 3),  # 直接出力
        )
        
        self.magnitude_head = nn.Sequential(
            nn.Linear(hidden_size, 1),  # 直接出力
            nn.Sigmoid()  # 0-1に正規化後、スケール
        )
        
        # エンコーダは初期化時に動的作成
        self._encoder_config = {
            "hidden_size": hidden_size,
            "num_layers": num_layers,
            "dropout": dropout
        }
        
    def add_encoder(self, tf_name: str, input_size: int):
        """TF別エンコーダを動的追加"""
        self.encoders[tf_name] = TFEncoder(
            input_size=input_size,
            hidden_size=self._encoder_config["hidden_size"],
            num_layers=self._encoder_config["num_layers"],
            dropout=self._encoder_config["dropout"]
        )
        # Xavier初期化
        for name, param in self.encoders[tf_name].named_parameters():
            if 'weight' in name:
                nn.init.xavier_uniform_(param)
            elif 'bias' in name:
                nn.init.zeros_(param)
        
    def forward(self, x: Dict[str, torch.Tensor]) -> Dict[str, torch.Tensor]:
        """
        Args:
            x: {TF名: (batch, seq_len, features)}
        Returns:
            output: {"direction": (batch, 3), "magnitude": (batch, 1)}
        """
        # TF別エンコード（最終隠れ状態のみ取得）
        encoded_states = []
        for tf_name in ["M1", "M5", "M15", "H1", "H4"]:  # 順序固定
            if tf_name in x and tf_name in self.encoders:
                seq = x[tf_name]
                # LSTMの全出力を取得
                encoded = self.encoders[tf_name](seq)  # (batch, seq_len, hidden)
                # 最終タイムステップのみ
                final_state = encoded[:, -1, :]  # (batch, hidden)
                encoded_states.append(final_state)
        
        # Phase 0: 単純な平均融合（重み付き）
        stacked = torch.stack(encoded_states, dim=0)  # (num_tf, batch, hidden)
        weights = self.tf_weights.view(-1, 1, 1)  # (num_tf, 1, 1)
        fused = (stacked * weights).sum(dim=0)  # (batch, hidden)
        
        # 出力
        direction_logits = self.direction_head(fused)  # (batch, 3)
        magnitude_raw = self.magnitude_head(fused)  # (batch, 1), range [0, 1]
        magnitude = 0.5 + magnitude_raw.squeeze(-1) * 4.5  # [0.5, 5.0] pips
        
        return {
            "direction": direction_logits,
            "magnitude": magnitude
        }


class Trainer:
    """学習管理クラス"""
    
    def __init__(self, config_path: str):
        """
        Args:
            config_path: 設定ファイルパス
        """
        # 設定読み込み
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)
        
        # ログ初期化
        self.logger = LoggingManager(
            name="trainer",
            log_dir="logs",
            level=self.config["logging"]["level"]
        )
        
        self.logger.info("🚀 学習処理開始（Phase 0）")
        self.logger.info(f"   設定ファイル: {config_path}")
        
        # デバイス設定
        self.device = self._setup_device()
        
        # 再現性設定
        self._setup_reproducibility()
        
        # データ読み込み
        self.data = self._load_data()
        
        # モデル構築
        self.model = self._build_model()
        
        # 損失関数・最適化設定
        self.criterion = self._setup_loss()
        self.optimizer = self._setup_optimizer()
        self.scheduler = self._setup_scheduler()
        
        # 学習状態
        self.best_val_loss = float("inf")
        self.patience_counter = 0
        
    def _setup_device(self) -> torch.device:
        """デバイス設定"""
        if self.config["device"]["use_cuda"] and torch.cuda.is_available():
            device_id = self.config["device"]["device_id"]
            device = torch.device(f"cuda:{device_id}")
            self.logger.info(f"   デバイス: CUDA (GPU {device_id})")
            self.logger.info(f"   GPU名: {torch.cuda.get_device_name(device_id)}")
        else:
            device = torch.device("cpu")
            self.logger.info("   デバイス: CPU")
        return device
    
    def _setup_reproducibility(self):
        """再現性設定"""
        seed = self.config["reproducibility"]["seed"]
        torch.manual_seed(seed)
        np.random.seed(seed)
        
        if self.config["reproducibility"]["deterministic"]:
            torch.backends.cudnn.deterministic = True
            torch.backends.cudnn.benchmark = False
            self.logger.info(f"   再現性: 有効（seed={seed}）")
    
    def _load_data(self) -> Dict:
        """データ読み込み"""
        self.logger.info("📂 データ読み込み")
        input_file = self.config["io"]["input_file"]
        
        with h5py.File(input_file, "r") as f:
            # メタデータ確認
            metadata = json.loads(f["metadata"][()])
            self.logger.info(f"   入力ファイル: {input_file}")
            self.logger.info(f"   生成日時: {metadata['processing_timestamp']}")
            self.logger.info(f"   特徴量数: {metadata['filter_stats']['initial']} → {metadata['filter_stats']['final']}")
            
            # シーケンスデータ読み込み
            sequences = {}
            for tf_name in ["M1", "M5", "M15", "H1", "H4"]:
                if f"sequences/{tf_name}" in f:
                    sequences[tf_name] = f[f"sequences/{tf_name}"][:]
                    self.logger.info(f"   {tf_name}: {sequences[tf_name].shape}")
            
            # 正規化パラメータ読み込み（推論時必要）
            scaler_params = json.loads(f["scaler_params"][()])
            
            # Phase 0: ダミーラベル生成（仮実装）
            # TODO: 実際のラベル生成ロジックを実装
            # 各TFのサンプル数が異なるため、最小数に揃える
            min_samples = min(len(seq) for seq in sequences.values())
            
            # シーケンスを最小サンプル数に揃える
            sequences = {tf: seq[:min_samples] for tf, seq in sequences.items()}
            
            n_samples = min_samples
            labels = {
                "direction": np.random.randint(0, 3, n_samples),  # UP/DOWN/NEUTRAL
                "magnitude": np.random.uniform(0.5, 5.0, n_samples)  # pips
            }
            self.logger.warning("⚠️  Phase 0: ダミーラベル使用中（実装待ち）")
            self.logger.info(f"   サンプル数を {min_samples} に統一")
        
        # データ分割
        train_data, val_data, test_data = self._split_data(sequences, labels)
        
        return {
            "train": train_data,
            "val": val_data,
            "test": test_data,
            "scaler_params": scaler_params,
            "metadata": metadata
        }
    
    def _split_data(self, sequences: Dict, labels: Dict) -> Tuple:
        """データ分割（時系列順序維持）"""
        n_samples = len(labels["direction"])
        train_ratio = self.config["data_split"]["train_ratio"]
        val_ratio = self.config["data_split"]["val_ratio"]
        
        train_end = int(n_samples * train_ratio)
        val_end = int(n_samples * (train_ratio + val_ratio))
        
        # Train
        train_sequences = {tf: seq[:train_end] for tf, seq in sequences.items()}
        train_labels = {k: v[:train_end] for k, v in labels.items()}
        
        # Val
        val_sequences = {tf: seq[train_end:val_end] for tf, seq in sequences.items()}
        val_labels = {k: v[train_end:val_end] for k, v in labels.items()}
        
        # Test
        test_sequences = {tf: seq[val_end:] for tf, seq in sequences.items()}
        test_labels = {k: v[val_end:] for k, v in labels.items()}
        
        self.logger.info(f"   Train: {len(train_labels['direction'])} samples")
        self.logger.info(f"   Val:   {len(val_labels['direction'])} samples")
        self.logger.info(f"   Test:  {len(test_labels['direction'])} samples")
        
        return (train_sequences, train_labels), (val_sequences, val_labels), (test_sequences, test_labels)
    
    def _build_model(self) -> nn.Module:
        """モデル構築"""
        self.logger.info("🏗️  モデル構築")
        
        model = MultiTFModel(self.config)
        
        # TF別エンコーダを動的追加
        train_sequences = self.data["train"][0]
        for tf_name, seq in train_sequences.items():
            input_size = seq.shape[2]  # 特徴量数
            model.add_encoder(tf_name, input_size)
            self.logger.info(f"   {tf_name} エンコーダ: input_size={input_size}")
        
        # デバイスへ移動
        model = model.to(self.device)
        
        # パラメータ数
        total_params = sum(p.numel() for p in model.parameters())
        trainable_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
        self.logger.info(f"   総パラメータ数: {total_params:,}")
        self.logger.info(f"   学習可能: {trainable_params:,}")
        
        return model
    
    def _setup_loss(self) -> Dict:
        """損失関数設定"""
        self.logger.info("⚙️  損失関数設定")
        
        # Direction: CrossEntropy
        direction_criterion = nn.CrossEntropyLoss()
        
        # Magnitude: Huber Loss
        huber_delta = self.config["loss"]["huber_delta"]
        magnitude_criterion = nn.HuberLoss(delta=huber_delta)
        
        self.logger.info(f"   Direction: CrossEntropyLoss")
        self.logger.info(f"   Magnitude: HuberLoss (δ={huber_delta})")
        
        return {
            "direction": direction_criterion,
            "magnitude": magnitude_criterion
        }
    
    def _setup_optimizer(self) -> optim.Optimizer:
        """最適化設定"""
        self.logger.info("⚙️  最適化設定")
        
        optimizer_name = self.config["training"]["optimizer"].lower()
        lr = self.config["training"]["learning_rate"]
        weight_decay = self.config["training"]["weight_decay"]
        
        if optimizer_name == "adam":
            optimizer = optim.Adam(
                self.model.parameters(),
                lr=lr,
                weight_decay=weight_decay
            )
        elif optimizer_name == "adamw":
            optimizer = optim.AdamW(
                self.model.parameters(),
                lr=lr,
                weight_decay=weight_decay
            )
        else:
            raise ValueError(f"未対応の最適化手法: {optimizer_name}")
        
        self.logger.info(f"   Optimizer: {optimizer_name.upper()}")
        self.logger.info(f"   Learning Rate: {lr}")
        self.logger.info(f"   Weight Decay: {weight_decay}")
        
        return optimizer
    
    def _setup_scheduler(self):
        """学習率スケジューラ設定"""
        if not self.config["training"]["lr_scheduler"]["enabled"]:
            return None
        
        self.logger.info("⚙️  学習率スケジューラ設定")
        
        scheduler_type = self.config["training"]["lr_scheduler"]["type"]
        
        if scheduler_type == "reduce_on_plateau":
            scheduler = optim.lr_scheduler.ReduceLROnPlateau(
                self.optimizer,
                mode="min",
                factor=self.config["training"]["lr_scheduler"]["factor"],
                patience=self.config["training"]["lr_scheduler"]["patience"]
            )
            self.logger.info(f"   Type: ReduceLROnPlateau")
        else:
            raise ValueError(f"未対応のスケジューラ: {scheduler_type}")
        
        return scheduler
    
    def train(self):
        """学習実行"""
        self.logger.info("🔄 学習開始")
        
        start_time = time.time()
        
        # データローダー作成
        train_dataset = MultiTFDataset(*self.data["train"])
        val_dataset = MultiTFDataset(*self.data["val"])
        
        train_loader = DataLoader(
            train_dataset,
            batch_size=self.config["training"]["batch_size"],
            shuffle=not self.config["data_split"]["shuffle"],  # Phase 0: 時系列順序維持
            num_workers=self.config["dataloader"]["num_workers"],
            pin_memory=self.config["dataloader"]["pin_memory"]
        )
        
        val_loader = DataLoader(
            val_dataset,
            batch_size=self.config["training"]["batch_size"],
            shuffle=False,
            num_workers=self.config["dataloader"]["num_workers"],
            pin_memory=self.config["dataloader"]["pin_memory"]
        )
        
        # エポックループ
        epochs = self.config["training"]["epochs"]
        for epoch in range(1, epochs + 1):
            self.logger.info(f"\n📊 Epoch {epoch}/{epochs}")
            
            # 学習
            train_loss, train_metrics = self._train_epoch(train_loader)
            
            # 検証
            val_loss, val_metrics = self._validate_epoch(val_loader)
            
            # ログ出力
            self._log_epoch_results(epoch, train_loss, train_metrics, val_loss, val_metrics)
            
            # 学習率調整
            if self.scheduler:
                self.scheduler.step(val_loss)
            
            # モデル保存（ベストのみ）
            if val_loss < self.best_val_loss:
                self.best_val_loss = val_loss
                self.patience_counter = 0
                self._save_model(epoch, val_loss, val_metrics)
            else:
                self.patience_counter += 1
            
            # 早期停止
            if self.patience_counter >= self.config["training"]["early_stopping_patience"]:
                self.logger.info(f"⏹️  早期停止（改善なし連続 {self.patience_counter} エポック）")
                break
        
        elapsed = time.time() - start_time
        self.logger.info(f"\n✅ 学習完了（{elapsed:.2f}秒）")
        
        # レポート生成
        self._generate_report()
    
    def _train_epoch(self, loader: DataLoader) -> Tuple[float, Dict]:
        """1エポック学習"""
        self.model.train()
        
        total_loss = 0.0
        all_direction_preds = []
        all_direction_labels = []
        all_magnitude_preds = []
        all_magnitude_labels = []
        
        loss_weights = self.config["loss"]["weights"]
        
        for batch_idx, (sequences, labels) in enumerate(loader):
            # デバイスへ移動
            sequences = {tf: seq.to(self.device) for tf, seq in sequences.items()}
            labels = {k: v.to(self.device) for k, v in labels.items()}
            
            # Forward
            outputs = self.model(sequences)
            
            # Loss計算
            direction_loss = self.criterion["direction"](outputs["direction"], labels["direction"])
            magnitude_loss = self.criterion["magnitude"](outputs["magnitude"], labels["magnitude"])
            
            loss = (
                loss_weights["direction"] * direction_loss +
                loss_weights["magnitude"] * magnitude_loss
            )
            
            # Backward
            self.optimizer.zero_grad()
            loss.backward()
            
            # 勾配クリッピング
            if self.config["training"]["gradient_clipping"]["enabled"]:
                torch.nn.utils.clip_grad_norm_(
                    self.model.parameters(),
                    self.config["training"]["gradient_clipping"]["max_norm"]
                )
            
            self.optimizer.step()
            
            # 統計
            total_loss += loss.item()
            
            direction_preds = outputs["direction"].argmax(dim=1).cpu().numpy()
            all_direction_preds.extend(direction_preds)
            all_direction_labels.extend(labels["direction"].cpu().numpy())
            
            all_magnitude_preds.extend(outputs["magnitude"].cpu().detach().numpy())
            all_magnitude_labels.extend(labels["magnitude"].cpu().numpy())
        
        # メトリクス計算
        avg_loss = total_loss / len(loader)
        
        # NaNチェック
        magnitude_preds_array = np.array(all_magnitude_preds)
        if np.isnan(magnitude_preds_array).any():
            self.logger.warning(f"   ⚠️  Magnitude予測にNaN検出: {np.isnan(magnitude_preds_array).sum()} / {len(magnitude_preds_array)}")
        metrics = self._compute_metrics(
            np.array(all_direction_preds),
            np.array(all_direction_labels),
            np.array(all_magnitude_preds),
            np.array(all_magnitude_labels)
        )
        
        return avg_loss, metrics
    
    def _validate_epoch(self, loader: DataLoader) -> Tuple[float, Dict]:
        """1エポック検証"""
        self.model.eval()
        
        total_loss = 0.0
        all_direction_preds = []
        all_direction_labels = []
        all_magnitude_preds = []
        all_magnitude_labels = []
        
        loss_weights = self.config["loss"]["weights"]
        
        with torch.no_grad():
            for sequences, labels in loader:
                # デバイスへ移動
                sequences = {tf: seq.to(self.device) for tf, seq in sequences.items()}
                labels = {k: v.to(self.device) for k, v in labels.items()}
                
                # Forward
                outputs = self.model(sequences)
                
                # Loss計算
                direction_loss = self.criterion["direction"](outputs["direction"], labels["direction"])
                magnitude_loss = self.criterion["magnitude"](outputs["magnitude"], labels["magnitude"])
                
                loss = (
                    loss_weights["direction"] * direction_loss +
                    loss_weights["magnitude"] * magnitude_loss
                )
                
                # 統計
                total_loss += loss.item()
                
                direction_preds = outputs["direction"].argmax(dim=1).cpu().numpy()
                all_direction_preds.extend(direction_preds)
                all_direction_labels.extend(labels["direction"].cpu().numpy())
                
                all_magnitude_preds.extend(outputs["magnitude"].cpu().numpy())
                all_magnitude_labels.extend(labels["magnitude"].cpu().numpy())
        
        # メトリクス計算
        avg_loss = total_loss / len(loader)
        metrics = self._compute_metrics(
            np.array(all_direction_preds),
            np.array(all_direction_labels),
            np.array(all_magnitude_preds),
            np.array(all_magnitude_labels)
        )
        
        return avg_loss, metrics
    
    def _compute_metrics(
        self,
        direction_preds: np.ndarray,
        direction_labels: np.ndarray,
        magnitude_preds: np.ndarray,
        magnitude_labels: np.ndarray
    ) -> Dict:
        """メトリクス計算"""
        # Direction
        direction_acc = accuracy_score(direction_labels, direction_preds)
        precision, recall, f1, _ = precision_recall_fscore_support(
            direction_labels, direction_preds, average="macro", zero_division=0
        )
        
        # Magnitude（NaN除外）
        nan_mask = ~np.isnan(magnitude_preds)
        if nan_mask.sum() > 0:
            clean_preds = magnitude_preds[nan_mask]
            clean_labels = magnitude_labels[nan_mask]
            
            mae = mean_absolute_error(clean_labels, clean_preds)
            rmse = np.sqrt(mean_squared_error(clean_labels, clean_preds))
            r2 = r2_score(clean_labels, clean_preds)
        else:
            # 全てNaNの場合
            mae = float('nan')
            rmse = float('nan')
            r2 = float('nan')
        
        return {
            "direction_accuracy": direction_acc,
            "direction_precision": precision,
            "direction_recall": recall,
            "direction_f1": f1,
            "magnitude_mae": mae,
            "magnitude_rmse": rmse,
            "magnitude_r2": r2
        }
    
    def _log_epoch_results(
        self,
        epoch: int,
        train_loss: float,
        train_metrics: Dict,
        val_loss: float,
        val_metrics: Dict
    ):
        """エポック結果ログ"""
        self.logger.info(f"   Train Loss: {train_loss:.4f}")
        self.logger.info(f"      Direction Acc: {train_metrics['direction_accuracy']:.4f}")
        self.logger.info(f"      Magnitude MAE: {train_metrics['magnitude_mae']:.4f} pips")
        
        self.logger.info(f"   Val Loss: {val_loss:.4f}")
        self.logger.info(f"      Direction Acc: {val_metrics['direction_accuracy']:.4f}")
        self.logger.info(f"      Magnitude MAE: {val_metrics['magnitude_mae']:.4f} pips")
        
        if val_loss < self.best_val_loss:
            self.logger.info(f"   💾 ベストモデル更新")
    
    def _save_model(self, epoch: int, val_loss: float, val_metrics: Dict):
        """モデル保存"""
        output_path = self.config["io"]["output_model"]
        
        # 保存データ
        save_dict = {
            "epoch": epoch,
            "model_state_dict": self.model.state_dict(),
            "optimizer_state_dict": self.optimizer.state_dict(),
            "val_loss": val_loss,
            "val_metrics": val_metrics,
            "config": self.config,
            "scaler_params": self.data["scaler_params"]
        }
        
        # 保存
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        torch.save(save_dict, output_path)
    
    def _generate_report(self):
        """レポート生成"""
        self.logger.info("📄 レポート生成")
        
        # TODO: 詳細レポート実装
        self.logger.info("   ⚠️  Phase 0: 簡易レポート（詳細実装待ち）")


def main():
    """メイン処理"""
    config_path = "config/trainer.yaml"
    
    if not os.path.exists(config_path):
        print(f"❌ 設定ファイルが見つかりません: {config_path}")
        print("   config/trainer.template.yaml をコピーしてください")
        return
    
    trainer = Trainer(config_path)
    trainer.train()


if __name__ == "__main__":
    main()
