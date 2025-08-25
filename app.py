import os
import sqlite3
import threading
from datetime import datetime, date

from flask import Flask, jsonify, render_template, request
from flask_socketio import SocketIO
import paho.mqtt.client as mqtt

# ---------------------------
# Configuração básica
# ---------------------------
APP_PORT = int(os.environ.get("PORT", 5000))
DB_FILE = os.environ.get("DB_FILE", "leituras.db")

MQTT_BROKER = os.environ.get("MQTT_BROKER", "f67708c3dd0e4e38822956f08a661bd7.s1.eu.hivemq.cloud")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "8883"))
MQTT_USER = os.environ.get("MQTT_USER", "joao_senac")
MQTT_PASSWORD = os.environ.get("MQTT_PASSWORD", "Senac_FMABC_7428")
MQTT_TOPIC = os.environ.get("MQTT_TOPIC", "joao/teste/temperatura")

app = Flask(__name__)
# Forçamos threading para evitar dores com eventlet/gevent em ambientes diversos
socketio = SocketIO(app, async_mode="threading", cors_allowed_origins="*")

# ---------------------------
# Banco de dados (SQLite)
# ---------------------------
def get_conn():
    # check_same_thread=False permite uso básico em threads diferentes
    return sqlite3.connect(DB_FILE, check_same_thread=False)

def init_db(reset=False):
    conn = get_conn()
    cur = conn.cursor()
    if reset:
        cur.execute("DROP TABLE IF EXISTS leituras")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS leituras (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            valor REAL NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def salvar_leitura(valor, ts=None):
    conn = get_conn()
    cur = conn.cursor()
    if ts is None:
        cur.execute("INSERT INTO leituras (valor) VALUES (?)", (valor,))
    else:
        cur.execute("INSERT INTO leituras (valor, timestamp) VALUES (?, ?)", (valor, ts))
    conn.commit()
    conn.close()

def buscar_ultimos(limite=200):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT valor, timestamp FROM leituras ORDER BY id DESC LIMIT ?", (limite,))
    rows = cur.fetchall()
    conn.close()
    rows.reverse()  # cronológico crescente
    return rows

def estatisticas_hoje():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT AVG(valor), COUNT(*)
        FROM leituras
        WHERE DATE(timestamp) = DATE('now', 'localtime')
    """)
    avg_val, count_val = cur.fetchone()
    # Última leitura
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
    # inicio_iso & fim_iso no formato YYYY-MM-DD
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT AVG(valor), COUNT(*)
        FROM leituras
        WHERE DATE(timestamp) >= DATE(?) AND DATE(timestamp) <= DATE(?)
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
        WHERE DATE(timestamp) >= DATE(?) AND DATE(timestamp) <= DATE(?)
        ORDER BY timestamp ASC
        LIMIT ?
    """, (inicio_iso, fim_iso, limite))
    rows = cur.fetchall()
    conn.close()
    return rows

# Inicializa DB (sem reset por padrão)
init_db(reset=False)

# ---------------------------
# MQTT (Paho)
# ---------------------------
def on_connect(client, userdata, flags, rc):
    print("Conectado ao broker MQTT com código:", rc)
    client.subscribe(MQTT_TOPIC)

def on_message(client, userdata, msg):
    try:
        payload_str = msg.payload.decode().strip()
        valor = float(payload_str)
        # timestamp de servidor para manter consistência
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        salvar_leitura(valor, ts)
        # emite para todos os clientes conectados
        socketio.emit('nova_temperatura', {"valor": valor, "timestamp": ts})
    except Exception as e:
        print("Erro ao processar mensagem MQTT:", e)

mqtt_client = mqtt.Client()
mqtt_client.username_pw_set(MQTT_USER, MQTT_PASSWORD)
mqtt_client.tls_set()  # HiveMQ Cloud usa TLS
mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message

def mqtt_loop():
    mqtt_client.connect(MQTT_BROKER, MQTT_PORT)
    mqtt_client.loop_forever()

threading.Thread(target=mqtt_loop, daemon=True).start()

# ---------------------------
# Rotas
# ---------------------------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/dados_iniciais")
def dados_iniciais():
    # últimos N (padrão 300) para encher o gráfico e permitir zoom
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
    # Evita problemas em IDEs com reloader
    socketio.run(app, host="0.0.0.0", port=APP_PORT, debug=True, use_reloader=False, allow_unsafe_werkzeug=True)

