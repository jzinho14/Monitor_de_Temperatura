import os
import threading
from datetime import datetime
import pytz
import requests
import psycopg2
from urllib.parse import urlparse

from flask import Flask, jsonify, render_template, request
from flask_socketio import SocketIO
import paho.mqtt.client as mqtt

# ---------------------------
# Configuração básica
# ---------------------------
APP_PORT = int(os.environ.get("PORT", 5000))
DATABASE_URL = os.environ.get("DATABASE_URL")

MQTT_BROKER = os.environ.get("MQTT_BROKER", "f67708c3dd0e4e38822956f08a661bd7.s1.eu.hivemq.cloud")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "8883"))
MQTT_USER = os.environ.get("MQTT_USER", "joao_senac")
MQTT_PASSWORD = os.environ.get("MQTT_PASSWORD", "Senac_FMABC_7428")
MQTT_TOPIC = os.environ.get("MQTT_TOPIC", "joao/teste/temperatura")

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

# ---------------------------
# Variáveis globais de status
# ---------------------------
last_message_ts = None   # ainda não recebemos nenhuma mensagem
STATUS_INTERVAL_SEC = 50
OFFLINE_THRESHOLD_SEC = 100
current_device_status = "offline"  # começa offline

# ---------------------------
# Banco de dados (PostgreSQL)
# ---------------------------
def get_conn():
    if not DATABASE_URL:
        raise Exception("DATABASE_URL environment variable is not set.")
    result = urlparse(DATABASE_URL)
    return psycopg2.connect(
        dbname=result.path[1:],
        user=result.username,
        password=result.password,
        host=result.hostname,
        port=result.port,
        sslmode="require"
    )

def init_db(reset=False):
    conn = get_conn()
    cur = conn.cursor()
    if reset:
        cur.execute("DROP TABLE IF EXISTS leituras")
        cur.execute("DROP TABLE IF EXISTS status_log")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS leituras (
            id SERIAL PRIMARY KEY,
            valor REAL NOT NULL,
            timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS status_log (
            id SERIAL PRIMARY KEY,
            status VARCHAR(20) NOT NULL,
            timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def salvar_leitura(valor, ts=None):
    conn = get_conn()
    cur = conn.cursor()
    if ts is None:
        cur.execute("INSERT INTO leituras (valor) VALUES (%s)", (valor,))
    else:
        cur.execute("INSERT INTO leituras (valor, timestamp) VALUES (%s, %s)", (valor, ts))
    conn.commit()
    conn.close()

def buscar_ultimos(limite=200):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT valor, timestamp FROM leituras ORDER BY id DESC LIMIT %s", (limite,))
    rows = cur.fetchall()
    conn.close()
    rows.reverse()
    return rows

def estatisticas_hoje():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT AVG(valor), COUNT(*)
        FROM leituras
        WHERE DATE(timestamp) = CURRENT_DATE
    """)
    avg_val, count_val = cur.fetchone()
    cur.execute("SELECT valor, timestamp FROM leituras ORDER BY id DESC LIMIT 1")
    ultimo = cur.fetchone()
    conn.close()
    return {
        "media_hoje": avg_val if avg_val is not None else 0.0,
        "qtd_hoje": count_val or 0,
        "atual": {"valor": (ultimo[0] if ultimo else None),
                  "timestamp": (ultimo[1] if ultimo else None)}
    }

def estatisticas_periodo(inicio_iso, fim_iso):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT AVG(valor), COUNT(*)
        FROM leituras
        WHERE DATE(timestamp) >= DATE(%s) AND DATE(timestamp) <= DATE(%s)
    """, (inicio_iso, fim_iso))
    avg_val, count_val = cur.fetchone()
    conn.close()
    return {"media_periodo": avg_val if avg_val is not None else 0.0,
            "qtd_periodo": count_val or 0}

def buscar_intervalo_data(inicio_iso, fim_iso, limite=2000):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT valor, timestamp
        FROM leituras
        WHERE DATE(timestamp) >= DATE(%s) AND DATE(timestamp) <= DATE(%s)
        ORDER BY timestamp ASC
        LIMIT %s
    """, (inicio_iso, fim_iso, limite))
    rows = cur.fetchall()
    conn.close()
    return rows

init_db(reset=False)

# ---------------------------
# Log de status
# ---------------------------
def add_status_event(status, timestamp):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT INTO status_log (status, timestamp) VALUES (%s, %s)", (status, timestamp))
    conn.commit()
    conn.close()
    print(f"Evento de status registrado: {status} em {timestamp}")

# ---------------------------
# MQTT
# ---------------------------
def on_connect(client, userdata, flags, rc):
    print("Conectado ao broker MQTT com código:", rc)
    client.subscribe(MQTT_TOPIC)

def on_message(client, userdata, msg):
    try:
        global last_message_ts, current_device_status
        valor = float(msg.payload.decode().strip())

        brazil_tz = pytz.timezone('America/Sao_Paulo')
        ts = datetime.now(brazil_tz)

        salvar_leitura(valor, ts)

        last_message_ts = datetime.now(pytz.utc)

        if current_device_status != "online":
            timestamp = datetime.now().isoformat()
            add_status_event("online", timestamp)
            current_device_status = "online"

        socketio.emit('nova_temperatura', {"valor": valor, "timestamp": ts.isoformat()})
        socketio.emit('esp32_status', {'status': 'online'})

    except Exception as e:
        print("Erro ao processar mensagem MQTT:", e)

mqtt_client = mqtt.Client()
mqtt_client.username_pw_set(MQTT_USER, MQTT_PASSWORD)
mqtt_client.tls_set()
mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message

def mqtt_loop():
    mqtt_client.connect(MQTT_BROKER, MQTT_PORT)
    mqtt_client.loop_forever()

threading.Thread(target=mqtt_loop, daemon=True).start()

# ---------------------------
# Rotinas de background
# ---------------------------
def check_device_status():
    global last_message_ts, current_device_status

    while True:
        if last_message_ts is None:
            new_status = "offline"
        else:
            delta = datetime.now(pytz.utc) - last_message_ts
            new_status = "online" if delta.total_seconds() < OFFLINE_THRESHOLD_SEC else "offline"

        if new_status != current_device_status:
            timestamp = datetime.now().isoformat()
            add_status_event(new_status, timestamp)
            current_device_status = new_status

        socketio.emit('esp32_status', {'status': new_status})
        socketio.sleep(STATUS_INTERVAL_SEC)

def keep_alive():
    print("Iniciando rotina de 'keep-alive'...")
    url = "http://localhost:" + str(APP_PORT)
    while True:
        try:
            requests.get(url)
            print("Keep-alive: requisição enviada com sucesso.")
        except Exception as e:
            print("Keep-alive: falha ao enviar requisição:", e)
        socketio.sleep(600)

@socketio.on('connect')
def handle_connect():
    if last_message_ts is None:
        status = "offline"
    else:
        delta = datetime.now(pytz.utc) - last_message_ts
        status = "online" if delta.total_seconds() < OFFLINE_THRESHOLD_SEC else "offline"
    socketio.emit('esp32_status', {'status': status})

# ---------------------------
# Rotas Flask
# ---------------------------
@app.route("/")
def index():
    return render_template("index.html", title="Monitoramento de Temperatura")

@app.route("/dados_iniciais")
def dados_iniciais():
    limite = int(request.args.get("limite", 300))
    rows = buscar_ultimos(limite)
    dados = [{"valor": r[0], "timestamp": r[1]} for r in rows]
    return jsonify({"dados": dados})

@app.route("/estatisticas")
def stats():
    inicio = request.args.get("inicio")
    fim = request.args.get("fim")
    if inicio and fim:
        return jsonify(estatisticas_periodo(inicio, fim))
    else:
        return jsonify(estatisticas_hoje())

@app.route("/historico_intervalo")
def historico_intervalo():
    inicio = request.args.get("inicio")
    fim = request.args.get("fim")
    limite = int(request.args.get("limite", 2000))
    if not inicio or not fim:
        return jsonify({"erro": "informe inicio e fim (YYYY-MM-DD)"}), 400
    rows = buscar_intervalo_data(inicio, fim, limite)
    dados = [{"valor": r[0], "timestamp": r[1]} for r in rows]
    return jsonify({"dados": dados})

# ---------------------------
# Run
# ---------------------------
if __name__ == "__main__":
    socketio.start_background_task(target=check_device_status)
    threading.Thread(target=keep_alive, daemon=True).start()
    socketio.run(app, host="0.0.0.0", port=APP_PORT)
