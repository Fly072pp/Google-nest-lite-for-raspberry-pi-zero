# 🎙️ Assistant Vocal Edge AI — Raspberry Pi Zero 2W

Assistant vocal autonome fonctionnant entièrement en local. **100% gratuit, aucune clé API, aucun compte requis.**

```
┌─────────────────────────────────────────────────────────┐
│  Micro  →  Wake Word   →  STT  →  LLM  →  TTS  →  HP   │
│          openWakeWord   Whisper  llama   Piper            │
└─────────────────────────────────────────────────────────┘
```

## 📦 Stack technique

| Composant | Librairie | Licence |
|-----------|-----------|---------|
| Wake word | **openWakeWord** | Apache 2.0 — gratuit |
| STT | **faster-whisper** (tiny, int8) | MIT — gratuit |
| LLM | **llama-cpp-python** + SmolLM2 135M Q8 | Apache 2.0 — gratuit |
| TTS | **piper-tts** / pyttsx3 | MIT — gratuit |
| Audio | **PyAudio** | MIT — gratuit |

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
| openWakeWord | ~20 MB |
| SmolLM2 135M Q8 | ~150 MB |
| Buffers audio | ~5 MB |
| **Total estimé** | **~345 MB** ✅ |

> **170 MB de marge libre** — très confortable sur 512 MB. Swap optionnel mais recommandé (128 MB suffisent) :
> ```bash
> sudo dphys-swapfile swapoff
> sudo nano /etc/dphys-swapfile  # CONF_SWAPSIZE=128
> sudo dphys-swapfile setup && sudo dphys-swapfile swapon
> ```

## 🚀 Installation rapide

```bash
# 1. Copiez les fichiers sur votre Pi
git clone <votre-repo> ~/assistant && cd ~/assistant

# 2. Rendez le script exécutable
chmod +x install.sh

# 3. Lancez l'installation (~15 min, télécharge les modèles)
./install.sh
```

L'installation est entièrement automatique. **Aucune clé API à configurer.**

## 🎛️ Utilisation

### Manuelle
```bash
source .venv/bin/activate

# Lancement normal
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
| `WAKE_WORD` | `"hey_google"` | Mot d'éveil (`"hey_google"`, `"alexa"`, `"hey_jarvis"`…) |
| `WAKE_WORD_THRESHOLD` | `0.5` | Sensibilité [0–1] (plus élevé = moins de faux positifs) |
| `WHISPER_MODEL` | `"tiny"` | `"tiny"` (~60 MB) ou `"base"` (~145 MB) |
| `WHISPER_LANGUAGE` | `"fr"` | `None` = détection automatique |
| `LLM_MODE` | `"local"` | `"local"` ou `"api"` |
| `LLM_MAX_TOKENS` | `150` | Longueur max de la réponse |
| `RECORD_SILENCE_THRESHOLD` | `0.015` | Sensibilité détection silence |

## 🌐 Mode API (alternative au LLM local)

Si le LLM local est trop lent, utilisez un PC du réseau avec Ollama :

```bash
# Sur le PC hôte :
ollama serve
ollama pull smollm2:135m

# Sur le Pi :
LLM_API_BASE="http://192.168.1.X:11434/v1" \
LLM_API_MODEL="smollm2:135m" \
python assistant.py --llm-mode api
```

## 📦 Modèles GGUF recommandés

| Modèle | Taille | RAM | Qualité | URL |
|--------|--------|-----|---------|-----|
| **SmolLM2 135M Q8** ✅ | ~150 MB | ~150 MB | ⭐⭐ | [HuggingFace](https://huggingface.co/bartowski/SmolLM2-135M-Instruct-GGUF) |
| Qwen 2.5 0.5B Q4_K_M | ~350 MB | ~310 MB | ⭐⭐⭐ | [HuggingFace](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF) |
| TinyLlama 1.1B Q2_K | ~420 MB | ~380 MB | ⭐⭐ | [HuggingFace](https://huggingface.co/TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF) |

## 🐛 Dépannage

**Pas d'audio détecté :**
```bash
arecord -l                          # liste les périphériques
arecord -D hw:1,0 -r 16000 -f S16_LE test.wav && aplay test.wav
```

**openWakeWord ne détecte pas le mot d'éveil :**
Baissez le seuil dans `assistant.py` : `WAKE_WORD_THRESHOLD = 0.3`

**LLM trop lent (>10s) :**
Passez en mode API (`--llm-mode api`) ou réduisez `LLM_MAX_TOKENS`.

**Erreur PyAudio `ALSA lib` :**
```bash
sudo usermod -aG audio $USER && newgrp audio
```
