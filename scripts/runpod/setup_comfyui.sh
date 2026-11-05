#!/usr/bin/env bash
# Set up ComfyUI with everything AutoExpress uses on a fresh GPU pod (RunPod or any Linux box with CUDA).
#
# Tested on RunPod with the image runpod/pytorch:2.8.0-py3.11-cuda12.8.1-cudnn-devel-ubuntu22.04
# (see docs/runpod.md). Run it on the pod, from anywhere:
#
#   curl -fsSL https://raw.githubusercontent.com/deepratna-awale/AutoExpress/main/scripts/runpod/setup_comfyui.sh | bash
#
# What it does:
#   1. Clones ComfyUI, ComfyUI-Impact-Pack and ComfyUI-Impact-Subpack (face inpainting), ComfyUI-See-through
#      (Live2D model kits) and starts ComfyUI on port 8188.
#   2. Downloads the face detector, an anime upscale model (small pictures for Live2D kits), Qwen-Image-Edit 2511 (expressions and poses) and Wan 2.2 image to video 14B
#      (animated sprites) with AutoExpress's own download commands.
#   3. Optionally a checkpoint for face inpainting (CHECKPOINT_URL).
#
# Settings (environment variables):
#   COMFYUI_DIR      where ComfyUI goes (default ~/ComfyUI, on the container disk). Set it to /workspace/ComfyUI
#                    to keep everything on a pod volume, which needs about 100 GB: RunPod's default 20 GB
#                    volume runs out of quota part way through the downloads.
#   AUTOEXPRESS_DIR  where AutoExpress goes (default next to ComfyUI)
#   AUTOEXPRESS_REF  branch or tag of AutoExpress to use (default main)
#   SKIP_QWEN=1      skip Qwen-Image-Edit (about 31 GB)
#   SKIP_WAN=1       skip Wan 2.2 (about 38 GB)
#   SKIP_SEETHROUGH=1  skip the See-through, DWPose, SAM 3.1 and Qwen3-VL nodes and models (about 22 GB, Live2D model kits)
#   CHECKPOINT_URL   a .safetensors checkpoint to put in models/checkpoints (for face inpainting)
#   HF_TOKEN         Hugging Face token, only needed when downloads are rate limited
#   COMFYUI_PORT     ComfyUI's port (default 8188)
set -euo pipefail

COMFYUI_DIR="${COMFYUI_DIR:-$HOME/ComfyUI}"
AUTOEXPRESS_DIR="${AUTOEXPRESS_DIR:-$(dirname "$COMFYUI_DIR")/AutoExpress}"
AUTOEXPRESS_REF="${AUTOEXPRESS_REF:-main}"
COMFYUI_PORT="${COMFYUI_PORT:-8188}"
PIP="python -m pip install -q"

echo "== ComfyUI in $COMFYUI_DIR"
if [ ! -d "$COMFYUI_DIR/.git" ]; then
  git clone -q https://github.com/comfyanonymous/ComfyUI "$COMFYUI_DIR"
fi
$PIP -r "$COMFYUI_DIR/requirements.txt"
for repo in ltdrdata/ComfyUI-Impact-Pack ltdrdata/ComfyUI-Impact-Subpack; do
  target="$COMFYUI_DIR/custom_nodes/${repo#*/}"
  [ -d "$target/.git" ] || git clone -q "https://github.com/$repo" "$target"
  if [ -f "$target/requirements.txt" ]; then $PIP -r "$target/requirements.txt"; fi
done

if [ "${SKIP_SEETHROUGH:-0}" != "1" ]; then
  echo "== ComfyUI-See-through (Live2D model kits)"
  target="$COMFYUI_DIR/custom_nodes/ComfyUI-See-through"
  [ -d "$target/.git" ] || git clone -q https://github.com/jtydhr88/ComfyUI-See-through "$target"
  $PIP -r "$target/requirements.txt"
  # Its models download on first use; fetch them now so the first kit doesn't wait.
  python -c "from huggingface_hub import snapshot_download as d; [d(r) for r in ('layerdifforg/seethroughv0.0.2_layerdiff3d', 'layerdifforg/seethroughv0.0.1_marigold')]" || true
  echo "== comfyui_controlnet_aux (DWPose: the puppet's joints)"
  target="$COMFYUI_DIR/custom_nodes/comfyui_controlnet_aux"
  [ -d "$target/.git" ] || git clone -q https://github.com/Fannovel16/comfyui_controlnet_aux "$target"
  $PIP -r "$target/requirements.txt" || true
  echo "== SAM 3.1 (finds the coat and each sleeve by name for the clothing layers)"
  [ -f "$COMFYUI_DIR/models/checkpoints/sam3.1_multiplex_fp16.safetensors" ] || \
    wget -q -O "$COMFYUI_DIR/models/checkpoints/sam3.1_multiplex_fp16.safetensors" https://huggingface.co/Comfy-Org/sam3.1/resolve/main/checkpoints/sam3.1_multiplex_fp16.safetensors || true
  echo "== Qwen3-VL 8B (names the clothes for SAM 3.1 when nothing else does)"
  [ -f "$COMFYUI_DIR/models/text_encoders/qwen3vl_8b_fp8_scaled.safetensors" ] || \
    wget -q -O "$COMFYUI_DIR/models/text_encoders/qwen3vl_8b_fp8_scaled.safetensors" https://huggingface.co/Comfy-Org/Qwen3-VL/resolve/main/text_encoders/qwen3vl_8b_fp8_scaled.safetensors || true
fi

echo "== AutoExpress ($AUTOEXPRESS_REF) in $AUTOEXPRESS_DIR"
if [ ! -d "$AUTOEXPRESS_DIR/.git" ]; then
  git clone -q --branch "$AUTOEXPRESS_REF" https://github.com/deepratna-awale/AutoExpress "$AUTOEXPRESS_DIR"
fi
$PIP requests pillow

echo "== Face detector"
mkdir -p "$COMFYUI_DIR/models/ultralytics/bbox"
[ -f "$COMFYUI_DIR/models/ultralytics/bbox/face_yolov8m.pt" ] || \
  wget -q -O "$COMFYUI_DIR/models/ultralytics/bbox/face_yolov8m.pt" https://huggingface.co/Bingsu/adetailer/resolve/main/face_yolov8m.pt

echo "== Upscale model (Live2D kits upscale small pictures before the layer split)"
mkdir -p "$COMFYUI_DIR/models/upscale_models"
[ -f "$COMFYUI_DIR/models/upscale_models/RealESRGAN_x4plus_anime_6B.pth" ] || \
  wget -q -O "$COMFYUI_DIR/models/upscale_models/RealESRGAN_x4plus_anime_6B.pth" \
    https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.2.4/RealESRGAN_x4plus_anime_6B.pth || true

cd "$AUTOEXPRESS_DIR"
if [ "${SKIP_QWEN:-0}" != "1" ]; then
  echo "== Qwen-Image-Edit 2511 (expressions, poses)"
  python -m autoexpress_core.instruction_edit download "$COMFYUI_DIR"
fi
if [ "${SKIP_WAN:-0}" != "1" ]; then
  echo "== Wan 2.2 image to video 14B (animated sprites)"
  python -m autoexpress_core.animation download "$COMFYUI_DIR"
fi
if [ -n "${CHECKPOINT_URL:-}" ]; then
  echo "== Checkpoint"
  wget -q --content-disposition -P "$COMFYUI_DIR/models/checkpoints" "$CHECKPOINT_URL"
fi

echo "== Starting ComfyUI on port $COMFYUI_PORT (log: $COMFYUI_DIR/comfyui.log)"
cd "$COMFYUI_DIR"
# Dynamic VRAM loading (ComfyUI's default since late 2026) leaves Qwen3-VL's weights unloaded when it
# generates text (TextGenerate fails: "linear(): argument 'weight' must be Tensor, not NoneType").
EXTRA_ARGS=""
python main.py --help 2>/dev/null | grep -q -- --disable-dynamic-vram && EXTRA_ARGS="--disable-dynamic-vram"
nohup python main.py --listen 0.0.0.0 --port "$COMFYUI_PORT" $EXTRA_ARGS > "$COMFYUI_DIR/comfyui.log" 2>&1 &
for _ in $(seq 1 120); do
  curl -sf "http://127.0.0.1:$COMFYUI_PORT/system_stats" > /dev/null && break
  sleep 2
done
echo "ComfyUI is up. On RunPod, connect AutoExpress to https://<pod id>-$COMFYUI_PORT.proxy.runpod.net"
