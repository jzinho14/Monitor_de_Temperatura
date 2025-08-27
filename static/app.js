// ----------------- Estado -----------------
const socket = io();
let historicoCompleto = []; 
let tempoRealAtivo = true;  
let janela = 20;            

const elAtual = document.getElementById("bn_atual");
const elAtualTs = document.getElementById("bn_atual_ts");
const elMediaDia = document.getElementById("bn_media_dia");
const elMediaPeriodo = document.getElementById("bn_media_periodo");

const btnTempoReal = document.getElementById("btnTempoReal");
const statusTempoReal = document.getElementById("statusTempoReal");
const inpJanela = document.getElementById("inpJanela");
const btnAplicar = document.getElementById("btnAplicar");

const statusESP32 = document.getElementById("statusESP32");

// ----------------- Helpers -----------------
function fmt(n){
  if(n === null || n === undefined || isNaN(n)) return "--";
  return Number(n).toFixed(1) + " °C";
}
function fmtTs(iso){
  if(!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString();
}
function sliceUltimosN(arr, n){
  return arr.slice(Math.max(0, arr.length - n));
}
function atualizarBigNumbers(ultimo, mediaDia, mediaPeriodo){
  elAtual.textContent = ultimo ? fmt(ultimo.valor) : "--";
  elAtualTs.textContent = ultimo ? ("Atualizado: " + fmtTs(ultimo.timestamp)) : "—";
  elMediaDia.textContent = fmt(mediaDia);
  elMediaPeriodo.textContent = fmt(mediaPeriodo);
}

// ----------------- Gráfico -----------------
const layout = {
  margin: { t: 24, r: 18, b: 48, l: 54 },
  xaxis: { title: 'Data/Hora', type: 'date' },
  yaxis: { title: 'Temperatura (°C)' },
  dragmode: 'pan'
};

Plotly.newPlot('chart', [{
  x: [],
  y: [],
  mode: 'lines+markers',
  name: 'Temperatura (°C)'
}], layout, {responsive: true});

// Detecta interação do usuário (pan/zoom) e desativa tempo real
document.getElementById('chart').on('plotly_relayout', function(evt){
  if(evt['xaxis.range[0]'] || evt['xaxis.range[1]'] || evt['xaxis.autorange'] === false){
    tempoRealAtivo = false;
    statusTempoReal.classList.remove('on');
    statusTempoReal.textContent = "Modo: Histórico (pan/zoom)";
  }
});

// ----------------- Inicialização -----------------
(async function init(){
  try{
    const res = await fetch('/dados_iniciais?preload=2000');
    const json = await res.json();

    historicoCompleto = json.dados.map(d => ({ x: new Date(d.timestamp), y: d.valor }));
    const ultimo = json.ultimo;
    const mediaDia = json.media_dia;

    janela = parseInt(inpJanela.value || "20", 10);
    const visivel = sliceUltimosN(historicoCompleto, janela);

    Plotly.react('chart', [{
      x: visivel.map(p => p.x),
      y: visivel.map(p => p.y),
      mode: 'lines+markers',
      name: 'Temperatura (°C)'
    }], layout);

    const est = await (await fetch('/estatisticas')).json();
    atualizarBigNumbers(ultimo, mediaDia, est.media_periodo);

  }catch(e){
    console.error("Falha ao inicializar:", e);
  }
})();

// ----------------- Tempo real (socket) -----------------
socket.on('nova_temperatura', (msg) => {
  const ponto = { x: new Date(msg.timestamp || Date.now()), y: msg.valor };
  historicoCompleto.push(ponto);

  // Atualiza big numbers
  elAtual.textContent = fmt(msg.valor);
  elAtualTs.textContent = "Atualizado: " + fmtTs(msg.timestamp || new Date().toISOString());

  // Atualiza gráfico em tempo real
  if(tempoRealAtivo){
    const visivel = sliceUltimosN(historicoCompleto, janela);
    Plotly.react('chart', [{
      x: visivel.map(p => p.x),
      y: visivel.map(p => p.y),
      mode: 'lines+markers',
      name: 'Temperatura (°C)'
    }], layout);
  }
});

// ----------------- Status ESP32 -----------------
socket.on('esp32_status', (msg) => {
  if (msg.status === 'online') {
    statusESP32.textContent = "ESP32: Online";
    statusESP32.classList.remove("offline");
    statusESP32.classList.add("online");
  } else {
    statusESP32.textContent = "ESP32: Offline";
    statusESP32.classList.remove("online");
    statusESP32.classList.add("offline");
  }
});

// ----------------- Controles -----------------
btnTempoReal.addEventListener('click', () => {
  tempoRealAtivo = true;
  statusTempoReal.classList.add('on');
  statusTempoReal.textContent = "Modo: Tempo real";
  janela = parseInt(inpJanela.value || "20", 10);

  const visivel = sliceUltimosN(historicoCompleto, janela);
  Plotly.react('chart', [{
    x: visivel.map(p => p.x),
    y: visivel.map(p => p.y),
    mode: 'lines+markers',
    name: 'Temperatura (°C)'
  }], layout);
});

inpJanela.addEventListener('change', () => {
  janela = parseInt(inpJanela.value || "20", 10);
  if(tempoRealAtivo){
    const visivel = sliceUltimosN(historicoCompleto, janela);
    Plotly.react('chart', [{
      x: visivel.map(p => p.x),
      y: visivel.map(p => p.y),
      mode: 'lines+markers',
      name: 'Temperatura (°C)'
    }], layout);
  }
});

btnAplicar.addEventListener('click', async () => {
  const ini = document.getElementById('f_inicio').value; 
  const fim = document.getElementById('f_fim').value;   
  if (!ini || !fim) return alert("Informe as duas datas!");

  const url = `/historico_intervalo?inicio=${ini}&fim=${fim}&limite=2000`;
  const est = await (await fetch(url)).json();

  historicoCompleto = est.dados.map(d => ({ x: new Date(d.timestamp), y: d.valor }));
  Plotly.react('chart', [{
    x: historicoCompleto.map(p => p.x),
    y: historicoCompleto.map(p => p.y),
    mode: 'lines+markers',
    name: 'Temperatura (°C)'
  }], layout);
});
