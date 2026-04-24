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
    alsa-utils sox bluez bluez-tools \
    git wget curl cmake \
    libopenblas-dev          # accélération BLAS pour llama-cpp

# ── 1.1) Groupes utilisateur ───────────────────────────────────────────────
sudo usermod -aG bluetooth $USER
sudo usermod -aG audio $USER

# ── 2) Environnement virtuel Python ───────────────────────────────────────
echo "[2/7] Création de l'environnement virtuel Python…"
python3 -m venv "$VENV_DIR"
# shellcheck source=/dev/null
source "$VENV_DIR/bin/activate"

pip install --upgrade pip wheel

# ── 3) Bibliothèques Python ────────────────────────────────────────────────
echo "[3/6] Installation des bibliothèques Python (requirements.txt)…"

# Fix pour Raspberry Pi : onnxruntime est plus stable que tflite-runtime sur ARM
pip install onnxruntime
# Installer openwakeword sans dépendances pour éviter l'erreur tflite-runtime
pip install openwakeword --no-deps

pip install tflite-runtime

pip install -r requirements.txt

# ── 4) Piper TTS (binaire ARM64 + voix française) ─────────────────────────
echo "[4/5] Installation de Piper TTS…"
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

# ── 7) Configuration Somfy TaHoma (Optionnel) ──────────────────────────────
echo ""
echo "[7/9] Configuration Somfy TaHoma (Optionnel)…"
SOMFY_ENV=""
read -p "Voulez-vous configurer l'intégration locale Somfy TaHoma ? (o/N) : " config_somfy
if [[ "$config_somfy" =~ ^[oO]$ ]]; then
    read -p "Entrez le PIN de la box (ex: 2001-1234-5678) : " somfy_pin
    read -p "Entrez le Token Développeur : " somfy_token
    read -p "Entrez l'IP de la box (laisser vide pour la détection auto) : " somfy_ip
    
    SOMFY_ENV="Environment=\"SOMFY_PIN=$somfy_pin\"\nEnvironment=\"SOMFY_TOKEN=$somfy_token\""
    if [ ! -z "$somfy_ip" ]; then
        SOMFY_ENV="$SOMFY_ENV\nEnvironment=\"SOMFY_IP=$somfy_ip\""
    fi
fi

# ── 8) Modules Optionnels (Radio, Minuteurs) ──────────────────────────────
echo ""
echo "[5/5] Configuration des modules optionnels…"
ENABLE_RADIO=false
ENABLE_TIMERS=true

read -p "Voulez-vous activer la radio internet ? (o/N) : " config_radio
if [[ "$config_radio" =~ ^[oO]$ ]]; then
    ENABLE_RADIO=true
    echo "  → Installation de VLC pour la radio…"
    sudo apt-get install -y vlc-bin vlc-plugin-base --no-install-recommends
fi

read -p "Voulez-vous activer les minuteurs et alarmes ? (O/n) : " config_timers
if [[ "$config_timers" =~ ^[nN]$ ]]; then
    ENABLE_TIMERS=false
fi

# Création/Mise à jour de config.json
if [ ! -f "config.json" ]; then
    echo "{\"ENABLE_RADIO\": $ENABLE_RADIO, \"ENABLE_TIMERS\": $ENABLE_TIMERS}" > config.json
else
    # Simple python one-liner to update existing config.json
    python3 -c "import json; c=json.load(open('config.json')); c.update({'ENABLE_RADIO': $ENABLE_RADIO, 'ENABLE_TIMERS': $ENABLE_TIMERS}); json.dump(c, open('config.json', 'w'), indent=4)"
fi

# ── 9) Service systemd ─────────────────────────────────────────────────────
echo "[6/6] Création du service systemd…"
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
$(echo -e $SOMFY_ENV)
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
