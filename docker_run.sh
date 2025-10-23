#!/bin/bash
# PyTorch FX LSTM Docker実行スクリプト

set -e

# プロジェクトルート（docker_run.shと同じディレクトリ）
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Docker設定
DOCKER_IMAGE="fx-lstm-pytorch"
CONTAINER_NAME="fx-lstm-$(date +%s)"

# GPU利用可能性チェック
echo "仮想環境起動確認中"

GPU_FLAG="--gpus=all"
if command -v nvidia-smi >/dev/null 2>&1; then
    echo "NVIDIA GPU検出 - 学習環境準備完了"

    # GPU詳細情報を取得・表示
    GPU_INFO=$(nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader,nounits 2>/dev/null | head -1)
    if [ -n "$GPU_INFO" ]; then
        GPU_NAME=$(echo "$GPU_INFO" | cut -d',' -f1 | xargs)
        GPU_MEMORY=$(echo "$GPU_INFO" | cut -d',' -f2 | xargs)
        DRIVER_VERSION=$(echo "$GPU_INFO" | cut -d',' -f3 | xargs)
        echo "   GPU: $GPU_NAME"
        echo "   VRAM: ${GPU_MEMORY}MB"
        echo "   Driver: v$DRIVER_VERSION"
    fi
else
    echo "NVIDIA GPU未検出 - 本プロジェクトはGPU必須のため中断します" >&2
    exit 1
fi

# 引数チェック
if [ $# -eq 0 ]; then
    echo "使用方法:"
    echo "$0 <command>               # コマンド実行"
    echo "$0 bash                    # インタラクティブモード"
    echo "$0 python3 <script>        # Python実行"
    exit 1
fi

# インタラクティブモードの判定
if [[ "$1" == "bash" || "$1" == "sh" ]]; then
    INTERACTIVE_FLAG="-it"
else
    INTERACTIVE_FLAG=""
fi
REMOVE_FLAG="--rm"  # 常に自動削除

echo "Docker実行開始..."
echo "   プロジェクトルート: $PROJECT_ROOT"
echo "   実行コマンド: $*"

echo ""
# Docker実行（.envファイルから環境変数を読み込み）
docker run $REMOVE_FLAG $INTERACTIVE_FLAG $GPU_FLAG \
    --name "$CONTAINER_NAME" \
    --shm-size=8g \
    --ipc=host \
    -v "$PROJECT_ROOT:/workspace" \
    -w /workspace \
    --env-file "$PROJECT_ROOT/.env" \
    -e LOCAL_UID="$(id -u)" \
    -e LOCAL_GID="$(id -g)" \
    -e LOCAL_USER="${USER:-app}" \
    -e LOCAL_GROUP="$(id -gn)" \
    -e PYTHONPATH=/workspace:/workspace/src \
    "$DOCKER_IMAGE" "$@"

echo "Docker実行完了"
