// Pestaña Escenarios: primero la respuesta (dónde podemos acabar) y, al desplegar, el porqué de cada cifra.
// Todos los números vienen de liga.py; aquí sólo se ordenan. El simulador es lo único que se calcula en el navegador.
// rendimiento.js guarda sus utilidades en su propio ámbito y las presta al arrancar.
let S, dec, plural, empty, sec, hash, paint, watchProgress;
function esBind(c) { ({S, dec, plural, empty, sec, hash, paint, watchProgress} = c); }
// La pestaña enseña lo que toca según en qué esté el clan ahora mismo.
const ES_PAGE = {
  liga: ['Predicciones de liga', 'Dónde podemos acabar esta liga, qué hace falta para cada puesto y cómo va cambiando día a día. Se actualiza sola con cada recogida.'],
  guerra: ['Predicciones de guerra', 'Cómo se espera que acabe la guerra en curso, quién debería atacar a quién y cómo va frente a lo previsto. Se actualiza sola mientras se juega.'],
  nada: ['Predicciones', 'El clan no está ahora en liga ni en guerra. Aquí queda lo último que se previó y cómo salió.'],
};
const ES_ST = {
  asegurado: {i: 'ti-circle-check', t: 'Asegurado'},
  posible: {i: 'ti-help-circle', t: 'Posible'},
  descartado: {i: 'ti-circle-x', t: 'Descartado'},
};
const esPct = p => p == null ? '–' : p <= 0 ? '0 %' : p >= 1 ? '100 %' : p < .01 ? 'menos del 1 %' : p > .99 ? 'más del 99 %' : Math.round(p * 100) + ' %';
const esBadge = (st, extra = '') => `<span class="es-st es-${st}"><i class="ti ${ES_ST[st].i}"></i>${ES_ST[st].t}${extra}</span>`;
const esBasis = r => r.basis === 'matematica' ? 'matemático' : r.basis === 'practica' ? 'en la práctica' : '';
const esB = t => `<bdi>${esc(t)}</bdi>`;
const esStars = n => `${num(n)}★`;
const esRound = r => r ? `Ronda ${r}` : 'Por confirmar';
const esTitle = p => p.title ?? esRound(p.round);
const esDiff = d => ({facil: '<span class="badge bg-green-lt">Fácil</span>', media: '<span class="badge bg-yellow-lt">Media</span>', dificil: '<span class="badge bg-red-lt">Difícil</span>'})[d];
const esWhen = ts => ts ? new Date(ts * 1000).toLocaleString('es-ES', {day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'}) : '–';
const esMe = v => v.table.find(x => x.us);
const esName = (v, tag) => v.table.find(x => x.tag === tag)?.name || tag;
const esLeft = (v, need) => need - v.needs.wars.reduce((a, w) => a + w.cur, 0);

function esReach(r, v) {
  const n = esLeft(v, r.need);
  return {
    ya: `Con lo que se espera de nosotros ya llega, si ${esB(r.rival)} acaba en su previsión.`,
    esperado: `Lo previsto da para ello: nos faltan ${esStars(Math.max(n, 0))}.`,
    techo: `Hace falta rendir por encima de lo previsto, pero está al alcance si cada cuenta ataca su mejor base: faltan ${esStars(n)}.`,
    maximo: `Haría falta casi todo triple: faltan ${esStars(n)}, por encima de nuestro techo realista.`,
    imposible: `Ni con nuestro máximo llegaríamos a la previsión de ${esB(r.rival)}: depende de que falle.`,
  }[r.reach];
}
function esLine(r, v) {
  const m = v.needs, top = m.base + m.max;
  if (r.status === 'descartado' && r.basis === 'practica' && r.rival) return `Matemáticamente cabe, pero no ha salido en ninguna simulación: se espera a ${esB(r.rival)} en ${num(Math.round(r.rival_mean))} y nuestro máximo es ${num(top)}.`;
  if (r.status === 'asegurado') return r.basis === 'matematica' ? 'Pase lo que pase, ya está conseguido.' : 'Aún no es matemático, pero no ha fallado en ninguna simulación.';
  if (r.status === 'descartado') return r.basis === 'matematica' ? `No se puede: ni con nuestro máximo (${num(top)} estrellas) daría.` : `Matemáticamente cabe, pero no ha salido en ninguna simulación${r.rival ? `: ${esB(r.rival)} va demasiado lejos` : ''}.`;
  return r.rival ? `Hay que acabar por delante de ${esB(r.rival)}. ${esReach(r, v)}` : 'Depende de cómo acaben las guerras que quedan.';
}
function esPosDetail(r, v) {
  const m = v.needs, more = [], left = esLeft(v, r.need ?? 0);
  if (r.status === 'posible' && r.need != null && m.wars.length) {
    more.push(`<div class="es-tiles">
      <div><small>Nos faltan</small><b>${esStars(Math.max(left, 0))}</b><small>en ${plural(m.wars.length, 'guerra', 'guerras')}, ganándolas</small></div>
      <div><small>Previsión</small><b>${esStars(Math.round(Math.max(m.expected - m.wars.reduce((a, w) => a + w.cur, 0), 0)))}</b><small>con nuestros hábitos</small></div>
      <div><small>Techo realista</small><b>${esStars(m.real - m.wars.reduce((a, w) => a + w.cur, 0))}</b><small>cada cuenta a su mejor base</small></div>
      <div><small>Máximo</small><b>${esStars(m.max - m.wars.reduce((a, w) => a + w.cur, 0))}</b><small>todo triple</small></div></div>`);
    if (r.plan?.length && r.need > 0) more.push(`<div class="es-h">Reparto por guerra</div><table class="xd-t"><thead><tr><th></th><th>Objetivo</th><th>Techo</th><th>Máximo</th></tr></thead><tbody>
      ${r.plan.map(p => `<tr><td>${esc(esName(v, p.rival))}<small>${esRound(p.round)}${p.state === 'inWar' ? ` · lleva ${esStars(p.cur)}` : ''}</small></td><td><b>${esStars(p.target)}</b></td><td>${esStars(p.ceil)}</td><td>${esStars(p.max)}</td></tr>`).join('')}</tbody></table>`);
    if (r.allow) more.push(`<div class="es-h">Lo que puede permitirse ${esB(r.rival)}</div><div class="small text-secondary mb-1">Previsión: acaba con ${num(Math.round(r.rival_mean))} (entre ${num(r.rival_lo)} y ${num(r.rival_hi)}). Contando ${plural(r.wins_rival, 'victoria', 'victorias')} suya${r.wins_rival === 1 ? '' : 's'} en lo que queda.</div>
      <table class="xd-t"><thead><tr><th>Si hacemos</th><th>Acabamos</th><th>Puede sacar</th></tr></thead><tbody>
      ${r.allow.map(a => `<tr><td>${esc(a.label)}<small>${esStars(a.stars)}</small></td><td>${num(a.final)}</td><td><b>${a.rival_max < 0 ? 'Nada' : `hasta ${esStars(a.rival_max)}`}</b>${a.rival_per_war != null && a.rival_max >= 0 ? `<small>${dec(a.rival_per_war, 1)} por guerra</small>` : ''}</td></tr>`).join('')}</tbody></table>`);
  }
  if (r.magic != null && r.status !== 'descartado') more.push(`<div class="es-note"><i class="ti ti-lock"></i>Para tenerlo matemáticamente seguro: ${esStars(Math.max(esLeft(v, r.magic), 0))} más y ganar las guerras que quedan, hagan lo que hagan los demás.</div>`);
  return more.join('');
}
function esPositions(v) {
  const rows = v.needs.rows, end = rows.findIndex(r => r.status === 'asegurado');
  const show = rows.slice(0, end + 1), first = show.find(r => r.status === 'posible');
  const zone = r => r.pos === v.zones.promote ? '<span class="es-zone up">Ascenso</span>' : r.pos === v.clans - v.zones.demote ? '<span class="es-zone stay">Sin descender</span>' : '';
  return `<div class="es-list">${show.map(r => {
    const body = esPosDetail(r, v), label = r.pos === v.clans ? `${r.pos}º` : r.pos === 1 ? '1º' : `${r.pos}º o mejor`, sub = esBasis(r);
    return `<details class="es-pos es-b-${r.status}" ${r === first ? 'open' : ''}><summary>
      <span class="es-pos-n">${label}${zone(r)}</span>${esBadge(r.status, sub ? ` <small>· ${sub}</small>` : r.status === 'posible' ? ` <small>· ${esPct(r.prob)}</small>` : '')}
      ${body ? '<i class="ti ti-chevron-down es-chev"></i>' : ''}<span class="es-line">${esLine(r, v)}</span></summary>${body ? `<div class="es-body">${body}</div>` : ''}</details>`;
  }).join('')}</div>${end < rows.length - 1 ? `<div class="small text-secondary mt-2">Cualquier puesto por debajo del ${rows[end].pos}º también está cubierto.</div>` : ''}`;
}
function esHero(v) {
  const me = esMe(v), n = v.clans, rows = v.needs.rows, likely = v.ranks.indexOf(Math.max(...v.ranks)) + 1;
  const up = v.zones.promote ? rows[v.zones.promote - 1] : null, safe = v.zones.demote ? rows[n - v.zones.demote - 1] : null;
  const phase = v.state === 'ended' ? `La liga ha terminado: quedamos <b>${me.rank}º</b> con <b>${num(me.stars)} estrellas</b>.`
    : v.rounds_done ? `Vamos <b>${me.rank}º</b> con <b>${num(me.stars)} estrellas</b> tras ${v.rounds_done} de ${v.rounds_total} rondas. Lo más probable es acabar <b>${likely}º</b> (${esPct(v.ranks[likely - 1])}).`
      : `La liga acaba de empezar. De entrada, lo más probable es acabar <b>${likely}º</b> (${esPct(v.ranks[likely - 1])}).`;
  const chip = (t, r) => r ? `<div class="es-chip es-b-${r.status}"><small>${t}</small>${esBadge(r.status, r.status === 'posible' ? ` <small>· ${esPct(r.prob)}</small>` : '')}</div>` : '';
  const rng = v.bounds[0] === v.bounds[1] ? `${v.bounds[0]}º` : `del ${me.from}º al ${me.to}º`;
  return `<div class="card hero mb-3"><div class="card-body">
    <div class="subheader">${esc(v.league || 'Liga')} · ${v.state === 'ended' ? 'Terminada' : `Ronda ${Math.min(v.rounds_done + 1, v.rounds_total)} de ${v.rounds_total}`}</div>
    <div class="hero-line mt-1">${phase}</div>
    <div class="es-chips">${chip('Ascender', up)}${chip('Evitar el descenso', safe)}${v.state !== 'ended' ? `<div class="es-chip"><small>Puesto final posible</small><b>${rng}</b></div>` : ''}</div>
    ${v.state !== 'ended' && up && up.status === 'posible' ? `<div class="small text-secondary mt-2">Si atacan todos los que pueden, ascender sube al ${esPct(v.ranks_all.slice(0, v.zones.promote).reduce((a, b) => a + b, 0))}; si además siguen el plan de ataque, al ${esPct(v.ranks_plan.slice(0, v.zones.promote).reduce((a, b) => a + b, 0))}${v.ranks_alt ? `; y con la alternativa donde sale más rentable, al ${esPct(v.ranks_alt.slice(0, v.zones.promote).reduce((a, b) => a + b, 0))}` : ''}.</div>` : ''}
    ${v.inactive.length ? `<div class="small text-secondary mt-2"><i class="ti ti-user-off me-1"></i>Se cuenta que no atacan: ${v.inactive.map(esc).join(', ')}. Se cambia en Admin.</div>` : ''}
    <div class="small text-secondary mt-1"><i class="ti ti-clock me-1"></i>Datos de la recogida del ${esWhen(v.ts)}.</div></div></div>`;
}
function esTable(v) {
  return `<div class="card-body pt-2"><div class="table-responsive"><table class="xd-t es-table"><thead><tr><th>#</th><th>Clan</th><th>★</th><th>Previsión</th><th>Puede acabar</th><th class="d-none d-sm-table-cell">V-E-D</th><th class="d-none d-sm-table-cell">Destrucción</th></tr></thead><tbody>
    ${v.table.map(x => `<tr class="${x.us ? 'es-us' : ''} es-z-${x.zone}"><td>${x.rank}</td><td class="es-clan">${esc(x.name)}</td><td><b>${num(x.stars)}</b></td><td>${num(Math.round(x.mean))}<small>${num(x.lo)}-${num(x.hi)}</small></td><td>${x.from === x.to ? `${x.from}º` : `${x.from}º-${x.to}º`}</td><td class="d-none d-sm-table-cell">${x.won}-${x.tied}-${x.lost}</td><td class="d-none d-sm-table-cell">${dec(x.pct, 1)} %</td></tr>`).join('')}</tbody></table></div>
    <div class="small text-secondary mt-2">Cuentan las guerras terminadas, con 10 estrellas extra por victoria. Las zonas de color marcan ${plural(v.zones.promote, 'plaza', 'plazas')} de ascenso y ${plural(v.zones.demote, 'plaza', 'plazas')} de descenso${v.zones.default ? ' (valor habitual: se ajusta en Admin)' : ''}.</div></div>`;
}
function esGames(v) {
  const direct = v.needs.rows.find(r => r.status === 'posible')?.rival_tag, card = g => `<div class="es-game">
      <div class="es-game-h">${esRound(g.round)}${g.deduced ? ' · cruce deducido' : ''}${g.state === 'inWar' ? ' · <span class="text-green">en juego</span>' : g.state === 'preparation' ? ' · preparación' : ''}<span class="ms-auto">Gana ${esc(g.win_a >= g.win_b ? g.a_name : g.b_name)}: ${esPct(Math.max(g.win_a, g.win_b))}</span></div>
      ${[['a', g.a_name, g.ax, g.alo, g.ahi, g.a_cur, g.a_diff], ['b', g.b_name, g.bx, g.blo, g.bhi, g.b_cur, g.b_diff]].map(([k, name, x, lo, hi, cur, diff]) => `<div class="es-game-r"><span class="text-truncate ${g[k] === v.us ? 'fw-bold' : ''}">${esc(name)}</span>${cur ? `<small>lleva ${esStars(cur.stars)}</small>` : ''}${esDiff(diff)}<b>${dec(x, 0)}★</b><small>${num(lo)}-${num(hi)}</small></div>`).join('')}</div>`;
  const mine = v.games.filter(g => g.mine), rival = v.games.filter(g => direct && !g.mine && [g.a, g.b].includes(direct)), rest = v.games.filter(g => !g.mine && !rival.includes(g));
  if (!v.games.length) return `<div class="card-body">${empty('No quedan guerras por jugar')}</div>`;
  return `<div class="card-body"><div class="small text-secondary mb-2">La etiqueta dice cómo de difícil lo tiene cada clan contra su rival; la cifra, las estrellas que se le esperan y su margen habitual.</div>
    <div class="es-h">Las nuestras</div><div class="es-games">${mine.map(card).join('')}</div>
    ${rival.length ? `<div class="es-h">Las de ${esB(esName(v, direct))}, nuestro rival directo</div><div class="es-games">${rival.map(card).join('')}</div>` : ''}
    ${rest.length ? `<details class="mt-3"><summary class="es-more">Ver las otras ${num(rest.length)} guerras</summary><div class="es-games mt-2">${rest.map(card).join('')}</div></details>` : ''}</div>`;
}
// ---------- plan de ataque
const ES_TIER = {seguro: 'Casi seguro', razonable: 'Razonable', dudoso: 'Dudoso'};
function esShape(p) {
  const n = p.assign.length, bottom = p.reserves.filter(r => !p.assign.some(a => a.a_pos > r.pos)).length;
  if (!n) return 'No queda nadie con un pleno razonable.';
  const low = p.assign.reduce((a, b) => (b.a_pos > a.a_pos ? b : a)), head = {espejo: 'Lo mejor es puro espejo.', bajada: 'Lo mejor es que todos bajen los mismos puestos.', mixto: 'Reparto a medida: cada cuenta a la aldea donde más plenos suma.'}[p.shape];
  return `${head} ${bottom ? `Empezando por abajo, el primero con pleno razonable es el nº ${low.a_pos}: por debajo de él ${plural(bottom, 'cuenta queda', 'cuentas quedan')} de reserva.` : ''}`;
}
function esPlanRow(a) {
  return `<div class="es-atk es-k-${a.tier}"><div class="es-atk-m"><span class="es-atk-t"><b>${a.a_pos}.</b> ${esB(a.a)}<small>TH${a.a_th}</small></span><i class="ti ti-arrow-right text-secondary"></i><span class="es-atk-t"><b>${a.b_pos}.</b> ${esB(a.b)}<small>TH${a.b_th}${a.best ? ` · ya ${a.best}★` : ''}</small></span><span class="es-atk-p"><b>${Math.round(a.p3 * 100)} %</b><small>${ES_TIER[a.tier]}</small></span></div>
    <div class="es-atk-w">${a.why.a_n ? `Sus últimos ${a.why.a_n}: ${a.why.a_3} plenos` : 'Sin historial'} · ${a.why.d_n ? `a esta aldea, ${a.why.d_3} plenos en ${a.why.d_n}` : 'aldea sin historial'}</div></div>`;
}
function esMatrix(p, alt) {
  const m = p.matrix, rows = alt ? p.alt.assign : p.assign, on = new Set(rows.map(a => `${a.a_pos}|${a.b_pos}`));
  const cell = (x, a, b) => { const high = b.pos < a.pos, used = on.has(`${a.pos}|${b.pos}`), up = high && !(alt && used), c = `background:rgba(45,160,90,${(x / 100 * .75).toFixed(2)})`;
    return `<td class="${used ? 'es-on' : ''} ${up ? 'es-up' : ''} ${b.best >= 3 ? 'es-done' : ''}" style="${up || b.best >= 3 ? '' : c}" title="${esc(a.name)} a ${esc(b.name)}: ${x} %">${b.best >= 3 ? '★' : x}</td>`; };
  return `<div class="table-responsive es-mx-w"><table class="es-mx"><thead><tr><th>Ataca</th>${m.b.map(b => `<th title="${esc(b.name)}">${b.pos}<small>TH${b.th}</small></th>`).join('')}</tr></thead><tbody>
    ${m.a.map((a, i) => `<tr><th title="${esc(a.name)}">${a.pos}. <bdi>${esc(a.name)}</bdi></th>${m.p3[i].map((x, j) => cell(x, a, m.b[j])).join('')}</tr>`).join('')}</tbody></table></div>
    <div class="small text-secondary mt-1">% de pleno de cada cuenta contra cada aldea. Más verde, más probable. Recuadro: lo que propone ${alt ? 'la alternativa' : 'el plan'}. Gris: por encima de su puesto${alt ? ', salvo las subidas elegidas' : ''}.</div>`;
}
// ---------- alternativa: qué se gana dejando subir a quien lo necesita
const esPlanKey = p => String(p.round ?? p.rival);
const esPick = p => !!(p.alt && S.planAlt?.[esPlanKey(p)]);
const esSigned = (n, d = 1) => `${n > 0 ? '+' : n < 0 ? '−' : ''}${dec(Math.abs(n), d)}`;
const ES_VERDICT = {
  mejor: ['es-b-asegurado', 'ti-trending-up', 'Sale más rentable'],
  mezcla: ['es-b-posible', 'ti-arrows-exchange', 'Depende de lo que busques'],
  igual: ['', 'ti-equal', 'Sale prácticamente igual'],
};
function esAltText(a) {
  const riskier = a.lo < a.base.lo ? ` A cambio, el peor día habitual baja de ${num(a.base.lo)} a ${num(a.lo)}★.` : '';
  if (a.verdict === 'mejor') return `Se esperan ${dec(a.triples, 1)} plenos y ${dec(a.stars, 0)}★ frente a ${dec(a.base.triples, 1)} y ${dec(a.base.stars, 0)}★ del plan principal.${riskier}`;
  if (a.verdict === 'mezcla') return `${a.gain_t > 0 ? 'Da más plenos pero menos estrellas' : 'Da más estrellas pero menos plenos'}: ${dec(a.triples, 1)} plenos y ${dec(a.stars, 0)}★ frente a ${dec(a.base.triples, 1)} y ${dec(a.base.stars, 0)}★. Si la guerra se decide por estrellas, mira esa cifra.${riskier}`;
  return `La diferencia (${dec(a.triples, 1)} frente a ${dec(a.base.triples, 1)} plenos) no se distingue del azar: mejor el plan principal, sin subir a nadie.`;
}
function esAltBox(p) {
  const a = p.alt, [cls, icon, title] = ES_VERDICT[a.verdict], key = esPlanKey(p), on = esPick(p);
  const move = r => { const change = r.was == null ? `entra al ${r.now}` : r.now == null ? `deja el ${r.was} y queda de reserva` : `al ${r.now} en vez del ${r.was}`, d = (r.p_now ?? 0) - (r.p_was ?? 0);
    return `<div class="es-sw-r"><span><b>${r.pos}.</b> ${esB(r.name)} ${change}${r.up ? ' <i class="ti ti-arrow-up text-secondary" title="Ataca por encima de su puesto"></i>' : ''}</span><small>${r.p_was == null ? '–' : Math.round(r.p_was * 100) + ' %'} → ${r.p_now == null ? '–' : Math.round(r.p_now * 100) + ' %'}</small><b class="${d >= 0 ? 'text-green' : 'text-red'}">${esSigned(Math.round(d * 100), 0)}</b></div>`; };
  return `<div class="es-alt ${cls}"><div class="es-alt-h"><i class="ti ${icon}"></i><b>Alternativa: ${title}</b><small>${esSigned(a.gain_t, 1)} plenos · ${esSigned(a.gain_s, 1)}★ · ${plural(a.ups, 'subida', 'subidas')}</small></div>
    <div class="small">${esAltText(a)}</div>
    <details class="mt-1"><summary class="es-more">Ver qué cambia</summary><div class="mt-1">${a.swaps.map(s => `<div class="es-sw">${s.rows.map(move).join('')}<div class="es-sw-t">Saldo: ${esSigned(Math.round(s.net * 100), 0)} puntos de pleno</div></div>`).join('')}
      <div class="small text-secondary">Cada subida tiene que ganar más de ${dec(a.margin * 100, 1)} puntos: es el error medio del modelo, y por debajo la diferencia podría no existir.</div></div></details>
    <div class="btn-group mt-2" role="group" aria-label="Plan elegido"><button type="button" class="btn btn-sm ${on ? 'btn-ghost-secondary' : 'btn-primary'}" data-plan-pick="${esc(key)}" data-alt="0">Plan principal</button><button type="button" class="btn btn-sm ${on ? 'btn-primary' : 'btn-ghost-secondary'}" data-plan-pick="${esc(key)}" data-alt="1">Alternativa</button></div></div>`;
}
function esPlans(v) {
  if (!v.plans?.length) return `<div class="card-body">${empty('No quedan guerras por jugar')}</div>`;
  const st = {inWar: ['bg-green-lt', 'En juego'], preparation: ['bg-blue-lt', 'En preparación'], pending: ['bg-secondary-lt', 'Aún no empieza']};
  const open = S.planOpen ?? esPlanKey(v.plans[0]);
  return `<div class="card-body">${v.plans.map(p => { const alt = esPick(p), x = alt ? p.alt : p, more = +(x.triples - p.mirror.triples).toFixed(1), extra = +(x.stars_free - x.stars).toFixed(1);
    return `<details class="es-plan" ${esPlanKey(p) === open ? 'open' : ''}><summary><span class="es-day-h"><b>${esTitle(p)} · ${esB(p.rival_name)}</b><small><span class="badge ${st[p.state][0]}">${st[p.state][1]}</span>${p.deduced ? ' · cruce deducido' : ''}${p.known ? '' : ' · con su última alineación'} · ${dec(x.triples, 1)} plenos previstos${alt ? ' · alternativa' : ''}</small></span><i class="ti ti-chevron-down es-chev"></i></summary>
    <div class="es-body"><div class="small mb-2">${esShape({...p, ...x})}</div>
    ${p.alt ? esAltBox(p) : ''}
    ${x.assign.length ? `<div class="es-tiles"><div><small>Plenos previstos</small><b>${dec(x.triples, 1)}</b><small>${p.done ? `contando ${p.done} ya hechos` : `de ${p.matrix.b.length} aldeas`}</small></div><div><small>Frente al espejo</small><b>${more > 0 ? '+' : ''}${dec(more, 1)}</b><small>el espejo da ${dec(p.mirror.triples, 1)}</small></div><div><small>Estrellas</small><b>${dec(x.stars, 0)}★</b><small>entre ${num(x.lo)} y ${num(x.hi)}</small></div><div><small>Nota de corte</small><b>${Math.round(p.tau * 100)} %</b><small>la elige el cálculo</small></div></div>
    <div class="es-h">Ataques</div><div class="es-atks">${x.assign.map(esPlanRow).join('')}</div>` : ''}
    ${x.reserves.length ? `<div class="es-h">Reservas: atacan después y rematan</div>${x.reserves.map(r => `<div class="es-res"><span><b>${r.pos}.</b> ${esB(r.name)} <small>TH${r.th}${r.n > 1 ? ` · ${r.n} ataques` : ''}</small></span><small>${r.covers.length ? r.covers.map(c => `aldea ${c.pos}: ${Math.round(c.p3 * 100)} %`).join(' · ') : 'sin aldea a su alcance para rematar'}</small></div>`).join('')}` : ''}
    ${x.uncovered.length ? `<div class="small text-secondary mt-2"><b>Sin pleno razonable:</b> ${x.uncovered.map(u => `aldea ${u.pos} (TH${u.th}${u.best ? `, ya ${u.best}★` : ''})`).join(', ')}.</div>` : ''}
    ${extra >= 1 ? `<div class="es-note"><i class="ti ti-star"></i>Las reservas no tienen nada que perder: si van a por estrellas a las aldeas libres, aunque sea sin pleno, se suman unas ${dec(extra, 0)}★ y se llega a ${dec(x.stars_free, 0)}★.</div>` : ''}
    <details class="mt-3"><summary class="es-more">Ver el % de todos contra todos</summary><div class="mt-2">${esMatrix(p, alt)}</div></details></div></details>`; }).join('')}</div>`;
}
function esPlanWire() {
  $('clanView').querySelectorAll('[data-plan-pick]').forEach(b => { b.onclick = () => { const k = b.dataset.planPick; (S.planAlt ??= {})[k] = b.dataset.alt === '1'; S.planOpen = k; paint(); }; });
}
// ---------- mensajes para el chat del clan
const ES_CHAT_SIZE = 5;
function esChatBlocks(p) {
  const rows = (esPick(p) ? p.alt : p).assign.slice().sort((a, b) => b.a_pos - a.a_pos), out = [];      // del jugador más bajo al más alto
  for (let i = 0; i < rows.length; i += ES_CHAT_SIZE) out.push(rows.slice(i, i + ES_CHAT_SIZE));
  return out;
}
const esChatText = (rows, lines) => rows.map(a => `@${a.a} -> al ${a.b_pos}`).join(lines ? '\n' : ' | ');
function esChat(v) {
  const plans = (v.plans || []).filter(p => (esPick(p) ? p.alt : p).assign.length);
  if (!plans.length) return `<div class="card-body">${empty('No hay ataques que avisar')}</div>`;
  const lines = localStorage.getItem('chatLineas') === '1';
  S.chat = {};
  const block = (p, rows, i) => { const key = `${p.round ?? p.rival}|${esPick(p) ? 'alt' : 'main'}|${i}`, text = esChatText(rows, lines), done = S.chatDone?.has(`${v.ts}|${key}`);
    S.chat[key] = rows;
    return `<div class="es-copy ${done ? 'es-copied' : ''}"><div class="es-copy-h"><b>Bloque ${i + 1}</b><small>del ${rows[0].a_pos} al ${rows[rows.length - 1].a_pos} · ${num([...text].length)} caracteres</small>
      <button class="btn btn-sm ${done ? 'btn-ghost-success' : 'btn-primary'} ms-auto" type="button" data-chat="${esc(key)}"><i class="ti ${done ? 'ti-check' : 'ti-copy'} me-1"></i>${done ? 'Copiado' : 'Copiar'}</button></div><pre class="es-pre" dir="ltr">${esc(text)}</pre></div>`; };
  return `<div class="card-body">
    <div class="d-flex flex-wrap align-items-center gap-2 mb-2"><span class="small text-secondary">${lines ? 'Una línea por jugador.' : 'Todo en una línea, separado por barras.'}</span><button class="btn btn-sm btn-ghost-secondary ms-auto" type="button" data-chat-mode>${lines ? 'Pasar a una sola línea' : 'Poner un jugador por línea'}</button></div>
    ${plans.map((p, i) => `<details class="es-plan" ${i === 0 ? 'open' : ''}><summary><span class="es-day-h"><b>${esTitle(p)} · ${esB(p.rival_name)}</b><small>${plural((esPick(p) ? p.alt : p).assign.length, 'aviso', 'avisos')}${esPick(p) ? ' · alternativa' : ''}${p.known ? '' : ' · alineación estimada'}</small></span><i class="ti ti-chevron-down es-chev"></i></summary>
      <div class="es-body">${p.known ? '' : '<div class="es-note mb-2 mt-0"><i class="ti ti-alert-triangle"></i>Esta ronda aún no está publicada: los números pueden cambiar. Mejor enviarlos cuando empiece la preparación.</div>'}${esChatBlocks(p).map((rows, b) => block(p, rows, b)).join('')}</div></details>`).join('')}</div>`;
}
async function esCopy(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {                                  // algunos navegadores de móvil no dejan: se copia a la antigua
    const t = document.createElement('textarea');
    t.value = text; t.style.position = 'fixed'; t.style.opacity = '0';
    document.body.appendChild(t); t.focus(); t.select();
    let ok = false;
    try { ok = document.execCommand('copy'); } catch { ok = false; }
    t.remove();
    return ok;
  }
}
function esChatWire(v) {
  $('clanView').querySelectorAll('[data-chat]').forEach(b => { b.onclick = async () => {
    const key = b.dataset.chat, text = esChatText(S.chat[key], localStorage.getItem('chatLineas') === '1');
    if (!await esCopy(text)) return toast('No se ha podido copiar: selecciona el texto a mano', 'danger');
    (S.chatDone ??= new Set()).add(`${v.ts}|${key}`);
    b.className = 'btn btn-sm btn-ghost-success ms-auto'; b.innerHTML = '<i class="ti ti-check me-1"></i>Copiado'; b.closest('.es-copy').classList.add('es-copied');
    toast('<i class="ti ti-check me-1"></i>Copiado: pégalo en el chat del clan'); }; });
  document.querySelector('[data-chat-mode]')?.addEventListener('click', () => { localStorage.setItem('chatLineas', localStorage.getItem('chatLineas') === '1' ? '0' : '1'); paint(); });
}
function esBench(d, v) {
  const b = v.bench, tag = {inWar: ['bg-secondary-lt', 'Bloqueada: ya está en juego'], preparation: ['bg-green-lt', 'Se puede cambiar en preparación'], pending: ['bg-blue-lt', 'Aún no empieza']};
  const round = r => `<div class="es-game">
    <div class="es-game-h"><b>${esRound(r.round)} · ${esB(r.rival_name)}</b>${r.deduced ? ' · deducido' : ''}<span class="ms-auto badge ${tag[r.state][0]}">${tag[r.state][1]}</span></div>
    ${r.swaps.length ? r.swaps.map(s => `<div class="es-swap"><div><span class="text-red"><i class="ti ti-arrow-down"></i>${esc(s.out)}</span> <small>TH${s.out_th}</small><i class="ti ti-arrow-right mx-1 text-secondary"></i><span class="text-green"><i class="ti ti-arrow-up"></i>${esc(s.in)}</span> <small>TH${s.in_th}</small><b class="ms-auto">+${dec(s.gain, 1)}★</b></div><small>${esc(s.why)}</small></div>`).join('')
    : `<div class="small text-secondary">${r.locked ? 'No se puede tocar: la alineación quedó fijada.' : b.spare ? 'La alineación actual es la mejor que tenemos contra este rival.' : 'Sin cambios posibles.'}</div>`}
    ${r.benched?.length ? `<div class="small text-secondary mt-1">En el banquillo: ${r.benched.map(esc).join(', ')}.</div>` : ''}
    </div>`;
  const miss = b.roster.filter(m => m.wars && m.used < m.wars), spare = d.spare || [];
  return `<div class="card-body">
    ${b.spare ? `<div class="mb-2"><b>${plural(b.spare, 'cuenta', 'cuentas')} en el banquillo.</b> <span class="text-secondary">Cada cambio dice cuántas estrellas se ganarían.</span></div>` : `<div class="es-note mb-3"><i class="ti ti-info-circle"></i>Inscritas ${b.roster.length} cuentas para ${b.size} plazas: no hay banquillo, así que esta liga no admite cambios. Lo que sí se puede mejorar es a qué base ataca cada uno.</div>`}
    <div class="es-games">${b.rounds.map(round).join('') || empty('No quedan guerras por jugar')}</div>
    ${miss.length ? `<div class="es-h">Quién falla ataques</div><table class="xd-t"><thead><tr><th>Cuenta</th><th>Ataques</th><th>Previsión de que ataque</th></tr></thead><tbody>${miss.sort((a, c) => a.used / a.wars - c.used / c.wars).map(m => `<tr><td>${esc(m.name)}<small>TH${m.th}</small></td><td>${m.used} de ${m.wars}</td><td>${m.inactive ? 'No atacará' : Math.round(m.p * 100) + ' %'}</td></tr>`).join('')}</tbody></table>` : ''}
    ${!b.spare && spare.length ? `<details class="mt-3"><summary class="es-more">Para la próxima liga: ${plural(spare.length, 'cuenta', 'cuentas')} del clan sin inscribir</summary><table class="xd-t mt-1"><thead><tr><th>Cuenta</th><th>TH</th><th>Índice</th></tr></thead><tbody>${spare.map(s => `<tr><td><a href="${hash(s.tag)}">${esc(s.name)}</a></td><td>${s.th ?? '–'}</td><td>${s.index ?? '–'}</td></tr>`).join('')}</tbody></table></details>` : ''}</div>`;
}
function esLog(v) {
  const icon = {fav: 'ti-arrow-up-right', bad: 'ti-arrow-down-right', neutral: 'ti-minus'};
  const item = i => `<div class="es-item es-t-${i.tone}"><i class="ti ${icon[i.tone]}"></i><span>${esc(i.text)}</span></div>`;
  const days = v.log.days, live = v.log.live;
  if (!days.length && !live.length) return `<div class="card-body">${empty('Aún no ha terminado ninguna ronda')}</div>`;
  const label = {fav: 'Buen día', bad: 'Mal día', neutral: 'Día neutro'};
  return `<div class="card-body">
    ${live.length ? `<div class="es-h">Hoy, en juego</div>${live.map(item).join('')}` : ''}
    ${days.map((d, i) => `<details class="es-day es-t-${d.tone}" ${i === 0 ? 'open' : ''}><summary><span class="es-day-h"><b>${esc(d.headline)}</b><small>${d.date ? `${esc(d.date)} · ` : ''}${label[d.tone]} · ${d.gained >= 0 ? '+' : ''}${num(d.gained)} estrellas</small></span><i class="ti ti-chevron-down es-chev"></i></summary><div class="es-body">${d.items.map(item).join('')}</div></details>`).join('')}</div>`;
}
function esLevels(v) {
  const rows = v.table.slice().sort((a, b) => b.level - a.level || (b.stars_attack || 0) - (a.stars_attack || 0));
  return `<div class="card-body pt-2"><div class="table-responsive"><table class="xd-t"><thead><tr><th>Clan</th><th>Nivel</th><th>★/ataque</th><th>Triples</th><th>Ataques</th><th>Encaja</th><th>TH</th></tr></thead><tbody>
    ${rows.map(x => `<tr class="${x.us ? 'es-us' : ''}"><td class="es-clan">${esc(x.name)}</td><td>${x.sample < 15 ? 'Pocos datos' : esc(x.level_name)}</td><td>${x.stars_attack == null ? '–' : dec(x.stars_attack, 2)}</td><td>${x.triples == null ? '–' : x.triples + ' %'}</td><td>${x.attacks_war == null ? '–' : dec(x.attacks_war, 1)}</td><td>${x.defended == null ? '–' : dec(x.defended, 1) + '★'}</td><td>${dec(x.th, 1)}</td></tr>`).join('')}</tbody></table></div>
    <div class="small text-secondary mt-2">«Nivel» mide cómo ataca cada clan para su ayuntamiento, no cuántas estrellas hace. «Ataques» es la media por guerra y «Encaja», las estrellas que le sacan. Con pocos ataques el nivel es poco fiable.</div></div>`;
}
function esCalc(v) {
  const t = v.backtest, k = v.model || {}, bins = k.bins || [];
  return `<div class="card-body es-calc">
    <p><b>Asegurado y descartado.</b> Se calcula el mejor y el peor final posibles: en cada guerra pendiente, las estrellas actuales y el máximo que da cada ataque que falta (3★ por cuenta, cada base cuenta una vez). «Matemático» significa que ya no puede cambiar. «En la práctica» significa que aún cabe en teoría, pero no ha salido en más del 99,5 % de las simulaciones.</p>
    <p><b>Clasificación.</b> Estrellas + 10 por victoria. Empate a estrellas: gana quien acumula más destrucción. Una guerra se gana por estrellas y, a igualdad, por destrucción.</p>
    <p><b>% de pleno.</b> Un modelo entrenado en cada recogida con ${num(k.rows || v.attacks)} ataques reales de ${num(k.players_a || 0)} jugadores. Tiene en cuenta la diferencia de ayuntamiento y su nivel, el historial del atacante, lo dura que es esa aldea concreta, la forma reciente de ambos, si es liga, si la aldea ya estaba tocada, el equipo de héroes y la posición entre aldeas del mismo ayuntamiento. Los ataques recientes pesan más: esa memoria y la fuerza de cada factor se eligen solas, probando cuál habría acertado más.</p>
    <p><b>Qué no cuenta.</b> Niveles de héroes, mascotas, hechizos, experiencia o estrellas de guerra se probaron y no mejoran la predicción una vez conocido el historial del jugador. De los edificios de la aldea la API no da nada: eso solo se ve a través de cómo le ha ido a quien la ha atacado.</p>
    ${bins.length ? `<p class="mb-1"><b>¿Acierta?</b> Sin ver las últimas semanas (${num(k.holdout)} ataques), esto dijo y esto pasó${k.auc ? `; ordena bien el ${Math.round(k.auc * 100)} % de las parejas pleno y no pleno` : ''}:</p><table class="xd-t mb-3"><thead><tr><th>Decía</th><th>Pasó</th><th>Ataques</th></tr></thead><tbody>${bins.map(b => `<tr><td>${Math.round(b.says * 100)} %</td><td><b>${Math.round(b.real * 100)} %</b></td><td>${num(b.n)}</td></tr>`).join('')}</tbody></table>` : ''}
    <p><b>Plan de ataque.</b> Se calcula el % de cada cuenta contra cada aldea y se busca el reparto con más plenos esperados, sin atacar nunca por encima del propio puesto. La nota de corte no es fija: es la más exigente que apenas pierde plenos. Quien se queda sin aldea queda de reserva para rematar.</p>
    <p><b>Alternativa.</b> Es el mismo cálculo dejando subir a quien lo necesita si el conjunto gana: si el 3 pierde 3 puntos por bajar y el 5 gana 9 por subir, salen 6 a favor. Cada subida debe ganar más que el error medio del modelo${k.calib != null ? ` (${dec(k.calib * 100, 1)} puntos)` : ''}. Después se juegan las dos versiones ${num(1500)} veces, y solo se dice que sale más rentable si la diferencia supera el azar.</p>
    <p><b>Previsto y real.</b> Cada guerra se predice con un modelo que solo ha visto lo terminado antes de que empezara, y la predicción se guarda sin retocarla: por eso se puede comparar con lo que pasó sin trampa. En el directo, el % de ganar parte del marcador real y simula los ataques que faltan.</p>
    <p><b>Probabilidades.</b> Cada guerra pendiente se juega ${num(300)} veces: ataca cada cuenta según su asistencia, cada una a la aldea más alta a la que suele apuntar su clan, y solo cuenta el mejor ataque por aldea. También hay días buenos y malos de todo el clan${k.war_sigma != null ? `, con la amplitud medida en guerras reales` : ''}. Después se combinan en 4.000 finales de liga.</p>
    <p><b>Techo realista.</b> Lo que da el plan de ataque en un día bueno: el mejor 10 % de sus resultados.</p>
    <p><b>Quien no ataca.</b> La asistencia combina esta liga con guerras anteriores, y lo reciente manda. Con 3 guerras o más alineada y ningún ataque se da por hecho que no atacará; en Admin se puede corregir. Si la guerra está avanzada y aún no ha atacado, se rebaja su probabilidad.</p>
    <p><b>Cruces.</b> Se juega contra todos: lo que falta son las parejas que quedan. Si solo cabe un cruce en la última ronda, se indica como deducido.</p>
    <p class="mb-0"><b>Fiabilidad.</b> ${t.n ? `Probado con ${num(t.n)} resultados de esta liga, prediciendo cada ronda solo con lo anterior: se desvía ${dec(t.mae, 1)}★ de media por guerra.` : 'Aún no hay rondas suficientes para medirla.'} Los cupos de ascenso y descenso no los da la API: ${v.zones.default ? 'se usa lo habitual, 2 y 2, y se pueden cambiar' : 'son los indicados'} en Admin.</p></div>`;
}
// ---------- batalla en juego y previsto frente a real
const esStarsTxt = n => `<span class="text-yellow" aria-label="${n} estrellas">${'★'.repeat(n)}</span><span class="text-secondary">${'★'.repeat(3 - n)}</span>`;
const ES_TONE = {up: ['ti-arrow-up', 'es-up-t', 'Mejor de lo esperado'], down: ['ti-arrow-down', 'es-down-t', 'Peor de lo esperado'], ok: ['ti-minus', 'es-ok-t', 'Lo esperado']};
const ES_HIT_HEAD = '<div class="es-hit-head"><span>Ataque</span><span title="% de pleno que se le daba antes de la guerra">Previsto</span><span>Resultado</span><span></span></div>';
function esHit(r) {
  const [i, c, t] = ES_TONE[r.tone];
  return `<div class="es-hit"><span class="es-hit-who" title="${esc(r.a)} a ${esc(r.b)}"><b>${r.a_pos}.</b> ${esB(r.a)}<i class="ti ti-arrow-right"></i><b>${r.b_pos}.</b> ${esB(r.b)}</span><span class="es-hit-p">${Math.round(r.p3 * 100)} %</span><span class="es-hit-r">${esStarsTxt(r.stars)}<small>${num(r.pct)} %</small></span><i class="ti ${i} ${c}" title="${t}" aria-label="${t}"></i></div>`;
}
const esGap = t => esSigned(+(t.stars - t.e).toFixed(1), 1) + '★';
function esBattle(b) {
  const live = b.state === 'inWar', left = (b.state === 'preparation' ? b.start : b.ends) - Date.now() / 1000, x = b.before, n = b.now;
  const side = (s, right) => `<div class="es-bat-s ${right ? 'r' : ''}"><b><bdi>${esc(s.name)}</bdi></b><small>${s.attacks} de ${s.max} ataques · ${dec(s.pct, 1)} %</small></div>`;
  return `<div class="card-body"><div id="esBattle">
    <div class="es-bat-top"><span class="badge ${live ? 'bg-green-lt' : 'bg-blue-lt'}">${live ? 'En juego' : 'En preparación'}</span><span>${b.cwl ? esRound(b.round) : 'Guerra normal'} · ${b.size} contra ${b.size}${b.per > 1 ? ` · ${b.per} ataques cada uno` : ''}</span><span>${left > 0 ? `${live ? 'Acaba' : 'Empieza'} en ${fmtMin(left)}` : 'Acaba de terminar'}</span></div>
    <div class="es-bat-score">${side(b.us)}<div class="es-bat-n">${b.us.stars}<span>–</span>${b.them.stars}</div>${side(b.them, true)}</div>
    ${x ? `<div class="es-tiles"><div><small>Ganar, antes de empezar</small><b>${esPct(x.win)}</b><small>${dec(x.us, 0)}★ frente a ${dec(x.them, 0)}★</small></div>
      ${n ? `<div><small>Ganar, ahora mismo</small><b>${esPct(n.win)}</b><small>acabaría ${dec(n.us, 0)}★ a ${dec(n.them, 0)}★</small></div>` : ''}
      ${b.t?.n ? `<div><small>Plenos hechos</small><b>${b.t.triples}</b><small>se esperaban ${dec(b.t.p3, 1)}</small></div><div><small>Frente a lo esperado</small><b>${esGap(b.t)}</b><small>en ${plural(b.t.n, 'ataque', 'ataques')}</small></div>` : ''}</div>`
      : '<div class="es-note mt-0"><i class="ti ti-clock"></i>La previsión de esta guerra llegará con la siguiente recogida: se hace antes de ver sus ataques.</div>'}
    ${b.hits?.length ? `<details class="mt-2" ${S.hitsOpen ? 'open' : ''} data-hits><summary class="es-more">Ver ${plural(b.hits.length, 'ataque hecho', 'ataques hechos')}: previsto y resultado</summary><div class="mt-1">${ES_HIT_HEAD}${b.hits.slice().reverse().map(esHit).join('')}</div></details>` : ''}
    <div class="small text-secondary mt-2"><i class="ti ti-clock me-1"></i>${b.fresh ? `En directo: actualizado a las ${new Date(b.ts * 1000).toLocaleTimeString('es-ES', {hour: '2-digit', minute: '2-digit'})}` : `Datos de la recogida del ${esWhen(b.ts)}`}.</div></div></div>`;
}
const esPastTitle = x => x.kind === 'cwl' && x.round ? esRound(x.round) : fechaApi(x.end);
const fechaApi = e => e ? `${String(e).slice(6, 8)}/${String(e).slice(4, 6)}` : '–';
function esPastRow(x, open) {
  const r = {win: 'Ganada', lose: 'Perdida', tie: 'Empatada'}[x.result], b = x.before, c = {win: 'bg-green-lt', lose: 'bg-red-lt', tie: 'bg-secondary-lt'}[x.result];
  return `<details class="es-plan" ${open ? 'open' : ''}><summary><span class="es-day-h"><b>${esPastTitle(x)} · ${esB(x.them.name)}</b><small><span class="badge ${c}">${r} ${x.us.stars}-${x.them.stars}</span> · se preveía ${esPct(b.win)} de ganar y ${dec(b.us, 0)}★${x.partial ? ' · datos parciales' : ''}</small></span><i class="ti ti-chevron-down es-chev"></i></summary>
    <div class="es-body"><div class="es-tiles"><div><small>Estrellas</small><b>${x.us.stars}</b><small>previstas ${dec(b.us, 1)} (${num(b.us_lo)}-${num(b.us_hi)})</small></div><div><small>Del rival</small><b>${x.them.stars}</b><small>previstas ${dec(b.them, 1)}</small></div><div><small>Plenos</small><b>${x.t.triples}</b><small>se esperaban ${dec(x.t.p3, 1)}</small></div><div><small>Ataques usados</small><b>${x.us.attacks}</b><small>de ${x.us.max}</small></div></div>
    ${x.rows.length ? `<div class="es-h">Cada ataque</div>${ES_HIT_HEAD}${x.rows.map(esHit).join('')}` : ''}${x.partial ? '<div class="small text-secondary mt-1">La guerra terminó entre dos recogidas: el marcador es el final, pero pueden faltar sus últimos ataques.</div>' : ''}</div></details>`;
}
function esPast(d) {
  const s = d.summary, list = d.past || [], name = d.past_kind === 'war' ? ['guerra', 'guerras'] : ['ronda', 'rondas'];
  if (!list.length) return `<div class="card-body">${empty(`Aún no ha terminado ninguna ${name[0]} desde que se guardan las previsiones`)}</div>`;
  return `<div class="card-body">
    ${s ? `<div class="es-tiles"><div><small>Plenos</small><b>${num(s.triples)}</b><small>previstos ${dec(s.p3, 1)}</small></div><div><small>Estrellas en ataques</small><b>${num(s.stars)}</b><small>previstas ${dec(s.e, 1)}</small></div><div><small>Ganador acertado</small><b>${s.right} de ${s.called}</b><small>${name[1]} con favorito</small></div><div><small>Error por guerra</small><b>${dec(s.stars_err, 1)}★</b><small>total del clan</small></div></div>
    <details class="mt-1"><summary class="es-more">¿Se cumple lo que dice el %?</summary><table class="xd-t mt-1"><thead><tr><th>Decía</th><th>Pasó</th><th>Ataques</th></tr></thead><tbody>${s.bins.map(b => `<tr><td>${Math.round(b.says * 100)} %</td><td><b>${Math.round(b.real * 100)} %</b></td><td>${num(b.n)}</td></tr>`).join('')}</tbody></table>${s.n < 300 ? `<div class="small text-secondary mt-1">Con ${num(s.n)} ataques los tramos aún bailan mucho: será más fiable al ir sumando guerras.</div>` : ''}</details>
    <details class="mt-1"><summary class="es-more">Quién rinde por encima o por debajo de lo previsto</summary><table class="xd-t mt-1"><thead><tr><th>Cuenta</th><th>Plenos</th><th>Previstos</th><th>Estrellas</th></tr></thead><tbody>${s.players.map(p => `<tr><td>${esc(p.name)}<small>${plural(p.n, 'ataque', 'ataques')}</small></td><td>${p.triples}</td><td>${dec(p.p3, 1)}</td><td><b class="${p.gap > 0 ? 'text-green' : p.gap < 0 ? 'text-red' : ''}">${esSigned(p.gap, 1)}</b></td></tr>`).join('')}</tbody></table></details>` : ''}
    <div class="es-h">${name[1][0].toUpperCase() + name[1].slice(1)} jugadas</div>${list.map((x, i) => esPastRow(x, i === 0)).join('')}
    ${s && s.wars > list.length ? `<div class="small text-secondary mt-1">Se enseñan las ${list.length} últimas de ${s.wars}.</div>` : ''}</div>`;
}
// Mientras se juega, el marcador y el % se piden al minuto. Lo demás no se repinta: no hay que perder lo que se está leyendo.
function esLiveStart(d) {
  if (S.liveFor === d) return;          // repintar los mismos datos no vuelve a preguntar
  S.liveFor = d; clearTimeout(S.liveTimer);
  const gen = S.liveGen = (S.liveGen || 0) + 1, on = () => gen === S.liveGen && S.sub === 'escenarios' && S.data === d;
  if (!d.battle) return;
  let attacks = d.battle.us.attacks + d.battle.them.attacks;
  const tick = () => { if (!on()) return;
    if (document.hidden) { S.liveTimer = setTimeout(tick, 15000); return; }
    api('api/vivo').then(j => { if (!on() || !j.battle) return;
      const b = {...j.battle, fresh: true}, now = b.us.attacks + b.them.attacks, moved = now !== attacks; attacks = now; d.battle = b;
      const box = document.getElementById('esBattle'); if (box) { const t = document.createElement('div'); t.innerHTML = esBattle(b); box.replaceWith(t.querySelector('#esBattle')); esHitsWire(); }
      if (b.plan) { const v = d.mode === 'liga' ? d.liga : null, list = v ? v.plans : d.plans, at = list?.findIndex(p => p.round === b.plan.round && p.rival === b.plan.rival);
        if (at >= 0) { list[at] = {...list[at], ...b.plan, title: list[at].title}; if (moved) esPlanRefresh(d); } }
    }).catch(() => {}).finally(() => { if (on() && d.battle.state === 'inWar') S.liveTimer = setTimeout(tick, 60000); }); };
  tick();
}
function esHitsWire() { document.querySelector('[data-hits]')?.addEventListener('toggle', e => { S.hitsOpen = e.target.open; }); }
function esPlanRefresh(d) {
  const v = d.mode === 'liga' ? d.liga : {plans: d.plans, ts: d.battle?.ts};
  const set = (id, html) => { const b = document.querySelector(`[data-sec=${id}] .sec-body`); if (b) b.innerHTML = html; };
  set('eplan', esPlans(v)); set('echat', esChat(v)); esChatWire(v); esPlanWire();
}
// ---------- simulador
function esWhatKey(g) { return `${g.a}|${g.b}`; }
function esWhatDefault(g) { return [Math.round(g.ax), Math.round(g.bx)]; }
function esWhatCalc(v) {
  const s = Object.fromEntries(v.table.map(x => [x.tag, {name: x.name, stars: x.stars, pct: x.pct, us: x.us}]));
  v.games.forEach(g => {
    const [x, y] = S.whatIf[esWhatKey(g)] ?? esWhatDefault(g);
    const xp = Math.min(100, g.ax ? g.ap * x / g.ax : x), yp = Math.min(100, g.bx ? g.bp * y / g.bx : y);
    s[g.a].stars += x; s[g.a].pct += xp; s[g.b].stars += y; s[g.b].pct += yp;
    if (x > y || (x === y && xp > yp)) s[g.a].stars += 10; else if (y > x || (x === y && yp > xp)) s[g.b].stars += 10;
  });
  return Object.values(s).sort((a, b) => b.stars - a.stars || b.pct - a.pct);
}
function esWhatResult(v) {
  const rows = esWhatCalc(v), at = rows.findIndex(x => x.us), me = rows[at], box = document.getElementById('esWhatOut'); if (!box) return;
  const near = rows.filter((_, i) => Math.abs(i - at) <= 1 || i < 1);
  box.innerHTML = `<div class="es-what-top"><span>Con estos resultados acabamos</span><b>${at + 1}º · ${num(me.stars)}★</b>${at + 1 <= v.zones.promote ? '<span class="es-zone up">Ascenso</span>' : at + 1 > v.clans - v.zones.demote ? '<span class="es-zone down">Descenso</span>' : ''}</div>
    ${near.map(x => `<div class="es-what-r ${x.us ? 'fw-bold' : ''}"><span>${rows.indexOf(x) + 1}º</span><span class="text-truncate">${esc(x.name)}</span><span>${num(x.stars)}★${x.us ? '' : ` <small>(${x.stars >= me.stars ? '+' : ''}${num(x.stars - me.stars)})</small>`}</span></div>`).join('')}`;
}
function esWhat(v) {
  if (!v.games.length) return `<div class="card-body">${empty('No quedan guerras por jugar')}</div>`;
  const direct = v.needs.rows.find(r => r.status === 'posible')?.rival_tag;
  const list = S.whatAll ? v.games : v.games.filter(g => g.mine || [g.a, g.b].includes(direct));
  const input = (g, i, name) => { const k = esWhatKey(g), val = (S.whatIf[k] ?? esWhatDefault(g))[i], c = i ? g.b_cur : g.a_cur, top = 3 * v.size;
    return `<label class="es-step"><span class="text-truncate">${esc(name)}</span><span class="es-step-c"><button type="button" class="btn btn-sm btn-icon" data-what="${esc(k)}" data-i="${i}" data-d="-3" aria-label="Quitar 3 estrellas a ${esc(name)}">−</button><input type="number" inputmode="numeric" min="${c ? c.stars : 0}" max="${top}" value="${val}" data-what-in="${esc(k)}" data-i="${i}" aria-label="Estrellas de ${esc(name)}"><button type="button" class="btn btn-sm btn-icon" data-what="${esc(k)}" data-i="${i}" data-d="3" aria-label="Sumar 3 estrellas a ${esc(name)}">+</button></span></label>`; };
  return `<div class="card-body"><div class="es-what-tools"><button class="btn btn-sm" data-preset="plan">Usar la previsión</button><button class="btn btn-sm" data-preset="ceil">Nuestro techo realista</button><button class="btn btn-sm" data-preset="max">Nuestro máximo</button>
      ${v.games.length > list.length || S.whatAll ? `<button class="btn btn-sm btn-ghost-secondary" data-preset="all">${S.whatAll ? 'Solo las clave' : `Ver las ${num(v.games.length)} guerras`}</button>` : ''}</div>
    <div id="esWhatOut" class="es-what-out" aria-live="polite"></div>
    <div class="es-games mt-3">${list.map(g => `<div class="es-game"><div class="es-game-h">${esRound(g.round)}${g.state === 'inWar' ? ' · en juego' : ''}</div><div class="es-steps">${input(g, 0, g.a_name)}${input(g, 1, g.b_name)}</div></div>`).join('')}</div>
    <div class="small text-secondary mt-2">Las guerras que no se ven cuentan con su previsión. La destrucción se estima, y solo decide los empates.</div></div>`;
}
function esWire(v) {
  const clamp = (k, i, val) => { const g = v.games.find(x => esWhatKey(x) === k), c = i ? g.b_cur : g.a_cur; return Math.max(c ? c.stars : 0, Math.min(3 * v.size, val)); };
  const set = (k, i, val) => { const g = v.games.find(x => esWhatKey(x) === k), cur = [...(S.whatIf[k] ?? esWhatDefault(g))]; cur[i] = clamp(k, i, val); S.whatIf[k] = cur;
    const el = document.querySelector(`[data-what-in="${CSS.escape(k)}"][data-i="${i}"]`); if (el) el.value = cur[i]; esWhatResult(v); };
  $('clanView').querySelectorAll('[data-what]').forEach(b => { b.onclick = e => { e.preventDefault(); const k = b.dataset.what, i = +b.dataset.i, g = v.games.find(x => esWhatKey(x) === k); set(k, i, (S.whatIf[k] ?? esWhatDefault(g))[i] + +b.dataset.d); }; });
  $('clanView').querySelectorAll('[data-what-in]').forEach(el => { el.onchange = () => set(el.dataset.whatIn, +el.dataset.i, +el.value || 0); });
  $('clanView').querySelectorAll('[data-preset]').forEach(b => { b.onclick = () => {
    const p = b.dataset.preset;
    if (p === 'all') { S.whatAll = !S.whatAll; paint(); return; }
    S.whatIf = {};
    if (p !== 'plan') v.needs.wars.forEach(w => { const g = v.games.find(x => [x.a, x.b].includes(v.us) && [x.a, x.b].includes(w.rival)); if (!g) return; const k = esWhatKey(g), i = g.a === v.us ? 0 : 1, val = [...esWhatDefault(g)]; val[i] = p === 'ceil' ? w.ceil : w.max; S.whatIf[k] = val; });
    paint(); }; });
  esWhatResult(v);
}
// Esqueleto mientras se calcula por primera vez: la forma de la página y las fases que quedan
const esSteps = p => (p.steps || []).map((t, i) => { const n = i + 1, st = n < p.step ? 'done' : n === p.step ? 'now' : 'todo';
  return `<li class="es-step-${st}"><i class="ti ${st === 'done' ? 'ti-circle-check' : st === 'now' ? 'ti-loader-2 spin' : 'ti-circle'}"></i>${esc(t)}</li>`; }).join('');
const esSkeleton = p => `<div class="card mb-3"><div class="card-body"><div class="fw-medium mb-2">Calculando los escenarios por primera vez</div><ol class="es-steps-l" id="esSteps">${esSteps(p)}</ol></div></div>
  <div class="sk mb-3" style="height:120px"></div><div class="sk mb-3" style="height:220px"></div><div class="sk mb-3" style="height:320px"></div>`;
function esCalcWar(d) {
  return `<div class="card-body es-calc"><p><b>% de pleno.</b> Es el mismo modelo que en liga: diferencia de ayuntamiento y su nivel, historial del atacante, lo dura que es esa aldea, la forma reciente de ambos y si la aldea ya estaba tocada. Aquí no se aplica el efecto de liga.</p>
    <p><b>Dos ataques.</b> Cada cuenta cuenta una vez por ataque que le quede y nunca repite aldea. Como hay el doble de ataques que aldeas, lo que no entra en el plan queda de reserva para rematar.</p>
    <p><b>Previsto y real.</b> La previsión se hace solo con lo terminado antes de empezar la guerra y se guarda sin retocarla. El % de ganar en directo parte del marcador real y simula los ataques que faltan, según la asistencia de cada cuenta en guerras normales.</p>
    <p class="mb-0"><b>Con pocos datos.</b> Si ClashKing no tiene historial de un jugador, el modelo parte de lo que suele pasar con esa diferencia de ayuntamiento, y afina según se juegan guerras.</p></div>`;
}
function renderGuerra(d, notice) {
  const b = d.battle, v = {plans: d.plans = b.plan ? [b.plan] : [], ts: b.ts}, open = !!b.plan;
  $('clanView').innerHTML = `${notice}
    ${sec('ebat', 'Batalla en juego', '', esBattle(b), true)}
    ${open ? sec('eplan', 'Plan de ataque', '', esPlans(v), true) : ''}
    ${open ? sec('echat', 'Mensajes para el chat', '', esChat(v), true) : ''}
    ${sec('eprev', 'Previsto y real', '', esPast(d), true)}
    ${sec('ecalc', 'Cómo se calcula', '', esCalcWar(d), false)}`;
  esChatWire(v); esPlanWire(); esHitsWire();
}
function renderEscenarios(d) {
  const v = d.liga;
  if (!v && !d.battle && !d.past?.length && d.progress?.active) { $('clanView').innerHTML = esSkeleton(d.progress); return; }
  let notice_ = '';
  const notice = [d.liga_error ? `<div class="alert alert-warning"><i class="ti ti-alert-triangle me-1"></i>No se ha podido actualizar la liga: ${esc(d.liga_error)}${v ? ' Se muestran los últimos datos buenos.' : ''}</div>` : '',
    d.off && v ? '<div class="alert alert-info"><i class="ti ti-info-circle me-1"></i>El clan no está ahora en ninguna liga. Esto es lo último que jugó.</div>' : ''].join('');
  if (d.battle_error) notice_ = `<div class="alert alert-warning"><i class="ti ti-alert-triangle me-1"></i>${esc(d.battle_error)}</div>`;
  if (d.mode === 'guerra') { renderGuerra(d, notice + notice_); esLiveStart(d); return; }
  if (!v) {
    $('clanView').innerHTML = `${notice}${notice_}<div class="card mb-3"><div class="card-body text-center py-5"><i class="ti ti-target-arrow" style="font-size:2.5rem;color:var(--tblr-secondary)"></i>
      <h3 class="mt-2">${!d.has_key ? 'Falta conectar la API oficial' : d.off ? 'El clan no está ahora en liga ni en guerra' : 'Aún no hay datos'}</h3>
      <p class="text-secondary mb-0">${!d.has_key ? 'Las guerras en curso y los grupos de liga solo están en la API de Supercell. Añade la clave en Admin y se calcularán las predicciones.' : d.off ? 'Cuando empiece una guerra o la próxima liga, las predicciones aparecerán aquí solas tras la siguiente recogida.' : 'Aparecerán aquí tras la siguiente recogida de datos.'}</p></div></div>
      ${d.past?.length ? sec('eprev', 'Previsto y real', '', esPast(d), true) : ''}`;
    return;
  }
  S.whatIf ??= {}; S.whatFor = S.whatFor === v.ts ? S.whatFor : (S.whatIf = {}, v.ts);
  $('clanView').innerHTML = `${notice}${notice_}${esHero(v)}
    ${d.battle ? sec('ebat', 'Batalla en juego', '', esBattle(d.battle), true) : ''}
    ${sec('epos', 'Dónde podemos acabar', '', `<div class="card-body">${esPositions(v)}</div>`, true)}
    ${v.state !== 'ended' ? sec('eplan', 'Plan de ataque', '', esPlans(v), true) : ''}
    ${v.state !== 'ended' ? sec('echat', 'Mensajes para el chat', '', esChat(v), true) : ''}
    ${sec('eprev', 'Previsto y real', '', esPast(d), true)}
    ${sec('etab', 'Clasificación y previsión', '', esTable(v), true)}
    ${sec('elog', 'Resumen diario', '', esLog(v), true)}
    ${v.state !== 'ended' ? sec('egam', 'Guerras que quedan', '', esGames(v), true) : ''}
    ${v.state !== 'ended' ? sec('eban', 'Alineación y banquillo', '', esBench(d, v), true) : ''}
    ${v.state !== 'ended' ? sec('ewhat', 'Simulador: ¿y si…?', '', esWhat(v), true) : ''}
    ${sec('eniv', 'Nivel de cada clan', '', esLevels(v), true)}
    ${sec('ecalc', 'Cómo se calcula', '', esCalc(v), false)}`;
  if (v.state !== 'ended') { esWire(v); esChatWire(v); esPlanWire(); }
  esHitsWire(); esLiveStart(d);
}
// ---------- administración
function esAdminSection(a) {
  const l = a.liga; if (!l) return '';
  return sec('aliga', 'Liga: cupos y atacantes', '', `<div class="card-body"><form id="adminLiga">
    <div class="d-flex flex-wrap gap-3 mb-3"><label>Plazas de ascenso<input class="form-control mt-1" style="width:7rem" type="number" min="0" max="4" id="ligaUp" value="${l.cfg.promote ?? ''}" placeholder="${l.zones.promote}"></label><label>Plazas de descenso<input class="form-control mt-1" style="width:7rem" type="number" min="0" max="4" id="ligaDown" value="${l.cfg.demote ?? ''}" placeholder="${l.zones.demote}"></label></div>
    <div class="fw-medium mb-1">Cuentas que no atacarán</div><div class="small text-secondary mb-2">Las marcadas no cuentan para el máximo ni para la previsión. Quien lleva 3 guerras sin atacar sale marcado solo: desmárcalo si sí va a atacar.</div>
    <div class="es-checks">${l.roster.map(m => `<label class="form-check"><input class="form-check-input" type="checkbox" data-tag="${esc(m.tag)}" data-auto="${m.auto ? 1 : 0}" ${m.inactive ? 'checked' : ''}><span class="form-check-label">${esc(m.name)} <small class="text-secondary">TH${m.th} · ${m.used} de ${m.wars}</small></span></label>`).join('')}</div>
    <button class="btn btn-primary mt-3">Guardar y recalcular</button></form></div>`, true);
}
function esAdminWire(done, fail) {
  const f = document.getElementById('adminLiga'); if (!f) return;
  f.onsubmit = e => { e.preventDefault(); const si = [], no = [];
    f.querySelectorAll('[data-tag]').forEach(c => { const auto = c.dataset.auto === '1'; if (c.checked && !auto) no.push(c.dataset.tag); if (!c.checked && auto) si.push(c.dataset.tag); });
    const btn = f.querySelector('button'); btn.disabled = true; watchProgress(4000);
    api('api/liga', {promote: $('ligaUp').value, demote: $('ligaDown').value, si, no}).then(done('Liga recalculada')).catch(fail).finally(() => { btn.disabled = false; }); };
}
