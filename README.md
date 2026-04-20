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
| Radio | **VLC (cvlc)** | GPL — gratuit |

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
git clone https://github.com/Fly072pp/Google-nest-lite-for-raspberry-pi-zero ~/assistant && cd ~/assistant

# 2. Rendez le script exécutable
chmod +x install.sh

# 3. Lancez l'installation (~15 min, télécharge les modèles)
./install.sh
```

L'installation est entièrement automatique. **Aucune clé API à configurer.**

## 🎛️ Utilisation

### 🌐 Panneau d'Administration Web (Nouveau !)
L'assistant intègre une magnifique interface de configuration web. Lancez l'assistant puis rendez-vous sur :
**[http://<IP_DU_RASPBERRY>:6524](http://<IP_DU_RASPBERRY>:6524)**

> *Lors de votre toute première connexion, il vous sera demandé de créer un nom d'utilisateur et un mot de passe pour sécuriser l'accès à ce panneau. Personne ne pourra reconfigurer votre maison sans ces identifiants !*

Vous pourrez y configurer le mot d'éveil, l'IA, les stations de **Radio** et vos identifiants Somfy TaHoma en quelques clics !

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
| `ouvre / ferme les volets [pièce]` | Contrôle les volets via Somfy TaHoma local |
| `lance le scénario [nom]` | Exécute un scénario Somfy local |
| `joue la radio [nom]` | Lance un flux radio configuré (VLC) |
| `arrête la radio / musique` | Stoppe la lecture en cours |
| `mets un minuteur de [X] min` | Lance un minuteur en arrière-plan |
| `réveille-moi à [H] heures [M]` | Programme une alarme ponctuelle |

## 🔧 Configuration avancée (`assistant.py` → classe `Config`)

| Paramètre | Défaut | Description |
|-----------|--------|-------------|
| `WAKE_WORD` | `"hey_google"` | Mot d'éveil (`"hey_google"`, `"alexa"`, `"hey_jarvis"`…) |
| `WAKE_WORD_THRESHOLD` | `0.5` | Sensibilité [0–1] (plus élevé = moins de faux positifs) |
| `WHISPER_MODEL` | `"tiny"` | `"tiny"` (~60 MB) ou `"base"` (~145 MB) |
| `WHISPER_LANGUAGE` | `"fr"` | `None` = détection automatique |
| `LLM_MODE` | `"local"` | `"local"` ou `"api"` |
| `LLM_MAX_TOKENS` | `150` | Longueur max de la réponse |
| `ENABLE_RADIO` | `false` | Active/Désactive le module Radio |
| `ENABLE_TIMERS` | `true` | Active/Désactive les minuteurs/alarmes |
| `RADIO_STATIONS` | *(JSON)* | Liste des flux radio (Nom: URL) |
| `RECORD_SILENCE_THRESHOLD` | `0.015` | Sensibilité détection silence |

### 🏠 Intégration Somfy TaHoma (Mode Développeur Local)
Pour contrôler vos équipements Somfy en 100% local sans cloud, activez le **Mode Développeur** depuis l'application TaHoma pour obtenir un token.
Définissez ces variables d'environnement (ou éditez la classe `Config` dans `assistant.py`) :
- `SOMFY_PIN` : Le code PIN de votre box (ex: `2001-1234-5678`)
- `SOMFY_TOKEN` : Le jeton Bearer généré
- `SOMFY_IP` : *(Optionnel)* L'adresse IP de votre box si `gateway-<pin>.local` ne fonctionne pas sur votre réseau.

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
