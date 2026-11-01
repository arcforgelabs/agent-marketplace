/* ExDraw: parts for hand-drawn figures (references/creative.md). Load after kit/charts.js and before kit/explainer.js.
   Every helper returns vector-graphic markup as a string; ExDraw.svg puts the string into an element.
   Tokens only: every colour comes from an .ex- class in kit/explainer.css.
   Tones: '' (plain), 'key' (the one red thing), 'alt' (second family), 'off' (dashed: planned or unknown).
   Clickable groups carry data-ex and the class ex-hit, so the runtime opens their pop-up. */
(function () {
  'use strict';
  var REDUCE = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  function esc(s) { return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }
  function n(v) { return Math.round(v * 10) / 10; }

  /* Line icons on a 24 by 24 grid. Add a page icon with ExDraw.icons.name = '<path d="…"/>'. */
  var IC = {
    key: '<circle cx="7" cy="12" r="4"/><path d="M11 12h10M17 12v4M20 12v3"/>',
    hardkey: '<rect x="7" y="2" width="10" height="15" rx="2.5"/><circle cx="12" cy="8" r="2.2"/><path d="M9.5 17v5h5v-5"/>',
    person: '<circle cx="12" cy="7" r="3.5"/><path d="M5 21c0-4 3-7 7-7s7 3 7 7"/>',
    people: '<circle cx="9" cy="8" r="3"/><path d="M3 20c0-3.5 2.5-6 6-6s6 2.5 6 6"/><circle cx="17" cy="9" r="2.5"/><path d="M16 14c3 0 5 2 5 5"/>',
    agent: '<rect x="5" y="8" width="14" height="11" rx="3"/><circle cx="9.5" cy="13.5" r="1.2"/><circle cx="14.5" cy="13.5" r="1.2"/><path d="M12 8V5"/><circle cx="12" cy="4" r="1"/>',
    server: '<rect x="4" y="4" width="16" height="7" rx="2"/><rect x="4" y="13" width="16" height="7" rx="2"/><path d="M8 7.5h.01M8 16.5h.01"/>',
    database: '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>',
    lock: '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
    unlock: '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 7.5-2"/>',
    vault: '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="12" cy="12" r="5"/><path d="M12 7v2M12 15v2M7 12h2M15 12h2"/>',
    shield: '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/>',
    file: '<path d="M6 3h9l4 4v14H6zM15 3v4h4M9 12h6M9 16h6"/>',
    cloud: '<path d="M7 18h10a4 4 0 0 0 0-8 6 6 0 0 0-11.5 1.5A3.5 3.5 0 0 0 7 18z"/>',
    phone: '<rect x="7" y="2" width="10" height="20" rx="2"/><path d="M11 18h2"/>',
    laptop: '<rect x="4" y="5" width="16" height="11" rx="1.5"/><path d="M2 19h20"/>',
    terminal: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 9l3 3-3 3M12 15h5"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    door: '<rect x="6" y="3" width="12" height="18" rx="1"/><path d="M15 12h.01"/>',
    bolt: '<path d="M13 2 4 14h7l-1 8 9-12h-7z"/>',
    eye: '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    no: '<circle cx="12" cy="12" r="9"/><path d="M6 18 18 6"/>',
    check: '<circle cx="12" cy="12" r="9"/><path d="M8 12.5l2.5 2.5L16 9.5"/>',
    warn: '<path d="M12 3 22 20H2z"/><path d="M12 10v4M12 17h.01"/>',
    globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3.5 3 14.5 0 18M12 3c-3 3.5-3 14.5 0 18"/>',
    coin: '<circle cx="12" cy="12" r="9"/><path d="M15 9c-.5-1-1.6-1.5-3-1.5-1.8 0-3 .9-3 2.2 0 3 6 1.6 6 4.6 0 1.3-1.2 2.2-3 2.2-1.4 0-2.6-.6-3-1.6M12 6v1.5M12 16.5V18"/>',
    gauge: '<path d="M3 16a9 9 0 0 1 18 0"/><path d="M12 16l4-5"/><circle cx="12" cy="16" r="1.2"/>',
    spark: '<path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M6 18l2.5-2.5M15.5 8.5 18 6"/>',
    gear: '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1 7 17M17 7l2.1-2.1"/>',
    mail: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/>',
    chat: '<path d="M4 5h16v11H9l-5 4z"/>',
    box: '<path d="M3 7l9-4 9 4v10l-9 4-9-4z"/><path d="M3 7l9 4 9-4M12 11v10"/>',
    branch: '<circle cx="6" cy="5" r="2"/><circle cx="6" cy="19" r="2"/><circle cx="18" cy="8" r="2"/><path d="M6 7v10M18 10c0 4-6 3-12 7"/>'
  };

  function t(x, y, txt, cls, anchor) {
    return '<text class="' + (cls || 'ex-t') + '" x="' + n(x) + '" y="' + n(y) + '"' + (anchor ? ' text-anchor="' + anchor + '"' : '') + '>' + esc(txt) + '</text>';
  }
  function icon(name, x, y, size, tone) {
    var s = (size || 24) / 24;
    if (!IC[name]) throw new Error('ExDraw: no icon "' + name + '"');
    return '<g class="ex-ic' + (tone ? ' ex-ic--' + tone : '') + '" transform="translate(' + n(x) + ' ' + n(y) + ') scale(' + n(s * 100) / 100 + ')">' + IC[name] + '</g>';
  }
  /* A clickable group: the runtime opens EX[ex] on a click. */
  function hit(ex, inner) { return ex ? '<g class="ex-hit" data-ex="' + esc(ex) + '">' + inner + '</g>' : '<g>' + inner + '</g>'; }
  /* An icon on a disc, with a title and a sub line under it. */
  function badge(x, y, o) {
    var r = o.r || 34, tone = o.tone || '';
    return hit(o.ex, '<circle class="ex-disc' + (tone ? ' ex-disc--' + tone : '') + '" cx="' + n(x) + '" cy="' + n(y) + '" r="' + r + '"/>' +
      icon(o.icon, x - r * 0.53, y - r * 0.53, r * 1.06, tone === 'off' ? '' : tone) +
      (o.title ? t(x, y + r + 22, o.title, 'ex-t', 'middle') : '') + (o.sub ? t(x, y + r + 40, o.sub, 'ex-ts', 'middle') : ''));
  }
  /* A real product or company logo on a light plate, so dark logos read in dark mode too. src: a data URI or a file. */
  function logo(x, y, o) {
    var r = o.r || 34, s = r * 1.3, tone = o.tone || '';
    return hit(o.ex, '<circle class="ex-plate' + (tone ? ' ex-plate--' + tone : '') + '" cx="' + n(x) + '" cy="' + n(y) + '" r="' + r + '"/>' +
      '<image href="' + esc(o.src) + '" x="' + n(x - s / 2) + '" y="' + n(y - s / 2) + '" width="' + n(s) + '" height="' + n(s) + '" preserveAspectRatio="xMidYMid meet"/>' +
      (o.title ? t(x, y + r + 22, o.title, 'ex-t', 'middle') : '') + (o.sub ? t(x, y + r + 40, o.sub, 'ex-ts', 'middle') : ''));
  }
  /* A path with an arrow head. Give it an id when dots will run along it. */
  function arrow(d, o) {
    o = o || {};
    var tone = o.tone || '', cls = 'ex-line' + (tone === 'key' ? ' ex-line--key' : '') + (tone === 'off' || o.dashed ? ' ex-line--off' : '');
    return '<path' + (o.id ? ' id="' + esc(o.id) + '"' : '') + ' class="' + cls + '" d="' + d + '"' + (o.head === false ? '' : ' marker-end="url(#' + (tone === 'key' ? 'exk' : 'exh') + '-{M})"') + '/>';
  }
  /* Dots that run along a path: flow, traffic or an attack in motion. None when the reader asks for reduced motion. */
  function dots(pathId, count, dur, tone) {
    if (REDUCE) return '';
    var o = '', c = count || 3, d = dur || 3;
    for (var i = 0; i < c; i++) o += '<circle class="ex-dot' + (tone ? ' ex-dot--' + tone : '') + '" r="4"><animateMotion dur="' + d + 's" begin="-' + (i * d / c).toFixed(2) + 's" repeatCount="indefinite"><mpath href="#' + esc(pathId) + '"/></animateMotion></circle>';
    return o;
  }
  /* A rubber stamp: HYPOTHETICAL, ANALOGY, PROPOSAL, NOT APPROVED, SYNTHETIC. */
  function stamp(x, y, txt) {
    return '<g class="ex-stamp" transform="rotate(-4 ' + n(x) + ' ' + n(y) + ')"><rect x="' + n(x - 6) + '" y="' + n(y - 16) + '" width="' + n(String(txt).length * 9.8 + 14) + '" height="24" rx="3"/>' + t(x, y, txt, 'ex-stamp-t') + '</g>';
  }
  /* A thin leader line from a part to its label. */
  function lead(x1, y1, x2, y2) { return '<path class="ex-lead" d="M' + n(x1) + ' ' + n(y1) + 'L' + n(x2) + ' ' + n(y2) + '"/>'; }
  /* Blast radius: rings spread out from the point of impact. ring: {r, ex, title, sub, hit}. hit = reached (solid red); else dashed. */
  function rings(cx, cy, list, core) {
    var b = '', sorted = list.slice().sort(function (a, z) { return z.r - a.r; });
    sorted.forEach(function (g, i) {
      var a = -0.8 + i * 0.32, lx = cx + g.r * Math.cos(a), ly = cy + g.r * Math.sin(a), tx = cx + sorted[0].r + 40;
      var ty = cy - sorted[0].r + 20 + i * 54;
      b += hit(g.ex, '<circle class="ex-ring' + (g.hit ? ' ex-ring--hit' : ' ex-ring--safe') + '" cx="' + n(cx) + '" cy="' + n(cy) + '" r="' + g.r + '"/>' +
        lead(lx, ly, tx - 8, ty - 4) + t(tx, ty, g.title, 'ex-t') + (g.sub ? t(tx, ty + 18, g.sub, g.hit ? 'ex-ta' : 'ex-ts') : ''));
    });
    if (core) b += hit(core.ex, '<circle class="ex-core" cx="' + n(cx) + '" cy="' + n(cy) + '" r="' + (core.r || 40) + '"/>' + (core.icon ? icon(core.icon, cx - 14, cy - 24, 28, 'key') : '') + t(cx, cy + 18, core.title || '', 'ex-ta', 'middle'));
    return b;
  }
  /* Put the markup into el as one vector graphic. minW: the width below which the figure scrolls sideways inside its card. */
  function svg(el, w, h, body, label, minW) {
    el.classList.add('ex-figure');
    var id = el.id || ('exd' + Math.random().toString(36).slice(2, 8));
    el.innerHTML = '<svg viewBox="0 0 ' + w + ' ' + h + '" role="img" aria-label="' + esc(label) + '" style="display:block;width:100%;min-width:' + (minW || 0) + 'px;height:auto">' +
      '<defs><marker id="exh-' + id + '" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path class="ex-head-fill" d="M0 0L10 5L0 10z"/></marker>' +
      '<marker id="exk-' + id + '" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path class="ex-head-fill--key" d="M0 0L10 5L0 10z"/></marker></defs>' +
      body.replace(/\{M\}/g, id) + '</svg>';
    if (minW) el.style.overflowX = 'auto';
    document.dispatchEvent(new CustomEvent('ex:drawn'));
    return el;
  }

  window.ExDraw = { icons: IC, t: t, icon: icon, hit: hit, badge: badge, logo: logo, arrow: arrow, dots: dots, stamp: stamp, lead: lead, rings: rings, svg: svg, esc: esc };
})();
