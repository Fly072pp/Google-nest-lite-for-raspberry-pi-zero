#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Script de nettoyage — Assistant vocal Edge AI
# ─────────────────────────────────────────────────────────────────────────────
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"

echo "🧹 Nettoyage de l'environnement..."

# 1) Arrêter le service si présent
if systemctl is-active --quiet voice-assistant.service; then
    echo "  → Arrêt du service voice-assistant..."
    sudo systemctl stop voice-assistant.service || true
fi

# 2) Supprimer l'environnement virtuel
if [ -d "$VENV_DIR" ]; then
    echo "  → Suppression de l'environnement virtuel ($VENV_DIR)..."
    rm -rf "$VENV_DIR"
fi

# 3) Nettoyer les fichiers temporaires et caches
echo "  → Nettoyage des caches Python..."
find "$SCRIPT_DIR" -type d -name "__pycache__" -exec rm -rf {} +
rm -rf /tmp/piper.tar.gz /tmp/whisper-cache

# 4) Optionnel : Nettoyer les modèles (décommenter si nécessaire)
# echo "  → Suppression des modèles (Piper/Whisper)..."
# rm -rf "$HOME/models" "$HOME/piper" "$HOME/.cache/whisper"

echo "✅ Nettoyage terminé. Vous pouvez maintenant relancer install.sh"
