import os
import sqlite3
import threading
from datetime import datetime, date, timedelta
import pytz
import requests
import json
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
socketio = SocketIO(app, async_mode="threading", cors_allowed_origins="*")

# Variáveis globais para o status
last_message_ts = datetime.now(pytz.utc)
STATUS_INTERVAL_SEC = 50
OFFLINE_THRESHOLD_SEC = 100
current_device_status = ""
# Não precisamos mais do LOG_FILE, pois o log irá para o banco de dados
# LOG_FILE = "status_log.json"

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

def init_db(reset=True):
    conn = get_conn()
    cur = conn.cursor()
    if reset:
        cur.execute("DROP TABLE IF EXISTS leituras")
        cur.execute("DROP TABLE IF EXISTS status_log")

    # Tabela para as leituras de temperatura
    cur.execute("""
        CREATE TABLE IF NOT EXISTS leituras (
            id SERIAL PRIMARY KEY,
            valor REAL NOT NULL,
            timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Nova tabela para o log de status do dispositivo
    cur.execute("""
        CREATE TABLE IF NOT EXISTS status_log (
            id SERIAL PRIMARY KEY,
            status VARCHAR(20) NOT NULL,
            timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
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

# Inicializa DB (sem reset por padrão)
init_db(reset=False)

# ---------------------------
# Funções de Log (agora usam o banco de dados)
# ---------------------------
# A função get_status_log não é mais necessária, pois vamos inserir diretamente no DB.

def add_status_event(status, timestamp):
    """Adiciona um novo evento ao histórico no banco de dados."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT INTO status_log (status, timestamp) VALUES (%s, %s)", (status, timestamp))
    conn.commit()
    conn.close()
    print(f"Evento de status registrado: {status} em {timestamp}")

# ---------------------------
# MQTT (Paho)
# ---------------------------
def on_connect(client, userdata, flags, rc):
    print("Conectado ao broker MQTT com código:", rc)
    client.subscribe(MQTT_TOPIC)

def on_message(client, userdata, msg):
    try:
        global last_message_ts, current_device_status
        payload_str = msg.payload.decode().strip()
        valor = float(msg.payload.decode().strip())
        
        # Use o fuso horário de São Paulo para manter a consistência com sua localização
        brazil_tz = pytz.timezone('America/Sao_Paulo')
        ts = datetime.now(brazil_tz)
    
        salvar_leitura(valor, ts)  # aqui ts vai como datetime com fuso
        
        # Atualiza o timestamp da última mensagem
        last_message_ts = datetime.now(pytz.utc)

        # Checa e força a mudança de status caso ele estivesse offline
        if current_device_status == "offline" or current_device_status == "":
            timestamp = datetime.now().isoformat()
            add_status_event("online", timestamp)
            current_device_status = "online"
            
        # emite para todos os clientes conectados
        socketio.emit('nova_temperatura', {"valor": valor, "timestamp": ts})
        socketio.emit('esp32_status', {'status': 'online'}) # Envia o status online imediatamente

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
# Rotinas em background
# ---------------------------
def check_device_status():
    """Verifica o status do dispositivo e emite para o front-end, registrando mudanças."""
    global last_message_ts, current_device_status

    while True:
        delta = datetime.now(pytz.utc) - last_message_ts
        new_status = "online" if delta.total_seconds() < OFFLINE_THRESHOLD_SEC else "offline"

        # Detecta a mudança de status e registra no log
        # Só registra se o status mudou (ou na primeira execução)
        if new_status != current_device_status:
            timestamp = datetime.now().isoformat()
            add_status_event(new_status, timestamp)
            current_device_status = new_status

        # Envia o status para todos os clientes conectados
        socketio.emit('esp32_status', {'status': new_status})
        
        # Pausa para o próximo ciclo de verificação
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
    # Envia o status atual do dispositivo para o cliente que acabou de se conectar
    delta = datetime.now(pytz.utc) - last_message_ts
    status = "online" if delta.total_seconds() < OFFLINE_THRESHOLD_SEC else "offline"
    socketio.emit('esp32_status', {'status': status})

# ---------------------------
# Rotas
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
    # Inicie a tarefa de monitoramento do dispositivo (ESP32)
    socketio.start_background_task(target=check_device_status)

    # Inicie a tarefa de keep-alive para evitar inatividade na hospedagem
    threading.Thread(target=keep_alive, daemon=True).start()

    # Evita problemas em IDEs com reloader
    socketio.run(app, host="0.0.0.0", port=APP_PORT, debug=True, use_reloader=False, allow_unsafe_werkzeug=True)