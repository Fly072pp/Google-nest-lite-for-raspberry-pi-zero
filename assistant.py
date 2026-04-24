#!/usr/bin/env python3
"""
Assistant vocal Edge AI pour Raspberry Pi Zero 2W
Wake word → STT (Faster-Whisper) → LLM (llama-cpp / API) → TTS (piper/pyttsx3)
Optimisé pour 512 MB de RAM.

Détection du mot d'éveil : openWakeWord (100% gratuit, open-source, ONNX)
LLM : SmolLM2 135M Q8 (~150 MB RAM)
"""

import os
import gc
import time
import wave
import struct
import logging
import tempfile
import argparse
import threading
from pathlib import Path
from typing import Optional, Generator

import numpy as np
import pyaudio
import requests
import urllib3
import subprocess
import re
import datetime
import json

# Désactiver les avertissements concernant le certificat SSL auto-signé de la passerelle locale
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ─────────────────────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("assistant")


# ─────────────────────────────────────────────────────────────────────────────
# Configuration centrale (modifiez ici selon votre setup)
# ─────────────────────────────────────────────────────────────────────────────
class Config:
    # ── Audio ──────────────────────────────────────────────────────────────
    SAMPLE_RATE: int = 16_000          # Hz – requis par Whisper & openWakeWord
    CHANNELS: int = 1
    FORMAT = pyaudio.paInt16
    CHUNK_SIZE: int = 1280             # frames par buffer (openWakeWord exige 1280)
    RECORD_SILENCE_THRESHOLD: float = 0.015   # RMS pour détecter le silence
    RECORD_SILENCE_DURATION: float = 1.5      # secondes de silence avant arrêt
    MAX_RECORD_SECONDS: float = 15.0           # limite de sécurité

    # ── Wake word (openWakeWord — 100% gratuit, aucune clé requise) ────────
    # Mots disponibles nativement : "hey_jarvis", "alexa", "hey_mycroft",
    #   "hey_rhasspy", "ok_nabu". ("hey_google" nécessite un téléchargement manuel)
    # Sensibilité [0.0 – 1.0] : plus élevée = plus de faux positifs
    WAKE_WORD: str = "alexa"
    WAKE_WORD_THRESHOLD: float = 0.5

    # ── STT (Faster-Whisper) ───────────────────────────────────────────────
    WHISPER_MODEL: str = "tiny"        # "tiny" (~75 MB) ou "tiny.en" (anglais seul)
    WHISPER_LANGUAGE: str = "fr"       # None = détection automatique
    WHISPER_DEVICE: str = "cpu"
    WHISPER_COMPUTE_TYPE: str = "int8" # int8 = moins de RAM, plus rapide sur CPU

    # ── LLM ───────────────────────────────────────────────────────────────
    # Mode: "local" (llama-cpp) ou "api" (OpenAI-compatible, ex: Ollama local)
    LLM_MODE: str = "api"

    # Paramètres llama-cpp (mode "local")
    # SmolLM2 135M Q8 : ~150 MB RAM, très rapide sur CPU ARM
    # https://huggingface.co/bartowski/SmolLM2-135M-Instruct-GGUF
    LLM_MODEL_PATH: str = str(Path.home() / "models" / "SmolLM2-135M-Instruct-Q8_0.gguf")
    LLM_N_CTX: int = 512              # contexte réduit pour économiser la RAM
    LLM_N_THREADS: int = 4            # Zero 2W a 4 cœurs
    LLM_N_GPU_LAYERS: int = 0         # pas de GPU sur Zero 2W
    LLM_MAX_TOKENS: int = 150         # réponses courtes
    LLM_TEMPERATURE: float = 0.7

    # Paramètres API (mode "api")
    LLM_API_BASE: str = os.getenv("LLM_API_BASE", "http://localhost:11434/v1")
    LLM_API_KEY: str = os.getenv("LLM_API_KEY", "ollama")
    LLM_API_MODEL: str = os.getenv("LLM_API_MODEL", "smollm2:135m")

    # Prompt système – gardez-le court pour économiser les tokens
    SYSTEM_PROMPT: str = (
        "Tu es un assistant vocal compact. "
        "Réponds en français, de façon concise (1-3 phrases maximum). "
        "Pas de listes, pas de markdown."
    )

    # ── TTS ────────────────────────────────────────────────────────────────
    # Mode: "piper" (qualité supérieure) ou "pyttsx3" (plus simple)
    TTS_MODE: str = "piper"

    # Piper : chemin vers le binaire et le modèle de voix
    # Téléchargez : https://github.com/rhasspy/piper/releases
    PIPER_BINARY: str = str(Path.home() / "piper" / "piper")
    PIPER_MODEL: str = str(Path.home() / "piper" / "fr_FR-upmc-medium.onnx")

    # pyttsx3 – taux de parole (mots/min)
    PYTTSX3_RATE: int = 175

    # ── Somfy TaHoma (Mode Développeur Local) ──────────────────────────────
    SOMFY_PIN: str = os.getenv("SOMFY_PIN", "")        # ex: "2001-1234-5678"
    SOMFY_IP: str = os.getenv("SOMFY_IP", "")          # ex: "192.168.1.50" (ou vide pour auto-résolution local)
    SOMFY_TOKEN: str = os.getenv("SOMFY_TOKEN", "")    # Token généré dans l'app

    # ── Radio & Utilitaires ──────────────────────────────────────────────
    ENABLE_RADIO: bool = False
    ENABLE_TIMERS: bool = True
    RADIO_STATIONS: str = '{"France Info": "https://stream.radiofrance.fr/franceinfo/franceinfo.m3u8", "FIP": "https://stream.radiofrance.fr/fip/fip.m3u8"}'

    # ── Chromecast ─────────────────────────────────────────────────────────
    ENABLE_CHROMECAST: bool = False
    CHROMECAST_NAME: str = ""
    CHROMECAST_APPS: str = '{"YouTube": "233637DE", "Netflix": "CA5E845A", "Spotify": "CC32E5A1"}'

    # ── Wake on LAN ───────────────────────────────────────────────────────
    ENABLE_WOL: bool = False
    WOL_DEVICES: str = '{"Mon PC": "AA:BB:CC:DD:EE:FF"}'

class WakeOnLanManager:
    def wake(self, mac_address: str):
        try:
            from wakeonlan import send_magic_packet
            log.info(f"⚡ Envoi du paquet magique WOL à {mac_address}")
            send_magic_packet(mac_address)
            return True
        except Exception as e:
            log.error(f"Erreur lors de l'envoi du paquet WOL : {e}")
            return False

cfg = Config()

import json
if os.path.exists("config.json"):
    try:
        with open("config.json", "r", encoding="utf-8") as f:
            data = json.load(f)
            for k, v in data.items():
                if hasattr(cfg, k):
                    if v is None:
                        setattr(cfg, k, None)
                        continue
                    if v == "":
                        continue
                    # Types supportés: float, int, str, bool
                    try:
                        curr_v = getattr(cfg, k)
                        if isinstance(curr_v, bool): v = bool(v)
                        elif isinstance(curr_v, float): v = float(v)
                        elif isinstance(curr_v, int): v = int(v)
                        else: v = str(v)
                        setattr(cfg, k, v)
                    except ValueError:
                        pass
    except Exception as e:
        log.error(f"Erreur de chargement config.json: {e}")

try:
    import web_admin
    # Le serveur web sera informé de l'instance d'assistant plus tard
    threading.Thread(target=web_admin.start_server, daemon=True).start()
    log.info("🌐 Panneau d'administration web lancé sur le port 6524")
except Exception as e:
    log.warning(f"Impossible de lancer le panneau web: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Somfy TaHoma Local API
# ─────────────────────────────────────────────────────────────────────────────
class TaHomaLocalAPI:
    def __init__(self, pin: str, ip: str, token: str):
        self.pin = pin
        self.ip = ip
        self.token = token
        host = self.ip if self.ip else f"gateway-{self.pin}.local"
        self.base_url = f"https://{host}:8443/enduser-mobile-web/1/enduserAPI"
        self.headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}

    def _request(self, method, endpoint, json=None):
        url = f"{self.base_url}{endpoint}"
        try:
            response = requests.request(method, url, headers=self.headers, json=json, verify=False, timeout=5)
            response.raise_for_status()
            return response.json() if response.content else None
        except requests.exceptions.RequestException as e:
            log.error(f"Erreur API Somfy : {e}")
            return None

    def get_setup(self):
        return self._request("GET", "/setup")

    def get_devices(self):
        return self._request("GET", "/setup/devices")

    def get_action_groups(self):
        setup = self.get_setup()
        if setup and "actionGroups" in setup:
            return setup["actionGroups"]
        return self._request("GET", "/setup/actionGroups")
        
    def execute_action(self, label: str, device_urls: list, command_name: str):
        if not device_urls:
            log.warning("Aucun deviceURL fourni pour l'action.")
            return False
        actions = [{"deviceURL": url, "commands": [{"name": command_name, "parameters": []}]} for url in device_urls]
        log.info(f"Exécution Somfy : {label} sur {len(device_urls)} périphérique(s), commande={command_name}")
        return self._request("POST", "/exec/apply", json={"label": label, "actions": actions}) is not None

    def control_shutters(self, action: str, room: str = None):
        devices = self.get_devices()
        if not devices:
            log.error("Impossible de récupérer les volets (devices).")
            return False
        target_urls = []
        for d in devices:
            if d.get("uiClass", "") in ["RollerShutter", "Screen", "ExteriorVenetianBlind", "Awning", "SwingingShutter"]:
                if not room or room.lower() in d.get("label", "").lower():
                    target_urls.append(d["deviceURL"])
        if not target_urls:
            log.info(f"Aucun volet trouvé pour la pièce '{room}'" if room else "Aucun volet trouvé sur l'installation.")
            return False
        return self.execute_action(f"{action.capitalize()} volets" + (f" {room}" if room else ""), target_urls, action)

    def execute_scenario(self, scenario_keyword: str):
        groups = self.get_action_groups()
        if not groups:
            return False
        for group in groups:
            if scenario_keyword.lower() in group.get("label", "").lower():
                log.info(f"Lancement du scénario : {group.get('label')}")
                return self._request("POST", "/exec/apply", json=group)
        log.info(f"Scénario contenant '{scenario_keyword}' introuvable.")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Gestion des Radios (VLC / cvlc)
# ─────────────────────────────────────────────────────────────────────────────
class RadioManager:
    def __init__(self):
        self._process = None

    def play(self, url: str):
        self.stop()
        log.info(f"📻 Lancement radio : {url}")
        try:
            # cvlc est la version headless de VLC
            self._process = subprocess.Popen(
                ["cvlc", "--no-video", url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            return True
        except Exception as e:
            log.error(f"Erreur lors du lancement de la radio : {e}")
            return False

    def stop(self):
        if self._process:
            log.info("🛑 Arrêt de la radio.")
            self._process.terminate()
            self._process = None
            return True
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Gestion des Minuteurs et Alarmes
# ─────────────────────────────────────────────────────────────────────────────
class TimerManager:
    def __init__(self, tts_callback):
        self.tts = tts_callback
        self.timers = []  # List of dicts: {"time": datetime, "label": str, "type": "timer"|"alarm"}
        self._running = True
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def add_timer(self, seconds: int, label: str = "Minuteur"):
        target_time = datetime.datetime.now() + datetime.timedelta(seconds=seconds)
        self.timers.append({"time": target_time, "label": label, "type": "timer"})
        log.info(f"⏲️ Minuteur réglé pour dans {seconds}s ({target_time.strftime('%H:%M:%S')})")

    def add_alarm(self, hour: int, minute: int, label: str = "Alarme"):
        now = datetime.datetime.now()
        target_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target_time < now:
            target_time += datetime.timedelta(days=1)
        self.timers.append({"time": target_time, "label": label, "type": "alarm"})
        log.info(f"⏰ Alarme réglée pour {target_time.strftime('%H:%M:%S')}")

    def _worker(self):
        while self._running:
            now = datetime.datetime.now()
            expired = [t for t in self.timers if t["time"] <= now]
            for t in expired:
                msg = f"C'est l'heure ! Votre {t['label']} est terminé."
                log.info(f"🔔 {msg}")
                self._play_alarm_sound()
                self.tts.speak(msg)
                self.timers.remove(t)
            time.sleep(1)

    def _play_alarm_sound(self):
        # Utilise aplay pour jouer un bip système ou un son
        try:
            # Génère un bip simple avec sox si disponible, sinon joue un silence pour tester
            subprocess.run(["speaker-test", "-t", "sine", "-f", "1000", "-l", "1", "-p", "100"], 
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

    def stop(self):
        self._running = False


# ─────────────────────────────────────────────────────────────────────────────
# Gestion des Chromecasts
# ─────────────────────────────────────────────────────────────────────────────
class ChromecastManager:
    def __init__(self, cast_name: str = ""):
        self.cast_name = cast_name
        self._cast = None
        self._browser = None

    def _get_cast(self):
        if self._cast:
            return self._cast

        try:
            import pychromecast
            log.info(f"📺 Recherche du Chromecast : {self.cast_name if self.cast_name else 'par défaut'}...")
            
            chromecasts, browser = pychromecast.get_chromecasts()
            if not chromecasts:
                log.warning("Aucun Chromecast trouvé sur le réseau.")
                return None

            if self.cast_name:
                cast = next((cc for cc in chromecasts if cc.name == self.cast_name), None)
            else:
                cast = chromecasts[0]

            if not cast:
                log.warning(f"Chromecast '{self.cast_name}' introuvable.")
                return None

            cast.wait()
            self._cast = cast
            self._browser = browser
            log.info(f"✅ Connecté au Chromecast : {cast.name}")
            return self._cast
        except Exception as e:
            log.error(f"Erreur lors de la connexion au Chromecast : {e}")
            return None

    def launch_app(self, app_id: str):
        cast = self._get_cast()
        if cast:
            log.info(f"🚀 Lancement de l'application ID: {app_id} sur {cast.name}")
            cast.start_app(app_id)
            return True
        return False

    def stop(self):
        cast = self._get_cast()
        if cast:
            log.info(f"🛑 Arrêt du contenu sur {cast.name}")
            cast.quit_app()
            return True
        return False

    def pause(self):
        cast = self._get_cast()
        if cast and cast.media_controller:
            cast.media_controller.pause()
            return True
        return False

    def play(self):
        cast = self._get_cast()
        if cast and cast.media_controller:
            cast.media_controller.play()
            return True
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Module Audio utilitaire
# ─────────────────────────────────────────────────────────────────────────────
class AudioManager:
    """Gère le flux PyAudio. Un seul objet partagé pour économiser les FD."""

    def __init__(self):
        self._pa = pyaudio.PyAudio()
        self._input_device = self._find_input_device()
        self._output_device = self._find_output_device()
        log.info(
            "Périphérique entrée : %s | sortie : %s",
            self._input_device,
            self._output_device,
        )

    def _find_input_device(self) -> Optional[int]:
        """Retourne l'index du premier périphérique d'entrée disponible."""
        for i in range(self._pa.get_device_count()):
            info = self._pa.get_device_info_by_index(i)
            if info["maxInputChannels"] > 0:
                return i
        return None

    def _find_output_device(self) -> Optional[int]:
        for i in range(self._pa.get_device_count()):
            info = self._pa.get_device_info_by_index(i)
            if info["maxOutputChannels"] > 0:
                return i
        return None

    def open_input_stream(self, frames_per_buffer: int = cfg.CHUNK_SIZE):
        return self._pa.open(
            rate=cfg.SAMPLE_RATE,
            channels=cfg.CHANNELS,
            format=cfg.FORMAT,
            input=True,
            input_device_index=self._input_device,
            frames_per_buffer=frames_per_buffer,
        )

    def terminate(self):
        self._pa.terminate()


# ─────────────────────────────────────────────────────────────────────────────
# 1) Détection du mot d'éveil (openWakeWord — gratuit, open-source)
# ─────────────────────────────────────────────────────────────────────────────
class WakeWordDetector:
    """
    Utilise openWakeWord pour la détection du mot d'éveil.
    100% gratuit, aucune clé API, modèles ONNX embarqués.
    Empreinte mémoire < 20 MB.
    Chunk size requis : 1280 samples à 16 kHz (80 ms).
    """

    def __init__(self, audio: AudioManager):
        from openwakeword.model import Model
        # Les modèles intégrés sont téléchargés automatiquement au premier lancement
        # Mots disponibles : hey_google, alexa, hey_jarvis, hey_mycroft, ok_nabu…
        self._model = Model(
            wakeword_models=[cfg.WAKE_WORD.lower()],
            inference_framework="onnx",
        )
        self._audio = audio
        self._threshold = cfg.WAKE_WORD_THRESHOLD
        log.info(
            "openWakeWord prêt — mot d'éveil : « %s » (seuil=%.2f)",
            cfg.WAKE_WORD, self._threshold,
        )

    def listen_for_wake_word(self) -> bool:
        """Bloque jusqu'à la détection du mot d'éveil. Retourne True."""
        stream = self._audio.open_input_stream(frames_per_buffer=cfg.CHUNK_SIZE)
        # Réinitialise les scores pour éviter les déclenchements résiduels
        self._model.reset()
        try:
            log.info("En attente du mot d'éveil…")
            while True:
                pcm_bytes = stream.read(cfg.CHUNK_SIZE, exception_on_overflow=False)
                # openWakeWord attend un tableau numpy int16
                audio_chunk = np.frombuffer(pcm_bytes, dtype=np.int16)
                prediction = self._model.predict(audio_chunk)
                # prediction est un dict {"hey_google": score, ...}
                score = prediction.get(cfg.WAKE_WORD, 0.0)
                if score >= self._threshold:
                    log.info("✅ Mot d'éveil détecté ! (score=%.3f)", score)
                    return True
        finally:
            stream.stop_stream()
            stream.close()

    def delete(self):
        # Pas de ressource externe à libérer pour openWakeWord
        pass


# ─────────────────────────────────────────────────────────────────────────────
# 2) Enregistrement de la requête utilisateur
# ─────────────────────────────────────────────────────────────────────────────
def record_utterance(audio: AudioManager) -> Optional[str]:
    """
    Enregistre l'audio après le mot d'éveil jusqu'au silence.
    Retourne le chemin vers le fichier WAV temporaire, ou None si vide.
    """
    log.info("🎙️  Enregistrement…")
    stream = audio.open_input_stream(frames_per_buffer=1024)
    frames = []
    silent_chunks = 0
    silence_limit = int(
        cfg.RECORD_SILENCE_DURATION * cfg.SAMPLE_RATE / 1024
    )
    max_chunks = int(cfg.MAX_RECORD_SECONDS * cfg.SAMPLE_RATE / 1024)

    try:
        for _ in range(max_chunks):
            data = stream.read(1024, exception_on_overflow=False)
            frames.append(data)
            # Calcul du RMS pour détecter le silence
            arr = np.frombuffer(data, dtype=np.int16).astype(np.float32)
            rms = np.sqrt(np.mean(arr ** 2)) / 32768.0
            if rms < cfg.RECORD_SILENCE_THRESHOLD:
                silent_chunks += 1
                if silent_chunks >= silence_limit and len(frames) > silence_limit:
                    break
            else:
                silent_chunks = 0
    finally:
        stream.stop_stream()
        stream.close()

    if not frames:
        return None

    # Sauvegarde dans un fichier temporaire (sera supprimé après transcription)
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    with wave.open(tmp.name, "wb") as wf:
        wf.setnchannels(cfg.CHANNELS)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(cfg.SAMPLE_RATE)
        wf.writeframes(b"".join(frames))
    log.info("Audio enregistré : %s (%.1f s)", tmp.name, len(frames) * 1024 / cfg.SAMPLE_RATE)
    return tmp.name


# ─────────────────────────────────────────────────────────────────────────────
# 3) STT — Faster-Whisper
# ─────────────────────────────────────────────────────────────────────────────
class WhisperTranscriber:
    """
    Charge le modèle Whisper une seule fois pour économiser la RAM.
    Utilise int8 pour réduire l'empreinte mémoire (~40 MB pour tiny).
    """

    def __init__(self):
        log.info("Chargement de Whisper (%s / %s)…", cfg.WHISPER_MODEL, cfg.WHISPER_COMPUTE_TYPE)
        from faster_whisper import WhisperModel
        self._model = WhisperModel(
            cfg.WHISPER_MODEL,
            device=cfg.WHISPER_DEVICE,
            compute_type=cfg.WHISPER_COMPUTE_TYPE,
            download_root=str(Path.home() / ".cache" / "whisper"),
            cpu_threads=cfg.LLM_N_THREADS,
            num_workers=1,
        )
        log.info("Whisper prêt.")

    def transcribe(self, wav_path: str) -> str:
        """Transcrit un fichier WAV et retourne le texte."""
        segments, info = self._model.transcribe(
            wav_path,
            language=cfg.WHISPER_LANGUAGE,
            beam_size=1,           # beam=1 = plus rapide, moins de RAM
            best_of=1,
            vad_filter=True,       # filtre le bruit de fond
        )
        text = " ".join(seg.text.strip() for seg in segments).strip()
        log.info("📝 Transcription [%s] : « %s »", info.language, text)
        return text


# ─────────────────────────────────────────────────────────────────────────────
# 4) LLM — llama-cpp ou API
# ─────────────────────────────────────────────────────────────────────────────
class LLMEngine:
    """Abstraction LLM : mode local (llama-cpp) ou API (OpenAI-compatible)."""

    def __init__(self):
        if cfg.LLM_MODE == "local":
            self._init_local()
        else:
            self._init_api()
        self._history = []  # historique de conversation en mémoire vive

    def _init_local(self):
        if not Path(cfg.LLM_MODEL_PATH).exists():
            raise FileNotFoundError(
                f"Modèle LLM introuvable : {cfg.LLM_MODEL_PATH}\n"
                "Téléchargez un modèle GGUF et mettez à jour LLM_MODEL_PATH."
            )
        log.info("Chargement du LLM local : %s", cfg.LLM_MODEL_PATH)
        from llama_cpp import Llama
        self._llm = Llama(
            model_path=cfg.LLM_MODEL_PATH,
            n_ctx=cfg.LLM_N_CTX,
            n_threads=cfg.LLM_N_THREADS,
            n_gpu_layers=cfg.LLM_N_GPU_LAYERS,
            verbose=False,
            use_mlock=False,   # ne pas verrouiller la RAM (important avec 512 MB)
            use_mmap=True,     # mapping mémoire pour réduire l'empreinte
        )
        log.info("LLM local prêt.")
        self._mode = "local"

    def _init_api(self):
        log.info("Mode LLM API : %s → %s", cfg.LLM_API_BASE, cfg.LLM_API_MODEL)
        try:
            from openai import OpenAI
            self._client = OpenAI(
                base_url=cfg.LLM_API_BASE,
                api_key=cfg.LLM_API_KEY,
            )
        except ImportError:
            raise ImportError("Installez openai : pip install openai")
        self._mode = "api"

    def generate(self, user_text: str) -> str:
        """Génère une réponse à partir du texte utilisateur."""
        # Construction des messages (historique court pour économiser la RAM)
        messages = [{"role": "system", "content": cfg.SYSTEM_PROMPT}]
        # On garde seulement les 4 derniers échanges
        messages.extend(self._history[-8:])
        messages.append({"role": "user", "content": user_text})

        if self._mode == "local":
            response = self._generate_local(messages)
        else:
            response = self._generate_api(messages)

        # Mise à jour de l'historique
        self._history.append({"role": "user", "content": user_text})
        self._history.append({"role": "assistant", "content": response})

        log.info("🤖 Réponse : « %s »", response)
        return response

    def _generate_local(self, messages: list) -> str:
        output = self._llm.create_chat_completion(
            messages=messages,
            max_tokens=cfg.LLM_MAX_TOKENS,
            temperature=cfg.LLM_TEMPERATURE,
            stop=["<|im_end|>", "</s>", "\n\n"],
        )
        return output["choices"][0]["message"]["content"].strip()

    def _generate_api(self, messages: list) -> str:
        resp = self._client.chat.completions.create(
            model=cfg.LLM_API_MODEL,
            messages=messages,
            max_tokens=cfg.LLM_MAX_TOKENS,
            temperature=cfg.LLM_TEMPERATURE,
        )
        return resp.choices[0].message.content.strip()

    def reset_history(self):
        self._history.clear()


# ─────────────────────────────────────────────────────────────────────────────
# 5) TTS — Piper ou pyttsx3
# ─────────────────────────────────────────────────────────────────────────────
class TTSEngine:
    """Synthèse vocale : Piper (qualité) ou pyttsx3 (fallback)."""

    def __init__(self):
        if cfg.TTS_MODE == "piper":
            self._init_piper()
        else:
            self._init_pyttsx3()

    def _init_piper(self):
        if not Path(cfg.PIPER_BINARY).exists():
            log.warning(
                "Binaire Piper introuvable (%s), bascule sur pyttsx3.", cfg.PIPER_BINARY
            )
            cfg.TTS_MODE = "pyttsx3"
            self._init_pyttsx3()
            return
        if not Path(cfg.PIPER_MODEL).exists():
            log.warning(
                "Modèle Piper introuvable (%s), bascule sur pyttsx3.", cfg.PIPER_MODEL
            )
            cfg.TTS_MODE = "pyttsx3"
            self._init_pyttsx3()
            return
        log.info("TTS Piper initialisé : %s", cfg.PIPER_MODEL)
        self._mode = "piper"

    def _init_pyttsx3(self):
        import pyttsx3
        self._engine = pyttsx3.init()
        self._engine.setProperty("rate", cfg.PYTTSX3_RATE)
        # Sélection d'une voix française si disponible
        voices = self._engine.getProperty("voices")
        for v in voices:
            if "fr" in v.id.lower() or "french" in v.name.lower():
                self._engine.setProperty("voice", v.id)
                log.info("Voix pyttsx3 sélectionnée : %s", v.name)
                break
        log.info("TTS pyttsx3 initialisé.")
        self._mode = "pyttsx3"

    def speak(self, text: str):
        """Énonce le texte donné."""
        log.info("🔊 Synthèse : « %s »", text)
        if self._mode == "piper":
            self._speak_piper(text)
        else:
            self._speak_pyttsx3(text)

    def _speak_piper(self, text: str):
        import subprocess
        import shlex
        # Piper lit sur stdin, joue le WAV via aplay
        cmd_piper = (
            f'echo {shlex.quote(text)} | '
            f'{shlex.quote(cfg.PIPER_BINARY)} '
            f'--model {shlex.quote(cfg.PIPER_MODEL)} '
            f'--output_raw | '
            f'aplay -r 22050 -f S16_LE -t raw -'
        )
        try:
            subprocess.run(cmd_piper, shell=True, check=True)
        except subprocess.CalledProcessError as e:
            log.error("Erreur Piper : %s — bascule pyttsx3", e)
            self._speak_pyttsx3(text)

    def _speak_pyttsx3(self, text: str):
        self._engine.say(text)
        self._engine.runAndWait()


# ─────────────────────────────────────────────────────────────────────────────
# Boucle principale de l'assistant
# ─────────────────────────────────────────────────────────────────────────────
class VoiceAssistant:
    """Orchestre tous les composants dans une boucle événementielle."""

    def __init__(self):
        log.info("═══ Démarrage de l'assistant vocal Edge AI ═══")
        gc.collect()  # libère la mémoire avant de charger les modèles

        self.audio = AudioManager()
        self.tts = TTSEngine()          # chargé en premier (léger)
        self.stt = WhisperTranscriber() # ~60-80 MB
        self.llm = LLMEngine()          # ~150-300 MB selon le modèle
        self.wake = WakeWordDetector(self.audio)  # ~5 MB

        if getattr(cfg, "SOMFY_PIN", "") and getattr(cfg, "SOMFY_TOKEN", ""):
            try:
                self.somfy = TaHomaLocalAPI(cfg.SOMFY_PIN, cfg.SOMFY_IP, cfg.SOMFY_TOKEN)
                log.info("🏠 Connecteur Somfy TaHoma initialisé.")
            except Exception as e:
                self.somfy = None
                log.warning(f"Erreur d'initialisation Somfy: {e}")
        else:
            self.somfy = None

        gc.collect()
        self._print_memory_usage()
        log.info("✅ Tous les composants sont prêts.")

    def _print_memory_usage(self):
        try:
            import psutil
            proc = psutil.Process(os.getpid())
            mb = proc.memory_info().rss / 1024 / 1024
            log.info("📊 Utilisation RAM : %.0f MB", mb)
        except ImportError:
            pass  # psutil optionnel

    def process_query(self, text: str) -> Optional[str]:
        """Traite une requête texte et retourne la réponse."""
        # 1) Commandes intégrées
        builtin_response = self._handle_builtin_command(text)
        if builtin_response:
            return builtin_response

        # 2) LLM
        try:
            # On ne dit "Un instant" que si c'est une requête vocale (détectée par l'absence d'un flag ?)
            # Pour simplifier, on le laisse ou on l'enlève.
            response = self.llm.generate(text)
            return response
        except Exception as e:
            log.error("Erreur LLM : %s", e)
            return "Désolé, je n'ai pas pu générer de réponse."

    def run(self):
        """Boucle principale : écoute → transcription → LLM → TTS."""
        self.radio = RadioManager()
        self.timers = TimerManager(self.tts)
        self.chromecast = ChromecastManager(cfg.CHROMECAST_NAME)
        self.wol = WakeOnLanManager()
        
        self.tts.speak("Assistant prêt. Dites Hé Google pour commencer.")
        try:
            while True:
                # ── Attente du mot d'éveil ──────────────────────────────
                self.wake.listen_for_wake_word()

                # ── Signal sonore de confirmation ───────────────────────
                self.tts.speak("Oui ?")

                # ── Enregistrement de la requête ────────────────────────
                wav_path = record_utterance(self.audio)
                if not wav_path:
                    log.warning("Aucun audio capturé, retour en attente.")
                    continue

                # ── Transcription ───────────────────────────────────────
                try:
                    text = self.stt.transcribe(wav_path)
                finally:
                    os.unlink(wav_path)  # supprime le fichier temporaire

                if not text:
                    self.tts.speak("Je n'ai pas compris, pouvez-vous répéter ?")
                    continue

                # ── Traitement de la requête ───────────────────────────
                response = self.process_query(text)
                if response:
                    self.tts.speak(response)
                gc.collect()  # libère la mémoire après chaque cycle

        except KeyboardInterrupt:
            log.info("Arrêt demandé par l'utilisateur.")
        finally:
            self._cleanup()

    def _handle_builtin_command(self, text: str) -> Optional[str]:
        """Gère les commandes intégrées sans passer par le LLM. Retourne la réponse texte si gérée."""
        t = text.lower().strip()
        if any(w in t for w in ("réinitialise", "reset", "oublie tout")):
            self.llm.reset_history()
            return "Historique effacé."
        if any(w in t for w in ("quelle heure", "il est quelle heure")):
            h = time.strftime("%H heures %M")
            return f"Il est {h}."
        if any(w in t for w in ("au revoir", "stop", "quitte", "arrête")):
            # On retourne la réponse avant de quitter
            # Note: Le quitter effectif se fera dans la boucle principale si besoin, 
            # ou via un flag. Pour l'instant, on lance l'exception ici.
            self.tts.speak("Au revoir !")
            raise KeyboardInterrupt
        
        # ... (reste des commandes Somfy, Radio, etc.)

        # ── Intégration Somfy TaHoma ────────────────────────────────────
        if hasattr(self, "somfy") and self.somfy:
            if "volet" in t or "volets" in t:
                action = None
                if any(w in t for w in ("ouvre", "monte")): action = "open"
                elif any(w in t for w in ("ferme", "descend")): action = "close"
                elif "stop" in t or "arrête" in t: action = "stop"

                if action:
                    room = None
                    for r in ["salon", "cuisine", "chambre", "bureau", "salle de bain", "garage", "véranda"]:
                        if r in t:
                            room = r
                            break
                    
                    msg = "J'ouvre les volets" if action == "open" else ("Je ferme les volets" if action == "close" else "J'arrête les volets")
                    if room: msg += f" pièce {room}"
                    
                    success = self.somfy.control_shutters(action, room)
                    if not success:
                        return "Il y a eu un problème avec les volets."
                    return msg
                    
            if "scénario" in t or "scenario" in t:
                words = t.split()
                try:
                    idx = words.index("scénario") if "scénario" in words else words.index("scenario")
                    if idx + 1 < len(words):
                        keyword = words[idx + 1]
                        success = self.somfy.execute_scenario(keyword)
                        if not success:
                            return f"Scénario {keyword} introuvable."
                        return f"Lancement du scénario {keyword}."
                except ValueError:
                    pass

        # ── Radio ───────────────────────────────────────────────────────
        if cfg.ENABLE_RADIO:
            if any(w in t for w in ("joue", "lance", "écoute")) and "radio" in t:
                stations = json.loads(cfg.RADIO_STATIONS)
                for name, url in stations.items():
                    if name.lower() in t:
                        self.radio.play(url)
                        return f"Lancement de la radio {name}."
            
            if any(w in t for w in ("arrête la musique", "coupe la radio", "stop radio", "arrête la radio")):
                if self.radio.stop():
                    return "Radio arrêtée."

        # ── Minuteurs & Alarmes ──────────────────────────────────────────
        if cfg.ENABLE_TIMERS:
            # Minuteur (ex: "mets un minuteur de 5 minutes")
            timer_match = re.search(r"minuteur de (\d+)\s*(minute|seconde|heure)", t)
            if timer_match:
                val = int(timer_match.group(1))
                unit = timer_match.group(2)
                seconds = val
                if "minute" in unit: seconds = val * 60
                elif "heure" in unit: seconds = val * 3600
                
                self.timers.add_timer(seconds)
                return f"C'est fait, minuteur de {val} {unit}s lancé."

            # Alarme (ex: "réveille moi à 7 heures 30")
            alarm_match = re.search(r"(alarme|réveille|réveil).* à (\d+)\s*heures?\s*(\d*)", t)
            if alarm_match:
                h = int(alarm_match.group(2))
                m = int(alarm_match.group(3)) if alarm_match.group(3) else 0
                self.timers.add_alarm(h, m)
                return f"C'est fait. Alarme réglée pour {h} heures {m if m else ''}."

        # ── Chromecast ──────────────────────────────────────────────────
        if cfg.ENABLE_CHROMECAST:
            if any(w in t for w in ("lance", "joue", "ouvre", "écoute")) and any(w in t for w in ("télé", "tv", "chromecast")):
                apps = json.loads(cfg.CHROMECAST_APPS)
                for name, app_id in apps.items():
                    if name.lower() in t:
                        self.chromecast.launch_app(app_id)
                        return f"Lancement de {name} sur la télé."
            
            if any(w in t for w in ("arrête la télé", "éteins la télé", "stop tv", "coupe la télé")):
                if self.chromecast.stop():
                    return "Télé arrêtée."
            
            if any(w in t for w in ("pause", "met en pause")) and any(w in t for w in ("télé", "tv")):
                if self.chromecast.pause():
                    return "C'est mis en pause sur la télé."

            if any(w in t for w in ("reprends", "lecture")) and any(w in t for w in ("télé", "tv")):
                if self.chromecast.play():
                    return "C'est reparti sur la télé."

        # ── Wake on LAN ──────────────────────────────────────────────────
        if cfg.ENABLE_WOL:
            if any(w in t for w in ("réveille", "allume", "démarre")) and any(w in t for w in ("pc", "ordinateur", "ordi", "machine")):
                devices = json.loads(cfg.WOL_DEVICES)
                for name, mac in devices.items():
                    if name.lower() in t or (("pc" in t or "ordinateur" in t) and len(devices) == 1):
                        self.wol.wake(mac)
                        return f"J'ai envoyé le signal d'allumage à {name}."

        return None

    def _cleanup(self):
        log.info("Nettoyage des ressources…")
        try:
            self.wake.delete()
        except Exception:
            pass
        try:
            self.audio.terminate()
        except Exception:
            pass
        log.info("Assistant arrêté proprement.")


# ─────────────────────────────────────────────────────────────────────────────
# Point d'entrée
# ─────────────────────────────────────────────────────────────────────────────
def parse_args():
    parser = argparse.ArgumentParser(description="Assistant vocal Edge AI – Raspberry Pi Zero 2W")
    parser.add_argument("--llm-mode", choices=["local", "api"], help="Mode LLM (local ou api)")
    parser.add_argument("--tts-mode", choices=["piper", "pyttsx3"], help="Moteur TTS")
    parser.add_argument("--model", help="Chemin vers le modèle GGUF (mode local)")
    parser.add_argument("--debug", action="store_true", help="Active les logs DEBUG")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    if args.llm_mode:
        cfg.LLM_MODE = args.llm_mode
    if args.tts_mode:
        cfg.TTS_MODE = args.tts_mode
    if args.model:
        cfg.LLM_MODEL_PATH = args.model

    assistant = VoiceAssistant()
    
    # Enregistrement de l'assistant auprès du serveur web
    try:
        import web_admin
        web_admin.set_assistant(assistant)
    except Exception:
        pass

    assistant.run()
