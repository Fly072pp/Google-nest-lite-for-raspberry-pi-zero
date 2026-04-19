import json
import os
import signal
import logging
import secrets
from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from werkzeug.security import generate_password_hash, check_password_hash

CONFIG_FILE = "config.json"

log = logging.getLogger("werkzeug")
log.setLevel(logging.ERROR)

app = Flask(__name__)
# Generate a random secret key for sessions
app.secret_key = secrets.token_hex(32)

def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {}
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        try:
            return json.load(f)
        except Exception:
            return {}

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

def start_server():
    app.run(host="0.0.0.0", port=6524, debug=False, use_reloader=False)
