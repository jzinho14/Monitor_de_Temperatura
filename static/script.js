var socket = io();
var data = [{
    x: [],
    y: [],
    mode: 'lines+markers',
    name: 'Temperatura (°C)'
}];

var layout = {
    title: 'Temperatura',
    xaxis: { title: 'Hora', rangeslider: { visible: false } },
    yaxis: { title: 'Temperatura (°C)' },
    dragmode: 'pan'
};

Plotly.newPlot('chart', data, layout);

// --- Recebe dados em tempo real ---
socket.on('nova_temperatura', function(msg) {
    console.log("CLOG :: fc nova_temperatura Tempo real");
    var x = new Date();
    var y = msg.valor;
    var numPontos = parseInt(document.getElementById("numPontos").value) || 20;

    data[0].x.push(x);
    data[0].y.push(y);

    // Mantém apenas os últimos N pontos para tempo real
    if(document.getElementById("tempoReal").classList.contains("ativo")) {
        if(data[0].x.length > numPontos){
            data[0].x.shift();
            data[0].y.shift();
        }
    }

    Plotly.update('chart', data, layout);
});



// --- Botões ---
document.getElementById("tempoReal").addEventListener("click", function(){
    console.log("click tempo real")
    this.classList.add("ativo");
    fetchHistorico();
});

document.getElementById("filtrar").addEventListener("click", function(){
    document.getElementById("tempoReal").classList.remove("ativo");
    fetchHistorico();
});

// --- Função de filtro/histórico ---
function fetchHistorico(){
    var inicio = document.getElementById("inicio").value;
    var fim = document.getElementById("fim").value;
    var url = "/historico";
    fetch(url).then(response => response.json()).then(dados => {
        var x = [];
        var y = [];
        dados.forEach(d => {
            var ts = new Date(d[1]);
            if((!inicio || ts >= new Date(inicio)) && (!fim || ts <= new Date(fim))){
                x.push(ts);
                y.push(d[0]);
            }
        });
        data[0].x = x;
        data[0].y = y;
        Plotly.react('chart', data, layout);
    });
}
