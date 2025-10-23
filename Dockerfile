# RTX 5000シリーズ (Blackwell) LSTM FX Prediction Model
FROM nvidia/cuda:12.8.0-cudnn-runtime-ubuntu22.04

# メタデータ（再現性/追跡用）
LABEL org.opencontainers.image.source="https://github.com/premani/mt5_lstm-model" \
      org.opencontainers.image.title="fx-lstm-pytorch" \
      org.opencontainers.image.description="FX LSTM Encoder-Decoder + Multi-Head Attention - PyTorch 2.8.0 cu128" \
      org.opencontainers.image.version="2.8.0-cu128" \
      org.pytorch.version="2.8.0" \
      org.pytorch.cuda="12.8" \
      org.python.version="3.10+" \
      maintainer="project-maintainers"

# 必要なパッケージのインストール（tzdata, git含む）
ARG DEBIAN_FRONTEND=noninteractive
ENV TZ=Asia/Tokyo
RUN apt-get update && \
    apt-get install -y --no-install-recommends tzdata python3-pip gosu git && \
    ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone && \
    dpkg-reconfigure -f noninteractive tzdata && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# CUDA 12.8 用 安定版 PyTorch 2.8.0 (cu128) をインストール
# バージョン対応目安: torch 2.8.0 / torchvision 0.23.0 / torchaudio 2.8.0
RUN pip install --no-cache-dir \
    torch==2.8.0 \
    torchvision==0.23.0 \
    torchaudio==2.8.0 \
    --index-url https://download.pytorch.org/whl/cu128

# 作業ディレクトリ
WORKDIR /workspace

# PyTorch関連の追加パッケージをインストール
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    pip cache purge

# ビルド時バージョン記録（GPUはビルドフェーズでは未接続想定）
RUN python3 - <<'PY' \
    | tee /TORCH_BUILD_INFO.json
import torch, json, os
info = {
    'torch_version': torch.__version__,
    'cuda_compiled': torch.version.cuda,
    'cuda_available_runtime': torch.cuda.is_available(),
    'cudnn_enabled': torch.backends.cudnn.enabled,
    'python_version': f"{os.sys.version_info.major}.{os.sys.version_info.minor}.{os.sys.version_info.micro}"
}
print(json.dumps(info, ensure_ascii=False))
PY

# エントリポイントを配置（ホストUID/GIDに合わせてユーザー作成・切替）
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["python3"]
