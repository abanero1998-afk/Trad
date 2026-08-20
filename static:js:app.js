let equityChart = null;
let robotRunning = false;

function formatEuro(n) {
  return new Intl.NumberFormat('it-IT', { style:'currency', currency:'EUR', minimumFractionDigits:2 }).format(n);
}
function formatPct(n) {
  return (n>=0?'+':'') + n.toFixed(2) + '%';
}
function toast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.classList.add('show');
  setTimeout(() => el.classList.remove('show'), 2800);
}

function initChart() {
  const ctx = document.getElementById('equityChart').getContext('2d');
  equityChart = new Chart(ctx, {
    type: 'line',
    data: { labels:[], datasets:[{
      label:'Capitale', data:[], borderColor:'#0a84ff',
      backgroundColor:'rgba(10,132,255,0.1)', borderWidth:2.2, fill:true, tension:0.35,
      pointRadius:0, pointHoverRadius:5, pointHoverBackgroundColor:'#0a84ff'
    }]},
    options: {
      responsive:true, maintainAspectRatio:false,
      plugins:{ legend:{display:false}, tooltip:{
        backgroundColor:'rgba(20,20,25,0.9)', titleFont:{family:'Inter',size:12},
        bodyFont:{family:'Inter',size:13}, padding:10, cornerRadius:8, displayColors:false,
        callbacks:{ label: ctx => formatEuro(ctx.parsed.y) }
      }},
      scales:{
        x:{ grid:{color:'rgba(255,255,255,0.04)'}, ticks:{color:'#8e8e93', font:{size:10}, maxTicksLimit:6} },
        y:{ grid:{color:'rgba(255,255,255,0.04)'}, ticks:{color:'#8e8e93', font:{size:10}, callback:v=>'€'+v.toLocaleString('it-IT')} }
      },
      interaction:{ intersect:false, mode:'index' }
    }
  });
}

function updateChart(curve) {
  if (!equityChart || !curve || !curve.length) return;
  equityChart.data.labels = curve.map(p => new Date(p.time).toLocaleTimeString('it-IT',{hour:'2-digit',minute:'2-digit'}));
  equityChart.data.datasets[0].data = curve.map(p => p.value);
  equityChart.update('none');
}

function renderPositions(positions) {
  const tbody = document.getElementById('positionsBody');
  if (!positions || !positions.length) {
    tbody.innerHTML = '<tr><td colspan="6" class="empty">Nessuna posizione</td></tr>';
    return;
  }
  tbody.innerHTML = positions.map(p => {
    const cls = p.pnl >= 0 ? 'pnl-pos' : 'pnl-neg';
    return `<tr>
      <td class="ticker">${p.ticker}</td>
      <td>${p.qty}</td>
      <td>€${p.prezzo_medio.toFixed(2)}</td>
      <td>€${p.prezzo_attuale.toFixed(2)}</td>
      <td>€${p.valore.toFixed(2)}</td>
      <td class="${cls}">${formatEuro(p.pnl)} <small>(${formatPct(p.pnl_pct)})</small></td>
    </tr>`;
  }).join('');
}

function renderScan(results) {
  const tbody = document.getElementById('scanBody');
  const keys = Object.keys(results || {});
  if (!keys.length) {
    tbody.innerHTML = '<tr><td colspan="5" class="empty">Premi Scansiona o avvia il robot</td></tr>';
    document.getElementById('gainersList').innerHTML = '';
    document.getElementById('losersList').innerHTML = '';
    return;
  }
  const sorted = keys.map(t => ({t, ...results[t]})).sort((a,b) => b.prob - a.prob);
  const top = sorted.slice(0,5);
  const bottom = sorted.slice(-5).reverse();
  document.getElementById('gainersList').innerHTML = top.map(r =>
    `<div class="mini-item"><span class="ticker">${r.t}</span><span class="prob" style="color:${r.prob>70?'#30d158':'#0a84ff'}">${r.prob}%</span></div>`
  ).join('');
  document.getElementById('losersList').innerHTML = bottom.map(r =>
    `<div class="mini-item"><span class="ticker">${r.t}</span><span class="prob" style="color:${r.prob<45?'#ff453a':'#8e8e93'}">${r.prob}%</span></div>`
  ).join('');
  tbody.innerHTML = keys.map(t => {
    const r = results[t];
    const w = Math.max(6, r.prob) + '%';
    let act = '—';
    if (r.action === 'COMPRA') act = '<span class="action-tag compra">COMPRA</span>';
    else if (r.action === 'VENDI') act = '<span class="action-tag vendi">VENDI</span>';
    else if (r.action === 'STOP LOSS') act = '<span class="action-tag stop">STOP</span>';
    return `<tr>
      <td class="ticker">${t}</td>
      <td><div class="prob-bar"><div class="prob-fill" style="width:${w};background:${r.prob>70?'#30d158':r.prob<45?'#ff453a':'#0a84ff'}"></div><span>${r.prob}%</span></div></td>
      <td>€${r.prezzo.toFixed(2)}</td>
      <td>${act}</td>
      <td style="color:#8e8e93;font-size:0.75rem">${r.note||'—'}</td>
    </tr>`;
  }).join('');
}

function renderHistory(storico) {
  const tbody = document.getElementById('historyBody');
  if (!storico || !storico.length) {
    tbody.innerHTML = '<tr><td colspan="6" class="empty">Nessun trade</td></tr>';
    return;
  }
  tbody.innerHTML = storico.map(t => {
    const time = new Date(t.time).toLocaleTimeString('it-IT',{hour:'2-digit',minute:'2-digit',second:'2-digit'});
    const cls = t.azione === 'COMPRA' ? 'compra' : 'vendi';
    const pnl = t.pnl !== undefined ? `<span class="${t.pnl>=0?'pnl-pos':'pnl-neg'}">${formatEuro(t.pnl)}</span>` : '—';
    return `<tr>
      <td>${time}</td>
      <td class="ticker">${t.ticker}</td>
      <td><span class="action-tag ${cls}">${t.azione}</span></td>
      <td>${t.qty}</td>
      <td>€${t.prezzo.toFixed(2)}</td>
      <td>${pnl}</td>
    </tr>`;
  }).join('');
}

async function fetchStatus() {
  try {
    const res = await fetch('/api/status');
    const data = await res.json();
    document.getElementById('kpiCapital').textContent = formatEuro(data.capitalizzazione);
    document.getElementById('kpiCash').textContent = 'Cash: ' + formatEuro(data.cash);
    const pnlEl = document.getElementById('kpiPnl');
    pnlEl.textContent = formatEuro(data.guadagno);
    pnlEl.className = 'kpi-value ' + (data.guadagno >= 0 ? 'positive' : 'negative');
    const pctEl = document.getElementById('kpiPnlPct');
    pctEl.textContent = formatPct(data.guadagno_pct);
    pctEl.style.color = data.guadagno_pct >= 0 ? 'var(--green)' : 'var(--red)';
    document.getElementById('kpiRealized').textContent = formatEuro(data.realized_pnl);
    document.getElementById('kpiRealized').className = 'kpi-value ' + (data.realized_pnl >= 0 ? 'positive' : 'negative');
    document.getElementById('kpiPositions').textContent = data.num_posizioni;
    if (data.last_scan) {
      document.getElementById('kpiLastScan').textContent = new Date(data.last_scan).toLocaleTimeString('it-IT');
    }
    robotRunning = data.robot_running;
    const pill = document.getElementById('robotStatus');
    const btn = document.getElementById('btnStart');
    if (robotRunning) {
      pill.classList.add('running');
      document.getElementById('statusText').textContent = 'Attivo';
      btn.textContent = 'Ferma Robot';
      btn.classList.add('running');
      document.getElementById('scanBadge').textContent = 'Robot attivo';
    } else {
      pill.classList.remove('running');
      document.getElementById('statusText').textContent = 'Fermo';
      btn.textContent = 'Avvia Robot';
      btn.classList.remove('running');
      document.getElementById('scanBadge').textContent = 'In attesa';
    }
    renderPositions(data.posizioni);
    renderScan(data.scan_results);
    renderHistory(data.storico);
    updateChart(data.equity_curve);
  } catch(e) { console.error(e); }
}

async function toggleRobot() {
  const ep = robotRunning ? '/api/stop' : '/api/start';
  try {
    const res = await fetch(ep, {method:'POST'});
    const d = await res.json();
    if (d.ok) { toast(robotRunning ? 'Robot fermato' : 'Robot avviato'); fetchStatus(); }
  } catch(e) { toast('Errore connessione'); }
}

async function manualScan() {
  toast('Scansione in corso…');
  try {
    const res = await fetch('/api/scan', {method:'POST'});
    const d = await res.json();
    if (d.ok) { toast('Scansione completata'); fetchStatus(); }
    else toast('Errore: ' + (d.error||''));
  } catch(e) { toast('Errore connessione'); }
}

async function resetPortfolio() {
  if (!confirm('Resettare il portafoglio a €10.000?')) return;
  try {
    const res = await fetch('/api/reset', {method:'POST'});
    if ((await res.json()).ok) { toast('Portafoglio resettato'); fetchStatus(); }
  } catch(e) { toast('Errore'); }
}

document.addEventListener('DOMContentLoaded', () => {
  initChart();
  fetchStatus();
  setInterval(fetchStatus, 8000);
});
