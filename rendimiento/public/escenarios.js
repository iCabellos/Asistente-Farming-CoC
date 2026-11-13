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
    ${v.state !== 'ended' && up && up.status === 'posible' ? `<div class="small text-secondary mt-2">Si atacan todos los que pueden, ascender sube al ${esPct(v.ranks_all.slice(0, v.zones.promote).reduce((a, b) => a + b, 0))}; si además siguen el plan de ataque, al ${esPct(v.ranks_plan.slice(0, v.zones.promote).reduce((a, b) => a + b, 0))}.</div>` : ''}
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
const ES_GOAL = {3: 'a por el pleno', 2: 'a por 2★', 1: 'a sumar lo que pueda'};
const ES_STYLE = {
  stars: 'El reparto que más estrellas suma es también el que más veces gana la guerra.',
  bold: 'Para ganar hay que arriesgar: este reparto busca más plenos que el de más estrellas, y gana la guerra más veces.',
  triples: 'Para ganar solo valen los plenos: cada ataque va donde más opciones tiene de hacer 3★.',
  safe: 'Asegurando 2★ en cada aldea se gana la guerra más veces que arriesgando.',
  train: 'Lo que más veces gana la guerra es que ataquen todos primero y guardar los segundos ataques para rematar.',
};
function esShape(p) {
  if (!p.assign.length) return 'No quedan ataques que repartir.';
  const idle = p.reserves.reduce((n, r) => n + r.n, 0);
  if (p.goal === 'train') {
    const one = p.assign.filter(a => a.phase !== 2).length, two = p.assign.length - one, lone = p.assign.filter(a => a.lone).length;
    return `${one ? `${plural(one, 'cuenta hace', 'cuentas hacen')} su primer ataque contra su mejor rival: una aldea para cada una y solo donde tiene opciones reales.` : 'Los primeros ataques ya están hechos.'}${lone ? ` ${plural(lone, 'cuenta no tiene', 'cuentas no tienen')} ninguna aldea propia a su alcance: ${lone === 1 ? 'va' : 'van'} a la que mejor se le da, aunque la comparta. A nadie se le manda a una aldea de arriba para cubrirla.` : ''}${two ? ` ${plural(two, 'segundo ataque ya se puede usar y va', 'segundos ataques ya se pueden usar y van')} donde más ayuda a ganar la guerra.` : ''}${idle ? ` ${plural(idle, 'ataque queda', 'ataques quedan')} por repartir: se deciden cuando sus cuentas hayan hecho el primero, con el mismo criterio que el plan 1.` : ''}`;
  }
  const head = p.win == null ? 'Reparto de más estrellas esperadas: aún no se puede medir el % de ganar.' : ES_STYLE[p.style] || ES_STYLE.stars;
  const cover = p.uncovered.length ? `${plural(p.uncovered.length, 'aldea se queda', 'aldeas se quedan')} sin rival: o nadie tiene opciones con ella o el ataque que haría falta rinde más en otra.` : `Las ${num(p.open)} aldeas que quedan tienen rival.`;
  return `${head} ${cover} Un solo ataque por aldea: repetir aldea gastaría un ataque que rinde más en otra.${idle ? ` ${plural(idle, 'ataque queda', 'ataques quedan')} en reserva: solo se usan si su cuenta, por sí sola, puede mejorar una aldea que no salga pleno.` : ''}`;
}
function esPlanHit(a) {
  return `<div class="es-tgt"><div class="es-tgt-m"><i class="ti ti-arrow-right text-secondary"></i><span class="es-atk-t"><b>${a.b_pos}.</b> ${esB(a.b)}<small>TH${a.b_th}${a.best ? ` · ya ${a.best}★` : ''}${a.phase === 2 ? ' · segundo ataque' : ''}${a.lone ? (a.ok ? ' · comparte aldea' : ' · sin aldea a su alcance: va a la más asequible') : ''}${a.up ? ' · <i class="ti ti-arrow-up" title="Ataca por encima de su puesto"></i> sube' : ''}</small></span><span class="es-atk-p"><b>${Math.round(a.p3 * 100)} %</b><small>${dec(a.stars, 1)}★ · ${ES_TIER[a.tier]}</small></span></div>
    <div class="es-atk-w">${ES_GOAL[a.goal] ?? ''} · ${esEvidence(a)}</div></div>`;
}
function esEvidence(a) {     // por qué ese %: lo que dicen las últimas 10 defensas de la aldea y los últimos 10 ataques de la cuenta
  const e = a.why.ev || {}, out = [];
  if (e.d_s) out.push(`le ${e.d_s === 1 ? 'hizo pleno 1' : `hicieron pleno ${e.d_s}`} de TH${a.a_th} o menos${e.d_best != null && e.d_best < a.a_th ? ` (hasta un TH${e.d_best})` : ''}`);
  if (e.d_f) out.push(`${e.d_f === 1 ? 'no pudo 1' : `no pudieron ${e.d_f}`} de TH${a.a_th} o más${e.d_fail != null && e.d_fail > a.a_th ? ` (hasta un TH${e.d_fail})` : ''}`);
  if (e.a_s) out.push(`${a.a} hizo ${e.a_s} ${e.a_s === 1 ? 'pleno' : 'plenos'} a TH${a.b_th} o más`);
  if (e.a_f) out.push(`${a.a} falló ${e.a_f} contra TH${a.b_th} o menos`);
  return out.length ? `historial: ${out.join(' · ')}` : (a.why.d_n ? `a esta aldea, ${a.why.d_3} plenos en ${a.why.d_n}` : 'sin historial que compare');
}
function esPlanCards(rows) {     // una tarjeta por cuenta, con su ataque o sus dos ataques dentro
  const by = new Map();
  for (const a of rows) {
    if (!by.has(a.a_tag)) by.set(a.a_tag, []);
    by.get(a.a_tag).push(a);
  }
  const color = {seguro: 'var(--tblr-green)', razonable: 'var(--tblr-yellow)', dudoso: 'var(--tblr-red)'};
  return [...by.values()].map(hits => { const a = hits[0], k1 = color[a.tier], k2 = color[hits[hits.length - 1].tier];     // el borde, partido si hay dos ataques
    return `<div class="es-atk es-acc" style="--k1:${k1};--k2:${k2}"><div class="es-acc-h"><span class="es-atk-t"><b>${a.a_pos}.</b> ${esB(a.a)}<small>TH${a.a_th}</small></span><small class="text-secondary">${a.why.a_n ? `sus últimos ${a.why.a_n}: ${a.why.a_3} plenos` : 'sin historial'}${hits.length > 1 ? ` · ${hits.length} ataques` : ''}</small></div>${hits.map(esPlanHit).join('')}</div>`; }).join('');
}
function esMatrix(p, alt) {
  const m = p.matrix, rows = alt ? p.alt.assign : p.assign, on = new Set(rows.map(a => `${a.a_pos}|${a.b_pos}`));
  const cell = (x, e, a, b) => { const up = false, used = on.has(`${a.pos}|${b.pos}`), c = `background:rgba(45,160,90,${(x / 100 * .75).toFixed(2)})`;
    return `<td class="${used ? 'es-on' : ''} ${up ? 'es-up' : ''} ${b.best >= 3 ? 'es-done' : ''}" style="${up || b.best >= 3 ? '' : c}" title="${esc(a.name)} a ${esc(b.name)}: ${x} % de pleno${e == null ? '' : `, ${dec(e, 1)}★ de media`}">${b.best >= 3 ? '★' : x}</td>`; };
  return `<div class="table-responsive es-mx-w"><table class="es-mx"><thead><tr><th>Ataca</th>${m.b.map(b => `<th title="${esc(b.name)}">${b.pos}<small>TH${b.th}</small></th>`).join('')}</tr></thead><tbody>
    ${m.a.map((a, i) => `<tr><th title="${esc(a.name)}">${a.pos}. <bdi>${esc(a.name)}</bdi></th>${m.p3[i].map((x, j) => cell(x, m.e?.[i]?.[j], a, m.b[j])).join('')}</tr>`).join('')}</tbody></table></div>
    <div class="small text-secondary mt-1">% de pleno de cada cuenta contra cada aldea (al pasar por encima, las estrellas de media). Más verde, más probable. Recuadro: lo que propone el plan ${alt ? '2' : '1'}.</div>`;
}
// ---------- segunda propuesta: entrenamiento para liga (atacan todos y el segundo ataque remata)
const esPlanKey = p => String(p.round ?? p.rival);
const esAlt = p => p.alt?.goal === 'train' && p.alt.final ? p.alt : null;      // un plan guardado con el formato anterior no tiene esta propuesta
const esPick = p => !!(esAlt(p) && S.chatAlt);       // el chat avisa del plan que se elija en su apartado
const esSigned = (n, d = 1) => `${n > 0 ? '+' : n < 0 ? '−' : ''}${dec(Math.abs(n), d)}`;
const ES_VERDICT = {
  mejor: ['es-b-asegurado', 'ti-trending-up', 'Frente al plan 1: aquí además gana más'],
  peor: ['es-b-posible', 'ti-arrows-exchange', 'Frente al plan 1: lo que cuesta que ataquen todos'],
  igual: ['', 'ti-equal', 'Frente al plan 1: sale prácticamente igual'],
};
function esAltText(a) {
  const b = a.base, w = a.win != null && b.win != null;
  const vs = `${w ? `Ganar la guerra: ${esPct(a.win)}, frente al ${esPct(b.win)} del plan 1. ` : ''}Acabaría en ${dec(a.final.stars, 0)}★ y ${dec(a.final.triples, 1)} plenos, frente a ${dec(b.final.stars, 0)}★ y ${dec(b.final.triples, 1)}.`;
  return `${vs}${a.verdict === 'igual' ? ' La diferencia no se distingue del azar.' : ''}`;
}
function esAltBox(p) {
  const a = esAlt(p), [cls, icon, title] = ES_VERDICT[a.verdict] || ES_VERDICT.igual;
  const move = r => { const change = r.was == null ? `entra al ${r.now}` : r.now == null ? `deja el ${r.was} y queda en reserva` : `al ${r.now} en vez del ${r.was}`, d = (r.p_now ?? 0) - (r.p_was ?? 0);
    return `<div class="es-sw-r"><span><b>${r.pos}.</b> ${esB(r.name)} ${change}</span><small>${r.e_was == null ? '–' : dec(r.e_was, 1) + '★'} → ${r.e_now == null ? '–' : dec(r.e_now, 1) + '★'}</small><b class="${d >= 0 ? 'text-green' : 'text-red'}">${esSigned(Math.round(d * 100), 0)} % pleno</b></div>`; };
  return `<div class="es-alt ${cls}"><div class="es-alt-h"><i class="ti ${icon}"></i><b>${title}</b><small>${a.gain_w != null ? `${esSigned(Math.round(a.gain_w * 100), 0)} % de ganar · ` : ''}${esSigned(a.gain_s, 1)}★</small></div>
    <div class="small">${esAltText(a)}</div>
    ${a.swaps.length ? `<details class="mt-1"><summary class="es-more">Ver qué cambia respecto al plan 1</summary><div class="mt-1">${a.swaps.map(s => `<div class="es-sw">${s.rows.map(move).join('')}</div>`).join('')}</div></details>` : ''}</div>`;
}
// Dos apartados: plan 1 (mejores ataques para ganar) y plan 2 (todos atacan; el segundo ataque se reparte para ganar)
function esPlans(v, alt = false) {
  if (!v.plans?.length) return `<div class="card-body">${empty('No quedan guerras por jugar')}</div>`;
  const st = {inWar: ['bg-green-lt', 'En juego'], preparation: ['bg-blue-lt', 'En preparación'], pending: ['bg-secondary-lt', 'Aún no empieza']};
  const open = S.planOpen ?? esPlanKey(v.plans[0]);
  return `<div class="card-body">${v.plans.map(p => { const x = alt ? esAlt(p) : p;
    const top = `<summary><span class="es-day-h"><b>${esTitle(p)} · ${esB(p.rival_name)}</b><small><span class="badge ${st[p.state][0]}">${st[p.state][1]}</span>${p.deduced ? ' · cruce deducido' : ''}${p.known ? '' : ' · con su última alineación'}${x ? ` · ${dec(x.stars, 0)}★ y ${dec(x.triples, 1)} plenos previstos${x.win != null ? ` · ganar: ${esPct(x.win)}` : ''}` : ''}</small></span><i class="ti ti-chevron-down es-chev"></i></summary>`;
    if (!x) return `<details class="es-plan" ${esPlanKey(p) === open ? 'open' : ''}>${top}<div class="es-body"><div class="es-note mt-0"><i class="ti ti-clock"></i>${p.assign.length ? 'Este plan se calculará con la próxima recogida.' : 'No quedan ataques que repartir.'}</div></div></details>`;
    const more = +(x.stars - p.mirror.stars).toFixed(1), nb = p.open ?? p.matrix.b.length, one = x.assign.filter(a => a.phase !== 2), two = x.assign.filter(a => a.phase === 2);
    const win = x.win != null && x.final ? `<div><small>Ganar la guerra</small><b>${esPct(x.win)}</b><small>acabaría en ${dec(x.final.stars, 0)}★ con todos los ataques</small></div>` : x.final && x.final.stars > x.stars ? `<div><small>Con todos los ataques</small><b>${dec(x.final.stars, 0)}★</b><small>entre ${num(x.final.lo)} y ${num(x.final.hi)}</small></div>` : '';
    return `<details class="es-plan" ${esPlanKey(p) === open ? 'open' : ''}>${top}
    <div class="es-body"><div class="small mb-2">${esShape({...p, ...x})}</div>
    ${alt ? esAltBox(p) : ''}
    ${x.assign.length ? `<div class="es-tiles">${win}<div><small>Estrellas</small><b>${dec(x.stars, 0)}★</b><small>entre ${num(x.lo)} y ${num(x.hi)}${p.stars_now ? `, con ${num(p.stars_now)} ya hechas` : ''}</small></div><div><small>Frente al espejo</small><b>${more > 0 ? '+' : ''}${dec(more, 1)}★</b><small>el espejo da ${dec(p.mirror.stars, 0)}★</small></div><div><small>Plenos previstos</small><b>${dec(x.triples, 1)}</b><small>${p.done ? `contando ${p.done} ya hechos` : `de ${p.matrix.b.length} aldeas`}</small></div><div><small>Aldeas con rival</small><b>${num(x.covered ?? nb)} de ${num(nb)}</b><small>${plural(p.attacks ?? x.assign.length, 'ataque', 'ataques')} por usar</small></div></div>
    ${alt ? `${one.length ? `<div class="es-h">Primer ataque: cada uno contra su mejor rival</div><div class="es-atks">${esPlanCards(one)}</div>` : ''}${two.length ? `<div class="es-h">Segundo ataque: donde más ayuda a ganar</div><div class="es-atks">${esPlanCards(two)}</div>` : ''}`
      : `<div class="es-h">Ataques: uno por aldea</div><div class="es-atks">${esPlanCards(x.assign)}</div>`}` : ''}
    ${x.reserves.length ? `<div class="es-h">${alt ? 'Segundos ataques por repartir: se deciden cuando hayan hecho el primero' : 'Ataques en reserva: otra cuenta rinde más en cada aldea'}</div>${x.reserves.map(r => `<div class="es-res"><span><b>${r.pos}.</b> ${esB(r.name)} <small>TH${r.th}</small></span><small>${alt ? (r.uses ? (r.n > 1 ? `le quedan ${r.n} ataques por repartir` : 'su segundo ataque, por repartir') : 'ahora no tiene ninguna aldea que pueda mejorar') : r.uses ? `ataca ${r.uses} vez · le sobra ${r.n}` : r.n > 1 ? `en reserva (${r.n} ataques)` : 'en reserva'}</small></div>`).join('')}` : ''}
    ${x.uncovered.length ? `<div class="small text-secondary mt-2"><b>${alt ? 'Sin primer ataque (nadie libre tiene opciones; quedan para los segundos ataques)' : 'Sin rival (no compensa)'}:</b> ${x.uncovered.map(u => `aldea ${u.pos} (TH${u.th}${u.best ? `, ya ${u.best}★` : ''})`).join(', ')}.</div>` : ''}
    <details class="mt-3"><summary class="es-more">Ver el % de todos contra todos</summary><div class="mt-2">${esMatrix(p, alt)}</div></details></div></details>`; }).join('')}</div>`;
}
function esPlanWire() {
  $('clanView').querySelectorAll('[data-plan-pick]').forEach(b => { b.onclick = () => { const k = b.dataset.planPick; (S.planAlt ??= {})[k] = b.dataset.alt === '1'; S.planOpen = k; paint(); }; });
}
// ---------- mensajes para el chat del clan
const ES_CHAT_SIZE = 5;
function esChatBlocks(p) {
  const by = new Map();
  for (const a of (esPick(p) ? p.alt : p).assign) {     // con dos ataques, una línea por cuenta
    if (!by.has(a.a_tag)) by.set(a.a_tag, {a: a.a, a_pos: a.a_pos, hits: []});
    by.get(a.a_tag).hits.push(a);
  }
  const rows = [...by.values()].sort((a, b) => b.a_pos - a.a_pos), out = [];      // del jugador más bajo al más alto
  for (let i = 0; i < rows.length; i += ES_CHAT_SIZE) out.push(rows.slice(i, i + ES_CHAT_SIZE));
  return out;
}
const esChatHit = a => a.phase === 2 ? `2.º ataque al ${a.b_pos}` : `al ${a.b_pos}`;
const esChatText = (rows, lines) => rows.map(r => `@${r.a} -> ${r.hits.map(esChatHit).join(' y ')}`).join(lines ? '\n' : ' | ');
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
    <div class="btn-group mb-2" role="group" aria-label="Plan que se avisa"><button type="button" class="btn btn-sm ${S.chatAlt ? 'btn-ghost-secondary' : 'btn-primary'}" data-chat-plan="0"><i class="ti ti-trophy me-1"></i>Plan 1: ganar</button><button type="button" class="btn btn-sm ${S.chatAlt ? 'btn-primary' : 'btn-ghost-secondary'}" data-chat-plan="1"><i class="ti ti-users me-1"></i>Plan 2: todos atacan</button></div>
    <div class="d-flex flex-wrap align-items-center gap-2 mb-2"><span class="small text-secondary">${lines ? 'Una línea por jugador.' : 'Todo en una línea, separado por barras.'}</span><button class="btn btn-sm btn-ghost-secondary ms-auto" type="button" data-chat-mode>${lines ? 'Pasar a una sola línea' : 'Poner un jugador por línea'}</button></div>
    ${plans.map((p, i) => `<details class="es-plan" ${i === 0 ? 'open' : ''}><summary><span class="es-day-h"><b>${esTitle(p)} · ${esB(p.rival_name)}</b><small>${plural(new Set((esPick(p) ? p.alt : p).assign.map(a => a.a_tag)).size, 'aviso', 'avisos')}${esPick(p) ? ' · plan 2' : ' · plan 1'}${p.known ? '' : ' · alineación estimada'}</small></span><i class="ti ti-chevron-down es-chev"></i></summary>
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
  document.querySelectorAll('[data-chat-plan]').forEach(b => { b.onclick = () => { S.chatAlt = b.dataset.chatPlan === '1'; paint(); }; });
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
    <p><b>Plan de ataque.</b> Se calcula la probabilidad de 0, 1, 2 y 3 estrellas de cada cuenta contra cada aldea y se busca el reparto que más suma. Cada aldea recibe un solo ataque: repetir aldea no suma, porque solo cuenta la mejor nota. El % de cada pareja sale del modelo y del historial directo: en las últimas 10 defensas de la aldea, quién de TH igual o menor le hizo pleno y quién de TH igual o mayor no pudo; y en los últimos 10 ataques de la cuenta, a qué TH hizo pleno y contra cuáles falló. Un ataque sin opciones (menos de un 10 % de pleno y sin 2★ probables) no se planea, y una aldea difícil no se cubre a cualquier precio: si el ataque que haría falta rinde mucho más en otra, gana el reparto que más suma entero. En guerra normal entran los dos ataques de cada cuenta y, como hay el doble de ataques que aldeas, el cálculo elige los que más rinden: a veces ataca dos veces una cuenta de abajo antes que una de la parte media. Solo se sube a alguien por encima de su puesto si gana más que el error del modelo.</p>
    <p><b>Cada ataque cuenta por sí solo.</b> Un ataque empieza de cero: no hereda nada de lo que otro hiciera antes en esa aldea. Por eso solo se planea si esa cuenta, ella sola, puede mejorar lo que la aldea ya tiene: en una aldea sin atacar, al menos un 10 % de pleno o 2★ probables; en una ya atacada, al menos un 25 % de sacar más estrellas de las que hay. No se manda a nadie a una aldea que le queda grande para «rascar algo».</p>
    <p><b>Plan 1, mejores ataques para ganar.</b> Entran los dos ataques de cada cuenta y el cálculo decide quién ataca y a quién. Se calculan cuatro repartos (el de más estrellas, uno más atrevido, el de más plenos y uno que asegura 2★) y cada uno se juega ${num(600)} veces contra las estrellas con las que se espera que acabe el rival. Se queda el que más veces gana: yendo por detrás conviene arriesgar, y yendo por delante, asegurar. Si ninguno gana más de lo que explica el azar, se queda el de más estrellas. El empate a estrellas cuenta como media victoria, porque lo decide la destrucción. Cada subida de puesto debe ganar más que el error medio del modelo${k.calib != null ? ` (${dec(k.calib * 100, 1)} puntos)` : ''}.</p>
    <p><b>Plan 2, todos atacan.</b> El primer ataque de cada cuenta va contra su mejor rival: una aldea distinta para cada una, la combinación que más estrellas suma, y solo donde tiene opciones reales. Quien no tiene ninguna aldea propia a su alcance va a la que mejor se le da, aunque la comparta con otra cuenta. El segundo ataque se gestiona para ganar la guerra: el de quien ya hizo el primero se reparte con las mismas reglas del plan 1, y el de los demás, cuando hayan atacado. Arriba se compara con el plan 1 jugando los dos ${num(1500)} veces con la misma suerte.</p>
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
// mapa previsto: el plan que había antes del primer ataque, cada cuenta con sus ataques y cada aldea con lo que se esperaba de ella
function esPlanMap(mp) {
  const them = new Map(mp.them.map(x => [x.pos, x])), n = Math.max(mp.us.length, mp.them.length);
  const left = m => !m ? '<div class="es-map-c es-map-empty">–</div>' : `<div class="es-map-c"><div class="es-map-n"><b>${m.pos}.</b> <bdi>${esc(m.name)}</bdi><small>TH${m.th}</small></div>
    <div class="es-map-s">${m.plan.length ? plural(m.plan.length, 'ataque previsto', 'ataques previstos') : 'sin ataque previsto'}</div><div class="es-map-a">${m.plan.map(a => `<span class="es-chip es-chip-${a.p3 >= .85 ? 3 : a.p3 >= .5 ? 2 : 1}">→${a.to} · ${Math.round(a.p3 * 100)} %<small>${dec(a.e, 1)}★</small></span>`).join('')}</div></div>`;
  const right = m => !m ? '<div class="es-map-c es-map-empty">–</div>' : `<div class="es-map-c"><div class="es-map-n"><b>${m.pos}.</b> <bdi>${esc(m.name)}</bdi><small>TH${m.th}</small></div>
    <div class="es-map-s">${m.exp ? `se esperaban ${dec(m.exp.e, 1)}★ · ${Math.round(m.exp.p3 * 100)} % de pleno` : 'sin rival previsto'}</div>${m.exp ? `<div class="es-map-a"><span class="es-chip">la ataca el ${m.exp.by}</span></div>` : ''}</div>`;
  const rows = Array.from({length: n}, (_, i) => { const a = mp.us[i]; return `<div class="es-map-r">${left(a)}<i class="ti ti-arrow-right text-secondary"></i>${right(them.get(a?.pos ?? i + 1))}</div>`; }).join('');
  return `<div class="es-map"><div class="small text-secondary mb-1">Plan de ${mp.goal === 'triples' ? 'más plenos' : mp.goal === 'stars' ? 'más estrellas' : 'ganar la guerra'}: ${dec(mp.stars, 0)}★ y ${dec(mp.triples, 1)} plenos previstos.</div>${rows}</div>`;
}
function esPastMaps(x) {
  if (!x.map_plan && !x.map_end) return '';
  return `<details class="es-past-map mt-2"><summary class="es-more">Mapa de la guerra: previsto y final</summary>
    ${x.map_plan ? `<div class="es-h mt-2">Previsto antes del primer ataque</div>${esPlanMap(x.map_plan)}` : '<div class="small text-secondary mt-2">El mapa previsto empezó a guardarse después de esta guerra.</div>'}
    ${x.map_end ? `<div class="es-h mt-3">Mapa final</div>${esMap({map: x.map_end, us: x.us, them: x.them}).replace(' id="esMap"', '')}` : ''}</details>`;
}
function esPastRow(x, open) {
  const r = {win: 'Ganada', lose: 'Perdida', tie: 'Empatada'}[x.result], b = x.before, c = {win: 'bg-green-lt', lose: 'bg-red-lt', tie: 'bg-secondary-lt'}[x.result];
  return `<details class="es-plan" ${open ? 'open' : ''}><summary><span class="es-day-h"><b>${esPastTitle(x)} · ${esB(x.them.name)}</b><small><span class="badge ${c}">${r} ${x.us.stars}-${x.them.stars}</span> · se preveía ${esPct(b.win)} de ganar y ${dec(b.us, 0)}★${x.partial ? ' · datos parciales' : ''}</small></span><i class="ti ti-chevron-down es-chev"></i></summary>
    <div class="es-body"><div class="es-tiles"><div><small>Estrellas</small><b>${x.us.stars}</b><small>previstas ${dec(b.us, 1)} (${num(b.us_lo)}-${num(b.us_hi)})</small></div><div><small>Del rival</small><b>${x.them.stars}</b><small>previstas ${dec(b.them, 1)}</small></div><div><small>Plenos</small><b>${x.t.triples}</b><small>se esperaban ${dec(x.t.p3, 1)}</small></div><div><small>Ataques usados</small><b>${x.us.attacks}</b><small>de ${x.us.max}</small></div></div>
    ${x.rows.length ? `<div class="es-h">Cada ataque</div>${ES_HIT_HEAD}${x.rows.map(esHit).join('')}` : ''}${x.partial ? '<div class="small text-secondary mt-1">La guerra terminó entre dos recogidas: el marcador es el final, pero pueden faltar sus últimos ataques.</div>' : ''}${esPastMaps(x)}</div></details>`;
}
// la guerra que se está jugando, arriba del histórico: su mapa previsto ya existe; el final llega al terminar
function esPastLive(b) {
  if (!b?.map_plan) return '';
  const live = b.state === 'inWar', x = b.before;
  return `<details class="es-plan"><summary><span class="es-day-h"><b>${b.cwl ? esRound(b.round) : 'Guerra normal'} · ${esB(b.them.name)}</b><small><span class="badge ${live ? 'bg-green-lt' : 'bg-blue-lt'}">${live ? `En juego ${b.us.stars}-${b.them.stars}` : 'En preparación'}</span>${x ? ` · se prevé ${esPct(x.win)} de ganar y ${dec(x.us, 0)}★` : ''}</small></span><i class="ti ti-chevron-down es-chev"></i></summary>
    <div class="es-body"><details class="es-past-map"><summary class="es-more">Mapa de la guerra: previsto${live ? ' (el final, al terminar)' : ''}</summary>
      <div class="es-h mt-2">Previsto antes del primer ataque</div>${esPlanMap(b.map_plan)}
      <div class="small text-secondary mt-2">El mapa final saldrá aquí cuando acabe la guerra; mientras, el de ahora está en «Mapa de la guerra».</div></details></div></details>`;
}
function esPast(d) {
  const s = d.summary, list = d.past || [], name = d.past_kind === 'war' ? ['guerra', 'guerras'] : ['ronda', 'rondas'], now = esPastLive(d.battle);
  if (!list.length) return `<div class="card-body">${now ? `<div class="es-h">En curso</div>${now}` : ''}${empty(`Aún no ha terminado ninguna ${name[0]} desde que se guardan las previsiones`)}</div>`;
  return `<div class="card-body">${now ? `<div class="es-h">En curso</div>${now}` : ''}
    ${s ? `<div class="es-tiles"><div><small>Plenos</small><b>${num(s.triples)}</b><small>previstos ${dec(s.p3, 1)}</small></div><div><small>Estrellas en ataques</small><b>${num(s.stars)}</b><small>previstas ${dec(s.e, 1)}</small></div><div><small>Ganador acertado</small><b>${s.right} de ${s.called}</b><small>${name[1]} con favorito</small></div><div><small>Error por guerra</small><b>${dec(s.stars_err, 1)}★</b><small>total del clan</small></div></div>
    <details class="mt-1"><summary class="es-more">¿Se cumple lo que dice el %?</summary><table class="xd-t mt-1"><thead><tr><th>Decía</th><th>Pasó</th><th>Ataques</th></tr></thead><tbody>${s.bins.map(b => `<tr><td>${Math.round(b.says * 100)} %</td><td><b>${Math.round(b.real * 100)} %</b></td><td>${num(b.n)}</td></tr>`).join('')}</tbody></table>${s.n < 300 ? `<div class="small text-secondary mt-1">Con ${num(s.n)} ataques los tramos aún bailan mucho: será más fiable al ir sumando guerras.</div>` : ''}</details>
    <details class="mt-1"><summary class="es-more">Quién rinde por encima o por debajo de lo previsto</summary><table class="xd-t mt-1"><thead><tr><th>Cuenta</th><th>Plenos</th><th>Previstos</th><th>Estrellas</th></tr></thead><tbody>${s.players.map(p => `<tr><td>${esc(p.name)}<small>${plural(p.n, 'ataque', 'ataques')}</small></td><td>${p.triples}</td><td>${dec(p.p3, 1)}</td><td><b class="${p.gap > 0 ? 'text-green' : p.gap < 0 ? 'text-red' : ''}">${esSigned(p.gap, 1)}</b></td></tr>`).join('')}</tbody></table></details>` : ''}
    <div class="es-h">${name[1][0].toUpperCase() + name[1].slice(1)} jugadas</div>${list.map((x, i) => esPastRow(x, i === 0)).join('')}
    ${s && s.wars > list.length ? `<div class="small text-secondary mt-1">Se enseñan las ${list.length} últimas de ${s.wars}.</div>` : ''}</div>`;
}
// Mientras se juega, el marcador y el % se piden al minuto. Lo demás no se repinta: no hay que perder lo que se está leyendo.
function esLiveStart(d) {
  if (S.liveFor === d) return;          // repintar los mismos datos no vuelve a preguntar
  S.liveFor = d; clearTimeout(S.liveTimer); S.livePlanShown = !!d.battle?.map_plan;
  const gen = S.liveGen = (S.liveGen || 0) + 1, on = () => gen === S.liveGen && S.sub === 'escenarios' && S.data === d;
  if (!d.battle) return;
  let attacks = d.battle.us.attacks + d.battle.them.attacks;
  const tick = () => { if (!on()) return;
    if (document.hidden) { S.liveTimer = setTimeout(tick, 15000); return; }
    api('api/vivo').then(j => { if (!on() || !j.battle) return;
      const b = {...j.battle, fresh: true}, now = b.us.attacks + b.them.attacks, moved = now !== attacks; attacks = now; d.battle = b;
      const box = document.getElementById('esBattle'); if (box) { const t = document.createElement('div'); t.innerHTML = esBattle(b); box.replaceWith(t.querySelector('#esBattle')); esHitsWire(); }
      if (b.map_plan && !S.livePlanShown) { S.livePlanShown = true; const sb = document.querySelector('[data-sec=eprev] .sec-body'); if (sb) sb.innerHTML = esPast(d); }     // el previsto de la guerra en juego, aunque la última recogida aún no lo traiga
      for (const id of ['esMap', 'esMapM']) { const el = document.getElementById(id); if (el && b.map) { const t = document.createElement('div'); t.innerHTML = esMap(b).replace('id="esMap"', `id="${id}"`); el.replaceWith(t.firstElementChild); } }
      if (b.plan) { const v = d.mode === 'liga' ? d.liga : null, list = v ? v.plans : d.plans, at = list?.findIndex(p => p.round === b.plan.round && p.rival === b.plan.rival);
        if (at >= 0) { list[at] = {...list[at], ...b.plan, title: list[at].title}; if (moved) esPlanRefresh(d); } }
    }).catch(() => {}).finally(() => { if (on() && d.battle.state === 'inWar') S.liveTimer = setTimeout(tick, 60000); }); };
  tick();
}
function esHitsWire() { document.querySelector('[data-hits]')?.addEventListener('toggle', e => { S.hitsOpen = e.target.open; }); }
function esPlanRefresh(d) {
  const v = d.mode === 'liga' ? d.liga : {plans: d.plans, ts: d.battle?.ts};
  const set = (id, html) => { const b = document.querySelector(`[data-sec=${id}] .sec-body`); if (b) b.innerHTML = html; };
  set('eplan', esPlans(v)); set('etrain', esPlans(v, true)); set('echat', esChat(v)); esChatWire(v); esPlanWire();
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
    <p><b>Dos ataques.</b> Cada cuenta cuenta una vez por ataque que le quede y nunca repite aldea. Como hay el doble de ataques que aldeas, los que no entran en el plan no se usan: cada aldea recibe un solo ataque.</p>
    <p><b>Previsto y real.</b> La previsión se hace solo con lo terminado antes de empezar la guerra y se guarda sin retocarla. El % de ganar en directo parte del marcador real y simula los ataques que faltan, según la asistencia de cada cuenta en guerras normales.</p>
    <p class="mb-0"><b>Con pocos datos.</b> Si ClashKing no tiene historial de un jugador, el modelo parte de lo que suele pasar con esa diferencia de ayuntamiento, y afina según se juegan guerras.</p></div>`;
}
// ---------- mapa de la guerra: cada cuenta frente a su espejo
function esMapSide(m, per, got) {
  if (!m) return '<div class="es-map-c es-map-empty">–</div>';
  const chips = m.atk.map(a => `<span class="es-chip es-chip-${a.stars}" title="${a.to ? `A la aldea ${a.to}` : ''}">${a.stars}★ ${a.pct} %${a.to ? `<small>→${a.to}</small>` : ''}</span>`).join('') + '<span class="es-chip es-chip-x" title="Ataque por hacer">–</span>'.repeat(m.left);
  const n = got ?? m.got ?? 0, stars = `<div class="es-map-d" title="${m.got == null ? 'Aún no la han atacado' : `El rival le ha hecho ${n}★`}">${'<i class="on">★</i>'.repeat(n)}${'<i>☆</i>'.repeat(3 - n)}</div>`;
  return `<div class="es-map-c"><div class="es-map-n"><b>${m.pos}.</b> <bdi>${esc(m.name)}</bdi><small>TH${m.th}</small></div>${stars}
    <div class="es-map-s">ha hecho ${m.stars}★ · ${m.left ? `${plural(m.left, 'ataque restante', 'ataques restantes')}` : 'sin ataques'}</div><div class="es-map-a">${chips}</div></div>`;
}
function esMap(b) {
  const m = b.map;
  if (!m) return '';
  const them = new Map(m.them.map(x => [x.pos, x])), n = Math.max(m.us.length, m.them.length);
  // las estrellas que tiene cada aldea salen de los ataques del otro lado: la mejor nota que le han hecho (como en el juego)
  const best = side => { const o = {}; for (const x of side) for (const a of x.atk) if (a.to != null) o[a.to] = Math.max(o[a.to] ?? 0, a.stars); return o; };
  const gotUs = best(m.them), gotThem = best(m.us);
  const rows = Array.from({length: n}, (_, i) => { const a = m.us[i], b = them.get(a?.pos ?? i + 1);
    return `<div class="es-map-r">${esMapSide(a, m.per, a && gotUs[a.pos])}<i class="ti ti-arrows-horizontal text-secondary"></i>${esMapSide(b, m.per, b && gotThem[b.pos])}</div>`; }).join('');
  const side = (s, right) => `<div class="es-bat-s ${right ? 'r' : ''}"><b><bdi>${esc(s.name)}</bdi></b><small>${s.attacks} de ${s.max} ataques · ${dec(s.pct, 1)} %</small></div>`;
  return `<div id="esMap" class="card-body es-map"><div class="es-bat-score es-map-score">${side(b.us)}<div class="es-bat-n">${b.us.stars}<span>–</span>${b.them.stars}</div>${side(b.them, true)}</div>${rows}</div>`;
}
// en escritorio, el mapa va a la derecha y se queda a la vista; en el móvil, como una sección más tras la batalla
function esWithMap(b, main) {
  if (!b?.map) return main;
  return `<div class="row g-3"><div class="col-12 col-xl-8">${main}</div><div class="col-xl-4 d-none d-xl-block"><div class="es-map-side">${sec('emap', 'Mapa de la guerra', '', esMap(b), true)}</div></div></div>`;
}
const esMapMobile = b => b?.map ? `<div class="d-xl-none">${sec('emapm', 'Mapa de la guerra', '', esMap(b).replace('id="esMap"', 'id="esMapM"'), false)}</div>` : '';
function renderGuerra(d, notice) {
  const b = d.battle, v = {plans: d.plans = b.plan ? [b.plan] : [], ts: b.ts}, open = !!b.plan;
  $('clanView').innerHTML = `${notice}${esWithMap(b, `
    ${sec('ebat', 'Batalla en juego', '', esBattle(b), true)}
    ${esMapMobile(b)}
    ${open ? sec('eplan', 'Plan 1 · Mejores ataques para ganar', '', esPlans(v), true) : ''}
    ${open ? sec('etrain', 'Plan 2 · Todos atacan', '', esPlans(v, true), true) : ''}
    ${open ? sec('echat', 'Mensajes para el chat', '', esChat(v), true) : ''}
    ${sec('eprev', 'Previsto y real', '', esPast(d), true)}
    ${sec('ecalc', 'Cómo se calcula', '', esCalcWar(d), false)}`)}`;
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
  $('clanView').innerHTML = `${notice}${notice_}${esHero(v)}${esWithMap(d.battle, `
    ${d.battle ? sec('ebat', 'Batalla en juego', '', esBattle(d.battle), true) : ''}
    ${esMapMobile(d.battle)}
    ${sec('epos', 'Dónde podemos acabar', '', `<div class="card-body">${esPositions(v)}</div>`, true)}
    ${v.state !== 'ended' ? sec('eplan', 'Plan 1 · Mejores ataques para ganar', '', esPlans(v), true) : ''}
    ${v.state !== 'ended' ? sec('etrain', 'Plan 2 · Todos atacan', '', esPlans(v, true), true) : ''}
    ${v.state !== 'ended' ? sec('echat', 'Mensajes para el chat', '', esChat(v), true) : ''}
    ${sec('eprev', 'Previsto y real', '', esPast(d), true)}
    ${sec('etab', 'Clasificación y previsión', '', esTable(v), true)}
    ${sec('elog', 'Resumen diario', '', esLog(v), true)}
    ${v.state !== 'ended' ? sec('egam', 'Guerras que quedan', '', esGames(v), true) : ''}
    ${v.state !== 'ended' ? sec('eban', 'Alineación y banquillo', '', esBench(d, v), true) : ''}
    ${v.state !== 'ended' ? sec('ewhat', 'Simulador: ¿y si…?', '', esWhat(v), true) : ''}
    ${sec('eniv', 'Nivel de cada clan', '', esLevels(v), true)}
    ${sec('ecalc', 'Cómo se calcula', '', esCalc(v), false)}`)}`;
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
