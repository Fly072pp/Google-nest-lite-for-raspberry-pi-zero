import json
import os
import signal
import logging
import secrets
from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from werkzeug.security import generate_password_hash, check_password_hash
import bluetooth_manager
import subprocess
import threading

CONFIG_FILE = "config.json"

log = logging.getLogger("werkzeug")
log.setLevel(logging.ERROR)

bt = bluetooth_manager.BluetoothManager()
active_assistant = None
default_config = {}

def set_assistant(assistant):
    global active_assistant
    active_assistant = assistant

def set_config(config_obj):
    """Importe les réglages par défaut depuis la classe Config d'assistant.py"""
    global default_config
    for key in dir(config_obj):
        if not key.startswith("_"):
            val = getattr(config_obj, key)
            if not callable(val):
                default_config[key] = val

app = Flask(__name__)
# Generate a random secret key for sessions
app.secret_key = secrets.token_hex(32)

def load_config():
    config = {}
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            try:
                config = json.load(f)
            except Exception:
                pass
    
    # On fusionne : le fichier config.json a la priorité sur les défauts d'assistant.py
    full_config = default_config.copy()
    full_config.update(config)
    return full_config

def save_config(data):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)

@app.before_request
def require_login():
    allowed_routes = ['login', 'setup', 'static']
    if request.endpoint in allowed_routes:
        return
        
    config = load_config()
    # Si aucun admin n'existe, on force le setup
    if "ADMIN_USERNAME" not in config or "ADMIN_PASSWORD_HASH" not in config:
        return redirect(url_for('setup'))
        
    # Si l'utilisateur n'est pas connecté, redirect login
    if not session.get('logged_in'):
        return redirect(url_for('login'))

@app.route("/setup", methods=["GET", "POST"])
def setup():
    config = load_config()
    if "ADMIN_USERNAME" in config and "ADMIN_PASSWORD_HASH" in config:
        return redirect(url_for('login'))
        
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        if username and password:
            config["ADMIN_USERNAME"] = username
            config["ADMIN_PASSWORD_HASH"] = generate_password_hash(password)
            save_config(config)
            session['logged_in'] = True
            return redirect(url_for('index'))
            
    return render_template("setup.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        
        config = load_config()
        if username == config.get("ADMIN_USERNAME") and \
           check_password_hash(config.get("ADMIN_PASSWORD_HASH", ""), password):
            session['logged_in'] = True
            return redirect(url_for('index'))
        else:
            return render_template("login.html", error="Identifiants incorrects")
            
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/config", methods=["GET"])
def get_config():
    config = load_config()
    # Remove sensitive data from frontend delivery
    config.pop("ADMIN_PASSWORD_HASH", None)
    config.pop("ADMIN_USERNAME", None)
    return jsonify(config)

@app.route("/api/config", methods=["POST"])
def update_config():
    data = request.json
    config = load_config()
    # Merge existing config to preserve sensitive data (passwords, usernames)
    for k, v in data.items():
        config[k] = v
    save_config(config)
    return jsonify({"status": "success"})

@app.route("/api/restart", methods=["POST"])
def restart_app():
    import threading
    def delay_exit():
        import time
        time.sleep(1)
        os.kill(os.getpid(), signal.SIGTERM)
    threading.Thread(target=delay_exit).start()
    return jsonify({"status": "restarting"})

@app.route("/api/system/update", methods=["POST"])
def system_update():
    try:
        # On tente de récupérer les dernières modifs sans écraser les fichiers locaux si possible
        # Mais git pull échouera s'il y a des conflits.
        log.info("Tentative de mise à jour via Git...")
        result = subprocess.run(["git", "pull"], capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            if "Already up to date" in result.stdout:
                return jsonify({"status": "up_to_date", "message": "Déjà à jour."})
            return jsonify({"status": "success", "message": "Mise à jour effectuée. Redémarrage nécessaire."})
        else:
            # Si erreur, on tente un fetch pour voir s'il y a vraiment des trucs
            return jsonify({"status": "error", "message": result.stderr})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

# --- Bluetooth API ---


@app.route("/api/bluetooth/discover", methods=["GET"])
def bt_discover():
    try:
        # 10s is better for finding all devices on a Pi
        devices = bt.discover(duration=10)
        return jsonify(devices)
    except Exception as e:
        logging.error(f"Error in bt_discover: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/bluetooth/status", methods=["GET"])
def bt_status():
    try:
        status = bt.get_status()
        # Also include list of paired devices
        paired = bt.get_paired_devices()
        return jsonify({
            "connected": status,
            "paired": paired
        })
    except Exception as e:
        logging.error(f"Error in bt_status: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/bluetooth/connect", methods=["POST"])
def bt_connect():
    data = request.json
    mac = data.get("mac")
    if not mac:
        return jsonify({"error": "MAC address required"}), 400
    
    success = bt.connect(mac)
    return jsonify({"status": "success" if success else "failed"})

@app.route("/api/bluetooth/disconnect", methods=["POST"])
def bt_disconnect():
    data = request.json
    mac = data.get("mac")
    if not mac:
        return jsonify({"error": "MAC address required"}), 400
    
    bt.disconnect(mac)
    return jsonify({"status": "success"})

@app.route("/api/bluetooth/remove", methods=["POST"])
def bt_remove():
    data = request.json
    mac = data.get("mac")
    if not mac:
        return jsonify({"error": "MAC address required"}), 400
    
    bt.remove(mac)
    return jsonify({"status": "success"})

# --- Ollama API ---

@app.route("/api/ollama/status", methods=["GET"])
def ollama_status():
    try:
        # Check if ollama is installed and running
        result = subprocess.run(["ollama", "--version"], capture_output=True, text=True, timeout=2)
        if result.returncode == 0:
            return jsonify({"status": "installed", "version": result.stdout.strip()})
        else:
            return jsonify({"status": "error", "message": result.stderr})
    except (FileNotFoundError, subprocess.SubprocessError):
        return jsonify({"status": "not_installed"})

@app.route("/api/ollama/install", methods=["POST"])
def ollama_install():
    def run_install():
        try:
            # Install Ollama using the official script
            # We use bash -c to handle the pipe
            subprocess.run("curl -fsSL https://ollama.com/install.sh | sh", shell=True, check=True)
            # Pull a lightweight model by default to make it ready
            subprocess.run(["ollama", "pull", "smollm2:135m"], check=True)
        except Exception as e:
            logging.error(f"Ollama installation failed: {e}")

    thread = threading.Thread(target=run_install)
    thread.start()
    return jsonify({"status": "started"})

# --- Chat API ---

@app.route("/api/chat", methods=["POST"])
def chat():
    if not active_assistant:
        return jsonify({"response": "Assistant non initialisé", "status": "error"}), 503
    
    data = request.json
    message = data.get("message")
    if not message:
        return jsonify({"response": "Message vide", "status": "error"}), 400
    
    # Traitement de la requête par l'assistant
    # Cela va aussi générer la voix sur les HP du Pi
    response = active_assistant.process_query(message)
    
    # On s'assure que l'assistant parle la réponse
    if response:
        active_assistant.tts.speak(response)
        
    return jsonify({"response": response, "status": "success"})

def start_server():
    app.run(host="0.0.0.0", port=6524, debug=False, use_reloader=False)
