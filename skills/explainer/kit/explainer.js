/* Explainer runtime (explainers.md). Data: window.EX = {"<key>": {t, l, d, x: []}}.
   Items: any element with data-ex="<key>". Facts lists: <details class="ex-facts" data-def="…"> in a section.
   Rail: <nav class="ex-rail"></nav>, filled from .ex-section[id] heads.
   Theme: one floating button per page (themeEngine, below). Themes come from kit/themes.js (window.ExThemes). */
(function () {
  if (window.ExRuntime) return; window.ExRuntime = true;
  var EX = window.EX = window.EX || {};
  var reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  var pop = document.createElement('div');
  pop.className = 'ex-pop'; pop.hidden = true; pop.setAttribute('role', 'dialog');
  pop.innerHTML = '<div class="ex-pop-l"></div><h4><span></span><button type="button" aria-label="Close">×</button></h4><p class="ex-def"></p><ol></ol>';
  document.body.appendChild(pop);
  var cur = null;
  function close() { pop.hidden = true; if (cur && cur.isConnected) { cur.setAttribute('aria-expanded', 'false'); cur.focus({ preventScroll: true }); } cur = null; }
  function open(el) {
    if (cur === el) { close(); return; }
    var d = EX[el.dataset.ex]; if (!d) return;
    pop.querySelector('.ex-pop-l').textContent = d.l || ''; pop.querySelector('.ex-pop-l').hidden = !d.l;
    pop.querySelector('h4 span').textContent = d.t;
    pop.querySelector('.ex-def').textContent = d.d;
    var ol = pop.querySelector('ol'); ol.textContent = '';
    (d.x || []).forEach(function (f) { var li = document.createElement('li'); li.textContent = f; ol.appendChild(li); });
    ol.hidden = !(d.x && d.x.length);
    pop.hidden = false;
    var r = el.getBoundingClientRect(), w = pop.offsetWidth, h = pop.offsetHeight;
    var left = Math.max(16, Math.min(r.left, document.documentElement.clientWidth - w - 16)) + scrollX;
    var top = r.bottom + 6 + scrollY;
    if (r.bottom + 6 + h > innerHeight) top = (r.top - 6 - h > 0 ? r.top - 6 - h : Math.max(16, innerHeight - h - 16)) + scrollY;
    pop.style.left = left + 'px'; pop.style.top = top + 'px';
    if (cur) cur.setAttribute('aria-expanded', 'false');
    cur = el; el.setAttribute('aria-expanded', 'true');
  }
  function prep(root) {
    root.querySelectorAll('[data-ex]').forEach(function (el) {
      if (el.hasAttribute('aria-haspopup')) return;
      el.setAttribute('aria-haspopup', 'dialog'); el.setAttribute('aria-expanded', 'false');
      if (!/^(BUTTON|A)$/.test(el.tagName)) { el.setAttribute('tabindex', '0'); el.setAttribute('role', 'button'); }
      if (!el.getAttribute('aria-label') && EX[el.dataset.ex]) el.setAttribute('aria-label', EX[el.dataset.ex].t);
    });
  }
  prep(document);
  // A chart drawn again (theme change, view switch) has new elements: mark them, and close a pop-up whose part is gone.
  document.addEventListener('ex:drawn', function () { prep(document); if (cur && !cur.isConnected) { pop.hidden = true; cur = null; } });
  document.addEventListener('click', function (e) {
    var el = e.target.closest && e.target.closest('[data-ex]');
    if (el && !pop.contains(el)) { e.stopPropagation(); open(el); return; }
    if (!pop.hidden && (!pop.contains(e.target) || e.target.closest('h4 button'))) close();
  }, true);
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && !pop.hidden) { close(); return; }
    var el = e.target.closest && e.target.closest('[data-ex]');
    if (el && el.getAttribute('role') === 'button' && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); open(el); }
  });

  // FactsList: every fact comes from an item and leads back to it
  function go(el) {
    el.scrollIntoView({ block: 'center', behavior: reduce ? 'auto' : 'smooth' });
    var last = -1, still = 0, t0 = performance.now();
    (function wait() {
      if (scrollY === last) still++; else still = 0; last = scrollY;
      if (still >= 4 || performance.now() - t0 > 1500) {
        el.classList.remove('ex-pulse'); void el.getBoundingClientRect(); el.classList.add('ex-pulse');
        setTimeout(function () { el.classList.remove('ex-pulse'); }, 1200);
        if (cur !== el) open(el); return;
      }
      requestAnimationFrame(wait);
    })();
  }
  document.querySelectorAll('details.ex-facts').forEach(function (det) {
    var scope = det.closest('.ex-section') || document, seen = {}, facts = [];
    scope.querySelectorAll('[data-ex]').forEach(function (el) {
      var d = EX[el.dataset.ex]; if (!d) return;
      (d.x || []).forEach(function (f) { if (!seen[f]) { seen[f] = 1; facts.push({ f: f, k: el.dataset.ex, t: d.t }); } });
    });
    det.textContent = '';
    var s = document.createElement('summary'); s.textContent = 'Facts · ' + facts.length; det.appendChild(s);
    if (det.dataset.def) { var p = document.createElement('p'); p.className = 'ex-def'; p.textContent = det.dataset.def; det.appendChild(p); }
    var ol = document.createElement('ol');
    facts.forEach(function (o, i) {
      var li = document.createElement('li'), b = document.createElement('button');
      b.type = 'button'; b.className = 'ex-fx';
      b.innerHTML = '<i></i><b></b><em></em>';
      b.children[0].textContent = i + 1; b.children[1].textContent = o.f; b.children[2].textContent = o.t;
      b.addEventListener('click', function (e) {
        e.stopPropagation();
        var el = [].filter.call(scope.querySelectorAll('[data-ex]'), function (x) { return x.dataset.ex === o.k; })[0];
        if (el) go(el);
      });
      li.appendChild(b); ol.appendChild(li);
    });
    det.appendChild(ol);
  });

  // TickRail
  var rail = document.querySelector('.ex-rail');
  if (rail) {
    var secs = [].slice.call(document.querySelectorAll('.ex-section[id]')).filter(function (s) { return s.querySelector('.ex-head h2'); });
    secs.forEach(function (s) {
      var n = (s.querySelector('.ex-n') || {}).textContent || '', t = s.querySelector('.ex-head h2').textContent;
      var a = document.createElement('a'); a.href = '#' + s.id; a.dataset.s = s.id; a.setAttribute('aria-label', n + ' ' + t);
      a.innerHTML = '<i class="ex-tk"></i><span class="ex-tip"><b></b></span>';
      a.querySelector('b').textContent = n; a.querySelector('.ex-tip').appendChild(document.createTextNode(t));
      rail.appendChild(a);
    });
    var links = [].slice.call(rail.querySelectorAll('a')), lock = null, raf = 0;
    function set(id) { links.forEach(function (l) { l.classList.toggle('ex-on', l.dataset.s === id); }); }
    function pick() {
      raf = 0; if (lock || !secs.length) return;
      var line = innerHeight * .35, id = secs[0].id;
      secs.forEach(function (s) { if (s.getBoundingClientRect().top <= line) id = s.id; });
      if (innerHeight + scrollY >= document.documentElement.scrollHeight - 4) id = secs[secs.length - 1].id;
      set(id);
    }
    addEventListener('scroll', function () { if (!raf) raf = requestAnimationFrame(pick); }, { passive: true });
    addEventListener('resize', pick);
    links.forEach(function (a) { a.addEventListener('click', function () { set(a.dataset.s); clearTimeout(lock); lock = setTimeout(function () { lock = null; pick(); }, 900); }); });
    pick();
  }

  // ThemeEngine: one button, a menu of themes with live preview, "Set as default", and a saved choice.
  // Order: this view's pick > the viewer's saved default > the page's theme (<meta name="ex-theme">) > Arc Forge.
  // Mode (Auto, Light, Dark) sets data-theme on <html>; Auto gives it back to the host or the system.
  // Saved default: the artifact's db (data/users/<id>/explainer-theme) when the page has the db and user
  // capabilities, and localStorage always. A pick lasts for this view only (sessionStorage).
  (function themeEngine() {
    var reg = window.ExThemes || { fallback: 'arc-forge', themes: [] }, byId = {};
    reg.themes.forEach(function (t) { byId[t.id] = t; });
    var root = document.documentElement, hostMode = root.getAttribute('data-theme');
    // The host can deliver its first message before this runtime loads.
    var inlineMode = root.style.getPropertyValue('color-scheme').trim();
    if (!hostMode && window.parent !== window && (inlineMode === 'light' || inlineMode === 'dark')) hostMode = inlineMode;
    var FB = byId[reg.fallback] ? reg.fallback : 'arc-forge', DKEY = 'ex.theme.default', PKEY = 'ex.theme.pick:' + location.pathname;
    var meta = document.querySelector('meta[name="ex-theme"]'), pageTheme = meta && byId[meta.content] ? meta.content : byId[reg.default] ? reg.default : null;
    function read(store, k) { try { var v = JSON.parse(window[store].getItem(k)); return v && byId[v.id] ? v : null; } catch (e) { return null; } }
    function write(store, k, v) { try { if (v) window[store].setItem(k, JSON.stringify(v)); else window[store].removeItem(k); } catch (e) { /* storage off */ } }
    var saved = read('localStorage', DKEY), pick = read('sessionStorage', PKEY), remote = null, shown = null;

    // One CSS rule set per theme, for <html> and for its swatch, in light and dark.
    // The selected page owns these tokens. Stock OpenClaw writes host tokens inline;
    // important declarations win without deleting host state or racing its message handler.
    function decl(o) { return Object.keys(o).map(function (k) { return '--' + k + ':' + o[k] + ' !important'; }).join(';'); }
    var css = reg.themes.map(function (t) {
      var a = ':root[data-ex-theme="' + t.id + '"]', w = '.ex-sw[data-ex-swatch="' + t.id + '"]';
      var light = decl(t.shape) + ';' + decl(t.light) + ';color-scheme:light !important', dark = decl(t.dark) + ';color-scheme:dark !important';
      return (t.fontFaces || '') + a + ',' + w + '{' + light + '}' +
        '@media (prefers-color-scheme:dark){' + a + ':not([data-theme="light"]),:root:not([data-theme="light"]) ' + w + '{' + dark + '}}' +
        a + '[data-theme="dark"],:root[data-theme="dark"] ' + w + '{' + dark + '}';
    }).join('\n');
    // A constructed style sheet: a page whose security policy allows only its own inline <style> blocks still applies it.
    (function (css, id) { try { var sh = new CSSStyleSheet(); sh.replaceSync(css); document.adoptedStyleSheets = document.adoptedStyleSheets.concat(sh); return; } catch (e) {} var st = document.createElement('style'); if (id) st.id = id; st.textContent = css; document.head.appendChild(st); })(css, 'ex-themes');

    function want() {
      var c = pick || saved || { id: pageTheme || FB, mode: 'auto' };
      return { id: c.id, mode: c.mode || 'auto' };
    }
    var fonts = {};
    function show(s) {
      var resolvedMode = s.mode === 'auto' ? hostMode : s.mode;
      if (shown && shown.id === s.id && shown.mode === s.mode && shown.resolvedMode === resolvedMode) return;
      root.setAttribute('data-ex-theme', s.id);
      if (s.mode === 'auto') { if (hostMode) root.setAttribute('data-theme', hostMode); else root.removeAttribute('data-theme'); }
      else root.setAttribute('data-theme', s.mode);
      var t = byId[s.id];
      if (t && t.fonts && !fonts[t.fonts]) {
        fonts[t.fonts] = 1;
        var l = document.createElement('link'); l.rel = 'stylesheet'; l.href = t.fonts; document.head.appendChild(l);
        if (document.fonts) document.fonts.ready.then(redraw);
      }
      shown = { id: s.id, mode: s.mode, resolvedMode: resolvedMode };
      redraw();
      document.dispatchEvent(new CustomEvent('ex:theme', { detail: { id: s.id, mode: s.mode } }));
    }
    var raf = 0;
    function redraw() { if (raf) return; raf = requestAnimationFrame(function () { raf = 0; if (window.ExCharts) ExCharts.redraw(); }); }
    function apply() { show(want()); paint(); }
    // Auto follows the protected widget host, not a stale mode captured at startup.
    addEventListener('message', function (e) {
      var d = e.data;
      if (window.parent === window || e.source !== window.parent || !d || d.type !== 'openclaw:widget-theme' ||
          !d.tokens || typeof d.tokens !== 'object' || (d.mode !== 'light' && d.mode !== 'dark')) return;
      hostMode = d.mode;
      if (shown && shown.mode === 'auto') show(shown);
    });
    matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function () {
      if (shown && shown.mode === 'auto' && !hostMode) redraw();
    });

    function choose(id, mode) { pick = { id: id, mode: mode || want().mode }; write('sessionStorage', PKEY, pick); apply(); }
    function setDefault() {
      saved = want(); write('localStorage', DKEY, saved);
      if (remote) remote.set({ id: saved.id, mode: saved.mode }).catch(function () { /* local copy kept */ });
      paint();
    }
    function clearDefault() {
      saved = null; write('localStorage', DKEY, null); pick = null; write('sessionStorage', PKEY, null);
      if (remote) remote.delete().catch(function () { /* local copy cleared */ });
      apply();
    }

    // The button and its menu.
    var box = document.createElement('div'); box.className = 'ex-theme';
    box.innerHTML = '<button type="button" class="ex-theme-btn" aria-label="Theme" title="Theme" aria-haspopup="dialog" aria-expanded="false">' +
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 3a9 9 0 0 0 0 18z" fill="currentColor"/></svg></button>' +
      '<div class="ex-theme-menu" role="dialog" aria-label="Theme" hidden><div class="ex-theme-h" id="ex-theme-h">Theme</div>' +
      '<div class="ex-theme-list" role="radiogroup" aria-labelledby="ex-theme-h"></div>' +
      '<div class="ex-theme-h">Mode</div><div class="ex-seg" role="group" aria-label="Mode">' +
      ['auto', 'light', 'dark'].map(function (m) { return '<button type="button" data-mode="' + m + '">' + m.charAt(0).toUpperCase() + m.slice(1) + '</button>'; }).join('') + '</div>' +
      '<div class="ex-theme-acts"><button type="button" data-act="default">Set as default</button><button type="button" data-act="clear">Clear default</button></div>' +
      '<p class="ex-theme-note"></p></div>';
    document.body.appendChild(box);
    var btn = box.firstChild, menu = box.lastChild, list = menu.querySelector('.ex-theme-list');
    reg.themes.forEach(function (t) {
      var o = document.createElement('button'); o.type = 'button'; o.className = 'ex-theme-opt'; o.setAttribute('role', 'radio'); o.dataset.id = t.id;
      o.innerHTML = '<span class="ex-sw" data-ex-swatch="' + t.id + '" aria-hidden="true"><i></i><i></i><i></i><i></i></span><b></b><em></em><span class="ex-theme-tag"></span>';
      o.querySelector('b').textContent = t.label; o.querySelector('em').textContent = t.description || '';
      list.appendChild(o);
    });
    var opts = [].slice.call(list.children);
    function paint() {
      var s = want();
      opts.forEach(function (o) {
        var on = o.dataset.id === s.id; o.setAttribute('aria-checked', on); o.tabIndex = on ? 0 : -1;
        o.querySelector('.ex-theme-tag').textContent = saved && saved.id === o.dataset.id ? 'Default' : o.dataset.id === (pageTheme || FB) ? 'Page' : '';
      });
      menu.querySelectorAll('[data-mode]').forEach(function (b) { b.setAttribute('aria-pressed', b.dataset.mode === s.mode); });
      var isDef = saved && saved.id === s.id && saved.mode === s.mode;
      menu.querySelector('[data-act="default"]').disabled = !!isDef;
      menu.querySelector('[data-act="default"]').textContent = isDef ? 'Default' : 'Set as default';
      menu.querySelector('[data-act="clear"]').hidden = !saved;
      menu.querySelector('.ex-theme-note').textContent = saved ? 'Default: ' + byId[saved.id].label + ', ' + saved.mode + '.' : 'Default: the page theme.';
    }
    function openMenu() { var style = getComputedStyle(root); menu.style.setProperty('--font-body', style.getPropertyValue('--font-body')); menu.style.setProperty('--font-mono', style.getPropertyValue('--font-mono')); menu.hidden = false; btn.setAttribute('aria-expanded', 'true'); paint(); (opts.filter(function (o) { return o.tabIndex === 0; })[0] || opts[0]).focus({preventScroll:true}); }
    function closeMenu(focus) { if (menu.hidden) return; menu.hidden = true; menu.style.removeProperty('--font-body'); menu.style.removeProperty('--font-mono'); btn.setAttribute('aria-expanded', 'false'); show(want()); if (focus) btn.focus(); }
    btn.addEventListener('click', function () { if (menu.hidden) openMenu(); else closeMenu(true); });
    // Live preview: pointing at or focusing a theme shows it on the page; leaving the list shows the choice again.
    opts.forEach(function (o, i) {
      o.addEventListener('pointerenter', function () { show({ id: o.dataset.id, mode: want().mode }); });
      o.addEventListener('focus', function () { show({ id: o.dataset.id, mode: want().mode }); });
      o.addEventListener('click', function () { choose(o.dataset.id); o.focus(); });
      o.addEventListener('keydown', function (e) {
        var j = e.key === 'ArrowDown' || e.key === 'ArrowRight' ? i + 1 : e.key === 'ArrowUp' || e.key === 'ArrowLeft' ? i - 1 : null;
        if (j === null) return; e.preventDefault(); opts[(j + opts.length) % opts.length].focus({preventScroll:true}); opts[(j + opts.length) % opts.length].scrollIntoView({block:'nearest'});
      });
    });
    list.addEventListener('pointerleave', function () { show(want()); });
    list.addEventListener('focusout', function (e) { if (!list.contains(e.relatedTarget)) show(want()); });
    menu.querySelectorAll('[data-mode]').forEach(function (b) { b.addEventListener('click', function () { choose(want().id, b.dataset.mode); }); });
    menu.querySelector('[data-act="default"]').addEventListener('click', setDefault);
    menu.querySelector('[data-act="clear"]').addEventListener('click', clearDefault);
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && !menu.hidden) closeMenu(true); });
    document.addEventListener('click', function (e) { if (!box.contains(e.target)) closeMenu(false); });

    apply();

    // Artifact storage: the viewer's default follows them to other devices, when the page may keep it.
    if (window.claude && typeof window.claude.use === 'function') {
      Promise.all([window.claude.use('db'), window.claude.use('user')]).then(function (r) {
        var db = r[0], user = r[1];
        if (!db || !user) return null;
        return user.id().then(function (uid) {
          if (!uid) return null;
          remote = db.doc('data/users/' + uid + '/explainer-theme');
          return remote.get().then(function (snap) {
            var d = snap.exists && snap.data();
            if (d && byId[d.id]) { saved = { id: d.id, mode: d.mode || 'auto' }; write('localStorage', DKEY, saved); apply(); }
            else if (saved) remote.set({ id: saved.id, mode: saved.mode }).catch(function () { remote = null; });
          });
        });
      }).catch(function () { remote = null; });
    }

    window.ExTheme = {
      themes: reg.themes.map(function (t) { return t.id; }),
      current: want, page: function () { return pageTheme || FB; }, saved: function () { return saved; },
      set: choose, setDefault: setDefault, clearDefault: clearDefault
    };
  })();

})();
