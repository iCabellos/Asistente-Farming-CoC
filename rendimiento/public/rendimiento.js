// Pestaña Rendimiento: Resumen, Miembros, Guerras normales, Ligas y ficha de jugador. Todo sale de /clan/* y se repinta solo.
// Guerras de liga y normales nunca se mezclan: cada apartado pide las suyas y la ficha las enseña por separado.
(() => {
const SERIES = {us: '#b07c0e', them: '#a855f7', war: '#b07c0e', cwl: '#a855f7'};   // par validado para daltonismo en claro y oscuro
const S = {kind: 'all', days: 0, scope: 'clan', sub: 'resumen', tag: null, stamp: null, syncing: false, data: null, openWar: null, openRow: null,
           search: '', state: 'all', sort: {k: 'index', d: -1}, seq: 0, secs: {}, season: null, memberView: localStorage.getItem('vistaMiembros') || 'cards',
           by: localStorage.getItem('verPor') || 'player', dragging: false};
const charts = {}, drawers = {};
const KIND_NAME = {all: 'todas', cur: 'liga actual', cwl: 'ligas', war: 'guerras normales'};
const LEVEL = {elite: 'bg-green-lt', solido: 'bg-azure-lt', irregular: 'bg-yellow-lt', riesgo: 'bg-red-lt', nada: 'bg-secondary-lt'};
const STATE = {war: ['bg-green-lt', 'ti-swords', 'En guerra'], idle: ['bg-secondary-lt', 'ti-moon', 'Sin guerra'], gone: ['bg-red-lt', 'ti-door-exit', 'En otro clan']};
const RESULT = {win: ['bg-green-lt', 'Victoria'], lose: ['bg-red-lt', 'Derrota'], tie: ['bg-secondary-lt', 'Empate']};
const dec = (n, d = 1) => n == null ? '–' : Number(n).toLocaleString('es-ES', {minimumFractionDigits: d, maximumFractionDigits: d});
const fecha = ts => ts ? new Date(ts * 1000).toLocaleDateString('es-ES', {day: '2-digit', month: '2-digit'}) : '–';
const fechaLarga = ts => ts ? new Date(ts * 1000).toLocaleDateString('es-ES', {day: '2-digit', month: '2-digit', year: '2-digit'}) : '–';
const pctTxt = v => v == null ? '–' : Math.round(v) + ' %';
const ligaTxt = p => p.liga_attacks ? Math.round(p.liga_total) + ' %' : '–';
const stars = n => `<span class="text-yellow" aria-label="${n} estrellas">${'★'.repeat(n)}</span><span class="text-secondary">${'★'.repeat(3 - n)}</span>`;
const levelBadge = l => `<span class="badge ${LEVEL[l.id]}">${esc(l.name)}</span>`;
const resultBadge = r => { const [c, t] = RESULT[r] || RESULT.tie; return `<span class="badge ${c}">${t}</span>`; };
const kindBadge = k => k === 'cwl' ? '<span class="badge bg-purple-lt">Liga</span>' : '<span class="badge bg-blue-lt">Normal</span>';
const fmtKpi = (k, v) => v == null ? '–' : k.unit === '%' ? Math.round(v) + ' %' : dec(v, 2) + ' ★';
const canEdit = () => !S.cloud || !!clave();      // en la nube leer es libre; cambiar algo pide contraseña
const hash = tag => '#jugador/' + encodeURIComponent(tag.slice(1));
const ownerHash = id => '#persona/' + encodeURIComponent(id);
const link = p => p.grouped ? ownerHash(p.id) : hash(p.tag);          // un jugador de una sola cuenta abre la ficha de esa cuenta
const thText = p => p.ths ? (p.ths.length ? p.ths.map(t => 'TH' + t).join(' · ') : 'TH?') : `TH${p.th ?? '?'}`;
const who = () => S.by === 'player' ? ['jugador', 'jugadores', 'Jugador', 'Jugadores'] : ['cuenta', 'cuentas', 'Cuenta', 'Cuentas'];
const ownerBadge = (name, id, own = '') => name && name !== own ? `<span class="badge bg-yellow-lt ms-1" title="Jugador">${id ? `<a class="text-reset" href="${ownerHash(id)}">${esc(name)}</a>` : esc(name)}</span>` : '';
const q = () => `kind=${S.kind}&days=${S.days}`;
const plural = (n, a, b) => `${num(n)} ${n === 1 ? a : b}`;
const empty = t => `<div class="text-secondary text-center py-5">${esc(t)}</div>`;
const hitsHtml = w => `${w.attacks.map(a => `<span class="hit">${stars(a.stars)} <span class="small text-secondary">${a.pct}%${a.enemy_th ? ' · TH' + a.enemy_th : ''}</span></span>`).join('')}${w.per > w.attacks.length ? `<span class="badge bg-red-lt ms-1">${w.per - w.attacks.length} sin usar</span>` : ''}`;

function trendHtml(t) {
  if (t == null) return '<span class="text-secondary">–</span>';
  const [ic, cl, tx] = t > 0.05 ? ['ti-trending-up', 'text-green', 'Mejora'] : t < -0.05 ? ['ti-trending-down', 'text-red', 'Baja'] : ['ti-minus', 'text-secondary', 'Estable'];
  return `<span class="${cl}" title="Estrellas de los últimos ataques frente a los anteriores"><i class="ti ${ic} me-1"></i>${tx}${Math.abs(t) > 0.05 ? ' ' + (t > 0 ? '+' : '') + dec(t, 2) : ''}</span>`;
}
function stateBadge(p) { const [c, i, t] = STATE[p.state] || STATE.idle; return `<span class="badge ${c}"><i class="ti ${i} me-1"></i>${t}</span>`; }
function liveText(p) {
  if (p.state === 'gone') return `Última guerra con ${esc(p.last_clan)}`;
  return (p.live || []).map(w => `vs ${esc(w.rival_name || w.rival)} · acaba en ${fmtMin(w.ends - Date.now() / 1000)}`).join('<br>') || (p.last_war ? `Última guerra ${fecha(p.last_war)}` : 'Aún no ha jugado guerras');
}

// ---------- textos: qué es cada cosa
const PAGES = {
  resumen: ['Resumen', 'Cómo va el clan de un vistazo: su nota general, la liga, los mejores jugadores y a quién conviene vigilar.'],
  miembros: ['Miembros', 'Quién hay en el clan, si está en guerra ahora y cómo le está yendo. Cambia entre jugadores y cuentas con «Ver por».'],
  guerras: ['Guerras normales', 'Guerras fuera de la liga. Cada jugador tiene 2 ataques. Aquí no entran las rondas de liga.'],
  ligas: ['Ligas', 'Liga de Guerras de Clanes: 8 clanes, 7 rondas y 1 ataque por jugador en cada ronda. Aquí no entran las guerras normales.'],
  admin: ['Administración', 'Cuentas ligadas a cada jugador, clan que se sigue, recogidas de datos y acceso.'],
  jugador: ['Ficha de la cuenta', 'Todo sobre una cuenta: cómo ataca, cómo defiende y su evolución. Usa «Este clan» o «Todo su historial» para cambiar qué guerras cuentan.'],
  persona: ['Ficha del jugador', 'Una persona con todas sus cuentas: sus KPIs son la media de las cuentas que han jugado guerras, y cada cuenta mantiene los suyos.'],
};
const DESC = {
  ranking: ['Ordenado por índice. Cambia entre jugadores y cuentas con «Ver por». Pulsa una fila para ver sus cuentas y cómo le va en liga y en normales.'],
  grupos: ['Arrastra las cuentas para decir de quién es cada una. El jugador recibe la media de sus cuentas y cada cuenta sigue teniendo sus propios KPIs. Se guarda solo.'],
  aclan: ['El clan que sigue la web. Al cambiarlo se recogen sus datos; el histórico del clan anterior se conserva.'],
  arec: ['Cuándo se recogieron los datos por última vez y si hubo errores.'],
  aapi: ['Clave gratuita de Supercell para ver la lista exacta de miembros. Nunca se muestra aquí.'],
  apass: ['Sustituye el acceso inicial. Sólo se guarda un hash de la contraseña.'],
  wplay: ['Cada jugador con la media de sus cuentas en estas guerras. Debajo, los datos de cada cuenta.'],
  lplay: ['Cada jugador con la media de sus cuentas en esta temporada. Debajo, los datos de cada cuenta.'],
  oacc: ['Cada cuenta conserva sus KPIs. Pulsa una para abrir su ficha completa.'],
  okpi: ['Los 9 indicadores del jugador, como media de sus cuentas, frente a su objetivo y a la media del clan.'],
  ocmp: ['Qué aporta cada cuenta a la media del jugador y cómo queda frente al clan.'],
  kpis: ['Los 9 indicadores que forman el índice, comparados con su objetivo, y quién va mejor y peor en cada uno.'],
  graficas: ['Cómo se reparte el rendimiento dentro del clan: quién tira del carro y qué ayuntamientos rinden más.'],
  calculo: ['Qué mide cada indicador, cuánto pesa en la nota y qué valor se considera el objetivo.'],
  msrc: ['Ahora sólo se ve a quien ha jugado alguna guerra. Con una clave gratuita de Supercell, las altas y bajas entran solas. Se hace una sola vez.'],
  mgraf: ['Cuántos miembros hay en cada estado y de qué nivel de ayuntamiento son.'],
  llist: ['Cada ronda de la temporada con su marcador. Pulsa una terminada para ver qué hizo cada jugador.'],
  lheat: ['Las estrellas que sacó cada cuenta en cada ronda, para ver de un vistazo quién cumple siempre.'],
  lgraf: ['Evolución del clan ronda a ronda: estrellas, destrucción, ataques usados y balance.'],
  lnone: ['Las rondas de la temporada, con su marcador cuando terminan.'],
  ljug: ['Lo que aportó cada cuenta en cada temporada: estrellas, ataques usados y su destrucción, la suma de sus % y la media por ataque.'],
  lhist: ['Todas las temporadas guardadas: en qué liga jugó el clan, en qué puesto acabó y cómo fue evolucionando.'],
  wlist: ['Cada guerra con su marcador. Pulsa una para ver qué hizo cada jugador.'],
  wheat: ['Las estrellas que sacó cada cuenta en cada guerra, para ver de un vistazo quién cumple siempre.'],
  wgraf: ['Evolución del clan guerra a guerra: estrellas, destrucción, ataques usados y balance.'],
  wother: ['Lo que hicieron tus miembros en guerras normales con otros clanes. Da contexto, pero no cuenta para el clan.'],
  pkpi: ['Los 9 indicadores de la cuenta frente a su objetivo y a la media del clan.'],
  pforma: ['Cómo ataca: su perfil, si va a mejor o a peor y cuántas estrellas saca.'],
  prival: ['Si rinde igual contra rivales más fuertes y en qué momento de la guerra suele atacar.'],
  pdef: ['Cuántas estrellas le sacan cuando le atacan y qué ayuntamientos le hacen más daño.'],
  pritmo: ['Cuánto tardan sus ataques y qué aportó en cada temporada de liga.'],
  phcwl: ['Cada ronda de liga que ha jugado, con sus ataques y las estrellas que le sacaron.'],
  phwar: ['Cada guerra normal que ha jugado, con sus ataques y las estrellas que le sacaron.'],
};
const key = (cls, text, style = '') => `<span class="lg"><i class="${cls}" style="${style}"></i>${text}</span>`;
const LG_STRIP = `<span class="lg-title">Últimos ataques</span>${key('sw s3', '3 estrellas')}${key('sw s2', '2')}${key('sw s1', '1')}${key('sw s0', '0')}${key('sw sx', 'Sin usar')}`;
const LG_LEVELS = `<span class="lg-title">Nivel según el índice</span>${key('sw', 'Élite 85+', 'background:var(--tblr-green)')}${key('sw', 'Sólido 70+', 'background:var(--tblr-azure)')}${key('sw', 'Irregular 50+', 'background:var(--tblr-yellow)')}${key('sw', 'En riesgo', 'background:var(--tblr-red)')}`;
const LG_HEAT = `<span class="lg-title">Color</span>${key('sw', 'Pocas estrellas', 'background:rgba(176,124,14,.2)')}${key('sw', 'Muchas', 'background:rgba(176,124,14,.8)')}<span class="lg">«!» = ataque sin usar</span><span class="lg">Celda vacía = no jugó</span>`;
const LG_CARD = `<span class="lg-title">Barra</span>${key('sw', 'Estrellas nuestras', 'background:#b07c0e')}${key('sw', 'Del rival', 'background:#a855f7')}<span class="lg-title">Borde superior</span>${key('sw', 'Victoria', 'background:var(--tblr-green)')}${key('sw', 'Derrota', 'background:var(--tblr-red)')}`;
const LG_BULLET = compare => `<span class="lg-title">Barra</span>${key('sw', 'Valor actual; llena = objetivo cumplido', 'background:#b07c0e')}${compare ? key('sw', 'Media del clan', 'background:#a855f7;width:3px') : ''}`;
const LG_TRACK = `${key('sw round', 'Victoria', 'background:var(--tblr-green)')}${key('sw round', 'Derrota', 'background:var(--tblr-red)')}${key('sw round', 'En batalla', 'box-shadow:inset 0 0 0 2px var(--tblr-green)')}${key('sw round', 'Preparación', 'box-shadow:inset 0 0 0 2px var(--tblr-secondary)')}${key('sw round s0', 'Pendiente')}`;
const LEGENDS = {ranking: LG_LEVELS + LG_STRIP, llist: LG_CARD, wlist: LG_CARD, lheat: LG_HEAT, wheat: LG_HEAT, kpis: LG_BULLET(false), pkpi: LG_BULLET(true), okpi: LG_BULLET(true)};
const legendBar = (...parts) => `<div class="card mb-3"><div class="legend-row border-0"><span class="lg-title">Estado</span>${parts.join('')}</div></div>`;
const legendRow = html => `<div class="legend-row">${html}</div>`;

// ---------- piezas visuales
const ROUNDS = 7;                     // una liga son 8 clanes: 7 rondas
const LEVEL_COL = {elite: 'var(--tblr-green)', solido: 'var(--tblr-azure)', irregular: 'var(--tblr-yellow)', riesgo: 'var(--tblr-red)', nada: 'var(--tblr-secondary)'};
function ring(v, level, size = 96, stroke = 9) {
  const r = (size - stroke) / 2, c = 2 * Math.PI * r, m = size / 2;
  return `<div class="ring" style="width:${size}px;height:${size}px" role="img" aria-label="Índice ${v ?? 'sin datos'}, ${esc(level.name)}"><svg viewBox="0 0 ${size} ${size}"><circle class="ring-bg" cx="${m}" cy="${m}" r="${r}" stroke-width="${stroke}"/>
    <circle class="ring-fg" cx="${m}" cy="${m}" r="${r}" stroke-width="${stroke}" stroke="${LEVEL_COL[level.id]}" stroke-dasharray="${c}" stroke-dashoffset="${c * (1 - (v || 0) / 100)}" transform="rotate(-90 ${m} ${m})"/></svg><b style="font-size:${size / 3.3}px">${v ?? '–'}</b></div>`;
}
const initials = n => (String(n).replace(/[^\p{L}\p{N}]/gu, '').slice(0, 2) || '?').toUpperCase();
const avatar = (p, cls = '') => `<span class="av ${cls}" aria-hidden="true">${esc(initials(p.name))}</span>`;
// Últimos ataques como cuadritos: más oscuro, más estrellas; borde rojo, ataque sin usar.
function strip(wars) {
  const cells = wars.flatMap(w => [...w.attacks.map(a => [`s${a.stars}`, `${fecha(w.ts)} vs ${w.opponent}: ${a.stars} estrellas`]),
    ...Array.from({length: Math.max(0, w.per - w.attacks.length)}, () => ['sx', `${fecha(w.ts)} vs ${w.opponent}: sin usar`])]);
  return cells.length ? `<span class="strip">${cells.slice(-10).map(c => `<i class="${c[0]}" title="${esc(c[1])}"></i>`).join('')}</span>` : '<span class="text-secondary">–</span>';
}
function bullet(k, c, compare) {
  const s = c.scores[k.id], v = c.values[k.id], mark = compare && compare.scores[k.id];
  const st = s == null ? ['text-secondary', 'ti-minus', 'Sin datos'] : s >= 100 ? ['text-green', 'ti-circle-check', 'Cumple'] : s >= 70 ? ['text-yellow', 'ti-alert-circle', 'Cerca'] : ['text-red', 'ti-alert-triangle', 'Lejos'];
  return `<div class="bullet" title="${esc(k.help)}"><div class="d-flex align-items-baseline gap-2"><span class="fw-medium">${esc(k.name)}</span><span class="ms-auto fw-bold">${fmtKpi(k, v)}</span><span class="small ${st[0]}" style="width:4.6rem"><i class="ti ${st[1]} me-1"></i>${st[2]}</span></div>
    <div class="bullet-track"><div class="bullet-fill" style="width:${s || 0}%"></div>${mark != null ? `<div class="bullet-mark" style="left:${mark}%" title="Media del clan"></div>` : ''}</div>
    <div class="small text-secondary">Objetivo ${fmtKpi(k, k.target)}${k.target < k.floor ? " · menos es mejor" : ""}${compare ? ` · clan ${fmtKpi(k, compare.values[k.id])}` : ''}</div></div>`;
}
const bullets = (K, c, compare) => `<div class="row g-4"><div class="col-lg-6">${K.slice(0, 4).map(k => bullet(k, c, compare)).join('')}</div><div class="col-lg-6">${K.slice(4).map(k => bullet(k, c, compare)).join('')}</div></div>`;
function tracker(rounds, live) {
  const icon = {win: 'ti-check', lose: 'ti-x', tie: 'ti-equal'}, cells = rounds.map(r => `<div class="t" title="vs ${esc(r.opponent)}: ${r.stars}–${r.opp_stars}"><div class="dot ${r.result}"><i class="ti ${icon[r.result]}"></i></div>R${0}</div>`);
  live.forEach(w => cells.push(`<div class="t" title="vs ${esc(w.rival_name || w.rival)}"><div class="dot ${w.phase}"><i class="ti ${w.phase === 'battle' ? 'ti-swords' : 'ti-hourglass'}"></i></div>R${0}</div>`));
  while (cells.length < ROUNDS) cells.push('<div class="t"><div class="dot"></div>R0</div>');
  return `<div class="tracker" aria-label="Rondas de la liga">${cells.slice(0, ROUNDS).map((c, i) => c.replace(/R0?<\/div>$/, `R${i + 1}</div>`)).join('')}</div><div class="legend-inline">${LG_TRACK}</div>`;
}
const skeleton = () => `<div class="sk mb-3" style="height:150px"></div><div class="row g-3 mb-3"><div class="col-md-7"><div class="sk" style="height:190px"></div></div><div class="col-md-5"><div class="sk" style="height:190px"></div></div></div><div class="sk" style="height:320px"></div>`;

// ---------- gráficas
const grid = () => getComputedStyle(document.documentElement).getPropertyValue('--chart-grid').trim();
const legend = {legend: {display: true, position: 'bottom', labels: {boxWidth: 10, boxHeight: 10}}};
const base = (extra = {}) => ({responsive: true, maintainAspectRatio: false, animation: {duration: 250},
  interaction: {mode: 'nearest', intersect: false},
  plugins: {legend: {display: false}, ...extra.plugins},
  scales: extra.scales || {x: {grid: {display: false}, ticks: {maxRotation: 0, autoSkip: true, maxTicksLimit: 10}}, y: {beginAtZero: true, ticks: {precision: 0}}}});
const pctY = {x: {grid: {display: false}, ticks: {maxRotation: 0, autoSkip: true, maxTicksLimit: 10}}, y: {min: 0, max: 100}};
const starY = {x: {grid: {display: false}, ticks: {maxRotation: 0, autoSkip: true, maxTicksLimit: 10}}, y: {min: 0, max: 3}};
const barSet = (label, data, color = SERIES.us, stack) => ({label, data, backgroundColor: color, borderRadius: 4, maxBarThickness: 26, borderSkipped: 'bottom', stack});
const lineSet = (label, data, color = SERIES.us) => ({label, data, borderColor: color, backgroundColor: color, borderWidth: 2, pointRadius: data.length > 40 ? 0 : 4, pointHoverRadius: 6, tension: .25, spanGaps: true});
const radarOpts = plugins => ({responsive: true, maintainAspectRatio: false, plugins, scales: {r: {min: 0, max: 100, ticks: {display: false}, grid: {color: grid()}, angleLines: {color: grid()}, pointLabels: {font: {size: 10}}}}});
const AXES = {chIndex: ['Índice (0 a 100)', 'Jugador'], chLevels: ['Nivel', 'Nº de jugadores'], oIndex: ['Cuenta', 'Índice (0 a 100)'], chTh: ['Ayuntamiento', 'Índice medio'], chStates: ['Estado', 'Nº de miembros'],
  chMemberTh: ['Ayuntamiento', 'Nº de cuentas'], Stars: [null, 'Estrellas'], Pct: [null, 'Destrucción %'], Used: [null, '% de ataques usados'], Bal: [null, 'Victorias menos derrotas'],
  chRank: ['Temporada', 'Puesto (1 es el mejor)'], chSeasonStars: ['Temporada', 'Estrellas'], chSeasonWL: ['Temporada', 'Rondas'], pForm: ['Fecha', 'Media de estrellas'], pStars: ['Fecha', 'Estrellas'],
  pPct: ['Fecha del ataque', 'Daño %'], pDist: ['Resultado del ataque', 'Nº de ataques'], pDiff: ['TH rival menos el suyo', 'Estrellas medias'], pTiming: ['Momento de la guerra', 'Nº de ataques'],
  pDef: ['Fecha', 'Estrellas otorgadas al rival'], pDefTh: ['Ayuntamiento del atacante', 'Estrellas medias'], pDur: ['Fecha del ataque', 'Segundos'], pSeasons: ['Temporada', 'Estrellas']};
function draw(id, config) {
  const el = document.getElementById(id); if (!el || charts[id]) return;
  const o = config.options, m = id.match(/^([wl])(Stars|Pct|Used|Bal)$/), a = AXES[m ? m[2] : id];
  o.plugins = {...o.plugins, legend: legend.legend};
  if (a && o.scales) {
    const title = text => ({display: true, text});
    o.scales.x = {...o.scales.x, title: title(a[0] || (m[1] === 'l' ? 'Ronda' : 'Fecha'))};
    o.scales.y = {...o.scales.y, title: title(a[1])};
  }
  charts[id] = new Chart(el, config);
}
function clearCharts() { for (const k of Object.keys(charts)) { charts[k].destroy(); delete charts[k]; } for (const k of Object.keys(drawers)) delete drawers[k]; }
function chart(id, title, sub, opts = {}) {
  const has = opts.has !== false;
  return `<div class="${opts.col || 'col-lg-6'}"><div class="fw-medium">${esc(title)}</div><div class="small text-secondary mb-2">${esc(sub)}</div>
    ${has ? `<div style="height:${opts.h || 270}px"><canvas id="${id}" role="img" aria-label="${esc(title)}"></canvas></div>` : empty(opts.none || 'Aún no hay datos suficientes')}</div>`;
}
const chartRow = html => `<div class="card-body"><div class="row g-4">${html}</div></div>`;
// Sección desplegable: recuerda si estaba abierta y sólo dibuja sus gráficas al abrirse.
const CLOSED = new Set(['calculo']);
// En el teléfono se abren plegadas las secciones largas o de consulta, para llegar antes a lo importante.
const CLOSED_MOBILE = new Set(['kpis', 'graficas', 'mgraf', 'wgraf', 'lgraf', 'ljug', 'lhist', 'wother', 'prival', 'pdef', 'pritmo', 'phcwl', 'phwar', 'ocmp']);
const isMobile = () => matchMedia('(max-width:767.98px)').matches;
function sec(id, title, sub, body, open, draw_) {
  if (draw_) drawers[id] = draw_;
  const isOpen = S.secs[id] ?? !(CLOSED.has(id) || (isMobile() && CLOSED_MOBILE.has(id))), desc = (DESC[id] || [sub || ''])[0];
  return `<details class="card mb-3 sec" data-sec="${id}" ${isOpen ? 'open' : ''}><summary class="card-header align-items-start"><i class="ti ti-chevron-right chev me-2 mt-1"></i><div><h3 class="card-title mb-0">${title}</h3><div class="small text-secondary sec-desc">${desc}</div></div></summary>
    <div class="sec-body">${LEGENDS[id] ? legendRow(LEGENDS[id]) : ''}${body}</div></details>`;
}
function drawOpen() { $('clanView').querySelectorAll('details[open][data-sec]').forEach(d => drawers[d.dataset.sec]?.()); }

// ---------- resumen
function splitCard(kind, title, icon, r, link, sub, none) {
  const v = r.values || {};
  return `<div class="col-md-6"><div class="card h-100 split-card split-${kind}"><div class="card-body">
    <div class="d-flex align-items-center mb-1"><div class="subheader"><i class="ti ${icon} me-1"></i>${title}</div>${link ? `<a class="ms-auto small" href="${link}">Ver todo <i class="ti ti-arrow-right"></i></a>` : ''}</div>
    ${r.wars ? `<div class="d-flex align-items-baseline gap-2"><div class="display-6 fw-bold">${r.index ?? '–'}</div>${levelBadge(r.level)}<span class="ms-auto text-secondary small">${plural(r.n, 'guerra', 'guerras')}</span></div>
      <div class="row g-2 mt-2 small">
        <div class="col-6"><div class="text-secondary" title="Victorias, empates y derrotas">Victorias-Empates-Derrotas</div><b>${r.won}-${r.tied}-${r.lost}</b></div>
        ${v.dano_liga != null ? `<div class="col-6"><div class="text-secondary" title="Suma del % de sus ataques de liga">% total en liga</div><b>${ligaTxt(r)}</b></div><div class="col-6"><div class="text-secondary" title="Destrucción media de sus ataques de liga">% medio en liga</div><b>${pctTxt(v.dano_liga)}</b></div>` : `<div class="col-6"><div class="text-secondary" title="Destrucción media por ataque disponible">Daño efectivo</div><b>${pctTxt(v.dano_efectivo)}</b></div>`}
        <div class="col-6"><div class="text-secondary">Ataques usados</div><b>${v.participacion == null ? '–' : Math.round(v.participacion) + ' %'}</b></div>
        <div class="col-6"><div class="text-secondary">Estrellas por ataque</div><b>${dec(v.estrellas, 2)} ★</b></div></div>
      ${sub ? `<div class="small text-secondary mt-2">${sub}</div>` : ''}` : `<div class="text-secondary mt-2">${none}</div>`}</div></div></div>`;
}
function alerts(d) {
  const risk = d.players.filter(p => p.level.id === 'riesgo'), down = d.players.filter(p => p.trend != null && p.trend <= -0.3), rows = [];
  const names = l => l.map(p => `<a class="player-name" href="${hash(p.tag)}">${esc(p.name)}</a>`).join(', ');
  if (d.last_missed.length) rows.push(['ti-alert-triangle text-red', `Sin atacar en la última guerra (${esc(d.last_war.opponent)})`, names(d.last_missed)]);
  if (risk.length) rows.push(['ti-alert-circle text-yellow', 'Nivel En riesgo', names(risk)]);
  if (down.length) rows.push(['ti-trending-down text-red', 'Bajando de forma', names(down)]);
  const joined = d.moves.filter(m => m.kind === 'join'), left = d.moves.filter(m => m.kind === 'leave');
  if (joined.length) rows.push(['ti-user-plus text-green', 'Nuevos en el clan (14 días)', joined.map(m => `<a class="player-name" href="${hash(m.tag)}">${esc(m.name || m.tag)}</a> <span class="text-secondary">${fecha(m.ts)}</span>`).join(', ')]);
  if (left.length) rows.push(['ti-user-minus text-red', 'Han salido del clan (14 días)', left.map(m => `${esc(m.name || m.tag)} <span class="text-secondary">${fecha(m.ts)}</span>`).join(', ')]);
  const gone = d.players.filter(p => p.state === 'gone');
  if (gone.length) rows.push(['ti-door-exit text-secondary', 'Ahora en otro clan', names(gone)]);
  return rows.length ? `<div class="list-group list-group-flush">${rows.map(r => `<div class="list-group-item d-flex gap-2"><i class="ti ${r[0]}"></i><div><div class="fw-medium">${r[1]}</div><div class="small">${r[2]}</div></div></div>`).join('')}</div>`
    : '<div class="card-body text-secondary">Nada que destacar ahora mismo.</div>';
}
// Cuentas de un jugador: una tarjeta por cuenta, con lo importante a la vista y el enlace a su ficha.
function accountCards(list) {
  const num = (label, value) => `<span class="xd-num"><small>${label}</small><b>${value}</b></span>`;
  return `<div class="xd-accs">${list.map(a => `<a class="xd-acc" href="${hash(a.tag)}">
    <span class="xd-top">${ring(a.index, a.level, 44, 5)}<span class="xd-name"><b>${esc(a.name)}</b><small>TH${a.th ?? '?'} · ${esc(a.level.name)}</small></span><span class="xd-trend">${trendHtml(a.trend)}</span><i class="ti ti-chevron-right text-secondary"></i></span>
    <span class="xd-nums">${num('% medio liga', pctTxt(a.values.dano_liga))}${num('% total liga', ligaTxt(a))}${num('★ por ataque', dec(a.values.estrellas, 2))}${num('Ataques', `${a.used}/${a.avail}`)}</span></a>`).join('')}</div>`;
}
// Liga, normales y otros clanes en una tabla compacta: sólo los tipos en los que ha jugado.
function typeTable(c) {
  const types = [['Liga', c.cwl], ['Normales', c.war], ['Otros clanes', c.other, c.other_clan]].filter(t => t[1].wars);
  if (!types.length) return '<div class="text-secondary small">Sin guerras</div>';
  return `<table class="xd-t"><thead><tr><th></th><th>Índice</th><th>Ataques</th><th>% medio</th><th>★</th><th class="d-none d-sm-table-cell">Triples</th></tr></thead><tbody>
    ${types.map(([t, x, sub]) => `<tr><td>${t}${sub ? `<small>${esc(sub)}</small>` : ''}</td><td><b style="color:${LEVEL_COL[x.level.id]}" title="${esc(x.level.name)}">${x.index ?? '–'}</b></td><td>${x.used}/${x.avail}</td><td>${pctTxt(x.values.dano)}</td><td>${dec(x.values.estrellas, 2)}</td><td class="d-none d-sm-table-cell">${pctTxt(x.values.triples)}</td></tr>`).join('')}</tbody></table>`;
}
// Últimas guerras agrupadas: varias cuentas en la misma guerra forman un solo bloque.
function recentWars(list) {
  const wars = new Map();
  list.forEach(w => { const k = `${w.ts}|${w.opponent}`; if (!wars.has(k)) wars.set(k, []); wars.get(k).push(w); });
  if (!wars.size) return '<div class="text-secondary small">Sin guerras en el clan</div>';
  return [...wars.values()].map(g => { const w = g[0]; return `<div class="xd-war xd-${esc(w.result)}"><div class="xd-war-h"><b>${esc(w.opponent)}</b><span>${fecha(w.ts)}</span>${kindBadge(w.kind)}</div>
    ${g.map(x => `<div class="xd-hit">${x.account ? `<span class="text-truncate">${esc(x.account)}</span>` : ''}<span class="xd-hits">${hitsHtml(x)}</span></div>`).join('')}</div>`; }).join('');
}
// Desglose al pulsar una fila: mismo diseño en móvil y en escritorio.
function ctxRow(p, cols) {
  const c = p.ctx;
  return `<tr class="ctx-row"><td colspan="${cols}"><div class="xd">
    ${p.grouped ? `<section><div class="xd-h">Sus cuentas</div>${accountCards(p.accounts)}</section>` : ''}
    <div class="xd-2"><section><div class="xd-h">Por tipo de guerra${p.grouped ? ' · media de sus cuentas' : ''}</div>${typeTable(c)}</section>
    <section><div class="xd-h">Últimas guerras en el clan</div>${recentWars(c.recent)}</section></div>
    <a class="btn btn-sm btn-primary w-100" href="${link(p)}">Abrir ficha completa <i class="ti ti-arrow-right ms-1"></i></a></div></td></tr>`;
}
// Tabla de jugadores de Guerras y Ligas: fila con la media y, debajo, una fila por cuenta.
function ownerTable(rows, none, liga) {
  const cells = p => `<td>${p.th ? thText(p) : '–'}</td><td class="scorecell"><div class="d-flex align-items-center gap-2"><div class="progress progress-sm flex-fill"><div class="progress-bar bg-gold" style="width:${p.index ?? 0}%"></div></div><b>${p.index ?? '–'}</b></div></td><td>${levelBadge(p.level)}</td><td class="text-end">${p.used}/${p.avail}</td>${liga ? `<td class="text-end">${ligaTxt(p)}</td><td class="text-end">${pctTxt(p.values.dano_liga)}</td>` : `<td class="text-end">${pctTxt(p.values.dano_efectivo)}</td>`}<td class="text-end">${dec(p.values.estrellas, 2)} ★</td><td class="text-end">${p.values.triples == null ? '–' : Math.round(p.values.triples) + ' %'}</td><td class="text-end ${p.missed ? 'text-red fw-bold' : 'text-secondary'}">${p.missed}</td>`;
  return `<div class="table-responsive"><table class="table table-vcenter card-table rank-table mb-0"><thead><tr><th>Jugador</th><th>TH</th><th>Índice</th><th>Nivel</th><th class="text-end">Ataques</th>${liga ? `<th class="text-end">% total liga</th><th class="text-end">% medio liga</th>` : `<th class="text-end">Daño efectivo</th>`}<th class="text-end">Estrellas por ataque</th><th class="text-end">Triples</th><th class="text-end">Sin usar</th></tr></thead><tbody>
    ${rows.map(p => `<tr><td><div class="d-flex align-items-center gap-2">${avatar(p)}<div><a class="player-name" href="${link(p)}">${esc(p.name)}</a>${p.grouped ? `<div class="small text-secondary">${plural(p.accounts.length, 'cuenta', 'cuentas')} · media</div>` : ''}</div></div></td>${cells(p)}</tr>
      ${p.grouped ? p.accounts.map(a => `<tr class="sub-row"><td><a class="player-name fw-normal" href="${hash(a.tag)}">${esc(a.name)}</a></td>${cells(a)}</tr>`).join('') : ''}`).join('') || `<tr><td colspan="${liga ? 10 : 9}">${empty(none)}</td></tr>`}</tbody></table></div>`;
}
// Tablero jugador → cuentas. Cada arrastre se guarda: cuentas entre jugadores, orden dentro de cada uno y orden de los jugadores.
function chip(a, groups) {
  const move = `<select class="form-select form-select-sm own-move d-md-none" aria-label="Mover ${esc(a.name)} a otro jugador"><option value="" selected disabled>Mover a…</option>${groups.map(g => `<option value="${esc(g.id)}">${esc(g.name)}</option>`).join('')}<option value="__suelta">Sin agrupar</option><option value="__nuevo">Jugador nuevo</option></select>`;
  return `<div class="own-chip" data-tag="${esc(a.tag)}" title="Arrastra para mover">${avatar(a)}<span class="own-name"><b>${esc(a.name)}</b><span class="small text-secondary">TH${a.th ?? '?'}</span></span><span class="ms-auto fw-bold" title="Índice de la cuenta">${a.index ?? '–'}</span>${move}</div>`;
}
function ownerBoard(d) {
  const by = Object.fromEntries(d.players.map(p => [p.tag, p])), inGroup = new Set(d.groups.flatMap(g => g.accounts));
  const owner = Object.fromEntries(d.owners.map(o => [o.id, o])), pool = d.players.filter(p => !inGroup.has(p.tag)).sort((a, b) => a.name.localeCompare(b.name));
  const groups = d.groups.filter(g => g.accounts.some(t => by[t]));
  return `<div class="card-body"><div class="row g-3">
    <div class="col-lg-4"><div class="own-card own-pool"><div class="own-head"><i class="ti ti-inbox text-secondary"></i><b>Cuentas sin agrupar</b><span class="badge bg-secondary-lt ms-auto">${pool.length}</span></div>
      <div class="small text-secondary px-2 pb-1">Cuentan como un jugador de una sola cuenta. Los miembros nuevos aparecen aquí.</div><div class="own-list" data-group="">${pool.map(a => chip(a, groups)).join('')}</div></div></div>
    <div class="col-lg-8"><div class="own-groups" id="ownGroups">${groups.map(g => { const o = owner[g.id];
      return `<div class="own-card own-group" data-id="${esc(g.id)}"><div class="own-head"><i class="ti ti-grip-vertical own-handle" title="Arrastra para ordenar jugadores"></i>
        <input class="form-control form-control-sm own-title" value="${esc(g.name)}" maxlength="30" aria-label="Nombre del jugador"><b class="own-index" title="Media de sus cuentas">${o?.index ?? '–'}</b>
        <button class="btn btn-icon btn-sm btn-ghost-secondary" data-ungroup="${esc(g.id)}" title="Deshacer jugador" aria-label="Deshacer jugador ${esc(g.name)}"><i class="ti ti-x"></i></button></div>
        <div class="own-list" data-group="${esc(g.id)}">${g.accounts.filter(t => by[t]).map(t => chip(by[t], groups.filter(x => x !== g))).join('')}</div></div>`; }).join('')}</div>
      <div class="own-card own-new"><div class="own-list" data-new="1"><div class="own-hint"><i class="ti ti-user-plus me-1"></i><span class="d-none d-md-inline">Suelta aquí una cuenta para crear un jugador nuevo</span><span class="d-md-none">Usa «Mover a…» para crear un jugador nuevo</span></div></div></div></div>
  </div></div>`;
}
function saveGroups(skip) {
  const view = $('clanView'), groups = [...view.querySelectorAll('.own-group')].filter(g => g.dataset.id !== skip).map(g => ({id: g.dataset.id, name: g.querySelector('.own-title').value,
    accounts: [...g.querySelectorAll('[data-tag]')].map(c => c.dataset.tag)}));
  view.querySelectorAll('[data-new] [data-tag]').forEach(c => groups.push({name: c.querySelector('b').textContent, accounts: [c.dataset.tag]}));
  return api('api/groups', {groups}).then(load).catch(err => { toast(esc(err.message), 'danger'); load(); });
}
function wireBoard() {
  const opts = {animation: 160, ghostClass: 'sortable-ghost', chosenClass: 'sortable-chosen', forceFallback: true, fallbackOnBody: true, filter: '.own-move', preventOnFilter: false, delay: 180, delayOnTouchOnly: true, touchStartThreshold: 5, onStart: () => { S.dragging = true; }, onEnd: e => { S.dragging = false; if (e.from !== e.to || e.oldIndex !== e.newIndex) saveGroups(); }};
  $('clanView').querySelectorAll('.own-list').forEach(l => Sortable.create(l, {...opts, group: 'cuentas', draggable: '.own-chip', sort: !l.dataset.new && l.dataset.group !== ''}));
  const box = document.getElementById('ownGroups'); if (box) Sortable.create(box, {...opts, handle: '.own-handle', draggable: '.own-group'});
  $('clanView').querySelectorAll('.own-title').forEach(i => { i.onchange = () => saveGroups(); });
  $('clanView').querySelectorAll('.own-move').forEach(s => { s.onchange = () => {
    const dest = s.value === '__nuevo' ? '[data-new]' : s.value === '__suelta' ? '.own-pool .own-list' : `.own-list[data-group="${s.value}"]`;
    $('clanView').querySelector(dest).append(s.closest('.own-chip')); saveGroups(); }; });
  $('clanView').querySelectorAll('[data-ungroup]').forEach(b => { b.onclick = () => saveGroups(b.dataset.ungroup); });
}
const SORTS = {index: p => p.index ?? -1, name: p => p.name.toLowerCase(), th: p => p.th ?? 0, used: p => p.used, liga_total: p => p.liga_total, dano_liga: p => p.values.dano_liga ?? -1, stars: p => p.stars, missed: p => p.missed, trend: p => p.trend ?? -9};
function renderResumen(d) {
  const sum = d.summary, players = (S.by === 'player' ? d.owners : d.players).filter(p => p.wars), sp = d.split, se = d.clan.season;
  const [one, many, One, Many] = who(), accounts = d.players.filter(p => p.wars);    // el ayuntamiento es de la cuenta, no del jugador
  AXES.chIndex[1] = One; AXES.chLevels[1] = 'Nº de ' + many;
  const counts = d.levels.map(l => players.filter(p => p.level.id === l.id).length);
  const ths = [...new Set(accounts.map(p => p.th).filter(Boolean))].sort((a, b) => a - b), th = t => accounts.filter(p => p.th === t);
  const sorted = players.slice().sort((a, b) => { const f = SORTS[S.sort.k], x = f(a), y = f(b); return (x > y ? 1 : x < y ? -1 : 0) * S.sort.d; });
  const col = (k, t, cls = '') => `<th class="${cls} sort" data-sort="${k}" role="button">${t}${S.sort.k === k ? (S.sort.d < 0 ? ' ↓' : ' ↑') : ''}</th>`;
  const inWar = d.players.filter(p => p.state === 'war').length;
  const leaders = d.kpis.map(k => { const r = (S.by === 'player' ? d.owners : d.players).filter(p => p.scores[k.id] != null).sort((a, b) => b.scores[k.id] - a.scores[k.id] || (k.id === 'defensa' ? a.values[k.id] - b.values[k.id] : b.values[k.id] - a.values[k.id]));
    return {k, top: r[0], low: r.length > 1 ? r[r.length - 1] : null}; });
  const ranked = players.filter(p => p.index != null);
  const top = ranked.slice(0, 3), order = top.length === 3 ? [top[1], top[0], top[2]] : top, medal = {0: '🥇', 1: '🥈', 2: '🥉'};
  const phrase = [se ? `Vais <b>${se.rank ?? '–'}º</b> en ${esc(se.league || 'la liga')} con <b>${se.won ?? 0}-${se.tied ?? 0}-${se.lost ?? 0}</b>.` : '',
    inWar ? `<b>${plural(inWar, 'miembro', 'miembros')}</b> en guerra ahora.` : 'Nadie en guerra ahora.',
    d.last_missed.length ? `<b>${plural(d.last_missed.length, 'jugador', 'jugadores')}</b> sin atacar en la última guerra.` : 'Todos atacaron en la última guerra.'].join(' ');
  $('clanView').innerHTML = `
    <div class="card hero mb-3"><div class="card-body d-flex flex-wrap align-items-center gap-4">
      ${ring(sum.index, sum.level, 112, 10)}
      <div style="flex:1 1 260px"><div class="subheader mb-1">Índice del clan · ${esc(sum.level.name)}</div><div class="hero-line">${phrase}</div><div class="small text-secondary mt-1">El índice es una nota de 0 a 100 que combina 9 indicadores de guerra.</div></div>
      ${se ? `<div class="hero-tracker"><div class="subheader mb-2">Liga · ${esc(se.league || '')}</div>${tracker(d.season_rounds, d.live.filter(w => w.type === 'cwl'))}</div>` : ''}
    </div></div>
    <div class="row row-cards mb-3">
      <div class="col-lg-7"><div class="card h-100"><div class="card-header"><div><h3 class="card-title mb-0"><i class="ti ti-trophy me-2 text-yellow"></i>Podio</h3><div class="small text-secondary sec-desc">${S.by === 'player' ? 'Los 3 jugadores' : 'Las 3 cuentas'} con mejor índice (${KIND_NAME[S.kind]}).</div></div></div><div class="card-body">
        <div class="row g-2 podium align-items-end">${order.map(p => { const pos = top.indexOf(p); return `<div class="col-4"><a class="card card-link lift ${pos === 0 ? 'first' : ''} text-reset text-decoration-none" href="${link(p)}"><div class="card-body ${pos === 0 ? 'py-4' : 'py-3'} px-2"><div class="medal mb-1" aria-hidden="true">${medal[pos]}</div>${avatar(p, pos === 0 ? 'av-lg' : '')}<div class="fw-bold text-truncate mt-2">${esc(p.name)}</div><div class="h2 mb-0">${p.index}</div><div class="small text-secondary text-truncate">${p.stars} ★ · ${p.grouped ? plural(p.accounts.length, 'cuenta', 'cuentas') : thText(p)}</div></div></a></div>`; }).join('') || `<div class="col-12">${empty('Sin guerras con estos filtros')}</div>`}</div></div></div></div>
      <div class="col-lg-5"><div class="card h-100"><div class="card-header"><div><h3 class="card-title mb-0"><i class="ti ti-eye me-2 text-yellow"></i>A vigilar</h3><div class="small text-secondary sec-desc">Quién necesita atención: ataques sin usar, nivel bajo o mala racha.</div></div></div>${alerts(d)}</div></div>
    </div>
    <div class="row row-cards mb-3">
      ${splitCard('cwl', 'Liga', 'ti-shield-star', sp.cwl, '#ligas', '', 'Sin rondas de liga guardadas.')}
      ${splitCard('war', 'Guerras normales', 'ti-swords', sp.war, '#guerras', '', `Aún sin guerras normales del clan. Tus miembros suman ${plural(d.others, 'participación', 'participaciones')} con otros clanes.`)}
    </div>
    ${sec('ranking', S.by === 'player' ? 'Ranking de jugadores' : 'Ranking de cuentas', `${players.every(p => p.few) ? 'Aún pocos datos · ' : ''}${KIND_NAME[S.kind]} · pulsa uno para ver su contexto`, `<div class="d-md-none px-3 py-2 d-flex align-items-center gap-2"><label class="small text-secondary" for="sortPick">Ordenar por</label><select class="form-select form-select-sm" id="sortPick">${[['index', 'Índice'], ['name', 'Nombre'], ['th', 'Ayuntamiento'], ['used', 'Ataques usados'], ['stars', 'Estrellas'], ['missed', 'Sin usar']].map(([k, t]) => `<option value="${k}" ${S.sort.k === k ? 'selected' : ''}>${t}</option>`).join('')}</select></div>
      <div class="table-responsive"><table class="table table-vcenter card-table rank-table mb-0"><thead><tr><th class="pos">#</th>${col('name', One)}${col('th', 'TH')}${col('index', 'Índice')}<th>Nivel</th>${col('used', 'Ataques', 'text-end')}${col('liga_total', '% total liga', 'text-end')}${col('dano_liga', '% medio liga', 'text-end')}${col('stars', 'Estrellas', 'text-end')}${col('missed', 'Sin usar', 'text-end')}<th>Últimos ataques</th></tr></thead>
      <tbody>${sorted.map((p, i) => `<tr class="player" data-row="${esc(p.tag)}" aria-expanded="${S.openRow === p.tag}"><td class="pos">${i + 1}</td>
        <td><div class="d-flex align-items-center gap-2"><i class="ti ti-chevron-right row-chev"></i>${avatar(p)}<div><a class="player-name" href="${link(p)}">${esc(p.name)}</a>${ownerBadge(p.owner?.name, p.owner?.id, p.name)}${p.grouped ? `<div class="small text-secondary">${plural(p.accounts.length, 'cuenta', 'cuentas')} · media</div>` : ''}</div></div></td>
        <td class="text-nowrap">${S.by === 'player' && p.ths?.length > 1 ? p.ths.join(' · ') : p.th ?? '–'}</td><td class="scorecell"><div class="d-flex align-items-center gap-2"><div class="progress progress-sm flex-fill"><div class="progress-bar bg-gold" style="width:${p.index ?? 0}%"></div></div><b>${p.index ?? '–'}</b></div></td>
        <td>${levelBadge(p.level)}</td><td class="text-end">${p.used}/${p.avail}</td><td class="text-end">${ligaTxt(p)}</td><td class="text-end">${pctTxt(p.values.dano_liga)}</td><td class="text-end">${p.stars}</td><td class="text-end ${p.missed ? 'text-red fw-bold' : 'text-secondary'}">${p.missed}</td><td>${strip(p.ctx.recent.slice().reverse())}</td></tr>
        ${S.openRow === p.tag ? ctxRow(p, 11) : ''}`).join('') || `<tr><td colspan="11">${empty('Sin guerras con estos filtros')}</td></tr>`}</tbody></table></div>`, true)}
    ${sec('kpis', 'KPIs del clan', 'Barras frente a cada objetivo', `<div class="card-body"><div class="mb-4">${bullets(d.kpis, sum)}</div>
      <div class="table-responsive"><table class="table table-sm mb-0"><thead><tr><th>KPI</th><th>Mejor</th><th>Por mejorar</th></tr></thead><tbody>
      ${leaders.map(l => `<tr><td>${esc(l.k.name)}</td><td>${l.top ? `<a class="player-name" href="${link(l.top)}">${esc(l.top.name)}</a> <span class="text-secondary">${fmtKpi(l.k, l.top.values[l.k.id])}</span>` : '–'}</td><td>${l.low ? `<a class="player-name" href="${link(l.low)}">${esc(l.low.name)}</a> <span class="text-secondary">${fmtKpi(l.k, l.low.values[l.k.id])}</span>` : '–'}</td></tr>`).join('')}</tbody></table></div></div>`, false)}
    ${sec('graficas', 'Gráficas del clan', '5 gráficas', chartRow(`
      ${chart('chIndex', `Índice por ${one}`, `Nota general de cada ${one}; pulsa una barra para abrir su ficha`, {col: 'col-lg-7', h: Math.max(320, players.length * 26), has: players.length > 0})}
      <div class="col-lg-5"><div class="row g-4">${chart('chLevels', `${Many} por nivel`, `${S.by === 'player' ? 'Cuántos jugadores' : 'Cuántas cuentas'} hay en cada nivel del índice`, {col: 'col-12', h: 190, has: players.length > 0})}${chart('chTh', 'Índice medio por ayuntamiento', 'Nota media de las cuentas de cada ayuntamiento', {col: 'col-12', h: 190, has: ths.length > 0})}</div></div>
      ${chart('chScatter', 'Participación y estrellas', `Cada punto es ${S.by === 'player' ? 'un jugador' : 'una cuenta'}; arriba a la derecha está quien ataca siempre y bien`, {has: players.length > 0})}
      ${chart('chRadar', 'Clan frente a objetivos', 'Nota de 0 a 100 en cada KPI: cuanto más lejos del centro, mejor', {has: sum.index != null})}`), false, () => {
      draw('chIndex', {type: 'bar', data: {labels: ranked.map(p => p.name), datasets: [barSet('Índice', ranked.map(p => p.index))]},
        options: {...base({scales: {x: {min: 0, max: 100}, y: {grid: {display: false}, ticks: {autoSkip: false}}}}), indexAxis: 'y', onClick: (e, el) => { if (el[0]) location.hash = link(ranked[el[0].index]); }}});
      draw('chLevels', {type: 'bar', data: {labels: d.levels.map(l => l.name), datasets: [barSet(Many, counts)]}, options: base()});
      draw('chTh', {type: 'bar', data: {labels: ths.map(t => 'TH' + t), datasets: [barSet('Índice medio', ths.map(t => Math.round(th(t).reduce((a, p) => a + (p.index || 0), 0) / th(t).length)))]}, options: base({scales: pctY})});
      draw('chScatter', {type: 'scatter', data: {datasets: [{label: Many, data: ranked.map(p => ({x: p.values.participacion, y: p.values.estrellas, name: p.name})), backgroundColor: SERIES.us, pointRadius: 6, pointHoverRadius: 8, clip: false}]},
        options: base({plugins: {tooltip: {callbacks: {label: c => `${c.raw.name}: ${Math.round(c.raw.x)} % · ${dec(c.raw.y, 2)} ★`}}}, scales: {x: {min: 0, max: 100, title: {display: true, text: 'Participación %'}}, y: {min: 0, max: 3, title: {display: true, text: 'Estrellas por ataque'}}}})});
      draw('chRadar', {type: 'radar', data: {labels: d.kpis.map(k => k.name), datasets: [{label: 'Clan', data: d.kpis.map(k => sum.scores[k.id]), borderColor: SERIES.us, backgroundColor: 'rgba(176,124,14,.2)', borderWidth: 2, pointRadius: 3}]}, options: radarOpts({legend: {display: false}})});
    })}
    ${sec('calculo', 'Cómo se calcula el índice', '', `<div class="card-body"><p class="text-secondary">Cada KPI se puntúa de 0 a 100 entre su mínimo y su objetivo, y el índice es la media según su peso. Si un KPI no se puede medir, su peso se reparte entre los demás. Niveles: ${d.levels.map(l => `${esc(l.name)} ≥ ${l.min}`).join(' · ')}.</p>
      <table class="table table-sm mb-0"><thead><tr><th>KPI</th><th>Qué mide</th><th class="text-end">Peso</th><th class="text-end">Mínimo</th><th class="text-end">Objetivo</th></tr></thead><tbody>
      ${d.kpis.map(k => `<tr><td>${esc(k.name)}</td><td class="text-secondary">${esc(k.help)}</td><td class="text-end">${k.weight} %</td><td class="text-end">${fmtKpi(k, k.floor)}</td><td class="text-end">${fmtKpi(k, k.target)}</td></tr>`).join('')}</tbody></table></div>`)}`;
  $('clanView').querySelectorAll('[data-sort]').forEach(th_ => th_.onclick = e => { e.stopPropagation(); const k = th_.dataset.sort; S.sort = {k, d: S.sort.k === k ? -S.sort.d : k === 'name' ? 1 : -1}; paint(); });
  document.getElementById('sortPick')?.addEventListener('change', e => { const k = e.target.value; S.sort = {k, d: k === 'name' ? 1 : -1}; paint(); });
}

// ---------- administración: en la nube pide usuario y contraseña; en el PC entra directo
function renderLogin() {
  $('clanView').innerHTML = `<div class="card mx-auto" style="max-width:24rem"><div class="card-body"><h3 class="card-title"><i class="ti ti-lock me-1 text-secondary"></i>Entrar</h3>
    <form id="loginForm" class="d-grid gap-2"><input class="form-control" id="loginUser" placeholder="Usuario" aria-label="Usuario" autocomplete="username" autocapitalize="none"><input class="form-control" type="password" id="loginPass" placeholder="Contraseña" aria-label="Contraseña" autocomplete="current-password"><button class="btn btn-primary" type="submit">Entrar</button></form></div></div>`;
  $('loginForm').onsubmit = e => { e.preventDefault();
    sessionStorage.setItem('clave', `${$('loginUser').value.trim()}:${$('loginPass').value}`);
    api('api/login', {}).then(load).catch(err => { sessionStorage.removeItem('clave'); toast(esc(err.message), 'danger'); }); };
}
function renderAdmin(d) {
  const a = d.admin; if (!canEdit() || !a) return renderLogin();
  const when = ts => ts ? new Date(ts * 1000).toLocaleString('es-ES', {day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'}) : 'nunca';
  const source = {diaria: 'Automática', panel: 'Manual'};
  $('clanView').innerHTML = `
    ${a.cloud && a.default ? '<div class="alert alert-danger"><i class="ti ti-alert-triangle me-1"></i>Sigues con el acceso inicial <b>admin/admin</b>. La web es pública: cualquiera que lo pruebe podría cambiar el clan. Cámbialo abajo.</div>' : ''}
    ${a.cloud ? `<div class="d-flex align-items-center gap-2 mb-3 small text-secondary"><i class="ti ti-user"></i>Sesión de ${esc(a.user)}<button class="btn btn-sm btn-ghost-secondary ms-auto" id="adminOut"><i class="ti ti-logout me-1"></i>Salir</button></div>` : ''}
    ${sec('grupos', 'Cuentas ligadas a cada jugador', '', ownerBoard(d), true)}
    ${sec('aclan', 'Clan', '', `<div class="card-body"><form class="d-flex flex-wrap gap-2" id="adminTag" style="max-width:26rem"><input class="form-control flex-fill" style="width:auto" id="adminTagInput" value="${esc(a.clan_tag || '')}" aria-label="Tag del clan" autocomplete="off" autocapitalize="characters"><button class="btn btn-primary" type="submit">Cambiar clan</button></form>
      <div class="small text-secondary mt-2">Ahora: ${esc(d.clan?.name || '–')} · ${plural(a.members, 'cuenta', 'cuentas')}</div></div>`, true)}
    ${sec('arec', 'Recogida de datos', '', `<div class="card-body"><div class="d-flex flex-wrap align-items-center gap-2 mb-3"><div>Última completa: <b>${when(a.full_ts)}</b></div><button class="btn btn-primary ms-md-auto" id="adminSync"><i class="ti ti-refresh me-1"></i>Recoger ahora</button></div>
      ${a.error ? `<div class="alert alert-warning">${esc(a.error)}</div>` : ''}
      <div class="table-responsive"><table class="table table-sm mb-0"><thead><tr><th>Cuándo</th><th>Tipo</th><th class="text-end">Cuentas</th><th class="text-end">Fallidas</th></tr></thead><tbody>${a.log.map(l => `<tr><td>${when(l.ts)}</td><td>${source[l.source] || esc(l.source)}</td><td class="text-end">${l.players}</td><td class="text-end ${l.failed ? 'text-red fw-bold' : 'text-secondary'}">${l.failed}</td></tr>`).join('') || `<tr><td colspan="4">${empty('Aún no hay recogidas')}</td></tr>`}</tbody></table></div></div>`, true)}
    ${sec('aapi', 'API oficial de Supercell', '', `<div class="card-body"><div class="mb-2">${a.official ? '<i class="ti ti-circle-check text-green me-1"></i>Conectada' : '<i class="ti ti-alert-circle text-yellow me-1"></i>Sin conectar'}</div>
      <form class="d-flex flex-wrap gap-2" id="adminKey" style="max-width:40rem"><input class="form-control flex-fill" style="width:auto" type="password" id="adminKeyInput" placeholder="Nueva clave (eyJ0eXAi…)" aria-label="Nueva clave de la API" autocomplete="off"><button class="btn btn-primary" type="submit">Guardar clave</button></form>
      <div class="small text-secondary mt-2">Créala en developer.clashofclans.com con la IP <code>${esc(a.proxy_ip)}</code>.</div></div>`, false)}
    ${a.cloud ? sec('apass', 'Usuario y contraseña', '', `<div class="card-body"><form class="d-grid gap-2" id="adminPass" style="max-width:24rem"><input class="form-control" id="passUser" value="${esc(a.user)}" aria-label="Usuario" autocomplete="username" autocapitalize="none"><input class="form-control" type="password" id="passNew" placeholder="Contraseña nueva (8 caracteres o más)" aria-label="Contraseña nueva" autocomplete="new-password"><input class="form-control" type="password" id="passRepeat" placeholder="Repite la contraseña" aria-label="Repite la contraseña" autocomplete="new-password"><button class="btn btn-primary" type="submit">Cambiar acceso</button></form></div>`, a.default) : ''}`;
  wireBoard();
  const done = t => () => { toast(`<i class="ti ti-check me-1"></i>${t}`); load(); }, fail = err => toast(esc(err.message), 'danger');
  document.getElementById('adminOut')?.addEventListener('click', () => { sessionStorage.removeItem('clave'); load(); });
  $('adminSync').onclick = e => { e.currentTarget.disabled = true; toast('Recogiendo datos…', 'info'); api('api/sync', {}).then(done('Recogida lanzada')).catch(fail); };
  $('adminTag').onsubmit = e => { e.preventDefault(); const tag = $('adminTagInput').value.trim();
    if (tag === a.clan_tag || !confirm(`¿Seguir el clan ${tag}? La web pasará a enseñar sus datos.`)) return;
    api('api/tag', {clan_tag: tag}).then(done('Clan cambiado')).catch(fail); };
  $('adminKey').onsubmit = e => { e.preventDefault(); api('api/key', {key: $('adminKeyInput').value}).then(done('Clave guardada')).catch(fail); };
  const pf = document.getElementById('adminPass');
  if (pf) pf.onsubmit = e => { e.preventDefault(); const user = $('passUser').value.trim(), password = $('passNew').value;
    if (password !== $('passRepeat').value) return toast('Las contraseñas no coinciden', 'danger');
    api('api/password', {user, password}).then(() => { sessionStorage.setItem('clave', `${user}:${password}`); done('Acceso cambiado')(); }).catch(fail); };
}

// ---------- miembros
function renderMembers(d) {
  const all = S.by === 'player' ? d.owners : d.players, n = k => all.filter(p => p.state === k).length, needle = S.search.toLowerCase();
  const list = all.filter(p => (S.state === 'all' || p.state === S.state) && [p, ...(p.accounts || [])].some(x => x.name.toLowerCase().includes(needle)));
  const pill = (k, t, c) => `<li class="nav-item"><a class="nav-link ${S.state === k ? 'active' : ''}" data-state="${k}" href="#">${t} <span class="badge bg-secondary-lt ms-1">${c}</span></a></li>`;
  const ths = [...new Set(d.players.map(p => p.th).filter(Boolean))].sort((a, b) => a - b), [, , One, Many] = who();
  const ownerCard = p => `<div class="col-sm-6 col-xl-4"><div class="card lift h-100"><div class="card-body">
      <div class="d-flex align-items-center gap-3">${avatar(p, 'av-lg')}<div class="flex-fill" style="min-width:0"><a class="fw-bold text-truncate d-block text-reset" href="${link(p)}">${esc(p.name)}</a><div class="small text-secondary">${plural(p.accounts.length, 'cuenta', 'cuentas')} · media</div></div>${p.index != null ? ring(p.index, p.level, 52, 6) : ''}</div>
      <div class="d-flex align-items-center gap-2 mt-3">${stateBadge(p)}${p.index != null ? levelBadge(p.level) : ''}</div>
      <div class="mt-2">${p.accounts.map(a => `<a class="own-row" href="${hash(a.tag)}"><span class="text-truncate">${esc(a.name)}</span><span class="small text-secondary">TH${a.th ?? '?'}</span><b>${a.index ?? '–'}</b></a>`).join('')}</div></div></div></div>`;
  const cards = `<div class="row row-cards">${list.map(p => p.grouped ? ownerCard(p) : `<div class="col-sm-6 col-xl-4"><a class="card card-link lift text-reset text-decoration-none h-100" href="${hash(p.tag)}"><div class="card-body">
      <div class="d-flex align-items-center gap-3">${avatar(p, 'av-lg')}<div class="flex-fill" style="min-width:0"><div class="fw-bold text-truncate">${esc(p.name)}</div><div class="small text-secondary">TH${p.th ?? '?'}${p.owner && p.owner.name !== p.name ? ' · ' + esc(p.owner.name) : ''}</div></div>${p.index != null ? ring(p.index, p.level, 52, 6) : ''}</div>
      <div class="d-flex align-items-center gap-2 mt-3">${stateBadge(p)}${p.index != null ? levelBadge(p.level) : ''}<span class="ms-auto">${strip(p.ctx.recent.slice().reverse())}</span></div>
      <div class="small text-secondary mt-2">${liveText(p)}</div></div></a></div>`).join('') || `<div class="col-12"><div class="card">${empty('Nadie con este filtro')}</div></div>`}</div>`;
  const table = `<div class="card"><div class="table-responsive"><table class="table table-vcenter card-table rank-table mb-0"><thead><tr><th>${One}</th><th>TH</th><th>Estado</th><th>Detalle</th><th>Índice</th><th>Últimos ataques</th><th class="text-end">Guerras</th><th class="text-end">Sin usar</th></tr></thead>
      <tbody>${list.map(p => `<tr class="player" data-row="${esc(p.tag)}" aria-expanded="${S.openRow === p.tag}"><td><div class="d-flex align-items-center gap-2"><i class="ti ti-chevron-right row-chev"></i>${avatar(p)}<div><a class="player-name" href="${link(p)}">${esc(p.name)}</a>${ownerBadge(p.owner?.name, p.owner?.id, p.name)}${p.grouped ? `<div class="small text-secondary">${plural(p.accounts.length, 'cuenta', 'cuentas')} · media</div>` : ''}</div></div></td>
        <td class="text-nowrap">${S.by === 'player' && p.ths?.length > 1 ? p.ths.join(' · ') : p.th ?? '–'}</td><td>${stateBadge(p)}</td><td class="small text-secondary">${liveText(p)}</td><td><b>${p.index ?? '–'}</b> ${p.index != null ? levelBadge(p.level) : ''}</td><td>${strip(p.ctx.recent.slice().reverse())}</td><td class="text-end">${p.wars}</td><td class="text-end ${p.missed ? 'text-red fw-bold' : 'text-secondary'}">${p.missed}</td></tr>
        ${S.openRow === p.tag ? ctxRow(p, 8) : ''}`).join('') || `<tr><td colspan="8">${empty('Nadie con este filtro')}</td></tr>`}</tbody></table></div></div>`;
  $('clanView').innerHTML = `
    <div class="d-flex flex-wrap align-items-center gap-2 mb-3"><div class="hscroll flex-fill"><ul class="nav nav-pills" id="stateTabs">${pill('all', 'Todos', all.length)}${pill('war', 'En guerra', n('war'))}${pill('idle', 'Sin guerra', n('idle'))}${pill('gone', 'En otro clan', n('gone'))}</ul></div>
      <div class="ms-md-auto d-flex gap-2 flex-fill flex-md-grow-0"><input class="form-control form-control-sm flex-fill" style="min-width:11rem" id="memberSearch" placeholder="Buscar jugador o cuenta…" aria-label="Buscar jugador o cuenta" value="${esc(S.search)}">
      <div class="btn-group" role="group" aria-label="Vista"><button class="btn btn-sm btn-icon ${S.memberView === 'cards' ? 'btn-primary' : 'btn-ghost-secondary'}" data-view="cards" title="Tarjetas" aria-label="Tarjetas"><i class="ti ti-layout-grid"></i></button><button class="btn btn-sm btn-icon ${S.memberView === 'table' ? 'btn-primary' : 'btn-ghost-secondary'}" data-view="table" title="Tabla" aria-label="Tabla"><i class="ti ti-list"></i></button></div></div></div>
    ${legendBar(`${key('sw round', 'En guerra', 'background:var(--tblr-green)')}${key('sw round', 'Sin guerra', 'background:var(--tblr-secondary)')}${key('sw round', 'En otro clan', 'background:var(--tblr-red)')}`, LG_LEVELS, LG_STRIP)}
    <div class="mb-3">${S.memberView === 'cards' ? cards : table}</div>
    ${d.meta.official ? '<div class="small text-secondary mb-3"><i class="ti ti-circle-check text-green me-1"></i>Lista oficial conectada: las altas y bajas del clan entran solas en cada recogida.</div>'
      : d.meta.cloud ? '<div class="alert alert-warning">Falta la variable COC_API_KEY: sin ella, los miembros que no juegan guerras no aparecen.</div>'
      : sec('msrc', 'Activar la lista automática de miembros', '', `<div class="card-body"><ol class="mb-3"><li>Entra en <a href="https://developer.clashofclans.com" target="_blank" rel="noopener">developer.clashofclans.com</a> y crea una cuenta gratuita.</li><li>En tu cuenta pulsa <b>Create New Key</b> y, donde pide la IP, escribe <code>${esc(d.meta.proxy_ip)}</code>.</li><li>Copia la clave y pégala aquí. Se guarda sólo en tu PC.</li></ol>
        <form class="d-flex flex-wrap gap-2" id="keyForm" style="max-width:40rem"><input class="form-control form-control-sm flex-fill" style="width:auto" type="password" id="keyInput" placeholder="eyJ0eXAiOiJKV1Qi…" aria-label="Clave de la API oficial" autocomplete="off"><button class="btn btn-sm btn-primary" type="submit">Conectar</button></form></div>`)}
    ${sec('mgraf', 'Composición del clan', 'Estados y ayuntamientos', chartRow(`${chart('chStates', 'Estado ahora', `${S.by === 'player' ? 'Cuántos jugadores' : 'Cuántas cuentas'} están ahora en guerra`, {col: 'col-md-5', h: 230, has: all.length > 0})}${chart('chMemberTh', 'Ayuntamientos', 'Cuántas cuentas hay de cada nivel de ayuntamiento', {col: 'col-md-7', h: 230, has: all.length > 0})}`), false, () => {
      draw('chStates', {type: 'bar', data: {labels: ['En guerra', 'Sin guerra', 'En otro clan'], datasets: [barSet(Many, [n('war'), n('idle'), n('gone')])]}, options: base()});
      draw('chMemberTh', {type: 'bar', data: {labels: ths.map(t => 'TH' + t), datasets: [barSet('Cuentas', ths.map(t => d.players.filter(p => p.th === t).length))]}, options: base()});
    })}`;
  $('stateTabs').onclick = e => { const a = e.target.closest('[data-state]'); if (!a) return; e.preventDefault(); S.state = a.dataset.state; paint(); };
  $('memberSearch').oninput = e => { const at = e.target.selectionStart; S.search = e.target.value; paint(); const i = $('memberSearch'); i.focus(); i.setSelectionRange(at, at); };
  $('clanView').querySelectorAll('[data-view]').forEach(b => b.onclick = () => { S.memberView = b.dataset.view; localStorage.setItem('vistaMiembros', S.memberView); paint(); });
  const kf = document.getElementById('keyForm');
  if (kf) kf.onsubmit = e => { e.preventDefault();
    api('api/key', {key: $('keyInput').value}).then(() => { toast('<i class="ti ti-check me-1"></i>Lista oficial conectada; recogiendo datos…'); load(); }).catch(err => toast(esc(err.message), 'danger')); };
}

// ---------- guerras normales: sólo normales; las de otros clanes van aparte y nunca suman al clan
function warCards(rows, opts) {
  const shown = opts.round ? rows.slice().reverse() : rows, open = rows.find(w => w.end_ts === S.openWar);
  const cards = shown.map(w => { const total = (w.stars + w.opp_stars) || 1, [, rt] = RESULT[w.result] || RESULT.tie;
    return `<div class="col-sm-6 col-lg-4 col-xl-3"><div class="card war-card lift ${w.result} ${S.openWar === w.end_ts ? 'open' : ''}" data-war="${w.end_ts}" role="button" tabindex="0" aria-expanded="${S.openWar === w.end_ts}" aria-label="${esc(opts.label(w))} contra ${esc(w.opponent)}: ${rt}, ${w.stars} a ${w.opp_stars}"><div class="card-body">
      <div class="d-flex small text-secondary"><span class="fw-medium">${opts.round ? esc(opts.round(w)) : fechaLarga(w.end_ts)}</span><span class="ms-auto">${opts.round ? fecha(w.end_ts) : `${w.size} vs ${w.size}`}</span></div>
      <div class="fw-bold text-truncate mt-1">vs ${esc(w.opponent)}</div>
      <div class="d-flex align-items-center mt-2"><span class="score">${w.stars}<span class="text-secondary"> – </span>${w.opp_stars}</span><span class="ms-auto">${resultBadge(w.result)}</span></div>
      <div class="vs" aria-hidden="true"><i class="us" style="flex:${w.stars / total}"></i><i class="them" style="flex:${w.opp_stars / total}"></i></div>
      <div class="d-flex small text-secondary mt-1"><span>${dec(w.pct)} %</span><span class="ms-auto">${dec(w.opp_pct)} %</span></div></div></div></div>`; });
  (opts.live || []).forEach((w, i) => cards.push(`<div class="col-sm-6 col-lg-4 col-xl-3"><div class="card war-card ghost"><div class="card-body">
      <div class="d-flex small text-secondary"><span class="fw-medium">Ronda ${rows.length + i + 1}</span><span class="ms-auto">${w.phase === 'battle' ? '<span class="text-green"><i class="ti ti-swords me-1"></i>En batalla</span>' : '<i class="ti ti-hourglass me-1"></i>Preparación'}</span></div>
      <div class="fw-bold text-truncate mt-1">vs ${esc(w.rival_name || w.rival)}</div><div class="score mt-2 text-secondary">? – ?</div>
      <div class="small text-secondary mt-2">Acaba en ${fmtMin(w.ends - Date.now() / 1000)}; el resultado entra al terminar</div></div></div></div>`));
  return `<div class="card-body"><div class="row g-3">${cards.join('')}</div>${open ? `<div class="mt-3 fade-in"><div class="fw-medium mb-2">Quién hizo qué vs ${esc(open.opponent)}</div><div class="table-responsive"><table class="table table-sm table-vcenter mb-0"><thead><tr><th>#</th><th>Cuenta</th><th>Ataques</th><th>Defensa</th></tr></thead><tbody>${open.lineup.map(m => `<tr><td class="text-secondary">${m.pos ?? ''}</td><td><a class="player-name" href="${hash(m.tag)}">${esc(m.name)}</a> <span class="text-secondary small">TH${m.th ?? '?'}</span>${ownerBadge(opts.owners?.[m.tag], null, m.name)}</td>
      <td>${hitsHtml(m)}</td><td>${m.defenses.map(x => `<span class="hit">${stars(x.stars)}</span>`).join('') || '<span class="text-secondary small">–</span>'}</td></tr>`).join('')}</tbody></table></div></div>` : ''}</div>`;
}
const heatCell = (w, t) => { const m = w.lineup.find(x => x.tag === t); if (!m) return '<td class="heat-off"></td>';
  const s = m.attacks.reduce((a, x) => a + x.stars, 0), max = m.per * 3, miss = m.per - m.attacks.length;
  return `<td class="heat" style="background:rgba(176,124,14,${(.12 + .68 * s / max).toFixed(2)})" title="${esc(m.name)} vs ${esc(w.opponent)}: ${s} de ${max} estrellas${miss ? ', ' + miss + ' sin usar' : ''}">${s}${miss ? '<span class="miss">!</span>' : ''}</td>`; };
function warBlock(id, rows, heat, opts) {           // rows: de la más reciente a la más antigua
  const wars = rows.slice().reverse(), lab = wars.map(opts.label), cols = rows.slice(0, 20), one = opts.one;
  let bal = 0; const balance = wars.map(w => bal += w.result === 'win' ? 1 : w.result === 'lose' ? -1 : 0);
  return `${sec(id + 'list', opts.title, `${plural(rows.length, one, opts.many)}; pulsa una para ver quién hizo qué`, warCards(rows, opts), true)}
    ${sec(id + 'heat', 'Mapa de jugadores', 'Estrellas de cada uno; «!» marca ataques sin usar', `<div class="table-responsive"><table class="table table-sm card-table heat-table mb-0"><thead><tr><th>Cuenta</th>${cols.map(w => `<th title="vs ${esc(w.opponent)}">${esc(opts.label(w))}</th>`).join('')}</tr></thead>
      <tbody>${heat.filter(p => cols.some(w => w.lineup.some(m => m.tag === p.tag))).map(p => `<tr><td><a class="player-name" href="${hash(p.tag)}">${esc(p.name)}</a>${ownerBadge(opts.owners?.[p.tag], null, p.name)}</td>${cols.map(w => heatCell(w, p.tag)).join('')}</tr>`).join('')}</tbody></table></div>`, true)}
    ${sec(id + 'graf', `Gráficas de ${opts.many}`, '4 gráficas', chartRow(`${chart(id + 'Stars', `Estrellas por ${one}`, 'Nosotros frente al rival')}${chart(id + 'Pct', `Destrucción por ${one}`, 'Porcentaje total de cada lado')}${chart(id + 'Used', 'Ataques usados', 'Qué parte de los ataques disponibles se usó')}${chart(id + 'Bal', 'Balance acumulado', 'Suma 1 por victoria y resta 1 por derrota: si sube, el clan va ganando')}`), false, () => {
      draw(id + 'Stars', {type: 'bar', data: {labels: lab, datasets: [barSet('Nosotros', wars.map(w => w.stars)), barSet('Rival', wars.map(w => w.opp_stars), SERIES.them)]}, options: {...base(), plugins: legend}});
      draw(id + 'Pct', {type: 'line', data: {labels: lab, datasets: [lineSet('Nosotros', wars.map(w => w.pct)), lineSet('Rival', wars.map(w => w.opp_pct), SERIES.them)]}, options: {...base({scales: pctY}), plugins: legend}});
      draw(id + 'Used', {type: 'bar', data: {labels: lab, datasets: [barSet('Usados %', wars.map(w => { const a = w.lineup.reduce((x, m) => x + m.per, 0); return a ? Math.round(100 * w.lineup.reduce((x, m) => x + m.attacks.length, 0) / a) : 0; }))]}, options: base({scales: pctY})});
      draw(id + 'Bal', {type: 'line', data: {labels: lab, datasets: [lineSet('Balance', balance)]}, options: base({scales: {x: {grid: {display: false}}, y: {ticks: {precision: 0}}}})});
    })}`;
}
function renderWars(d) {
  const has = d.wars.length > 0, r = d.summary;
  const others = `<div class="table-responsive"><table class="table table-vcenter card-table rank-table mb-0"><thead><tr><th>Cuenta</th><th>TH</th><th>Índice</th><th class="text-end">Guerras</th><th class="text-end">Ataques</th><th class="text-end">Daño efectivo</th><th class="text-end">Media</th><th class="text-end">Clanes</th><th>Último clan</th><th class="text-end">Última</th></tr></thead>
    <tbody>${d.others.map(o => `<tr><td><a class="player-name" href="${hash(o.tag)}">${esc(o.name)}</a>${ownerBadge(d.owner_names[o.tag], null, o.name)}</td><td>${o.th ?? '–'}</td><td><b>${o.index ?? '–'}</b> ${levelBadge(o.level)}</td><td class="text-end">${o.wars}</td><td class="text-end">${o.used}/${o.avail}</td><td class="text-end">${pctTxt(o.values.dano_efectivo)}</td><td class="text-end">${dec(o.values.estrellas, 2)} ★</td><td class="text-end">${o.clans}</td><td class="small">${esc(o.last_clan)}</td><td class="text-end text-secondary">${fechaLarga(o.last_ts)}</td></tr>`).join('') || `<tr><td colspan="10">${empty('Sin guerras con otros clanes')}</td></tr>`}</tbody></table></div>`;
  $('clanView').innerHTML = `
    ${has ? `<div class="row row-cards mb-3">${splitCard('war', 'Guerras normales del clan', 'ti-swords', r, null, '', '')}</div>` : `<div class="card mb-3"><div class="empty-state"><i class="ti ti-swords"></i><div class="h3 mt-2 mb-1">Aún no hay guerras normales</div><div class="text-secondary">Este apartado se irá llenando con las próximas guerras del clan.</div><a class="btn btn-sm btn-ghost-primary mt-3" href="#ligas">Ver las rondas de liga <i class="ti ti-arrow-right ms-1"></i></a></div></div>`}
    ${has ? sec('wplay', 'Jugadores en guerras normales', '', ownerTable(d.owners, 'Sin guerras normales'), true) : ''}
    ${has ? warBlock('w', d.wars, d.heat, {title: 'Guerras', one: 'guerra', many: 'guerras', label: w => fecha(w.end_ts), owners: d.owner_names}) : ''}
    ${sec('wother', 'Tus miembros en otros clanes', `Guerras normales fuera de ${esc(d.clan.name)}; no cuentan para el clan`, others, !has)}`;
}

// ---------- ligas: sólo liga
function renderLeagues(d) {
  const se = d.seasons, has = se.length > 0, months = se.map(s => s.season.slice(0, 7));
  const month = S.season && months.includes(S.season) ? S.season : months[months.length - 1];
  const cur = se[months.indexOf(month)], live = cur && cur.state !== 'ended';
  const rows = d.rounds.filter(w => new Date(w.end_ts * 1000).toISOString().slice(0, 7) === month), rd = rows.slice().reverse();
  const num_ = Object.fromEntries(rd.map((w, i) => [w.end_ts, i + 1])), label = w => `R${num_[w.end_ts]}`;
  const lab = months.map(m => { const [y, mo] = m.split('-'); return `${mo}/${y.slice(2)}`; });
  const liveCwl = live ? d.live.filter(w => w.type === 'cwl') : [];
  $('clanView').innerHTML = `
    ${months.length > 1 ? `<div class="d-flex align-items-center gap-2 mb-3"><span class="small text-secondary">Temporada</span><select class="form-select form-select-sm w-auto" id="seasonPick" aria-label="Temporada">${months.slice().reverse().map(m => `<option ${m === month ? 'selected' : ''}>${m}</option>`).join('')}</select></div>` : ''}
    ${cur ? `<div class="card hero mb-3"><div class="card-body d-flex flex-wrap align-items-center gap-4">
      <div style="flex:1 1 220px"><div class="subheader">${live ? 'Liga en curso' : 'Liga'}</div><div class="h1 mb-0">${esc(cur.league || '–')}</div></div>
      <div class="text-center"><div class="subheader">Puesto</div><div class="h1 mb-0">${cur.rank ?? '–'}º</div></div>
      <div class="text-center"><div class="subheader">Estrellas</div><div class="h1 mb-0">${cur.stars ?? '–'}</div></div>
      <div class="text-center"><div class="subheader" title="Si hay empate a estrellas, desempata la destrucción acumulada">Destrucción acumulada</div><div class="h1 mb-0">${cur.destruction == null ? '–' : dec(cur.destruction, 1) + ' %'}</div></div>
      <div class="text-center"><div class="subheader">Victorias-Empates-Derrotas</div><div class="h1 mb-0">${cur.won ?? 0}-${cur.tied ?? 0}-${cur.lost ?? 0}</div></div>
      <div class="hero-tracker">${tracker(rd, liveCwl)}</div></div></div>` : ''}
    ${rows.length ? warBlock('l', rows, d.heat, {title: 'Rondas', one: 'ronda', many: 'rondas', label, live: liveCwl, round: w => `Ronda ${num_[w.end_ts]}`, owners: d.owner_names}) : sec('lnone', 'Rondas', '', warCards([], {live: liveCwl}), true)}
    ${d.owners[month] ? sec('lplay', 'Jugadores de la temporada', '', ownerTable(d.owners[month], 'Sin rondas', true), true) : ''}
    ${sec('ljug', 'Cuentas por temporada', 'Estrellas · ataques usados · % total y % medio', `<div class="table-responsive"><table class="table table-vcenter card-table rank-table mb-0"><thead><tr><th>Cuenta</th>${months.map(m => `<th class="text-end">${m}</th>`).join('')}</tr></thead>
      <tbody>${d.matrix.map(r => `<tr><td><a class="player-name" href="${hash(r.tag)}">${esc(r.name)}</a>${ownerBadge(d.owner_names[r.tag], null, r.name)}</td>${months.map(m => { const c = r.cells[m]; return `<td class="text-end">${c ? `${c.stars} ★ <span class="text-secondary small">${c.used}/${c.avail}</span>${c.used ? `<div class="small text-secondary">${Math.round(c.pct)} % · media ${Math.round(c.pct / c.used)} %</div>` : ''}` : '<span class="text-secondary">–</span>'}</td>`; }).join('')}</tr>`).join('') || `<tr><td colspan="9">${empty('Sin datos')}</td></tr>`}</tbody></table></div>`)}
    ${sec('lhist', 'Histórico de temporadas', `${plural(se.length, 'temporada', 'temporadas')} guardadas`, `<div class="table-responsive"><table class="table table-vcenter card-table rank-table mb-0"><thead><tr><th>Temporada</th><th>Liga</th><th>Estado</th><th class="text-end">Puesto</th><th class="text-end">Estrellas</th><th class="text-end">Destrucción acumulada</th><th class="text-end">Victorias-Empates-Derrotas</th></tr></thead>
      <tbody>${se.slice().reverse().map(s => `<tr><td>${esc(s.season.slice(0, 7))}</td><td>${esc(s.league || '–')}</td><td>${s.state === 'ended' ? '<span class="badge bg-secondary-lt">Terminada</span>' : '<span class="badge bg-green-lt">En curso</span>'}</td><td class="text-end">${s.rank ?? '–'}º</td><td class="text-end">${s.stars ?? '–'}</td><td class="text-end">${s.destruction == null ? '–' : dec(s.destruction, 1) + ' %'}</td><td class="text-end">${s.won ?? 0}-${s.tied ?? 0}-${s.lost ?? 0}</td></tr>`).join('') || `<tr><td colspan="7">${empty('Sin temporadas')}</td></tr>`}</tbody></table></div>
      ${has ? chartRow(`${chart('chRank', 'Puesto por temporada', 'Puesto final en cada temporada: más arriba es mejor', {col: 'col-lg-4'})}${chart('chSeasonStars', 'Estrellas por temporada', 'Total del clan', {col: 'col-lg-4'})}${chart('chSeasonWL', 'Rondas ganadas y perdidas', 'Por temporada', {col: 'col-lg-4'})}`) : ''}`, false, () => {
      if (!has) return;
      draw('chRank', {type: 'line', data: {labels: lab, datasets: [lineSet('Puesto', se.map(s => s.rank))]}, options: base({scales: {x: {grid: {display: false}}, y: {reverse: true, min: 1, max: 8, ticks: {precision: 0}}}})});
      draw('chSeasonStars', {type: 'bar', data: {labels: lab, datasets: [barSet('Estrellas', se.map(s => s.stars))]}, options: base()});
      draw('chSeasonWL', {type: 'bar', data: {labels: lab, datasets: [barSet('Ganadas', se.map(s => s.won)), barSet('Perdidas', se.map(s => s.lost), SERIES.them)]}, options: {...base(), plugins: legend}});
    })}`;
  const pick = document.getElementById('seasonPick');
  if (pick) pick.onchange = e => { S.season = e.target.value; S.openWar = null; paint(); };
}

// ---------- ficha de jugador
function historyTable(rows, none) {
  return `<div class="table-responsive" style="max-height:420px"><table class="table table-vcenter card-table rank-table mb-0"><thead class="sticky-top"><tr><th>Fin</th><th>Clan</th><th>Rival</th><th>Resultado</th><th>Ataques</th><th class="text-end">Estrellas otorgadas al rival</th></tr></thead>
    <tbody>${rows.slice().reverse().map(w => `<tr><td class="text-secondary">${fechaLarga(w.ts)}</td><td class="small">${esc(w.clan)}</td><td>${esc(w.opponent)}</td><td>${resultBadge(w.result)}</td><td>${hitsHtml(w)}</td><td class="text-end">${w.defenses ? w.conceded : '–'}</td></tr>`).join('') || `<tr><td colspan="6">${empty(none)}</td></tr>`}</tbody></table></div>`;
}
function renderPlayer(d) {
  const p = d.player, c = d.card, tl = d.timeline, lab = tl.map(w => fecha(w.ts)), has = tl.length > 0;
  const atk = tl.reduce((a, w) => a + w.attacks.length, 0), def = tl.some(w => w.defenses), timingTotal = d.timing.reduce((a, b) => a + b, 0);
  const cwlT = tl.filter(w => w.kind === 'cwl'), warT = tl.filter(w => w.kind === 'war');
  const scoped = S.scope === 'clan' && d.history.wars > tl.length;
  const byKind = (label, f, k) => barSet(label, tl.map(w => w.kind === k ? f(w) : null), SERIES[k], 's');
  const tip = {tooltip: {callbacks: {afterTitle: i => { const w = tl[i[0].dataIndex]; return w ? `vs ${w.opponent} (${w.kind === 'cwl' ? 'liga' : 'normal'})` : ''; }}}, ...legend};
  const stacked = {x: {stacked: true, grid: {display: false}, ticks: {maxRotation: 0, autoSkip: true, maxTicksLimit: 10}}, y: {stacked: true, beginAtZero: true, ticks: {precision: 0}}};
  $('clanView').innerHTML = `
    <a class="btn btn-ghost-secondary btn-sm mb-2" href="#miembros"><i class="ti ti-arrow-left me-1"></i>Miembros</a>
    <div class="card hero mb-3"><div class="card-body d-flex flex-wrap align-items-center gap-4">
      ${avatar(p, 'av-lg')}
      <div style="flex:1 1 240px"><div class="h1 mb-1">${esc(p.name)}</div><div class="text-secondary small">${esc(p.tag)} · TH${p.th ?? '?'} · ${plural(d.history.wars, 'guerra', 'guerras')} en ${plural(d.history.clans, 'clan', 'clanes')}</div>
        <div class="mt-2">${stateBadge(p)} <span class="small text-secondary ms-1">${liveText(p)}</span></div>
        ${atk ? `<div class="mt-2 d-flex align-items-center gap-2 small text-secondary">Últimos ataques ${strip(tl)}</div><div class="legend-inline">${LG_STRIP.replace(/<span class="lg-title">.*?<\/span>/, '')}</div>` : ''}</div>
      <div class="text-center">${ring(c.index, c.level, 104, 10)}<div class="mt-1">${levelBadge(c.level)}</div><div class="small mt-1">${trendHtml(c.trend)}</div></div>
      <div class="btn-group" role="group" aria-label="Ámbito"><button class="btn btn-sm ${S.scope === 'clan' ? 'btn-primary' : 'btn-ghost-secondary'}" data-scope="clan">Este clan</button><button class="btn btn-sm ${S.scope === 'all' ? 'btn-primary' : 'btn-ghost-secondary'}" data-scope="all">Todo su historial</button></div>
    </div></div>
    ${d.owner ? `<div class="card mb-3"><div class="card-body d-flex flex-wrap align-items-center gap-3">${ring(d.owner.index, d.owner.level, 56, 6)}
      <div style="flex:1 1 220px"><div class="subheader">Cuenta de</div><a class="h3 mb-0 text-reset" href="${ownerHash(d.owner.id)}">${esc(d.owner.name)}</a><div class="small text-secondary">Índice como jugador: media de sus ${plural(d.owner.accounts.length, 'cuenta', 'cuentas')}</div></div>
      <div class="d-flex flex-wrap gap-2">${d.owner.accounts.filter(a => a.tag !== p.tag).map(a => `<a class="btn btn-sm" href="${hash(a.tag)}">${esc(a.name)} <span class="text-secondary ms-1">${a.index ?? '–'}</span></a>`).join('')}</div></div></div>` : ''}
    <div class="row row-cards mb-3">${splitCard('cwl', 'Liga · todo su historial', 'ti-shield-star', d.split.cwl, null, '', 'Sin rondas de liga.')}${splitCard('war', 'Guerras normales · todo su historial', 'ti-swords', d.split.war, null, '', 'Sin guerras normales.')}</div>
    ${scoped ? `<div class="alert alert-info py-2">Vista de este clan: ${plural(tl.length, 'guerra', 'guerras')}. Tiene ${d.history.wars} en total; pulsa «Todo su historial» para verlas.</div>` : ''}
    ${sec('pkpi', 'KPIs', `Frente al clan · ${KIND_NAME[S.kind]}`, `<div class="card-body">${bullets(d.kpis, c, d.clan_card)}</div>`, true)}
    ${sec('pforma', 'Forma y ataque', '5 gráficas', chartRow(`${chart('pRadar', 'Perfil frente al clan', 'Nota de 0 a 100 en cada KPI: cuanto más lejos del centro, mejor', {col: 'col-lg-5', h: 280, has})}${chart('pForm', 'Forma', 'Media de estrellas de sus 5 últimos ataques: si sube, va a mejor', {col: 'col-lg-7', h: 280, has: atk > 0})}${chart('pStars', 'Estrellas por guerra', 'Violeta: rondas de liga (máximo 3). Dorado: guerras normales (máximo 6)', {has})}${chart('pPct', 'Daño por ataque', 'Porcentaje de la aldea rival que destruyó en cada ataque', {has: atk > 0})}${chart('pDist', 'Reparto de estrellas', `Cuántos de sus ${plural(atk, 'ataque', 'ataques')} sacaron 0, 1, 2 o 3 estrellas`, {col: 'col-12', h: 220, has: atk > 0})}`), true, () => {
      if (!has) return;
      draw('pRadar', {type: 'radar', data: {labels: d.kpis.map(k => k.name), datasets: [
        {label: p.name, data: d.kpis.map(k => c.scores[k.id]), borderColor: SERIES.us, backgroundColor: 'rgba(176,124,14,.2)', borderWidth: 2, pointRadius: 3},
        {label: 'Clan', data: d.kpis.map(k => d.clan_card.scores[k.id]), borderColor: SERIES.them, backgroundColor: 'rgba(168,85,247,.12)', borderWidth: 2, borderDash: [5, 4], pointRadius: 3}]}, options: radarOpts(legend)});
      draw('pForm', {type: 'line', data: {labels: d.rolling.map(r => fecha(r.ts)), datasets: [lineSet('Media de 5', d.rolling.map(r => r.avg))]}, options: base({scales: starY})});
      draw('pStars', {type: 'bar', data: {labels: lab, datasets: [byKind('Liga', w => w.stars, 'cwl'), byKind('Normales', w => w.stars, 'war')]}, options: base({plugins: tip, scales: stacked})});
      const hits = tl.flatMap(w => w.attacks.map(a => ({...a, ts: w.ts})));
      draw('pPct', {type: 'line', data: {labels: hits.map(h => fecha(h.ts)), datasets: [lineSet('Daño %', hits.map(h => h.pct))]}, options: base({scales: pctY})});
      draw('pDist', {type: 'bar', data: {labels: ['0 ★', '1 ★', '2 ★', '3 ★'], datasets: [barSet('Ataques', d.dist)]}, options: base()});
    })}
    ${sec('prival', 'Contra quién y cuándo', '2 gráficas', chartRow(`${chart('pDiff', 'Según el TH rival', 'Estrellas medias según lo fuerte que sea el rival; 0 es su mismo ayuntamiento', {has: d.by_diff.length > 0})}${chart('pTiming', 'Cuándo ataca', 'En qué parte de la guerra usa sus ataques: al principio, a mitad o al final', {has: timingTotal > 0})}`), false, () => {
      draw('pDiff', {type: 'bar', data: {labels: d.by_diff.map(x => (x.diff > 0 ? '+' : '') + x.diff), datasets: [barSet('Estrellas medias', d.by_diff.map(x => x.stars))]},
        options: base({plugins: {tooltip: {callbacks: {afterLabel: c_ => `${d.by_diff[c_.dataIndex].n} ataques · ${d.by_diff[c_.dataIndex].pct} % de daño`}}}, scales: {...starY, x: {grid: {display: false}, title: {display: true, text: 'TH rival menos el suyo'}}}})});
      draw('pTiming', {type: 'bar', data: {labels: ['Primer tercio', 'Segundo', 'Último'], datasets: [barSet('Ataques', d.timing)]}, options: base()});
    })}
    ${sec('pdef', 'Defensa', '2 gráficas', chartRow(`${chart('pDef', 'Estrellas otorgadas al rival', 'Estrellas que le sacan en cada guerra: cuantas menos, mejor', {has: def})}${chart('pDefTh', 'Defensa por TH atacante', 'Estrellas medias que le sacan según quién le ataque', {has: d.def_by_th.length > 0})}`), false, () => {
      draw('pDef', {type: 'bar', data: {labels: lab, datasets: [byKind('Liga', w => w.conceded, 'cwl'), byKind('Normales', w => w.conceded, 'war')]}, options: base({plugins: tip, scales: stacked})});
      draw('pDefTh', {type: 'bar', data: {labels: d.def_by_th.map(x => 'TH' + x.th), datasets: [barSet('Estrellas', d.def_by_th.map(x => x.stars))]}, options: base({plugins: {tooltip: {callbacks: {afterLabel: c_ => `${d.def_by_th[c_.dataIndex].n} defensas`}}}, scales: starY})});
    })}
    ${sec('pritmo', 'Ritmo y temporadas', '2 gráficas', chartRow(`${chart('pDur', 'Duración de sus ataques', 'Tiempo que dura cada ataque, en segundos', {has: d.durations.length > 0})}${chart('pSeasons', 'Estrellas por temporada de liga', 'Incluye temporadas con otros clanes', {has: d.seasons.length > 0})}`), false, () => {
      draw('pDur', {type: 'line', data: {labels: d.durations.map(x => fecha(x.ts)), datasets: [lineSet('Segundos', d.durations.map(x => x.s))]}, options: base()});
      draw('pSeasons', {type: 'bar', data: {labels: d.seasons.map(s => s.season.slice(0, 7)), datasets: [barSet('Estrellas', d.seasons.map(s => s.stars), SERIES.cwl)]}, options: base({plugins: {tooltip: {callbacks: {afterLabel: c_ => { const s = d.seasons[c_.dataIndex]; return `${s.clan_name} · ${s.league || ''} · ${s.attacks} ataques`; }}}}})});
    })}
    ${sec('phcwl', 'Histórico de liga', plural(cwlT.length, 'ronda', 'rondas'), historyTable(cwlT, 'Sin rondas con estos filtros'), S.kind !== 'war')}
    ${sec('phwar', 'Histórico de guerras normales', plural(warT.length, 'guerra', 'guerras'), historyTable(warT, S.scope === 'clan' ? 'Sin guerras normales en este clan; pulsa «Todo su historial»' : 'Sin guerras normales con estos filtros'), S.kind === 'war')}`;
  $('clanView').querySelectorAll('[data-scope]').forEach(b => b.onclick = () => { S.scope = b.dataset.scope; load(); });
}

function renderOwner(d) {
  const o = d.owner, c = {values: o.values, scores: o.scores}, acc = o.accounts, played = acc.filter(a => a.index != null), has = played.length > 0;
  $('clanView').innerHTML = `
    <a class="btn btn-ghost-secondary btn-sm mb-2" href="#miembros"><i class="ti ti-arrow-left me-1"></i>Miembros</a>
    <div class="card hero mb-3"><div class="card-body d-flex flex-wrap align-items-center gap-4">
      ${avatar(o, 'av-lg')}
      <div style="flex:1 1 240px"><div class="h1 mb-1">${esc(o.name)}</div><div class="text-secondary small">${plural(acc.length, 'cuenta', 'cuentas')} · ${thText(o)} · ${plural(d.history.wars, 'participación', 'participaciones')} en ${plural(d.history.clans, 'clan', 'clanes')}</div>
        <div class="mt-2">${stateBadge(o)} <span class="small text-secondary ms-1">${liveText(o)}</span></div></div>
      <div class="text-center">${ring(o.index, o.level, 104, 10)}<div class="mt-1">${levelBadge(o.level)}</div><div class="small mt-1">${trendHtml(o.trend)}</div></div>
      <div class="btn-group" role="group" aria-label="Ámbito"><button class="btn btn-sm ${S.scope === 'clan' ? 'btn-primary' : 'btn-ghost-secondary'}" data-scope="clan">Este clan</button><button class="btn btn-sm ${S.scope === 'all' ? 'btn-primary' : 'btn-ghost-secondary'}" data-scope="all">Todo su historial</button></div>
    </div></div>
    ${sec('oacc', 'Sus cuentas', '', `<div class="card-body">${accountCards(acc)}</div>`, true)}
    <div class="row row-cards mb-3">${splitCard('cwl', 'Liga · media de sus cuentas', 'ti-shield-star', d.split.cwl, null, 'Todo su historial', 'Sin rondas de liga.')}${splitCard('war', 'Guerras normales · media de sus cuentas', 'ti-swords', d.split.war, null, 'Todo su historial', 'Sin guerras normales.')}</div>
    ${sec('okpi', 'KPIs del jugador', '', `<div class="card-body">${bullets(d.kpis, c, d.clan_card)}</div>`, true)}
    ${sec('ocmp', 'Cuenta a cuenta', '', `<div class="table-responsive"><table class="table table-sm card-table rank-table mb-0"><thead><tr><th>KPI</th>${acc.map(a => `<th class="text-end">${esc(a.name)}</th>`).join('')}<th class="text-end">Jugador</th><th class="text-end">Clan</th></tr></thead><tbody>
      ${d.kpis.map(k => `<tr><td>${esc(k.name)}</td>${acc.map(a => `<td class="text-end">${fmtKpi(k, a.values[k.id])}</td>`).join('')}<td class="text-end fw-bold">${fmtKpi(k, o.values[k.id])}</td><td class="text-end text-secondary">${fmtKpi(k, d.clan_card.values[k.id])}</td></tr>`).join('')}</tbody></table></div>
      ${chartRow(`${chart('oIndex', 'Índice por cuenta', 'La nota del jugador es la media de estas barras', {has})}${chart('oRadar', 'Perfil frente al clan', 'Nota de 0 a 100 en cada KPI: cuanto más lejos del centro, mejor', {has})}`)}`, true, () => {
      if (!has) return;
      draw('oIndex', {type: 'bar', data: {labels: played.map(a => a.name), datasets: [barSet('Índice', played.map(a => a.index))]}, options: base({scales: pctY})});
      draw('oRadar', {type: 'radar', data: {labels: d.kpis.map(k => k.name), datasets: [
        {label: o.name, data: d.kpis.map(k => o.scores[k.id]), borderColor: SERIES.us, backgroundColor: 'rgba(176,124,14,.2)', borderWidth: 2, pointRadius: 3},
        {label: 'Clan', data: d.kpis.map(k => d.clan_card.scores[k.id]), borderColor: SERIES.them, backgroundColor: 'rgba(168,85,247,.12)', borderWidth: 2, borderDash: [5, 4], pointRadius: 3}]}, options: radarOpts(legend)});
    })}`;
  $('clanView').querySelectorAll('[data-scope]').forEach(b => b.onclick = () => { S.scope = b.dataset.scope; load(); });
}

// Cada tabla se puede leer como tarjetas en el teléfono: cada celda toma como etiqueta el título de su columna.
function cardTables() {
  $('clanView').querySelectorAll('table.table:not(.heat-table)').forEach(t => {
    const heads = t.tHead ? [...t.tHead.rows[0].cells] : null; if (!heads) return;
    t.classList.add('m-cards');
    const pos = heads[0].classList.contains('pos') ? 1 : 0;
    [...t.tBodies[0].rows].forEach(r => {
      if (r.classList.contains('ctx-row')) return;
      [...r.cells].forEach((c, i) => { if (c.colSpan > 1) return; if (i === pos) c.classList.add('m-main'); const l = heads[i]?.textContent.replace(/[↑↓]/g, '').trim(); if (l && !c.classList.contains('pos')) c.dataset.l = l; });
    });
  });
}

// ---------- marco: filtros, cabecera y carga
function paintHead(m) {
  const syncing = m.syncing, full = m.full_ts ? new Date(m.full_ts * 1000).toLocaleString('es-ES', {day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'}) : 'nunca';
  const next = m.next ? new Date(m.next * 1000).toLocaleString('es-ES', {weekday: 'long', hour: '2-digit', minute: '2-digit'}).replace(', ', ' a las ') : null;
  $('clanSync').innerHTML = syncing ? '<i class="ti ti-refresh spin me-1"></i>Recogiendo datos…' : `<i class="ti ti-clock me-1"></i>Última recogida ${full}${next ? ` · próxima ${next}` : ' · se recoge una vez al día'}`;
  $('clanRefresh').disabled = syncing; $('clanRefresh').classList.toggle('d-none', !canEdit());
  $('clanError').classList.toggle('d-none', !m.error); $('clanError').textContent = m.error || '';
}
// El desglose ocupa lo visible aunque la tabla tenga scroll lateral.
function fitCtx() { $('clanView').querySelectorAll('.ctx-row').forEach(r => { const t = r.closest('.table-responsive'); if (t) t.style.setProperty('--vis', t.clientWidth + 'px'); }); }
window.addEventListener('resize', fitCtx);
function paint() {
  const d = S.data; if (!d) return;
  clearCharts();
  $('clanFilters').classList.toggle('d-none', ['ligas', 'admin'].includes(S.sub));
  const fixedKind = S.sub === 'guerras';                  // Guerras normales sólo enseña normales: no hay tipo que elegir
  $('clanKind').classList.toggle('d-none', fixedKind); $('clanKindLabel').classList.toggle('d-none', fixedKind);
  $('clanBy').classList.toggle('d-none', !['resumen', 'miembros'].includes(S.sub));
  $('clanBy').querySelectorAll('[data-by]').forEach(b => { b.classList.toggle('btn-primary', b.dataset.by === S.by); b.classList.toggle('btn-ghost-secondary', b.dataset.by !== S.by); });
  $('clanTabs').querySelectorAll('.nav-link').forEach(a => a.classList.toggle('active', a.dataset.v === (['jugador', 'persona'].includes(S.sub) ? 'miembros' : S.sub)));
  if (d.clan) { $('clanName').textContent = d.clan.name; $('clanMeta').textContent = `${d.clan.tag}${d.clan.season ? ' · ' + (d.clan.season.league || '') : ''}`; }
  ({resumen: renderResumen, miembros: renderMembers, guerras: renderWars, ligas: renderLeagues, jugador: renderPlayer, persona: renderOwner, admin: renderAdmin})[S.sub](d);
  const page = PAGES[S.sub];
  $('clanView').insertAdjacentHTML('afterbegin', `<div class="page-intro"><h2 class="mb-1">${page[0]}</h2><p class="text-secondary mb-3">${page[1]}</p></div>`);
  cardTables();
  fitCtx();
  drawOpen();
  if (S.enter) { S.enter = false; $('clanView').classList.remove('fade-in'); void $('clanView').offsetWidth; $('clanView').classList.add('fade-in'); }
}
function url() {
  if (S.sub === 'guerras') return `api/wars?kind=war&days=${S.days}`;
  if (S.sub === 'ligas') return 'api/leagues';
  if (S.sub === 'jugador') return `api/player?tag=${encodeURIComponent(S.tag)}&scope=${S.scope}&${q()}`;
  if (S.sub === 'persona') return `api/owner?id=${encodeURIComponent(S.tag)}&scope=${S.scope}&${q()}`;
  return `api/overview?${q()}${S.sub === 'admin' ? '&fresh=1' : ''}`;
}
function load() {
  const seq = ++S.seq;
  const admin = S.sub === 'admin' && canEdit() ? api('api/admin', {}).catch(() => new Promise(r => setTimeout(r, 1300)).then(() => api('api/admin', {}))).catch(() => { sessionStorage.removeItem('clave'); return null; }) : null;   // un reintento antes de cerrar la sesión
  return Promise.all([api(url()), admin]).then(([d, info]) => {
    d.admin = info;
    if (seq !== S.seq || S.dragging) return;    // llegó otra petición más nueva, o repintar cortaría el arrastre
    S.stamp = d.meta.stamp; S.syncing = d.meta.syncing; S.cloud = d.meta.cloud;
    paintHead(d.meta);
    const noTag = !d.meta.clan_tag;
    $('clanSetup').classList.toggle('d-none', !noTag); $('clanBody').classList.toggle('d-none', noTag);
    if (noTag) return;
    S.data = d; paint();
  }).catch(e => { if (seq === S.seq) { $('clanError').classList.remove('d-none'); $('clanError').textContent = e.message; } });
}
function poll() {
  api('api/status').then(m => {
    paintHead(m); S.cloud = m.cloud;
    if (m.stamp !== S.stamp) load(); else S.syncing = m.syncing;
  }).catch(() => {}).finally(() => setTimeout(poll, S.cloud ? 600000 : 15000));   // en la nube cada consulta gasta cuota
}
window.Clan = {
  show() {
    const [sub, tag] = location.hash.slice(1).split('/');
    S.sub = ['resumen', 'miembros', 'guerras', 'ligas', 'jugador', 'persona', 'admin'].includes(sub) ? sub : 'resumen';
    S.tag = sub === 'jugador' && tag ? '#' + decodeURIComponent(tag) : sub === 'persona' && tag ? decodeURIComponent(tag) : null;
    S.openWar = S.openRow = null; S.data = null; clearCharts(); $('clanView').innerHTML = skeleton(); S.enter = true;
    if (['jugador', 'persona'].includes(S.sub) && !S.tag) S.sub = 'miembros';
    window.scrollTo(0, 0); load();
  },
  repaint() { paint(); }     // cambio de tema: las gráficas toman los colores nuevos
};
$('clanKind').addEventListener('click', e => {
  const a = e.target.closest('[data-k]'); if (!a) return; e.preventDefault(); S.kind = a.dataset.k;
  $('clanKind').querySelectorAll('.nav-link').forEach(x => x.classList.toggle('active', x === a)); load();
});
$('clanDays').onchange = e => { S.days = +e.target.value; load(); };
$('clanBy').addEventListener('click', e => {
  const b = e.target.closest('[data-by]'); if (!b) return;
  S.by = b.dataset.by; localStorage.setItem('verPor', S.by); S.openRow = null; paint();
});
$('clanView').addEventListener('toggle', e => {          // 'toggle' no burbujea: se escucha en captura
  const id = e.target.dataset && e.target.dataset.sec; if (!id) return;
  S.secs[id] = e.target.open; if (e.target.open) drawers[id]?.();
}, true);
$('clanView').addEventListener('click', e => {
  if (e.target.closest('a, button, input, summary, .own-chip')) return;
  const card_ = e.target.closest('[data-war]');
  if (card_) { const w = +card_.dataset.war; S.openWar = S.openWar === w ? null : w; paint(); return; }
  const tr = e.target.closest('tr.player'); if (!tr) return;
  if (tr.dataset.row) { S.openRow = S.openRow === tr.dataset.row ? null : tr.dataset.row; paint(); }
});
$('clanView').addEventListener('keydown', e => {
  if ((e.key === 'Enter' || e.key === ' ') && e.target.matches('[data-war]')) { e.preventDefault(); const w = e.target.dataset.war; e.target.click(); document.querySelector(`[data-war="${w}"]`)?.focus(); }
});
$('clanRefresh').onclick = () => { $('clanRefresh').disabled = true; $('clanSync').innerHTML = '<i class="ti ti-refresh spin me-1"></i>Recogiendo datos…';
  api('api/sync', {}).then(j => { toast(j.started ? 'Recogiendo datos…' : 'Ya hay una recogida en marcha', j.started ? 'info' : 'secondary'); S.syncing = true; if (S.cloud) load(); }).catch(e => { toast(esc(e.message), 'danger'); load(); }); };
window.addEventListener('hashchange', () => Clan.show());
Clan.show();
$('clanForm').onsubmit = e => { e.preventDefault();
  api('api/tag', {clan_tag: $('clanTagInput').value}).then(() => { toast('<i class="ti ti-check me-1"></i>Clan guardado; recogiendo datos…'); load(); }).catch(err => toast(esc(err.message), 'danger')); };
poll();
})();
