// static/app.js
(() => {
  if (window.__APP_LOADED__) return;
  window.__APP_LOADED__ = true;

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
  
  function fmt(n){
    if(n === null || n === undefined || isNaN(n)) return "--";
    return Number(n).toFixed(1) + "\u00B0C";   // usa escape Unicode
  }

  function fmtTs(iso){
    if(!iso) return "Ñ";
    const d = new Date(iso);
    return d.toLocaleString();
  }
  function sliceUltimosN(arr, n){ return arr.slice(Math.max(0, arr.length - n)); }
  function atualizarBigNumbers(ultimo, mediaDia, mediaPeriodo){
    elAtual.textContent = ultimo && ultimo.valor != null ? fmt(ultimo.valor) : "--";
    elAtualTs.textContent = ultimo && ultimo.timestamp ? ("Atualizado: " + fmtTs(ultimo.timestamp)) : "Ñ";
    elMediaDia.textContent = mediaDia != null ? fmt(mediaDia) : "--";
    elMediaPeriodo.textContent = mediaPeriodo != null ? fmt(mediaPeriodo) : "--";
  }

  const layout = {
    margin: { t: 24, r: 18, b: 48, l: 54 },
    xaxis: { title: 'Data/Hora', type: 'date' },
    yaxis: { title: 'Temperatura (\u00B0C)' },
    dragmode: 'pan'
  };

  Plotly.newPlot('chart', [{
    x: [], y: [], mode: 'lines+markers', name: 'Temperatura (¡C)'
  }], layout, {responsive: true});

  document.getElementById('chart').on('plotly_relayout', function(evt){
    if(evt['xaxis.range[0]'] || evt['xaxis.range[1]'] || evt['xaxis.autorange'] === false){
      tempoRealAtivo = false;
      statusTempoReal.classList.remove('on');
      statusTempoReal.textContent = "Modo: Hist—rico (pan/zoom)";
    }
  });

  (async function init(){
    try{
      let res = await fetch('/dados_iniciais?preload=2000');
      if(!res.ok) res = await fetch('/dados_iniciais?limite=2000');
      const json = await res.json();

      const dados = json.dados || [];
      historicoCompleto = dados.map(d => ({ x: new Date(d.timestamp), y: d.valor }));

      const ultimoCalc = historicoCompleto.length
        ? { valor: historicoCompleto[historicoCompleto.length-1].y, timestamp: historicoCompleto[historicoCompleto.length-1].x }
        : null;

      let mediaDia = null, mediaPeriodo = null, ultimo = null;
      try{
        const est = await (await fetch('/estatisticas')).json();
        mediaDia = est.media_hoje ?? est.mediaDia ?? json.media_dia ?? null;
        mediaPeriodo = est.media_periodo ?? null;
        ultimo = est.atual || json.ultimo || ultimoCalc || null;
      }catch(e){
        ultimo = json.ultimo || ultimoCalc || null;
      }

      atualizarBigNumbers(ultimo, mediaDia, mediaPeriodo);

      janela = parseInt(inpJanela.value || "20", 10);
      const visivel = sliceUltimosN(historicoCompleto, janela);
      Plotly.react('chart', [{
        x: visivel.map(p => p.x),
        y: visivel.map(p => p.y),
        mode: 'lines+markers',
        name: 'Temperatura (¡C)'
      }], layout);

    }catch(e){
      console.error("Falha ao inicializar:", e);
    }
  })();

  socket.on('nova_temperatura', (msg) => {
    const ponto = { x: new Date(msg.timestamp || Date.now()), y: msg.valor };
    historicoCompleto.push(ponto);

    atualizarBigNumbers({ valor: ponto.y, timestamp: ponto.x }, null, null);

    if(tempoRealAtivo){
      const visivel = sliceUltimosN(historicoCompleto, janela);
      Plotly.react('chart', [{
        x: visivel.map(p => p.x),
        y: visivel.map(p => p.y),
        mode: 'lines+markers',
        name: 'Temperatura (¡C)'
      }], layout);
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
      name: 'Temperatura (¡C)'
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
        name: 'Temperatura (¡C)'
      }], layout);
    }
  });

  btnAplicar.addEventListener('click', async () => {
    const ini = document.getElementById('f_inicio').value;
    const fim = document.getElementById('f_fim').value;
    if (!ini || !fim) return alert("Informe as duas datas!");

    try{
      const urlHist = `/historico_intervalo?inicio=${ini}&fim=${fim}&limite=2000`;
      const hist = await (await fetch(urlHist)).json();
      historicoCompleto = (hist.dados || []).map(d => ({ x: new Date(d.timestamp), y: d.valor }));

      Plotly.react('chart', [{
        x: historicoCompleto.map(p => p.x),
        y: historicoCompleto.map(p => p.y),
        mode: 'lines+markers',
        name: 'Temperatura (¡C)'
      }], layout);

      const urlEst = `/estatisticas?inicio=${ini}&fim=${fim}`;
      const est = await (await fetch(urlEst)).json();

      const ultimo = historicoCompleto.length
        ? { valor: historicoCompleto[historicoCompleto.length-1].y, timestamp: historicoCompleto[historicoCompleto.length-1].x }
        : null;

      atualizarBigNumbers(ultimo, est.media_hoje ?? null, est.media_periodo ?? null);
    }catch(e){
      console.error("Falha ao aplicar filtro:", e);
    }
  });
})();
