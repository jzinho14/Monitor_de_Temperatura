// static/calibragem.js
(() => {
  if (window.__CAL_PAGE__) return;
  window.__CAL_PAGE__ = true;

  const socket = io();
  const chartsContainer = document.getElementById('chartsContainer');
  const bigNumbersContainer = document.getElementById('bigNumbers');
  const statusESP32 = document.getElementById('statusESP32');
  const statusTempoReal = document.getElementById('statusTempoReal');

  const fInicio = document.getElementById('f_inicio');
  const fFim = document.getElementById('f_fim');
  const fSensor = document.getElementById('f_sensor');
  const btnAplicar = document.getElementById('btnAplicar');

  let tempoRealAtivo = true;
  const charts = new Map();
  // Novo Map para rastrear o estado de visibilidade dos gr‡ficos
  const chartVisibility = new Map();

  const baseLayout = {
    margin: { t: 28, r: 18, b: 50, l: 60 },
    xaxis: { title: 'Data/Hora', type: 'date' },
    // Corrigindo o s’mbolo de graus aqui tambŽm, por segurana
    yaxis: { title: 'Temperatura (\u00B0C)' },
    dragmode: 'pan',
    plot_bgcolor: 'var(--card)',
    paper_bgcolor: 'var(--card)',
    font: {
      color: 'var(--text)'
    }
  };

  // Fun‹o para alternar a visibilidade de um gr‡fico
  function toggleChartVisibility(sensor) {
    const isVisible = chartVisibility.get(sensor);
    const chartDiv = document.getElementById(`chart_${sensor}`);
    const bigCard = document.getElementById(`bn_${sensor}`);

    if (isVisible) {
      chartDiv.style.display = 'none';
      bigCard.classList.remove('selected');
      chartVisibility.set(sensor, false);
    } else {
      chartDiv.style.display = 'block';
      bigCard.classList.add('selected');
      chartVisibility.set(sensor, true);
    }
  }

  function ensureChart(sensor) {
    if (charts.has(sensor)) return charts.get(sensor);

    const div = document.createElement('div');
    div.className = 'chart-item';
    div.id = `chart_${sensor}`;
    // Gr‡ficos comeam escondidos para n‹o poluir a tela
    div.style.display = 'none';
    chartsContainer.appendChild(div);

    Plotly.newPlot(div.id, [{
      x: [],
      y: [],
      mode: 'lines+markers',
      name: sensor
    }], { ...baseLayout,
      title: `Sensor: ${sensor}`
    }, {
      responsive: true
    });

    document.getElementById(div.id).on('plotly_relayout', (evt) => {
      if (evt['xaxis.range[0]'] || evt['xaxis.range[1]'] || evt['xaxis.autorange'] === false) {
        tempoRealAtivo = false;
        statusTempoReal.classList.remove('on');
        statusTempoReal.textContent = "Hist—rico (pan/zoom)";
      }
    });

    const entry = {
      divId: div.id,
      data: []
    };
    charts.set(sensor, entry);
    // Por padr‹o, um novo sensor n‹o est‡ vis’vel
    chartVisibility.set(sensor, false);
    return entry;
  }

function addPoint(sensor, ts, val) {
  const c = ensureChart(sensor);

  // Adiciona o novo ponto ao nosso array de dados interno
  c.data.push({
    x: new Date(ts),
    y: val
  });

  // Se estivermos em modo tempo real, atualiza o gr‡fico
  if (tempoRealAtivo) {
    
    // 1. Garante que nosso array de dados em mem—ria n‹o cresa para sempre.
    // Se tiver mais de 20 pontos, removemos o mais antigo (o primeiro do array).
    if (c.data.length > 20) {
      c.data.shift();
    }
    
    // 2. Usa o recurso do Plotly para limitar os pontos na TELA.
    // O quarto par‰metro '20' diz ao Plotly para manter no m‡ximo 20 pontos vis’veis.
    Plotly.extendTraces(c.divId, {
      x: [
        [new Date(ts)]
      ],
      y: [
        [val]
      ]
    }, [0], 20); // <-- A MçGICA ACONTECE AQUI!

  }
}

  function redrawFull(sensor) {
    const c = charts.get(sensor);
    if (!c) return;
    Plotly.react(c.divId, [{
      x: c.data.map(p => p.x),
      y: c.data.map(p => p.y),
      mode: 'lines+markers',
      name: sensor
    }], { ...baseLayout,
      title: `Sensor: ${sensor}`
    });
  }

  function updateBigNumber(sensor, valor) {
    let card = document.getElementById("bn_" + sensor);
    if (!card) {
      card = document.createElement("div");
      card.className = "big-card";
      card.id = "bn_" + sensor;
      card.innerHTML = `
          <div class="title">${sensor}</div>
          <div class="value">--</div>
        `;
      // Adiciona o evento de clique para exibir/ocultar o gr‡fico
      card.addEventListener('click', () => toggleChartVisibility(sensor));
      bigNumbersContainer.appendChild(card);
    }
    // *** AQUI ESTç A CORRE‚ÌO DO SêMBOLO DE GRAUS ***
    // Usamos o caractere ¡ ou o c—digo unicode \u00B0
    card.querySelector(".value").textContent = `${valor.toFixed(2)} \u00B0C`;
  }
  
  // As demais fun›es (loadInitial, btnAplicar, listeners do socket) permanecem as mesmas.
  // ... (Cole o resto do seu c—digo JS aqui)
  // ...
  // ...

  socket.on('nova_calibragem', (msg) => {
    if(!msg || !msg.sensor) return;
    addPoint(msg.sensor, msg.timestamp || Date.now(), msg.valor);
    updateBigNumber(msg.sensor, msg.valor);
  });


  async function loadInitial(){
    try{
      const url = `/calibragem_dados?limite=1000`;
      const resp = await fetch(url);
      const j = await resp.json();
      const dados = j.dados || [];

      const group = {};
      for(const d of dados){
        const s = d.sensor;
        group[s] = group[s] || [];
        group[s].push({ x: new Date(d.timestamp), y: d.valor });
      }
      
      // Limpa os cards de sensores antigos antes de carregar novos
      bigNumbersContainer.innerHTML = '';
      
      for(const sensor of Object.keys(group)){
        const c = ensureChart(sensor);
        c.data = group[sensor].sort((a,b)=>a.x-b.x);
        redrawFull(sensor);
        // Atualiza o "big number" com o valor mais recente
        const ultimoValor = c.data[c.data.length - 1].y;
        updateBigNumber(sensor, ultimoValor);
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

      charts.clear();
      chartsContainer.innerHTML = "";
      bigNumbersContainer.innerHTML = ""; // Limpa os cards tambŽm

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
        const ultimoValor = c.data[c.data.length - 1].y;
        updateBigNumber(s, ultimoValor);
      }
    }catch(e){
      console.error("Falha ao aplicar filtro:", e);
    }
  });

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

  // O segundo listener 'nova_calibragem' parece redundante.
  // O primeiro j‡ faz o addPoint e o updateBigNumber.
  // Vou comentar este para evitar processamento duplicado.
  /*
  socket.on('nova_calibragem', (msg) => {
    if(!msg || !msg.sensor) return;
    if(!tempoRealAtivo) return;
    addPoint(msg.sensor, msg.timestamp || Date.now(), msg.valor);
  });
  */

  loadInitial();
})();