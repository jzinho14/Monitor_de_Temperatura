// static/calibragem.js
(() => {
  if (window.__CAL_PAGE__) return;
  window.__CAL_PAGE__ = true;

  const socket = io();
  const chartsContainer = document.getElementById('chartsContainer');
  const statusESP32 = document.getElementById('statusESP32');
  const statusTempoReal = document.getElementById('statusTempoReal');

  const fInicio = document.getElementById('f_inicio');
  const fFim = document.getElementById('f_fim');
  const fSensor = document.getElementById('f_sensor');
  const btnAplicar = document.getElementById('btnAplicar');

  let tempoRealAtivo = true;
  const charts = new Map(); // sensor -> {divId, data[]}

  const baseLayout = {
    margin: { t: 24, r: 18, b: 48, l: 54 },
    xaxis: { title: 'Data/Hora', type: 'date' },
    yaxis: { title: 'Temperatura (¡C)' },
    dragmode: 'pan'
  };

  function ensureChart(sensor){
    if(charts.has(sensor)) return charts.get(sensor);
    const div = document.createElement('div');
    div.className = 'chart-item';
    div.id = `chart_${sensor}`;
    chartsContainer.appendChild(div);

    Plotly.newPlot(div.id, [{
      x: [], y: [], mode: 'lines+markers', name: sensor
    }], { ...baseLayout, title: `Sensor: ${sensor}` }, {responsive: true});

    // Se o usu‡rio fizer pan/zoom, desliga tempo real
    document.getElementById(div.id).on('plotly_relayout', (evt) => {
      if(evt['xaxis.range[0]'] || evt['xaxis.range[1]'] || evt['xaxis.autorange'] === false){
        tempoRealAtivo = false;
        statusTempoReal.classList.remove('on');
        statusTempoReal.textContent = "Hist—rico (pan/zoom)";
      }
    });

    const entry = { divId: div.id, data: [] };
    charts.set(sensor, entry);
    return entry;
  }

  function addPoint(sensor, ts, val){
    const c = ensureChart(sensor);
    c.data.push({ x: new Date(ts), y: val });
    if(tempoRealAtivo){
      Plotly.extendTraces(c.divId, {
        x: [[new Date(ts)]],
        y: [[val]]
      }, [0]);
    }
  }

  function redrawFull(sensor){
    const c = charts.get(sensor);
    if(!c) return;
    Plotly.react(c.divId, [{
      x: c.data.map(p => p.x),
      y: c.data.map(p => p.y),
      mode: 'lines+markers',
      name: sensor
    }], { ...baseLayout, title: `Sensor: ${sensor}` });
  }

  async function loadInitial(){
    try{
      const url = `/calibragem_dados?limite=1000`;
      const resp = await fetch(url);
      const j = await resp.json();
      const dados = j.dados || [];

      // Agrupa por sensor
      const group = {};
      for(const d of dados){
        const s = d.sensor;
        group[s] = group[s] || [];
        group[s].push({ x: new Date(d.timestamp), y: d.valor });
      }

      // Cria gr‡ficos e plota
      for(const sensor of Object.keys(group)){
        const c = ensureChart(sensor);
        c.data = group[sensor].sort((a,b)=>a.x-b.x);
        redrawFull(sensor);
      }
    }catch(e){
      console.error("Falha ao carregar hist—rico de calibra‹o:", e);
    }
  }

  btnAplicar.addEventListener('click', async () => {
    const ini = fInicio.value;
    const fim = fFim.value;
    const sensor = fSensor.value;

    try{
      let url = `/calibragem_dados?limite=5000`;
      if(sensor) url += `&sensor=${encodeURIComponent(sensor)}`;
      if(ini && fim) url += `&inicio=${ini}&fim=${fim}`;

      tempoRealAtivo = false;
      statusTempoReal.classList.remove('on');
      statusTempoReal.textContent = "Hist—rico (pan/zoom)";

      const resp = await fetch(url);
      const j = await resp.json();
      const dados = j.dados || [];

      // Limpa estrutura
      charts.clear();
      chartsContainer.innerHTML = "";

      const group = {};
      for(const d of dados){
        const s = d.sensor;
        group[s] = group[s] || [];
        group[s].push({ x: new Date(d.timestamp), y: d.valor });
      }

      for(const s of Object.keys(group)){
        const c = ensureChart(s);
        c.data = group[s].sort((a,b)=>a.x-b.x);
        redrawFull(s);
      }
    }catch(e){
      console.error("Falha ao aplicar filtro:", e);
    }
  });

  // SocketIO: status
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

  // SocketIO: nova calibra‹o (um sensor por evento)
  socket.on('nova_calibragem', (msg) => {
    // msg = { sensor, valor, timestamp }
    if(!msg || !msg.sensor) return;
    if(!tempoRealAtivo) return; // em hist—rico n‹o atualiza
    addPoint(msg.sensor, msg.timestamp || Date.now(), msg.valor);
  });

  // Inicializa
  loadInitial();
})();
