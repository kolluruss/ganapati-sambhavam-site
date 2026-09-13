/* Ganapati Sambhavam — reading site
 * Static, no build step. Fetches pre-generated JSON from data/ and
 * renders a bhagavatavani.com-style two-pane reading experience with
 * a Telugu / English toggle. See tools/build_data.py for the source
 * of the JSON this consumes.
 */
(function () {
  'use strict';

  var DEFAULT_HASH = '#/te/s1/t01';

  var meta = null;
  var frontMatter = { te: null, en: null };
  var sargaCache = {};      // `${lang}-${n}` -> topics array
  var currentLang = 'te';
  var openGroups = new Set(['s1']);  // sidebar groups expanded by default

  var els = {};

  // ── Verse recitation audio ────────────────────────────────────────
  // One shared <audio> element; each .verse-block with a data-audio
  // attribute gets a play/pause button (added at build time only when a
  // matching gs_<sarga>_<verse> audio (.wav or .mp3) was actually synced
  // — see tools/build_data.py. new Audio(src) plays either format based
  // on the file itself, no extension-specific handling needed here.
  // Starting a new verse stops whatever was playing.

  var activeAudio = null;
  var activeBtn = null;

  function stopAudio() {
    if (activeAudio) { activeAudio.pause(); }
    if (activeBtn) { activeBtn.classList.remove('playing'); activeBtn.textContent = '▶'; }
    activeAudio = null;
    activeBtn = null;
  }

  function toggleVerseAudio(btn) {
    var block = btn.closest('.verse-block');
    var src = block && block.getAttribute('data-audio');
    if (!src) return;
    if (activeBtn === btn) { stopAudio(); return; }
    stopAudio();
    var audio = new Audio(src);
    audio.addEventListener('ended', stopAudio);
    audio.addEventListener('error', stopAudio);
    audio.play();
    btn.classList.add('playing');
    btn.textContent = '⏸';
    activeAudio = audio;
    activeBtn = btn;
  }

  function $(sel, root) { return (root || document).querySelector(sel); }

  function getJSON(path) {
    return fetch(path).then(function (r) {
      if (!r.ok) throw new Error('Failed to load ' + path + ' (' + r.status + ')');
      return r.json();
    });
  }

  // ── Routing ──────────────────────────────────────────────────────

  function parseHash() {
    var h = location.hash.replace(/^#\/?/, '');
    var parts = h.split('/').filter(Boolean);
    var lang = (parts[0] === 'en') ? 'en' : 'te';
    if (parts[1] === 'front' && parts[2]) {
      return { lang: lang, kind: 'front', id: parts[2] };
    }
    var sm = parts[1] && parts[1].match(/^s(\d+)$/);
    var tm = parts[2] && parts[2].match(/^t(\d+)$/);
    if (sm && tm) {
      return { lang: lang, kind: 'topic', sarga: parseInt(sm[1], 10), topicNum: parseInt(tm[1], 10) };
    }
    return null;
  }

  function hashFor(lang, target) {
    if (target.kind === 'front') return '#/' + lang + '/front/' + target.id;
    return '#/' + lang + '/s' + target.sarga + '/t' + String(target.topicNum).padStart(2, '0');
  }

  // ── Data access ──────────────────────────────────────────────────

  function sargaMeta(n) {
    return meta.sargas.find(function (s) { return s.number === n; });
  }

  function ensureSarga(lang, n) {
    var key = lang + '-' + n;
    if (sargaCache[key]) return Promise.resolve(sargaCache[key]);
    return getJSON('data/' + lang + '/sarga-' + n + '.json').then(function (data) {
      sargaCache[key] = data;
      return data;
    });
  }

  function frontEntryLabel(entry) {
    // tools/build_data.py always fills in a same-language label (real H1,
    // or a fallback lifted from the file's own heading/bold lead-in) —
    // entry.id is a last-resort safety net only, never a language mix-up.
    return entry.title || entry.id;
  }

  // ── Sidebar ──────────────────────────────────────────────────────

  function buildSidebar() {
    var html = '';

    // Front matter group
    var feEntries = frontMatter[currentLang] || [];
    html += navGroup('front', currentLang === 'te' ? 'ముందుమాట' : 'Front Matter', '', feEntries.map(function (e) {
      return { href: hashFor(currentLang, { kind: 'front', id: e.id }), label: frontEntryLabel(e) };
    }));

    // Sarga groups
    meta.sargas.forEach(function (s) {
      var groupId = 's' + s.number;
      var title = currentLang === 'te' ? s.name_te : s.name_en;
      var topicItems = s.topics.map(function (t) {
        return {
          href: hashFor(currentLang, { kind: 'topic', sarga: s.number, topicNum: t.number }),
          label: topicLabel(s, t),
          range: t.shloka_range.start + '–' + t.shloka_range.end,
        };
      });
      html += navGroup(groupId, title, s.number, topicItems);
    });

    els.sidebarContent.innerHTML = html;
    els.sidebarContent.querySelectorAll('.nav-group-btn').forEach(function (btn) {
      btn.addEventListener('click', function () { toggleGroup(btn.dataset.group); });
    });
    // Close the mobile drawer whenever a topic link is chosen.
    els.sidebarContent.querySelectorAll('a').forEach(function (a) {
      a.addEventListener('click', closeSidebar);
    });
    applyOpenGroups();
  }

  function topicLabel(sargaM, topic) {
    if (currentLang === 'te') return topic.name_te;
    var cached = sargaCache['en-' + sargaM.number];
    if (cached) {
      var t = cached.find(function (x) { return x.id === 's' + sargaM.number + '-t' + String(topic.number).padStart(2, '0'); });
      if (t) return t.title;
    }
    return 'Topic ' + topic.number;
  }

  function navGroup(groupId, title, num, items) {
    var itemsHtml = items.map(function (it) {
      return '<li><a href="' + it.href + '" data-nav-id="' + it.href + '">' + escapeHtml(it.label) +
        (it.range ? ' <span class="range">(' + it.range + ')</span>' : '') + '</a></li>';
    }).join('');
    return (
      '<div class="nav-group">' +
      '<button type="button" class="nav-group-btn" data-group="' + groupId + '">' +
      '<span class="chev">▸</span>' +
      (num ? '<span class="nav-group-num">' + num + '</span>' : '') +
      '<span>' + escapeHtml(title) + '</span>' +
      '</button>' +
      '<ul class="nav-topics" data-group-list="' + groupId + '">' + itemsHtml + '</ul>' +
      '</div>'
    );
  }

  function toggleGroup(groupId) {
    if (openGroups.has(groupId)) openGroups.delete(groupId);
    else openGroups.add(groupId);
    applyOpenGroups();
  }

  function applyOpenGroups() {
    els.sidebarContent.querySelectorAll('.nav-group-btn').forEach(function (btn) {
      var isOpen = openGroups.has(btn.dataset.group);
      btn.classList.toggle('open', isOpen);
      var list = els.sidebarContent.querySelector('[data-group-list="' + btn.dataset.group + '"]');
      if (list) list.classList.toggle('open', isOpen);
    });
  }

  function highlightActive(hash) {
    els.sidebarContent.querySelectorAll('a').forEach(function (a) {
      a.classList.toggle('active', a.getAttribute('href') === hash);
    });
  }

  function refreshSidebarLabelsFor(sargaNum) {
    var s = sargaMeta(sargaNum);
    var list = els.sidebarContent.querySelector('[data-group-list="s' + sargaNum + '"]');
    if (!s || !list) return;
    var links = list.querySelectorAll('a');
    s.topics.forEach(function (t, i) {
      var a = links[i];
      if (!a) return;
      var range = t.shloka_range.start + '–' + t.shloka_range.end;
      a.innerHTML = escapeHtml(topicLabel(s, t)) + ' <span class="range">(' + range + ')</span>';
    });
  }

  function escapeHtml(s) {
    var d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  }

  // ── Flat reading order (for prev/next) ────────────────────────────

  function flatList(lang) {
    var out = [];
    (frontMatter[lang] || []).forEach(function (e) {
      out.push({ kind: 'front', id: e.id, label: frontEntryLabel(e) });
    });
    meta.sargas.forEach(function (s) {
      s.topics.forEach(function (t) {
        out.push({
          kind: 'topic', sarga: s.number, topicNum: t.number,
          label: 'Sarga ' + s.number + ' · ' + (lang === 'te' ? t.name_te : 'Topic ' + t.number),
        });
      });
    });
    return out;
  }

  function findIndexInFlat(list, route) {
    for (var i = 0; i < list.length; i++) {
      var e = list[i];
      if (route.kind === 'front' && e.kind === 'front' && e.id === route.id) return i;
      if (route.kind === 'topic' && e.kind === 'topic' && e.sarga === route.sarga && e.topicNum === route.topicNum) return i;
    }
    return -1;
  }

  function renderPageNav(route) {
    var list = flatList(currentLang);
    var idx = findIndexInFlat(list, route);
    if (idx === -1) return '';
    var prev = list[idx - 1];
    var next = list[idx + 1];
    var prevHtml = prev
      ? '<a href="' + hashFor(currentLang, prev) + '"><span class="dir">' + (currentLang === 'te' ? '← క్రితం' : '← Previous') + '</span>' + escapeHtml(prev.label) + '</a>'
      : '<span class="spacer"></span>';
    var nextHtml = next
      ? '<a class="next" href="' + hashFor(currentLang, next) + '"><span class="dir">' + (currentLang === 'te' ? 'తదుపరి →' : 'Next →') + '</span>' + escapeHtml(next.label) + '</a>'
      : '<span class="spacer"></span>';
    return '<div class="page-nav">' + prevHtml + nextHtml + '</div>';
  }

  // ── Rendering ──────────────────────────────────────────────────────

  function setLangUI(lang) {
    currentLang = lang;
    document.documentElement.setAttribute('data-active-lang', lang);
    document.documentElement.lang = lang;
    els.langBtns.forEach(function (b) { b.classList.toggle('active', b.dataset.lang === lang); });
  }

  function renderBreadcrumb(route) {
    var parts = [];
    if (route.kind === 'front') {
      parts.push(currentLang === 'te' ? 'ముందుమాట' : 'Front Matter');
      var entry = (frontMatter[currentLang] || []).find(function (e) { return e.id === route.id; });
      if (entry) parts.push(frontEntryLabel(entry));
    } else {
      var s = sargaMeta(route.sarga);
      parts.push((currentLang === 'te' ? 'సర్గ ' : 'Sarga ') + route.sarga + ' · ' + (currentLang === 'te' ? s.name_te : s.name_en));
    }
    els.content.insertAdjacentHTML('afterbegin',
      '<div class="breadcrumb">' + parts.map(escapeHtml).join(' <span class="sep">›</span> ') + '</div>');
  }

  var sidebarLang = null;

  function render() {
    var route = parseHash();
    if (!route) { location.hash = DEFAULT_HASH; return; }
    stopAudio();
    setLangUI(route.lang);
    if (sidebarLang !== route.lang) {
      sidebarLang = route.lang;
      buildSidebar();
    }
    highlightActive(location.hash);

    if (route.kind === 'front') {
      openGroups.add('front');
      applyOpenGroups();
      renderFront(route);
    } else {
      openGroups.add('s' + route.sarga);
      applyOpenGroups();
      renderTopic(route);
    }
  }

  function renderFront(route) {
    els.content.innerHTML = '<p class="loading">Loading…</p>';
    var list = frontMatter[currentLang];
    var entry = list && list.find(function (e) { return e.id === route.id; });
    if (!entry) {
      els.content.innerHTML = '<p class="error">Page not found.</p>';
      return;
    }
    els.content.innerHTML = entry.html + renderPageNav(route);
    renderBreadcrumb(route);
    window.scrollTo(0, 0);
  }

  function renderTopic(route) {
    els.content.innerHTML = '<p class="loading">Loading…</p>';
    ensureSarga(route.lang, route.sarga).then(function (topics) {
      // Route may be stale if the user navigated again while this was
      // in flight; bail out rather than clobbering the newer view.
      var cur = parseHash();
      if (!cur || cur.lang !== route.lang || cur.sarga !== route.sarga || cur.topicNum !== route.topicNum) return;

      var tid = 's' + route.sarga + '-t' + String(route.topicNum).padStart(2, '0');
      var topic = topics.find(function (t) { return t.id === tid; });
      if (!topic) {
        els.content.innerHTML = '<p class="error">Topic not found.</p>';
        return;
      }
      var pendingBanner = topic.pending
        ? '<div class="pending-banner">' + (route.lang === 'te'
            ? 'ఈ విభాగం ఇంకా అందుబాటులో లేదు.'
            : 'This section has not been translated to English yet — check back soon, or switch to Telugu above.') +
          '</div>'
        : '';
      els.content.innerHTML = pendingBanner + topic.html + renderPageNav(route);
      renderBreadcrumb(route);
      window.scrollTo(0, 0);

      if (route.lang === 'en') refreshSidebarLabelsFor(route.sarga);
    }).catch(function (err) {
      els.content.innerHTML = '<p class="error">' + escapeHtml(err.message) + '</p>';
    });
  }

  // ── Language / theme controls ─────────────────────────────────────

  function switchLang(lang) {
    var route = parseHash();
    if (!route) { location.hash = DEFAULT_HASH; return; }
    if (route.kind === 'front' && frontMatter[lang] && !frontMatter[lang].some(function (e) { return e.id === route.id; })) {
      // No equivalent front-matter page in the target language (e.g. a
      // Telugu-only photo gallery) — land on the default page instead.
      location.hash = DEFAULT_HASH.replace('/te/', '/' + lang + '/');
      return;
    }
    var target = route.kind === 'front' ? { kind: 'front', id: route.id } : { kind: 'topic', sarga: route.sarga, topicNum: route.topicNum };
    var newHash = hashFor(lang, target);
    if (newHash === location.hash) render(); else location.hash = newHash;
  }

  function initTheme() {
    var saved = localStorage.getItem('gs-theme');
    var theme = saved || (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    document.documentElement.setAttribute('data-theme', theme);
    updateThemeIcon(theme);
  }

  function updateThemeIcon(theme) {
    els.themeToggle.textContent = theme === 'dark' ? '☀️' : '🌙';
  }

  function toggleTheme() {
    var cur = document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
    var next = cur === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('gs-theme', next);
    updateThemeIcon(next);
  }

  function openSidebar() { els.sidebar.classList.add('open'); els.scrim.classList.add('show'); }
  function closeSidebar() { els.sidebar.classList.remove('open'); els.scrim.classList.remove('show'); }
  function toggleSidebar() { els.sidebar.classList.contains('open') ? closeSidebar() : openSidebar(); }

  // ── Init ───────────────────────────────────────────────────────────

  function init() {
    els.sidebar = $('#sidebar');
    els.sidebarContent = $('#sidebarContent');
    els.content = $('#content');
    els.scrim = $('#scrim');
    els.navToggle = $('#navToggle');
    els.themeToggle = $('#themeToggle');
    els.langBtns = Array.prototype.slice.call(document.querySelectorAll('.lang-btn'));

    initTheme();
    els.themeToggle.addEventListener('click', toggleTheme);
    els.navToggle.addEventListener('click', toggleSidebar);
    els.scrim.addEventListener('click', closeSidebar);
    els.langBtns.forEach(function (b) {
      b.addEventListener('click', function () { switchLang(b.dataset.lang); });
    });
    els.content.addEventListener('click', function (e) {
      var btn = e.target.closest('.play-btn');
      if (btn) toggleVerseAudio(btn);
    });

    Promise.all([
      getJSON('data/meta.json'),
      getJSON('data/te/sarga-0.json'),
      getJSON('data/en/sarga-0.json'),
    ]).then(function (results) {
      meta = results[0];
      frontMatter.te = results[1];
      frontMatter.en = results[2];

      var route = parseHash();
      if (route) {
        openGroups.add(route.kind === 'front' ? 'front' : 's' + route.sarga);
      }
      window.addEventListener('hashchange', render);

      if (!location.hash) location.hash = DEFAULT_HASH;
      else render();
    }).catch(function (err) {
      els.content.innerHTML = '<p class="error">Could not load site data: ' + escapeHtml(err.message) +
        '<br>Make sure you are running this through a local web server (see README.md), not opening index.html directly from disk.</p>';
      els.sidebarContent.innerHTML = '';
    });
  }

  document.addEventListener('DOMContentLoaded', init);
})();
