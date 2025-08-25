import os
import sqlite3
import threading
from datetime import datetime, date, timedelta
import pytz
import requests
import json # Importamos a biblioteca para JSON

from flask import Flask, jsonify, render_template, request
from flask_socketio import SocketIO
import paho.mqtt.client as mqtt

# Nome do arquivo de log que será gerado
LOG_FILE = "status_log.json" 

# Variáveis globais para o status
last_message_ts = datetime.now(pytz.utc)
STATUS_INTERVAL_SEC = 10
OFFLINE_THRESHOLD_SEC = 30

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
        global last_message_ts, current_device_status
        payload_str = msg.payload.decode().strip()
        valor = float(payload_str)
        
        # Use o fuso horário de São Paulo para manter a consistência com sua localização
        brazil_tz = pytz.timezone('America/Sao_Paulo')
        ts = datetime.now(brazil_tz).strftime("%Y-%m-%d %H:%M:%S")

        salvar_leitura(valor, ts)
        
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
mqtt_client.tls_set()  # HiveMQ Cloud usa TLS
mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message

def mqtt_loop():
    mqtt_client.connect(MQTT_BROKER, MQTT_PORT)
    mqtt_client.loop_forever()

threading.Thread(target=mqtt_loop, daemon=True).start()


def get_status_log():
    """Carrega o histórico de status do arquivo JSON."""
    if not os.path.exists(LOG_FILE):
        return []
    with open(LOG_FILE, "r") as f:
        return json.load(f)

def add_status_event(status, timestamp):
    """Adiciona um novo evento ao histórico e salva no arquivo."""
    log = get_status_log()
    log.append({"status": status, "timestamp": timestamp})
    with open(LOG_FILE, "w") as f:
        json.dump(log, f, indent=4)
    print(f"Evento de status registrado: {status} em {timestamp}")


# Variável global para armazenar o último status conhecido
current_device_status = "" # Alteramos o valor inicial para uma string vazia

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
        
        
@socketio.on('connect')
def handle_connect():
    # Envia o status atual do dispositivo para o cliente que acabou de se conectar
    delta = datetime.now(pytz.utc) - last_message_ts
    status = "online" if delta.total_seconds() < OFFLINE_THRESHOLD_SEC else "offline"
    socketio.emit('esp32_status', {'status': status})
    
        
def keep_alive():
    """Mantém a aplicação ativa enviando requisições a si mesma."""
    print("Iniciando rotina de 'keep-alive'...")
    url = "http://localhost:" + str(APP_PORT)
    while True:
        try:
            requests.get(url)
            print("Keep-alive: requisição enviada com sucesso.")
        except Exception as e:
            print("Keep-alive: falha ao enviar requisição:", e)
        # Envia a cada 10 minutos
        socketio.sleep(600)
        

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
    # Inicie a tarefa de monitoramento do dispositivo (ESP32)
    socketio.start_background_task(target=check_device_status)
    

    # Inicie a tarefa de keep-alive para evitar inatividade na hospedagem
    threading.Thread(target=keep_alive, daemon=True).start()
    

    # Evita problemas em IDEs com reloader
    socketio.run(app, host="0.0.0.0", port=APP_PORT, debug=True, use_reloader=False, allow_unsafe_werkzeug=True)

