/* Explainer charts (references/charts.md). Data-driven vector graphics for the top-rated Chart Lab kinds.
   Each renderer draws into an element (usually a .ex-figure), puts an .ex-hot rect with data-ex
   over every part, and adds inline items to window.EX. Load this file and call the renderers
   BEFORE explainer.js, so the runtime finds every [data-ex].
   Item field `ex`: a key into window.EX, or an object {t, l, d, x} that is added under an auto key.
   Layers: "" (plain), "key" (red, the one thing to see first), "alt" (steel), "off" (dashed, optional).
   Colours, fonts and radii come from the token contract (kit/tokens.css) through classes and var(); no literal colours.
   Every chart is kept with its data. ExCharts.redraw() draws them all again (explainer.js calls it on a theme change),
   with the same auto keys, so a pop-up or a Facts list still finds its part. */
(function () {
  var drawn = [], depth = 0, ctx = { p: 'c', n: 0 };
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function key(ex, hint) {
    if (!ex) return '';
    if (typeof ex === 'string') return ex;
    var k = 'auto.' + ctx.p + '.' + (hint || 'item') + '.' + (++ctx.n);
    (window.EX = window.EX || {})[k] = ex; return k;
  }
  function mod(base, layer) { return base + (layer ? ' ' + base + '--' + layer : ''); }
  // Corner radius from the token contract: a class sets the rx property; the attribute is the fallback when styles do not apply.
  function rc(rx) { return rx >= 14 ? 'ex-r-lg' : rx >= 10 ? 'ex-r-md' : 'ex-r-sm'; }
  function hot(k, x, y, w, h, rx) {
    rx = rx == null ? 10 : rx;
    return k ? '<rect class="ex-hot ' + rc(rx) + '" data-ex="' + esc(k) + '" x="' + x + '" y="' + y + '" width="' + w + '" height="' + h + '" rx="' + rx + '"/>' : '';
  }
  function svg(el, w, h, label, body, hots, minW) {
    var id = 'exc-' + ctx.p;
    var defs = '<defs>' +
      '<marker id="' + id + 'h" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path class="ex-head-fill" d="M0 0 L10 5 L0 10 z"/></marker>' +
      '<marker id="' + id + 'k" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path class="ex-head-fill ex-head-fill--key" d="M0 0 L10 5 L0 10 z"/></marker></defs>';
    el.innerHTML = '<svg viewBox="0 0 ' + w + ' ' + h + '" role="img" aria-label="' + esc(label || '') + '"' +
      ' style="max-width:' + w + 'px;min-width:' + Math.min(minW || w, w) + 'px">' + defs + body.replace(/\{M\}/g, id).replace(/(<rect class="[^"]*)("[^>]*? rx="(\d+)")/g, function (m, a, b, rx) { return a + ' ' + rc(+rx) + b; }) + '<g>' + hots + '</g></svg>';
    return el.firstChild;
  }
  // A data chart opens in a pop-up window, not on the full-window canvas (kit/canvas.js).
  function pop(s) { s.setAttribute('data-view', 'pop'); return s; }
  function boxText(x, y, w, h, title, sub) {
    var cy = y + h / 2;
    return sub
      ? '<text class="ex-t" x="' + (x + 14) + '" y="' + (cy - 3) + '">' + esc(title) + '</text><text class="ex-ts" x="' + (x + 14) + '" y="' + (cy + 15) + '">' + esc(sub) + '</text>'
      : '<text class="ex-t" x="' + (x + 14) + '" y="' + (cy + 5) + '">' + esc(title) + '</text>';
  }

  /* Connection diagram: parts as boxes in columns, joined by labelled arrows. A structure view.
     {cols: ["Reader", "Page"], nodes: [{id, col, row, title, sub, layer, ex}],
      edges: [{from, to, label, layer, ex}], boxW, boxH, gapX, gapY} */
  function connection(el, o) {
    // Allocate identities in the same edge-then-node order in both layouts.
    var edgeKeys = (o.edges || []).map(function(e){return key(e.ex, "edge");});
    var nodeKeys = o.nodes.map(function(n){return key(n.ex, n.id);});
    // In a narrow container use real wrapping flow nodes, not a scaled 760px drawing.
    if (el.clientWidth && el.clientWidth < 700) {
      var flow = document.createElement('div'); flow.className = 'ex-flow ex-connection-narrow';
      flow.setAttribute('aria-label', o.label || 'Connections');
      o.nodes.forEach(function (n, index) {
        var node = document.createElement('button'); node.type = 'button'; node.className = mod('ex-node', n.layer);
        var k = nodeKeys[index]; if (k) node.dataset.ex = k;
        node.textContent = n.title + (n.sub ? ' — ' + n.sub : ''); flow.appendChild(node);
        (o.edges || []).filter(function (e) {return e.from === n.id;}).forEach(function (e) {
          var target = o.nodes.find(function (item) {return item.id === e.to;});
          if (!target) throw new Error('connection: unknown node ' + e.to);
          var link = document.createElement(e.ex ? 'button' : 'p');
          if (e.ex) {link.type = 'button'; link.dataset.ex = edgeKeys[o.edges.indexOf(e)];}
          link.className = 'ex-connection-link'; link.textContent = (e.label || 'Connects') + ' → ' + target.title; flow.appendChild(link);
        });
      });
      el.replaceChildren(flow); return flow;
    }
    var bw = o.boxW || 200, bh = o.boxH || 62, gx = o.gapX || 120, gy = o.gapY || 34, top = o.cols ? 44 : 16, pad = 20;
    var byId = {}, maxCol = 0, maxRow = 0, body = '', hots = '';
    o.nodes.forEach(function (n) { n.x = pad + n.col * (bw + gx); n.y = top + n.row * (bh + gy); byId[n.id] = n; maxCol = Math.max(maxCol, n.col); maxRow = Math.max(maxRow, n.row); });
    var W = pad * 2 + (maxCol + 1) * bw + maxCol * gx, H = top + (maxRow + 1) * bh + maxRow * gy + 20;
    (o.cols || []).forEach(function (c, i) { body += '<text class="ex-tm" x="' + (pad + i * (bw + gx)) + '" y="24">' + esc(c) + '</text>'; });
    (o.edges || []).forEach(function (e, index) {
      var a = byId[e.from], b = byId[e.to], d, lx, ly;
      if (!a || !b) throw new Error('connection: unknown node in edge ' + e.from + ' → ' + e.to);
      if (a.col === b.col) {
        var down = b.row > a.row, x = a.x + bw / 2, y1 = down ? a.y + bh : a.y, y2 = down ? b.y : b.y + bh;
        d = 'M' + x + ' ' + y1 + ' V' + y2; lx = x + 8; ly = (y1 + y2) / 2 + 4;
      } else {
        var right = b.col > a.col, x1 = right ? a.x + bw : a.x, x2 = right ? b.x : b.x + bw;
        var ya = a.y + bh / 2 + (e.offset || 0), yb = b.y + bh / 2 + (e.offset || 0), mx = (x1 + x2) / 2;
        d = ya === yb ? 'M' + x1 + ' ' + ya + ' H' + x2 : 'M' + x1 + ' ' + ya + ' H' + mx + ' V' + yb + ' H' + x2;
        lx = Math.min(x1, x2) + 8; ly = ya - 8;
      }
      body += '<path class="' + mod('ex-line', e.layer === 'key' ? 'key' : e.layer === 'off' ? 'off' : '') + '" d="' + d + '" marker-end="url(#{M}' + (e.layer === 'key' ? 'k' : 'h') + ')"/>';
      if (e.label) {
        body += '<text class="' + (e.ex ? 'ex-ta' : 'ex-tl') + '" x="' + lx + '" y="' + ly + '">' + esc(e.label) + '</text>';
        if (e.ex) hots += hot(edgeKeys[index], lx - 4, ly - 13, e.label.length * 7 + 8, 18, 4);
      }
    });
    o.nodes.forEach(function (n, index) {
      body += '<rect class="' + mod('ex-box', n.layer) + (n.layer === 'off' ? '' : '') + '" x="' + n.x + '" y="' + n.y + '" width="' + bw + '" height="' + bh + '" rx="10"/>' + boxText(n.x, n.y, bw, bh, n.title, n.sub);
      hots += hot(nodeKeys[index], n.x, n.y, bw, bh);
    });
    return svg(el, W, H, o.label, body, hots, o.minWidth || 760);
  }

  /* Container diagram: zones that hold parts. Rated great.
     {zones: [{title, layer, ex, items: [{title, sub, layer, ex}]}], perRow: 2, zoneCols: 2} */
  function container(el, o) {
    var per = o.perRow || 2, zc = o.zoneCols || Math.min(o.zones.length, 3), iw = o.itemW || 170, ih = o.itemH || 54, g = 12, pad = 20, zh0 = 40;
    var zw = per * iw + (per - 1) * g + 2 * 16, body = '', hots = '', rowsH = [];
    o.zones.forEach(function (z, i) { var r = Math.floor(i / zc), h = zh0 + Math.ceil(z.items.length / per) * (ih + g) + 4; rowsH[r] = Math.max(rowsH[r] || 0, h); });
    var W = pad * 2 + zc * zw + (zc - 1) * 24, H = pad * 2 + rowsH.reduce(function (s, h) { return s + h; }, 0) + (rowsH.length - 1) * 24;
    o.zones.forEach(function (z, i) {
      var r = Math.floor(i / zc), c = i % zc, zx = pad + c * (zw + 24), zy = pad;
      for (var k = 0; k < r; k++) zy += rowsH[k] + 24;
      var zcls = z.layer ? mod('ex-box', z.layer) : 'ex-zone';
      body += '<rect class="' + zcls + '" x="' + zx + '" y="' + zy + '" width="' + zw + '" height="' + rowsH[r] + '" rx="14"/><text class="ex-tm" x="' + (zx + 16) + '" y="' + (zy + 26) + '">' + esc(z.title) + '</text>';
      hots += hot(key(z.ex, 'zone'), zx, zy, zw, 34, 14);
      z.items.forEach(function (it, j) {
        var x = zx + 16 + (j % per) * (iw + g), y = zy + zh0 + Math.floor(j / per) * (ih + g);
        body += '<rect class="' + mod('ex-box', it.layer) + '" x="' + x + '" y="' + y + '" width="' + iw + '" height="' + ih + '" rx="10"/>' + boxText(x, y, iw, ih, it.title, it.sub);
        hots += hot(key(it.ex, 'part'), x, y, iw, ih);
      });
    });
    return svg(el, W, H, o.label, body, hots, o.minWidth || 760);
  }

  /* Capacity bars: one limit split into named parts, one bar per step. Rated good.
     {limit: 200, unit: "k", rows: [{label, parts: [{label, value, layer, ex}]}]} */
  function capacity(el, o) {
    var lw = o.labelW || 150, bw = o.barW || 560, bh = 30, gy = 30, pad = 20, top = 34, body = '', hots = '';
    var W = pad * 2 + lw + bw + 60, H = top + o.rows.length * (bh + gy) + 10, u = o.unit || '';
    body += '<text class="ex-tm" x="' + (pad + lw) + '" y="20">0</text><text class="ex-tm" x="' + (pad + lw + bw) + '" y="20" text-anchor="end">' + esc(o.limit + u) + ' limit</text>';
    o.rows.forEach(function (r, i) {
      var y = top + i * (bh + gy), x = pad + lw, used = 0;
      body += '<text class="ex-t" x="' + pad + '" y="' + (y + 20) + '">' + esc(r.label) + '</text>';
      body += '<rect class="ex-box ex-box--off" x="' + x + '" y="' + y + '" width="' + bw + '" height="' + bh + '" rx="6"/>';
      r.parts.forEach(function (p) {
        var w = bw * p.value / o.limit;
        body += '<rect class="' + mod('ex-box', p.layer) + '" x="' + x + '" y="' + y + '" width="' + w + '" height="' + bh + '" rx="6"/>';
        if (w > 60) body += '<text class="ex-ts" x="' + (x + 8) + '" y="' + (y + 19) + '">' + esc(p.label) + '</text>';
        hots += hot(key(p.ex || { t: p.label, l: r.label, d: p.label + ' is one part of ' + r.label + '.', x: ['It uses ' + p.value + u + ' of ' + o.limit + u + '.', 'That is ' + Math.round(100 * p.value / o.limit) + '% of the limit.'] }, 'part'), x, y, w, bh, 6);
        x += w; used += p.value;
      });
      body += '<text class="' + (used > o.limit ? 'ex-ta' : 'ex-tl') + '" x="' + (pad + lw + bw + 8) + '" y="' + (y + 20) + '">' + Math.round(100 * used / o.limit) + '%</text>';
    });
    return pop(svg(el, W, H, o.label, body, hots, o.minWidth || 760));
  }

  /* Heatmap: a value for each row and column pair. Rated great.
     {rows: [..], cols: [..], values: [[..]], fmt: v => text, cellEx: (row, col, v) => {t,l,d,x}} */
  /* Column headers for fixed-width columns. headers: 'auto' (default), 'flat', 'wrap' or 'angle'.
     auto: flat when every title fits its column, two wrapped lines when that fits, else angled.
     Angled titles rise left to right at 40 degrees from the column centre, with a short guide line,
     the usual form for a matrix with fixed columns. Returns {svg, top, right}: header height and the
     extra width the last angled title needs. Widths are estimated for .ex-tm (11px mono, uppercase). */
  function colHeads(cols, x0, cw, mode) {
    var cpx = 7.7, room = cw - 10, out = '', top = 40, right = 0, A = 40 * Math.PI / 180;
    function fits(s) { return String(s).length * cpx <= room; }
    function wrap(s) {
      var lines = [''];
      String(s).split(' ').forEach(function (w) { var cur = lines[lines.length - 1], next = cur ? cur + ' ' + w : w; if (!cur || fits(next)) lines[lines.length - 1] = next; else lines.push(w); });
      return lines;
    }
    mode = mode || 'auto';
    if (mode === 'auto') mode = cols.every(fits) ? 'flat' : cols.every(function (c) { var l = wrap(c); return l.length <= 2 && l.every(fits); }) ? 'wrap' : 'angle';
    if (mode === 'flat') {
      cols.forEach(function (c, j) { out += '<text class="ex-tm" x="' + (x0 + j * cw + cw / 2) + '" y="26" text-anchor="middle">' + esc(c) + '</text>'; });
    } else if (mode === 'wrap') {
      top = 56;
      cols.forEach(function (c, j) {
        var l = wrap(c), cx = x0 + j * cw + cw / 2, y = top - 14 - (l.length - 1) * 15;
        l.forEach(function (line, k) { out += '<text class="ex-tm" x="' + cx + '" y="' + (y + k * 15) + '" text-anchor="middle">' + esc(line) + '</text>'; });
      });
    } else {
      var maxLen = Math.max.apply(null, cols.map(function (c) { return String(c).length * cpx; }));
      top = Math.ceil(maxLen * Math.sin(A)) + 30;
      cols.forEach(function (c, j) {
        var cx = x0 + j * cw + cw / 2, by = top - 10, len = String(c).length * cpx;
        out += '<path d="M' + cx + ' ' + (top - 2) + 'V' + (by + 2) + '" style="stroke:var(--border);stroke-width:1"/>';
        out += '<text class="ex-tm" x="' + (cx + 2) + '" y="' + by + '" transform="rotate(-40 ' + cx + ' ' + by + ')">' + esc(c) + '</text>';
        right = Math.max(right, cx + 2 + len * Math.cos(A) - (x0 + cols.length * cw));
      });
      right = Math.max(0, Math.ceil(right));
    }
    return { svg: out, top: top, right: right };
  }

  function heatmap(el, o) {
    var lw = o.labelW || 140, cw = o.cellW || 64, ch = o.cellH || 40, pad = 20, body = '', hots = '';
    var flat = [].concat.apply([], o.values), lo = Math.min.apply(null, flat), hi = Math.max.apply(null, flat), fmt = o.fmt || String;
    var heads = colHeads(o.cols, pad + lw, cw, o.headers), top = heads.top;
    var W = pad * 2 + lw + o.cols.length * cw + heads.right, H = top + o.rows.length * ch + pad;
    body += heads.svg;
    o.rows.forEach(function (r, i) {
      var y = top + i * ch;
      body += '<text class="ex-t" x="' + pad + '" y="' + (y + ch / 2 + 5) + '">' + esc(r) + '</text>';
      o.cols.forEach(function (c, j) {
        var v = o.values[i][j], t = hi === lo ? 1 : (v - lo) / (hi - lo), x = pad + lw + j * cw;
        var fill = t < .5 ? 'color-mix(in oklab, var(--seq-2) ' + Math.round(t * 200) + '%, var(--seq-1))' : 'color-mix(in oklab, var(--seq-3) ' + Math.round((t - .5) * 200) + '%, var(--seq-2))';
        body += '<rect class="ex-cell" x="' + (x + 1) + '" y="' + (y + 1) + '" width="' + (cw - 2) + '" height="' + (ch - 2) + '" rx="4" style="fill:' + fill + '"/>';
        body += '<text class="ex-tl" x="' + (x + cw / 2) + '" y="' + (y + ch / 2 + 4) + '" text-anchor="middle" style="fill:' + inkOn(el, fill) + '">' + esc(fmt(v)) + '</text>';
        var ex = o.cellEx ? o.cellEx(r, c, v) : { t: r + ' · ' + c, l: 'Heatmap', d: 'This cell is ' + r + ' against ' + c + '.', x: ['Its value is ' + fmt(v) + '.'] };
        hots += hot(key(ex, 'cell'), x + 1, y + 1, cw - 2, ch - 2, 4);
      });
    });
    return pop(svg(el, W, H, o.label, body, hots, o.minWidth || Math.min(760, W)));
  }

  /* Sankey: flows as bands; band width = amount. Rated great.
     {nodes: [{id, col, title, layer, ex}], links: [{from, to, value, layer, ex}], unit} */
  function sankey(el, o) {
    var nw = 14, gap = o.gapY || 26, pad = 20, H = o.height || 320, W = o.width || 760, labelW = o.labelW || 150, body = '', hots = '', u = o.unit || '';
    var byId = {}, cols = [];
    o.nodes.forEach(function (n) { n.inV = 0; n.outV = 0; byId[n.id] = n; (cols[n.col] = cols[n.col] || []).push(n); });
    o.links.forEach(function (l) { byId[l.from].outV += l.value; byId[l.to].inV += l.value; });
    o.nodes.forEach(function (n) { n.v = Math.max(n.inV, n.outV); });
    var scale = Infinity;
    cols.forEach(function (c) { var s = c.reduce(function (a, n) { return a + n.v; }, 0); scale = Math.min(scale, (H - 2 * pad - (c.length - 1) * gap) / s); });
    var x0 = pad + labelW, colW = cols.length > 1 ? (W - pad - labelW - nw - x0) / (cols.length - 1) : 0;
    cols.forEach(function (c, ci) {
      var y = pad;
      c.forEach(function (n) { n.left = ci === 0 && cols.length > 1; n.x = x0 + ci * colW; n.y = y; n.h = n.v * scale; n.oy = y; n.iy = y; y += n.h + gap; });
    });
    o.links.forEach(function (l) {
      var a = byId[l.from], b = byId[l.to], h = l.value * scale, x1 = a.x + nw, x2 = b.x, y1 = a.oy, y2 = b.iy, mx = (x1 + x2) / 2;
      a.oy += h; b.iy += h;
      var d = 'M' + x1 + ' ' + y1 + ' C' + mx + ' ' + y1 + ' ' + mx + ' ' + y2 + ' ' + x2 + ' ' + y2 + ' V' + (y2 + h) + ' C' + mx + ' ' + (y2 + h) + ' ' + mx + ' ' + (y1 + h) + ' ' + x1 + ' ' + (y1 + h) + ' Z';
      var k = key(l.ex || { t: a.title + ' → ' + b.title, l: 'Flow', d: 'This flow goes from ' + a.title + ' to ' + b.title + '.', x: ['It carries ' + l.value + u + '.', 'That is ' + Math.round(100 * l.value / a.v) + '% of ' + a.title + '.'] }, 'flow');
      body += '<path d="' + d + '" style="fill:' + (l.layer === 'key' ? 'var(--accent)' : l.layer === 'alt' ? 'var(--accent-2)' : 'var(--border-strong)') + ';fill-opacity:' + (l.layer ? .35 : .5) + '"/>';
      hots += '<path class="ex-hot" data-ex="' + esc(k) + '" d="' + d + '"/>';
    });
    o.nodes.forEach(function (n) {
      body += '<rect class="ex-cell" x="' + n.x + '" y="' + n.y + '" width="' + nw + '" height="' + Math.max(n.h, 2) + '" rx="3" style="fill:' + (n.layer === 'key' ? 'var(--accent)' : n.layer === 'alt' ? 'var(--accent-2)' : 'var(--text-strong)') + '"/>';
      var tx = n.left ? n.x - 8 : n.x + nw + 8, anchor = n.left ? ' text-anchor="end"' : '';
      body += '<text class="ex-t"' + anchor + ' x="' + tx + '" y="' + (n.y + n.h / 2 + 1) + '">' + esc(n.title) + '</text><text class="ex-ts"' + anchor + ' x="' + tx + '" y="' + (n.y + n.h / 2 + 17) + '">' + esc(n.v + u) + '</text>';
      hots += hot(key(n.ex || { t: n.title, l: 'Node', d: n.title + ' is one stage of the flow.', x: [n.title + ' carries ' + n.v + u + '.'] }, n.id), n.left ? n.x - labelW + 10 : n.x - 2, n.y, nw + labelW - 10, Math.max(n.h, 34), 4);
    });
    return svg(el, W, H, o.label, body, hots, o.minWidth || 760);
  }

  /* ---- Colour reading: a token expression as the browser paints it (for ink choice and the check). ---- */
  var cv = null;
  function rgba(el, expr) {
    var probe = document.createElement('i');
    probe.style.cssText = 'position:absolute;width:0;height:0;overflow:hidden;color:' + expr;
    (el || document.body).appendChild(probe);
    var c = getComputedStyle(probe).color; probe.remove();
    cv = cv || document.createElement('canvas').getContext('2d', { willReadFrequently: true });
    cv.clearRect(0, 0, 1, 1); cv.fillStyle = c; cv.fillRect(0, 0, 1, 1);
    var d = cv.getImageData(0, 0, 1, 1).data;
    return [d[0], d[1], d[2], d[3] / 255];
  }
  function lum(c) { return c.slice(0, 3).map(function (x) { x /= 255; return x <= .04045 ? x / 12.92 : Math.pow((x + .055) / 1.055, 2.4); }).reduce(function (s, x, i) { return s + x * [.2126, .7152, .0722][i]; }, 0); }
  function contrast(a, b) { var x = lum(a), y = lum(b); return (Math.max(x, y) + .05) / (Math.min(x, y) + .05); }
  // The text token that reads best on a fill: --text-strong or --on-accent.
  function inkOn(el, fill) {
    if (!el.isConnected) return 'var(--text-strong)';
    var f = rgba(el, fill);
    return contrast(rgba(el, 'var(--text-strong)'), f) >= contrast(rgba(el, 'var(--on-accent)'), f) ? 'var(--text-strong)' : 'var(--on-accent)';
  }

  /* Bars: one bar per row, coloured from the chart series tokens. Rated good.
     {rows: [{label, value, layer, ex}], unit, max, label} */
  function bars(el, o) {
    var lw = o.labelW || 160, bw = o.barW || 520, bh = 26, gy = 14, pad = 20, top = 30, body = '', hots = '', u = o.unit || '';
    var max = o.max || Math.max.apply(null, o.rows.map(function (r) { return r.value; }));
    var W = pad * 2 + lw + bw + 70, H = top + o.rows.length * (bh + gy) + 6;
    body += '<text class="ex-tm" x="' + (pad + lw) + '" y="18">0</text><text class="ex-tm" x="' + (pad + lw + bw) + '" y="18" text-anchor="end">' + esc(max + u) + '</text>';
    o.rows.forEach(function (r, i) {
      var y = top + i * (bh + gy), w = Math.max(2, bw * r.value / max), s = r.layer === 'key' ? 'ex-bar--key' : 'ex-bar--s' + (i % 5 + 1);
      body += '<text class="ex-t" x="' + pad + '" y="' + (y + 18) + '">' + esc(r.label) + '</text>';
      body += '<rect class="ex-bar ' + s + '" x="' + (pad + lw) + '" y="' + y + '" width="' + w + '" height="' + bh + '" rx="4"/>';
      body += '<text class="ex-tl" x="' + (pad + lw + w + 8) + '" y="' + (y + 17) + '">' + esc(r.value + u) + '</text>';
      hots += hot(key(r.ex || { t: r.label, l: o.layer || 'Value', d: r.label + ' is one row of ' + (o.label || 'this data') + '.', x: ['Its value is ' + r.value + u + '.'] }, 'row' + i), pad, y - 4, lw + w + 60, bh + 8, 4);
    });
    return pop(svg(el, W, H, o.label, body, hots, o.minWidth || 760));
  }

  /* CrispTable from rows. {cols: ["Part", "Value"], rows: [{cells: [..], ex}]} */
  function table(el, o) {
    var h = '<div class="ex-table-wrap"><table class="ex-table"><thead><tr>' + o.cols.map(function (c) { return '<th scope="col">' + esc(c) + '</th>'; }).join('') + '</tr></thead><tbody>';
    o.rows.forEach(function (r, i) {
      var k = key(r.ex, 'row' + i);
      h += '<tr>' + r.cells.map(function (c, j) { return j === 0 && k ? '<td data-column="' + esc(o.cols[j]) + '"><button type="button" class="ex-cellbtn" data-ex="' + esc(k) + '">' + esc(c) + '</button></td>' : '<td data-column="' + esc(o.cols[j]) + '">' + esc(c) + '</td>'; }).join('') + '</tr>';
    });
    el.innerHTML = h + '</tbody></table></div>';
    return el.firstChild;
  }

  /* View switch: the same data as a chart, a table or a diagram. One segmented control per data block.
     {label, views: [{id, label, draw: function (el) {..}}], start} */
  function views(el, o) {
    var cur = el.dataset.view || o.start || o.views[0].id, v = o.views.filter(function (x) { return x.id === cur; })[0] || o.views[0];
    el.classList.add('ex-views');
    el.innerHTML = '<div class="ex-seg" role="group" aria-label="' + esc((o.label || 'Data') + ': view') + '">' +
      o.views.map(function (x) { return '<button type="button" data-view="' + esc(x.id) + '" aria-pressed="' + (x === v) + '">' + esc(x.label) + '</button>'; }).join('') +
      '</div><div class="ex-view"></div>';
    var body = el.lastChild;
    if (v.id !== 'table') body.classList.add('ex-figure');
    v.draw(body);
    el.querySelectorAll('.ex-seg button').forEach(function (b) {
      b.addEventListener('click', function (e) { e.stopPropagation(); el.dataset.view = b.dataset.view; redrawOne(el); el.querySelector('[data-view="' + b.dataset.view + '"]').focus(); });
    });
    return el;
  }

  /* Data block: one data set, three views. Chart = bars, table = CrispTable, diagram = capacity (each row's share of the limit).
     {label, unit, cols, rows: [{label, value, layer, ex}], limit, total, views: ["chart", "table", "diagram"], start} */
  function data(el, o) {
    var u = o.unit || '', sum = o.rows.reduce(function (s, r) { return s + r.value; }, 0), limit = o.limit || sum;
    var rows = o.rows.map(function (r) {
      return { label: r.label, value: r.value, layer: r.layer, ex: r.ex || { t: r.label, l: o.layer || 'Value', d: r.label + ' is one part of ' + (o.label || 'the total') + '.', x: ['Its value is ' + r.value + u + '.', 'That is ' + Math.round(100 * r.value / limit) + '% of ' + limit + u + '.'] } };
    });
    var all = {
      chart: { id: 'chart', label: 'Chart', draw: function (b) { bars(b, { label: o.label, unit: u, rows: rows }); } },
      table: { id: 'table', label: 'Table', draw: function (b) { table(b, { cols: o.cols || ['Part', 'Value', 'Share'], rows: rows.map(function (r) { return { cells: [r.label, r.value + u, Math.round(100 * r.value / limit) + '%'], ex: r.ex }; }) }); } },
      diagram: { id: 'diagram', label: 'Diagram', draw: function (b) { capacity(b, { label: o.label, unit: u, limit: limit, rows: [{ label: o.total || 'Total', parts: rows.map(function (r, i) { return { label: r.label, value: r.value, layer: r.layer || (i % 2 ? 'alt' : ''), ex: r.ex }; }) }] }); } }
    };
    return views(el, { label: o.label, start: o.start, views: (o.views || ['chart', 'table', 'diagram']).map(function (id) { return all[id]; }) });
  }

  /* Timeline: events and spans on a real time scale. Rated good. Use it for dated changes, not a table of dates.
     {events: [{at: "2026-05-17", title, sub, layer, ex}], spans: [{from, to, title, layer, ex}], start, end} */
  function timeline(el, o) {
    var W = o.width || 760, pad = 24, bw = o.boxW || 150, bh = o.boxH || 50, gy = 12, body = '', hots = '';
    var ev = (o.events || []).map(function (e) { return { e: e, t: Date.parse(e.at) }; }).sort(function (a, b) { return a.t - b.t; });
    var sp = (o.spans || []).map(function (s) { return { s: s, a: Date.parse(s.from), b: Date.parse(s.to || o.end || new Date().toISOString().slice(0, 10)) }; });
    var all = [].concat(ev.map(function (x) { return x.t; }), [].concat.apply([], sp.map(function (x) { return [x.a, x.b]; })));
    if (o.start) all.push(Date.parse(o.start)); if (o.end) all.push(Date.parse(o.end));
    if (all.some(isNaN)) throw new Error('timeline: a date does not parse (use YYYY-MM-DD)');
    var t0 = Math.min.apply(null, all), t1 = Math.max.apply(null, all); if (t1 === t0) t1 = t0 + 864e5;
    var x0 = pad + bw / 2, x1 = W - pad - bw / 2, X = function (t) { return x0 + (x1 - x0) * (t - t0) / (t1 - t0); };
    // Events alternate above and below the axis; a box moves out one level while it would cover the last box on that side.
    var lanes = { up: [], dn: [] };
    ev.forEach(function (x, i) {
      var side = i % 2 ? 'dn' : 'up', cx = X(x.t), lv = 0;
      while (lanes[side][lv] != null && lanes[side][lv] > cx - bw / 2 - 8) lv++;
      lanes[side][lv] = cx + bw / 2; x.side = side; x.lv = lv; x.cx = cx;
    });
    var up = lanes.up.length, dn = lanes.dn.length, axis = 30 + up * (bh + gy) + 14, spanTop = axis + 34 + dn * (bh + gy);
    var H = spanTop + sp.length * 34 + 16;
    // Ticks: weeks for a range up to 10 weeks, months up to 18 months, else years.
    var d = new Date(t0), span = t1 - t0, mode = span <= 70 * 864e5 ? 'week' : span <= 18 * 2.63e9 ? 'month' : 'year';
    var MON = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'], shown = 0;
    function next(t) {
      return mode === 'week' ? new Date(t.getTime() + 7 * 864e5) : mode === 'month' ? new Date(Date.UTC(t.getUTCFullYear(), t.getUTCMonth() + 1, 1)) : new Date(Date.UTC(t.getUTCFullYear() + 1, 0, 1));
    }
    var tick = mode === 'week' ? new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate())) : next(new Date(Date.UTC(d.getUTCFullYear(), mode === 'month' ? d.getUTCMonth() : 0, 1)));
    body += '<path class="ex-line" d="M' + (x0 - 12) + ' ' + axis + ' H' + (x1 + 12) + '"/>';
    while (tick.getTime() <= t1 && shown < 40) {
      var tx = X(tick.getTime()), lab = mode === 'week' ? tick.getUTCDate() + ' ' + MON[tick.getUTCMonth()] : mode === 'month' ? MON[tick.getUTCMonth()] + (tick.getUTCMonth() === 0 ? ' ' + tick.getUTCFullYear() : '') : String(tick.getUTCFullYear());
      body += '<path class="ex-line" d="M' + tx + ' ' + (axis - 4) + ' V' + (axis + 4) + '"/><text class="ex-tm" x="' + tx + '" y="' + (axis + 18) + '" text-anchor="middle">' + lab + '</text>';
      tick = next(tick); shown++;
    }
    ev.forEach(function (x) {
      var e = x.e, by = x.side === 'up' ? axis - 14 - (x.lv + 1) * (bh + gy) + gy : axis + 28 + x.lv * (bh + gy);
      var bx = Math.max(pad, Math.min(W - pad - bw, x.cx - bw / 2)), sy = x.side === 'up' ? by + bh : by;
      body += '<path class="' + mod('ex-line', e.layer === 'key' ? 'key' : e.layer === 'off' ? 'off' : '') + '" d="M' + x.cx + ' ' + axis + ' V' + sy + '"/>';
      body += '<circle class="' + (e.layer === 'key' ? 'ex-head-fill ex-head-fill--key' : 'ex-head-fill') + '" cx="' + x.cx + '" cy="' + axis + '" r="5"/>';
      body += '<rect class="' + mod('ex-box', e.layer) + '" x="' + bx + '" y="' + by + '" width="' + bw + '" height="' + bh + '" rx="10"/>' + boxText(bx - 4, by, bw, bh, e.title, e.sub || e.at);
      hots += hot(key(e.ex || { t: e.title, l: e.at, d: e.title + ' happened on ' + e.at + '.', x: [] }, 'event'), bx, by, bw, bh);
    });
    sp.forEach(function (x, i) {
      var s = x.s, y = spanTop + i * 34, a = X(x.a), b = Math.max(X(x.b), a + 6);
      body += '<rect class="' + mod('ex-box', s.layer || 'alt') + '" x="' + a + '" y="' + y + '" width="' + (b - a) + '" height="24" rx="6"/>';
      var inside = (b - a) > s.title.length * 7 + 16;
      body += '<text class="ex-ts" x="' + (inside ? a + 8 : b + 8) + '" y="' + (y + 16) + '">' + esc(s.title) + '</text>';
      hots += hot(key(s.ex || { t: s.title, l: 'SPAN', d: s.title + ' lasted from ' + s.from + ' to ' + (s.to || 'now') + '.', x: [] }, 'span'), a, y, Math.max(b - a, 40), 24, 6);
    });
    return pop(svg(el, W, H, o.label, body, hots, o.minWidth || 760));
  }

  /* Tree: parent and child parts, left to right. Rated good. Use it for causes, ownership or a breakdown.
     {root: {title, sub, layer, ex, edge, children: [..]}, boxW, boxH, cols: ["CAUSE", ..]} */
  function tree(el, o) {
    var hasEdge = JSON.stringify(o.root).indexOf('"edge"') > -1;
    var bw = o.boxW || 200, bh = o.boxH || 54, gx = o.gapX || (hasEdge ? 120 : 64), gy = o.gapY || 14, pad = 20, top = o.cols ? 40 : 16, body = '', hots = '', leaf = 0, depthMax = 0;
    function place(n, dep) {
      depthMax = Math.max(depthMax, dep); n.x = pad + dep * (bw + gx);
      if (n.children && n.children.length) { n.children.forEach(function (c) { place(c, dep + 1); }); n.y = (n.children[0].y + n.children[n.children.length - 1].y) / 2; }
      else n.y = top + (leaf++) * (bh + gy);
    }
    place(o.root, 0);
    var W = pad * 2 + (depthMax + 1) * bw + depthMax * gx, H = top + leaf * (bh + gy) - gy + 20;
    (o.cols || []).forEach(function (c, i) { body += '<text class="ex-tm" x="' + (pad + i * (bw + gx)) + '" y="24">' + esc(c) + '</text>'; });
    (function draw(n) {
      (n.children || []).forEach(function (c) {
        var x1 = n.x + bw, y1 = n.y + bh / 2, x2 = c.x, y2 = c.y + bh / 2, mx = x1 + (hasEdge ? 24 : gx / 2);
        body += '<path class="' + mod('ex-line', c.layer === 'key' ? 'key' : c.layer === 'off' ? 'off' : '') + '" d="M' + x1 + ' ' + y1 + ' H' + mx + ' V' + y2 + ' H' + x2 + '"/>';
        if (c.edge) body += '<text class="ex-tl" x="' + (mx + 6) + '" y="' + (y2 - 6) + '">' + esc(c.edge) + '</text>';
        draw(c);
      });
      body += '<rect class="' + mod('ex-box', n.layer) + '" x="' + n.x + '" y="' + n.y + '" width="' + bw + '" height="' + bh + '" rx="10"/>' + boxText(n.x, n.y, bw, bh, n.title, n.sub);
      hots += hot(key(n.ex, 'node'), n.x, n.y, bw, bh);
    })(o.root);
    return svg(el, W, H, o.label, body, hots, o.minWidth || 760);
  }

  /* Tabs: one figure per item (a customer, an option, a before and after). The reader switches; the page does not stack them.
     {label, tabs: [{id, label, draw: function (el) {..}}], start} */
  function tabs(el, o) {
    var r = views(el, { label: o.label, start: o.start, views: o.tabs });
    el.classList.add('ex-tabs');
    return r;
  }

  /* ---- Keep each chart with its data, so a theme change can draw it again with the same keys. ---- */
  var count = 0;
  function run(el, kind, o) {
    if (!el.dataset.exChart) el.dataset.exChart = el.id || 'c' + (++count);
    var keep = ctx; ctx = { p: el.dataset.exChart, n: 0 }; depth++;
    try { return api[kind](el, o); } finally { depth--; ctx = keep; }
  }
  function redrawOne(el) {
    drawn.forEach(function (d) { if (d.el === el) run(d.el, d.kind, d.o); });
    document.dispatchEvent(new CustomEvent('ex:drawn', { detail: { el: el } }));
  }
  function redraw() {
    drawn.forEach(function (d) { if (d.el.isConnected) run(d.el, d.kind, d.o); });
    document.dispatchEvent(new CustomEvent('ex:drawn', { detail: { el: null } }));
  }
  var api = { connection: connection, container: container, capacity: capacity, heatmap: heatmap, sankey: sankey, bars: bars, timeline: timeline, tree: tree, tabs: tabs, table: table, views: views, data: data };
  var pub = { redraw: redraw, rgba: rgba, contrast: contrast };
  Object.keys(api).forEach(function (kind) {
    pub[kind] = function (el, o) {
      if (depth) return api[kind](el, o);
      drawn = drawn.filter(function (d) { return d.el !== el; }); drawn.push({ el: el, kind: kind, o: o });
      return run(el, kind, o);
    };
  });
  if (window.ResizeObserver) {
    var widths = new WeakMap(), resizeFrame = 0;
    var observer = new ResizeObserver(function (entries) {
      var changed = entries.some(function (entry) {var narrow = entry.contentRect.width < 700, old = widths.get(entry.target); widths.set(entry.target, narrow); return old !== undefined && old !== narrow;});
      if (changed && !resizeFrame) resizeFrame = requestAnimationFrame(function () {resizeFrame = 0; redraw();});
    });
    var connectionPublic = pub.connection;
    pub.connection = function (el, o) {observer.observe(el); return connectionPublic(el, o);};
  }
  window.ExCharts = pub;
})();
