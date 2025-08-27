// ----------------- Estado -----------------
const socket = io();
let historicoCompleto = []; // todos os pontos carregados do backend (preload)
let tempoRealAtivo = true;  // se o usuário mexer no gráfico, desativa até clicar "Tempo real"
let janela = 20;            // quantidade de pontos exibidos no modo tempo real

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
const trace = {
  x: [],
  y: [],
  mode: 'lines+markers',
  name: 'Temperatura (°C)'
};

const layout = {
  margin: { t: 24, r: 18, b: 48, l: 54 },
  xaxis: { title: 'Data/Hora', type: 'date' },
  yaxis: { title: 'Temperatura (°C)' },
  dragmode: 'pan'
};

Plotly.newPlot('chart', [trace], layout, {responsive: true});

// Detecta interação do usuário (pan/zoom) e desativa “tempo real”
document.getElementById('chart').on('plotly_relayout', function(evt){
  // Só desativa se a mudança vier do usuário (tem xaxis.range etc.)
  if(evt['xaxis.range[0]'] || evt['xaxis.range[1]'] || evt['xaxis.autorange'] === false){
    tempoRealAtivo = false;
    statusTempoReal.classList.remove('on');
    statusTempoReal.textContent = "Modo: Histórico (pan/zoom)";
  }
});

// ----------------- Inicialização -----------------
(async function init(){
  try{
    console.log("CLOG :: fc init");

    // carrega um histórico grande para permitir pan/zoom sem clicks
    const res = await fetch('/dados_iniciais?preload=2000');
    const json = await res.json();

    historicoCompleto = json.dados.map(d => ({ x: new Date(d.timestamp), y: d.valor }));
    const ultimo = json.ultimo;
    const mediaDia = json.media_dia;

    // janela inicial
    janela = parseInt(inpJanela.value || "20", 10);
    const visivel = sliceUltimosN(historicoCompleto, janela);

    Plotly.react('chart', [{
      x: visivel.map(p => p.x),
      y: visivel.map(p => p.y),
      mode: 'lines+markers',
      name: 'Temperatura (°C)'
    }], layout);

    // Big numbers iniciais
    // média do período padrão (últimos 7 dias) virá de /estatisticas
    const est = await (await fetch('/estatisticas')).json();
    atualizarBigNumbers(ultimo, mediaDia, est.media_periodo);

  }catch(e){
    console.error("Falha ao inicializar:", e);
  }
})();

// ----------------- Tempo real (socket) -----------------
socket.on('nova_temperatura', (msg) => {
  console.log("CLOG :: fc nova_temperatura Tempo real");
  // adiciona no histórico completo
  const ponto = { x: new Date(msg.timestamp || Date.now()), y: msg.valor };
  historicoCompleto.push(ponto);
  

  // atualiza big number atual e média do dia (recalcular leve no cliente: opcional)
  elAtual.textContent = fmt(msg.valor);
  elAtualTs.textContent = "Atualizado: " + fmtTs(msg.timestamp || new Date().toISOString());

  // se tempo real está ativo, mostra janela deslizante (ponto atual + N anteriores)
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


// Listener para o status do ESP32
socket.on('esp32_status', (msg) => {
  console.log("CLOG :: fc esp32_status");
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
  const ini = document.getElementById('f_inicio').value; // YYYY-MM-DD
  const fim = document.getElementById('f_fim').value;   // YYYY-MM-DD
  const q = new URLSearchParams();
  if(ini) q.set('inicio', ini);
  if(fim) q.set('fim', fim);

  const url = '/estatisticas' + (q.toString() ? ('?' + q.toString()) : '');
  const est = await (await fetch(url)).json();
  atualizarBigNumbers(est.ultimo, est.media_dia, est.media_periodo);
});


