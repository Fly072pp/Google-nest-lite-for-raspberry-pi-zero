# 🎙️ Assistant Vocal Edge AI — Raspberry Pi Zero 2W

Assistant vocal autonome fonctionnant entièrement en local. Aucune dépendance cloud.

```
┌─────────────────────────────────────────────────────────┐
│  Micro  →  Wake Word  →  STT  →  LLM  →  TTS  →  HP   │
│            Porcupine   Whisper  llama   Piper            │
└─────────────────────────────────────────────────────────┘
```

## 📋 Prérequis matériels

| Composant | Spécification |
|-----------|--------------|
| Carte     | Raspberry Pi Zero 2W |
| RAM       | 512 MB (intégrée) |
| Stockage  | MicroSD ≥ 16 GB (classe 10) |
| Audio     | Chapeau audio avec micro + HP (ex: ReSpeaker 2-Mic) |
| OS        | Raspberry Pi OS Bookworm **64-bit** |

## ⚡ Budget RAM estimé

| Composant | RAM utilisée |
|-----------|-------------|
| OS + Kernel | ~80 MB |
| Python + runtime | ~30 MB |
| Whisper tiny (int8) | ~60 MB |
| Porcupine wake word | ~5 MB |
| Qwen 2.5 0.5B Q4_K_M | ~310 MB |
| Buffers audio | ~5 MB |
| **Total estimé** | **~490 MB** |

> ⚠️ Activez le **swap** (au moins 256 MB) comme filet de sécurité :
> ```bash
> sudo dphys-swapfile swapoff
> sudo nano /etc/dphys-swapfile  # CONF_SWAPSIZE=256
> sudo dphys-swapfile setup && sudo dphys-swapfile swapon
> ```

## 🚀 Installation rapide

```bash
# 1. Clonez / copiez les fichiers sur votre Pi
git clone <votre-repo> ~/assistant && cd ~/assistant

# 2. Rendez le script exécutable
chmod +x install.sh

# 3. Lancez l'installation (nécessite ~15 min)
./install.sh
```

## 🔑 Configuration de la clé Picovoice

1. Créez un compte gratuit sur [console.picovoice.ai](https://console.picovoice.ai/)
2. Copiez votre **Access Key**
3. Exportez-la avant de lancer l'assistant :
   ```bash
   export PICOVOICE_ACCESS_KEY="votre_cle_ici"
   ```
   Ou éditez la variable dans `/etc/systemd/system/voice-assistant.service`.

## 🎛️ Utilisation

### Manuelle
```bash
source .venv/bin/activate

# Mode local (llama-cpp)
python assistant.py

# Mode API (Ollama sur un autre PC du réseau)
python assistant.py --llm-mode api

# Avec logs détaillés
python assistant.py --debug

# Changer de modèle GGUF
python assistant.py --model ~/models/mon-modele.gguf
```

### Service systemd (démarrage automatique)
```bash
sudo systemctl start voice-assistant
sudo systemctl status voice-assistant
sudo journalctl -u voice-assistant -f    # logs en temps réel
```

## 🗣️ Commandes vocales intégrées

| Commande | Action |
|----------|--------|
| `quelle heure est-il ?` | Donne l'heure sans appeler le LLM |
| `réinitialise` / `oublie tout` | Efface l'historique conversation |
| `au revoir` / `stop` / `arrête` | Éteint l'assistant proprement |

## 🔧 Configuration avancée (`assistant.py` → classe `Config`)

| Paramètre | Défaut | Description |
|-----------|--------|-------------|
| `WHISPER_MODEL` | `"tiny"` | `"tiny"` (~75 MB) ou `"base"` (~145 MB) |
| `WHISPER_LANGUAGE` | `"fr"` | `None` = détection automatique |
| `LLM_MODE` | `"local"` | `"local"` ou `"api"` |
| `LLM_MAX_TOKENS` | `150` | Longueur max de la réponse |
| `RECORD_SILENCE_THRESHOLD` | `0.015` | Sensibilité détection silence |
| `WAKE_WORD_SENSITIVITY` | `0.5` | Sensibilité mot d'éveil (0–1) |

## 🌐 Mode API (alternative au LLM local)

Si `llama-cpp` est trop lent, utilisez un PC du réseau avec Ollama :

```bash
# Sur le PC hôte :
ollama serve
ollama pull qwen2.5:0.5b

# Sur le Pi, lancez :
LLM_API_BASE="http://192.168.1.X:11434/v1" \
LLM_API_MODEL="qwen2.5:0.5b" \
python assistant.py --llm-mode api
```

## 📦 Modèles GGUF recommandés

| Modèle | Taille | Qualité | URL |
|--------|--------|---------|-----|
| Qwen 2.5 0.5B Q4_K_M | ~350 MB | ⭐⭐⭐ | [HuggingFace](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF) |
| TinyLlama 1.1B Q2_K | ~420 MB | ⭐⭐ | [HuggingFace](https://huggingface.co/TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF) |
| SmolLM2 135M Q8 | ~150 MB | ⭐ | [HuggingFace](https://huggingface.co/bartowski/SmolLM2-135M-Instruct-GGUF) |

## 🐛 Dépannage

**Pas d'audio détecté :**
```bash
arecord -l                          # liste les périphériques
arecord -D hw:1,0 -r 16000 -f S16_LE test.wav && aplay test.wav
```

**Erreur Porcupine "Invalid AccessKey" :**
Vérifiez que `PICOVOICE_ACCESS_KEY` est correctement défini.

**LLM trop lent (>10s) :**
Passez en mode API ou utilisez un modèle plus petit (SmolLM2 135M).

**Erreur PyAudio `ALSA lib` :**
Ajoutez votre utilisateur au groupe `audio` :
```bash
sudo usermod -aG audio $USER && newgrp audio
```
