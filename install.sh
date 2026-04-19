#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Script d'installation — Assistant vocal Edge AI
# Testé sur Raspberry Pi OS Bookworm (64-bit) / Pi Zero 2W
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
MODELS_DIR="$HOME/models"
PIPER_DIR="$HOME/piper"

echo "════════════════════════════════════════════════"
echo "  Installation de l'assistant vocal Edge AI"
echo "  $(uname -m) — $(uname -r)"
echo "════════════════════════════════════════════════"

# ── 1) Dépendances système ─────────────────────────────────────────────────
echo "[1/7] Installation des paquets système…"
sudo apt-get update -qq
sudo apt-get install -y \
    python3-pip python3-venv python3-dev \
    portaudio19-dev libsndfile1 \
    espeak-ng espeak-ng-data \
    alsa-utils sox \
    git wget curl cmake \
    libopenblas-dev          # accélération BLAS pour llama-cpp

# ── 2) Environnement virtuel Python ───────────────────────────────────────
echo "[2/7] Création de l'environnement virtuel Python…"
python3 -m venv "$VENV_DIR"
# shellcheck source=/dev/null
source "$VENV_DIR/bin/activate"

pip install --upgrade pip wheel

# ── 3) Bibliothèques Python ────────────────────────────────────────────────
echo "[3/7] Installation de PyAudio, Numpy, openwakeword, faster-whisper…"
pip install pyaudio numpy openwakeword faster-whisper psutil openai pyttsx3

# ── 4) llama-cpp-python (compilé avec OpenBLAS) ───────────────────────────
echo "[4/7] Compilation de llama-cpp-python (OpenBLAS, ~10 min)…"
CMAKE_ARGS="-DGGML_BLAS=ON -DGGML_BLAS_VENDOR=OpenBLAS" \
    pip install --no-cache-dir llama-cpp-python

# ── 5) Téléchargement du modèle LLM (SmolLM2 135M Q8 ~150 MB) ────────────
echo "[5/7] Téléchargement du modèle LLM SmolLM2 135M Q8…"
mkdir -p "$MODELS_DIR"
MODEL_FILE="$MODELS_DIR/SmolLM2-135M-Instruct-Q8_0.gguf"
if [ ! -f "$MODEL_FILE" ]; then
    wget -q --show-progress \
        "https://huggingface.co/bartowski/SmolLM2-135M-Instruct-GGUF/resolve/main/SmolLM2-135M-Instruct-Q8_0.gguf" \
        -O "$MODEL_FILE"
else
    echo "  → Modèle déjà présent, skip."
fi

# ── 6) Piper TTS (binaire ARM64 + voix française) ─────────────────────────
echo "[6/7] Installation de Piper TTS…"
mkdir -p "$PIPER_DIR"
PIPER_VERSION="2023.11.14-2"
PIPER_ARCHIVE="piper_linux_aarch64.tar.gz"

if [ ! -f "$PIPER_DIR/piper" ]; then
    wget -q --show-progress \
        "https://github.com/rhasspy/piper/releases/download/${PIPER_VERSION}/${PIPER_ARCHIVE}" \
        -O /tmp/piper.tar.gz
    tar -xzf /tmp/piper.tar.gz -C "$PIPER_DIR" --strip-components=1
    rm /tmp/piper.tar.gz
fi

# Voix française (upmc-medium ~60 MB)
PIPER_VOICE="fr_FR-upmc-medium"
if [ ! -f "$PIPER_DIR/${PIPER_VOICE}.onnx" ]; then
    wget -q --show-progress \
        "https://huggingface.co/rhasspy/piper-voices/resolve/main/fr/fr_FR/upmc/medium/${PIPER_VOICE}.onnx" \
        -O "$PIPER_DIR/${PIPER_VOICE}.onnx"
    wget -q \
        "https://huggingface.co/rhasspy/piper-voices/resolve/main/fr/fr_FR/upmc/medium/${PIPER_VOICE}.onnx.json" \
        -O "$PIPER_DIR/${PIPER_VOICE}.onnx.json"
fi

# ── 7) Service systemd ─────────────────────────────────────────────────────
echo "[7/7] Création du service systemd…"
SERVICE_FILE="/etc/systemd/system/voice-assistant.service"
sudo tee "$SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=Assistant Vocal Edge AI
After=sound.target network.target
Wants=sound.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$SCRIPT_DIR
Environment="PYTHONUNBUFFERED=1"
ExecStart=$VENV_DIR/bin/python $SCRIPT_DIR/assistant.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable voice-assistant.service

echo ""
echo "════════════════════════════════════════════════"
echo "  ✅ Installation terminée !"
echo ""
echo "  Avant de démarrer :"
echo "  (aucune clé API nécessaire — openWakeWord est 100% gratuit)"
echo ""
echo "  1. Testez manuellement :"
echo "     source $VENV_DIR/bin/activate"
echo "     python $SCRIPT_DIR/assistant.py --debug"
echo ""
echo "  3. Démarrez le service :"
echo "     sudo systemctl start voice-assistant"
echo "     sudo journalctl -u voice-assistant -f"
echo "════════════════════════════════════════════════"
