from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO
import sqlite3
import threading
import paho.mqtt.client as mqtt
import time
import os

app = Flask(__name__)
socketio = SocketIO(app)

DB_FILE = 'leituras.db'
MQTT_TOPIC = "joao/teste/temperatura"

# --- Cria/Reseta a tabela do banco ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS leituras")
    cursor.execute("""
        CREATE TABLE leituras (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            valor REAL NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()
    print("Banco resetado e tabela criada!")

init_db()

# --- Função para salvar leitura ---
def salvar_leitura(valor):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO leituras (valor) VALUES (?)", (valor,))
    conn.commit()
    conn.close()

# --- MQTT ---
MQTT_BROKER = "f67708c3dd0e4e38822956f08a661bd7.s1.eu.hivemq.cloud"
MQTT_PORT = 8883
MQTT_USER = "joao_senac"
MQTT_PASSWORD = "Senac_FMABC_7428"

def on_connect(client, userdata, flags, rc):
    print("Conectado ao broker MQTT com código:", rc)
    client.subscribe(MQTT_TOPIC)

def on_message(client, userdata, msg):
    try:
        payload = float(msg.payload.decode())
        salvar_leitura(payload)
        socketio.emit('nova_temperatura', {'valor': payload})
    except:
        print("Erro ao processar mensagem MQTT")

mqtt_client = mqtt.Client()
mqtt_client.username_pw_set(MQTT_USER, MQTT_PASSWORD)
mqtt_client.tls_set()
mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message

def mqtt_loop():
    mqtt_client.connect(MQTT_BROKER, MQTT_PORT)
    mqtt_client.loop_forever()

threading.Thread(target=mqtt_loop, daemon=True).start()

# --- Rotas Flask ---
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/historico")
def historico():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT valor, timestamp FROM leituras ORDER BY id DESC LIMIT 1000")
    dados = cursor.fetchall()
    conn.close()
    dados.reverse()  # Ordem cronológica
    return jsonify(dados)

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True, use_reloader=False)