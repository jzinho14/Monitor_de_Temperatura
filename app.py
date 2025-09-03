# app.py
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
import json

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
MQTT_TOPIC_CAL = os.environ.get("MQTT_TOPIC_CAL", "joao/teste/calibragem")

app = Flask(__name__, template_folder="templates", static_folder="static")

socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# ---------------------------
# Variáveis globais de status (MODIFICADO)
# ---------------------------
STATUS_INTERVAL_SEC = 15  # Diminuí o intervalo para uma resposta mais rápida
OFFLINE_THRESHOLD_SEC = 45

# NOVO: Dicionário para rastrear o status de múltiplos dispositivos.
# Estrutura: { 'device_id': {'last_ts': datetime, 'status': 'online'/'offline'} }
device_statuses = {}
# NOVO: Lock para garantir acesso seguro ao dicionário por múltiplas threads
status_lock = threading.Lock()


# ---------------------------
# Banco de dados (sem alterações)
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
        cur.execute("DROP TABLE IF EXISTS calibragem")
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
            device_id VARCHAR(50) NOT NULL,
            status VARCHAR(20) NOT NULL,
            timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS calibragem (
            id SERIAL PRIMARY KEY,
            sensor VARCHAR(50) NOT NULL,
            valor REAL NOT NULL,
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

def salvar_calibragem(sensor, valor, ts=None):
    conn = get_conn()
    cur = conn.cursor()
    if ts is None:
        cur.execute("INSERT INTO calibragem (sensor, valor) VALUES (%s, %s)", (sensor, valor))
    else:
        cur.execute("INSERT INTO calibragem (sensor, valor, timestamp) VALUES (%s, %s, %s)", (sensor, valor, ts))
    conn.commit()
    conn.close()

# ... (demais funções de banco de dados sem alteração) ...
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

def buscar_calibragem(limite=1000, sensor=None):
    conn = get_conn()
    cur = conn.cursor()
    if sensor:
        cur.execute("""
            SELECT sensor, valor, timestamp
            FROM calibragem
            WHERE sensor = %s
            ORDER BY id DESC
            LIMIT %s
        """, (sensor, limite))
    else:
        cur.execute("""
            SELECT sensor, valor, timestamp
            FROM calibragem
            ORDER BY id DESC
            LIMIT %s
        """, (limite,))
    rows = cur.fetchall()
    conn.close()
    rows.reverse()
    return rows

def buscar_calibragem_intervalo(inicio_iso, fim_iso, limite=5000, sensor=None):
    conn = get_conn()
    cur = conn.cursor()
    if sensor:
        cur.execute("""
            SELECT sensor, valor, timestamp
            FROM calibragem
            WHERE DATE(timestamp) >= DATE(%s) AND DATE(timestamp) <= DATE(%s)
              AND sensor = %s
            ORDER BY timestamp ASC
            LIMIT %s
        """, (inicio_iso, fim_iso, sensor, limite))
    else:
        cur.execute("""
            SELECT sensor, valor, timestamp
            FROM calibragem
            WHERE DATE(timestamp) >= DATE(%s) AND DATE(timestamp) <= DATE(%s)
            ORDER BY timestamp ASC
            LIMIT %s
        """, (inicio_iso, fim_iso, limite))
    rows = cur.fetchall()
    conn.close()
    return rows

init_db(reset=False)

# ---------------------------
# Log de status (MODIFICADO)
# ---------------------------
def add_status_event(device_id, status, timestamp): # MODIFICADO para aceitar device_id
    conn = get_conn()
    cur = conn.cursor()
    # Adicionamos a coluna device_id na tabela status_log
    cur.execute("INSERT INTO status_log (device_id, status, timestamp) VALUES (%s, %s, %s)", (device_id, status, timestamp))
    conn.commit()
    conn.close()
    print(f"Evento de status registrado: {device_id} -> {status} em {timestamp}")

# ---------------------------
# MQTT (MODIFICADO)
# ---------------------------
def on_connect(client, userdata, flags, rc):
    print("Conectado ao broker MQTT com código:", rc)
    client.subscribe(MQTT_TOPIC)
    client.subscribe(MQTT_TOPIC_CAL)

def on_message(client, userdata, msg):
    try:
        payload = msg.payload.decode().strip()
        brazil_tz = pytz.timezone('America/Sao_Paulo')
        ts = datetime.now(brazil_tz)
        device_id = None # MODIFICADO

        if msg.topic == MQTT_TOPIC:
            device_id = "main_esp" # ID fixo para o monitor principal
            valor = float(payload)
            salvar_leitura(valor, ts)
            socketio.emit('nova_temperatura', {"valor": valor, "timestamp": ts.isoformat()})

        elif msg.topic == MQTT_TOPIC_CAL:
            if ":" in payload:
                nome, val = payload.split(":", 1)
                device_id = nome.strip() # O ID do dispositivo é o nome do sensor
                try:
                    v = float(val)
                    salvar_calibragem(device_id, v, ts)
                    socketio.emit('nova_calibragem', {
                        "sensor": device_id,
                        "valor": v,
                        "timestamp": ts.isoformat()
                    })
                except ValueError:
                    print("Valor inválido na calibração:", payload)
            else:
                print("Formato inesperado na calibração:", payload)
        
        # NOVO: Bloco de atualização de status individual
        if device_id:
            with status_lock:
                # Se for a primeira mensagem deste dispositivo, inicializa seu status
                if device_id not in device_statuses:
                    device_statuses[device_id] = {'last_ts': None, 'status': 'offline'}

                old_status = device_statuses[device_id]['status']
                device_statuses[device_id]['last_ts'] = datetime.now(pytz.utc)
                device_statuses[device_id]['status'] = 'online'
            
            # Se o status mudou de offline para online, registra e emite
            if old_status == 'offline':
                add_status_event(device_id, "online", ts.isoformat())
                # NOVO: Evento de status específico para o dispositivo
                socketio.emit('device_status_update', {'device_id': device_id, 'status': 'online'})


    except Exception as e:
        print("Erro ao processar mensagem MQTT:", e)

# ... (configuração do mqtt_client sem alterações) ...
mqtt_client = mqtt.Client()
mqtt_client.username_pw_set(MQTT_USER, MQTT_PASSWORD)
mqtt_client.tls_set()
mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message

threading.Thread(target=mqtt_client.loop_forever, daemon=True).start()

# ---------------------------
# Rotinas de background (MODIFICADO)
# ---------------------------
# NOVO: Função de verificação de status refatorada
def background_status_checker():
    """Verifica o status de todos os dispositivos conhecidos periodicamente."""
    while True:
        now_utc = datetime.now(pytz.utc)
        
        with status_lock:
            # Itera sobre uma cópia das chaves para poder modificar o dict
            device_ids = list(device_statuses.keys())

            for device_id in device_ids:
                device_info = device_statuses[device_id]
                last_ts = device_info.get('last_ts')
                current_status = device_info.get('status')

                if last_ts is None:
                    new_status = "offline"
                else:
                    delta = now_utc - last_ts
                    new_status = "online" if delta.total_seconds() < OFFLINE_THRESHOLD_SEC else "offline"

                # Se o status mudou, atualiza e notifica
                if new_status != current_status:
                    device_statuses[device_id]['status'] = new_status
                    timestamp = datetime.now().isoformat()
                    add_status_event(device_id, new_status, timestamp)
                    socketio.emit('device_status_update', {'device_id': device_id, 'status': new_status})
        
        socketio.sleep(STATUS_INTERVAL_SEC)


@socketio.on('connect')
def handle_connect():
    # NOVO: Envia o status atual de todos os dispositivos conhecidos quando um cliente se conecta
    with status_lock:
        for device_id, info in device_statuses.items():
            socketio.emit('device_status_update', {'device_id': device_id, 'status': info['status']})


# ---------------------------
# Rotas Flask (sem alterações, exceto a remoção do 'keep_alive' que não é ideal)
# ---------------------------
@app.route("/")
def index():
    return render_template("index.html", title="Monitoramento de Temperatura")

# ... (demais rotas sem alterações) ...
@app.route("/dados_iniciais")
def dados_iniciais():
    limite = int(request.args.get("preload", request.args.get("limite", 300)))
    rows = buscar_ultimos(limite)
    dados = [{"valor": r[0], "timestamp": r[1]} for r in rows]
    est = estatisticas_hoje()
    ultimo = est["atual"]
    return jsonify({
        "dados": dados,
        "ultimo": ultimo,
        "media_dia": est["media_hoje"]
    })

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

@app.route("/calibragem")
def calibragem():
    return render_template("calibragem.html", title="Calibração dos Sensores")

@app.route("/calibragem_dados")
def calibragem_dados():
    sensor = request.args.get("sensor")
    inicio = request.args.get("inicio")
    fim    = request.args.get("fim")
    limite = int(request.args.get("limite", 2000))

    if inicio and fim:
        rows = buscar_calibragem_intervalo(inicio, fim, limite, sensor)
    else:
        rows = buscar_calibragem(limite, sensor)

    out = [{"sensor": r[0], "valor": r[1], "timestamp": r[2]} for r in rows]
    return jsonify({"dados": out})


# ---------------------------
# Run (MODIFICADO)
# ---------------------------
if __name__ == "__main__":
    # Substituímos a tarefa de background pela nova função
    socketio.start_background_task(target=background_status_checker)
    socketio.run(app, host="0.0.0.0", port=APP_PORT, allow_unsafe_werkzeug=True)