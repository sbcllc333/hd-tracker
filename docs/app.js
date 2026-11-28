/* Penny Run v21 — Home Depot penny candidates + deep clearance at Paul's stores, plus his own penny leads.
   Pennies never show online: only the register shows $0.01. No build step, no server. */
(() => {
  const $ = (s, el = document) => el.querySelector(s);
  const view = $('#view');
  const store = {
    get(k, d) { try { const v = localStorage.getItem('pr_' + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
    set(k, v) { try { localStorage.setItem('pr_' + k, JSON.stringify(v)); } catch { /* private mode */ } }
  };
  const DEF = { minPct: 75, maxPrice: 1, noStepPct: 90, staleDays: 3, defStore: 'all', stockDef: false, light: false };
  const CFG = Object.assign({}, DEF, store.get('settings', {}));
  const S = {
    data: null, tab: 'today', store: CFG.defStore, q: '', group: 'all', likely: false, stock: !!CFG.stockDef,
    sort: store.get('sort', 'penny'), retailer: 'homedepot', run: store.get('run', {}), limit: 12, offline: false
  };
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const money = v => v == null || v === '' ? '' : '$' + Number(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const dayMs = 864e5;
  const today = () => new Date().toLocaleDateString('en-CA', { timeZone: 'America/New_York' });
  const daysAgo = iso => {
    if (!iso) return null;
    const t = new Date(iso.length > 10 ? iso : iso + 'T12:00:00').getTime();
    return Math.max(0, Math.round((Date.now() - t) / dayMs));
  };
  const ago = iso => { const d = daysAgo(iso); return d == null ? 'never' : d === 0 ? 'today' : d === 1 ? 'yesterday' : d + ' days ago'; };
  const niceDate = iso => iso ? new Date(iso.length > 10 ? iso : iso + 'T12:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) : '';
  const base = () => location.origin + location.pathname;
  const stores = () => (S.data.stores || []).filter(s => (s.retailer || 'homedepot') === 'homedepot');
  const storeName = id => (S.data.stores.find(s => s.id === id) || {}).short || id;
  const storeFull = id => (S.data.stores.find(s => s.id === id) || {}).name || id;
  const PENNY_LIST = 'https://www.pennycentral.com/penny-list';
  const PAYDIRT = 'https://paydirt.gg/home-depot-penny-list/';

  function toast(msg) {
    const t = $('#toast'); t.textContent = msg; t.hidden = false;
    clearTimeout(toast.t); toast.t = setTimeout(() => (t.hidden = true), 1800);
  }
  function applyTheme() { document.documentElement.dataset.theme = CFG.light ? 'light' : 'dark'; }
  function saveCfg() { store.set('settings', CFG); }

  // ---------- run marks (Strategist: keep stop-sale separate from "not a penny") ----------
  const MARKS = { penny: 'Rang 1¢', blocked: 'Stop-sale / blocked', full: 'Not a penny', gone: 'Not there', found: 'Found' };

  // ---------- leads book (pasted finds + trip marks, kept on this phone) ----------
  function localBook() { return store.get('book', { leads: [], trips: [] }); }
  function saveLocalBook(b) { store.set('book', b); }
  function nid() { return 'ld_' + Math.random().toString(16).slice(2, 12); }
  function toLead(i) {
    return {
      id: i.id, sku: i.sku || '', upc: i.upc || '', name: i.name || i.title || '',
      stores: i.stores || (i.store_id ? [i.store_id] : []), source: i.source || 'community',
      reported_price: i.reported_price != null ? i.reported_price : i.price, reported_at: i.reported_at || i.first_seen || '',
      confirmed_at_register: !!i.confirmed_at_register, notes: i.notes || '', retailer: 'homedepot', local: !!i.local
    };
  }
  function book() {
    const leads = new Map();
    (S.data.items || []).forEach(l => leads.set(l.id, toLead(l)));
    const loc = localBook();
    (loc.leads || []).forEach(l => leads.set(l.id, { ...(leads.get(l.id) || {}), ...toLead(l), local: true }));
    const key = t => [t.lead_id, t.store_id || '', t.date].join('|');
    const trips = new Map();
    (S.data.trips || []).forEach(t => trips.set(key(t), t));
    (S.data.items || []).forEach(i => (i.trips || []).forEach(t => trips.set(key({ ...t, lead_id: t.lead_id || i.id }), { ...t, lead_id: t.lead_id || i.id })));
    (loc.trips || []).forEach(t => trips.set(key(t), t));
    return { leads: [...leads.values()], trips: [...trips.values()], localLeads: loc.leads || [] };
  }
  const tripsFor = (b, id) => b.trips.filter(t => t.lead_id === id).sort((a, c) => (c.date || '').localeCompare(a.date || ''));
  const rang = trips => trips.some(t => t.mark === 'penny');

  // ---------- store deals: one card per product (pid) ----------
  const stepped = h => { const p = (h || []).map(x => x[1]).filter(x => x != null); return p.some((v, i) => i && v < p[i - 1]); };
  function late(d) {   // user-tunable version of the data rule (Settings > thresholds)
    if (d.price == null || d.gone_on) return false;
    return ((d.pct || 0) >= CFG.minPct || d.price < CFG.maxPrice) && (stepped(d.history) || (d.pct || 0) >= CFG.noStepPct);
  }
  function confirmedIds() {
    const b = book(), ids = new Set();
    b.trips.forEach(t => { if (t.mark === 'penny') ids.add(t.lead_id); });
    b.leads.forEach(l => { if (l.confirmed_at_register) ids.add(l.id); });
    return ids;
  }
  function deals() {
    const conf = confirmedIds();
    return (S.data.deals || []).map(d => {
      const isLate = late(d);
      const stage = conf.has(d.id) ? 'confirmed' : d.gone_on ? 'hidden' : isLate ? 'late' : d.qty === 0 ? 'weak' : '';
      return { ...d, kind: 'deal', stage, late: isLate };
    });
  }
  function groups(list) {
    const m = new Map();
    for (const d of list) {
      const k = d.pid || d.id;
      if (!m.has(k)) m.set(k, []);
      m.get(k).push(d);
    }
    const rank = { confirmed: 0, hidden: 1, late: 2, '': 3, weak: 4 };
    return [...m.values()].map(ds => {
      ds.sort((a, b) => (rank[a.stage] - rank[b.stage]) || ((b.penny_score || 0) - (a.penny_score || 0)) || ((a.price ?? 1e9) - (b.price ?? 1e9)));
      const r = ds[0];
      return { ...r, at: ds, inStock: ds.some(x => x.qty > 0) };
    });
  }
  const textOf = i => [i.title, i.sku, i.upc, i.brand, i.model, i.dept, i.group, i.notes, i.name].join(' ').toLowerCase();
  function filtered(list, { group = true, likely = true, stock = true } = {}) {
    const q = S.q.trim().toLowerCase();
    return list.filter(i =>
      (S.store === 'all' || i.store_id === S.store) &&
      (!group || S.group === 'all' || i.group === S.group) &&
      (!q || textOf(i).includes(q)));
  }
  function grouped(opts = {}) {
    let g = groups(filtered(deals(), opts));
    if (opts.stock !== false && S.stock) g = g.filter(x => x.inStock);
    if (opts.likely !== false && S.likely) g = g.filter(x => ['confirmed', 'hidden', 'late'].includes(x.stage));
    return sortG(g);
  }
  function sortG(g) {
    const rank = { confirmed: 0, hidden: 1, late: 2, '': 3, weak: 4 };
    const by = {
      penny: (a, b) => (rank[a.stage] - rank[b.stage]) || ((b.penny_score || 0) - (a.penny_score || 0)) || ((b.pct || 0) - (a.pct || 0)) || ((a.price ?? 1e9) - (b.price ?? 1e9)),
      pct: (a, b) => ((b.pct || 0) - (a.pct || 0)) || ((b.inStock ? 1 : 0) - (a.inStock ? 1 : 0)) || ((a.price ?? 1e9) - (b.price ?? 1e9)),
      new: (a, b) => (b.last_seen || '').localeCompare(a.last_seen || '') || (b.first_seen || '').localeCompare(a.first_seen || '') || ((b.pct || 0) - (a.pct || 0))
    }[S.sort] || (() => 0);
    return g.slice().sort(by);
  }
  function leads() {
    const b = book();
    const q = S.q.trim().toLowerCase();
    return b.leads.map(l => {
      const trips = tripsFor(b, l.id);
      return { ...l, kind: 'lead', title: l.name || l.sku || l.upc || 'Untitled find', price: l.reported_price, trips,
        confirmed: l.confirmed_at_register || rang(trips), store_id: (l.stores || [])[0] || '' };
    }).filter(l => (S.store === 'all' || !(l.stores || []).length || l.stores.includes(S.store)) && (!q || textOf(l).includes(q)))
      .sort((a, b) => (b.confirmed - a.confirmed) || (b.reported_at || '').localeCompare(a.reported_at || ''));
  }
  const findItem = id => {
    const d = deals().find(x => x.id === id);
    if (d) return groups(deals().filter(x => x.pid === d.pid)).map(g => ({ ...g, ...d, at: g.at }))[0];
    return leads().find(x => x.id === id) || book().leads.map(l => ({ ...l, kind: 'lead', title: l.name || l.sku, price: l.reported_price, trips: [] })).find(x => x.id === id);
  };

  // ---------- freshness ----------
  function scanInfo() {
    const f = S.data.feed || {}, per = f.stores || {};
    const dates = Object.values(per).map(x => x.last_scan).filter(Boolean).sort();
    return { oldest: dates[0] || null, newest: dates[dates.length - 1] || null, per, unscanned: stores().filter(s => !(per[s.id] || {}).last_scan) };
  }

  // ---------- rendering ----------
  async function load() {
    if (!S.data) view.innerHTML = '<div class="skel"></div>'.repeat(4);
    try {
      const r = await fetch('data.json?t=' + Math.floor(Date.now() / 6e4), { cache: 'no-store' });
      if (!r.ok) throw new Error(r.status);
      S.data = await r.json(); S.offline = false; store.set('cache', S.data);
    } catch {
      S.data = store.get('cache', null); S.offline = true;
    }
    if (!S.data) {
      view.innerHTML = '<div class="empty"><h3>Can\'t load right now</h3><p>Check your signal, then try again.</p><button class="btn fill" id="retry">Try again</button></div>';
      $('#updated').textContent = 'No data yet';
      return;
    }
    if (S.store !== 'all' && !stores().some(s => s.id === S.store)) S.store = 'all';
    S.loaded = Date.now();
    draw();
    route();
  }

  function header() {
    const d = S.data, si = scanInfo();
    const up = $('#updated');
    if (si.oldest) {
      const age = daysAgo(si.oldest);
      up.textContent = 'Store scans: ' + niceDate(si.oldest) + ' (' + (age === 0 ? 'today' : age + ' day' + (age === 1 ? '' : 's') + ' old') + ')';
      up.classList.toggle('stale', age >= CFG.staleDays);
    } else { up.textContent = 'No store scans yet'; }
    const b = $('#banner');
    let msg = '';
    const scanAsOf = si.oldest || si.newest;
    if (S.offline) msg = 'Offline. Showing what this phone saved on ' + niceDate(d.generated_at) + '.';
    else if (d.status && d.status.ok === false) msg = 'Feed paused, last store scan ' + niceDate(scanAsOf) + '. Every price shows its date.';
    b.textContent = msg; b.hidden = !msg;
    const ss = stores();
    $('#stores').innerHTML = [{ id: 'all', short: 'All ' + ss.length + ' stores' }, ...ss].map(s =>
      `<button class="chip ${S.store === s.id ? 'on' : ''}" data-store="${esc(s.id)}">${esc(s.short)}</button>`).join('');
    const ids = new Set(deals().map(x => x.id).concat(book().leads.map(l => l.id)));
    const n = Object.keys(S.run).filter(id => ids.has(id)).length, rc = $('#runcount');
    rc.hidden = !n; rc.textContent = n;
    document.querySelectorAll('.nav button').forEach(x => x.classList.toggle('on', x.dataset.tab === S.tab));
  }

  function filtersUI() {
    const all = grouped({ group: false });
    const cnt = {};
    all.forEach(g => (cnt[g.group || 'Other'] = (cnt[g.group || 'Other'] || 0) + 1));
    const names = (S.data.dept_groups || Object.keys(cnt)).filter(n => cnt[n] || n === S.group);
    return `<div class="chips row" aria-label="Department">${[['all', 'All', all.length], ...names.map(n => [n, n, cnt[n] || 0])].map(([k, l, c]) =>
      `<button class="chip ${S.group === k ? 'on' : ''}" data-group="${esc(k)}">${esc(l)} <small>${c}</small></button>`).join('')}</div>
      <div class="frow">
        <button class="chip tog ${S.likely ? 'on' : ''}" id="likelytog" aria-pressed="${S.likely}">Penny signals only</button>
        <button class="chip tog ${S.stock ? 'on' : ''}" id="stocktog" aria-pressed="${S.stock}">In stock only</button>
        <label class="sortsel"><span>Sort</span><select id="sort">
          <option value="penny" ${S.sort === 'penny' ? 'selected' : ''}>Penny first</option>
          <option value="pct" ${S.sort === 'pct' ? 'selected' : ''}>Deepest % off</option>
          <option value="new" ${S.sort === 'new' ? 'selected' : ''}>Newest</option></select></label>
      </div>
      <div class="searchwrap"><input class="search" id="q" type="text" placeholder="Search name, SKU, UPC, brand" value="${esc(S.q)}" autocomplete="off" enterkeyhint="search" inputmode="search">
        ${S.q ? '<button class="clearq" id="clearq" aria-label="Clear search">×</button>' : ''}</div>`;
  }

  const stockLine = d => d.qty > 0 ? d.qty + ' in stock online' : d.qty === 0 ? 'likely sold out (0 online)' : '';
  function tagsFor(i) {
    const t = [];
    if (i.kind === 'lead') {
      t.push(i.confirmed ? '<span class="tag ok">Confirmed 1¢</span>' : '<span class="tag lead">Lead · confirm at register</span>');
      t.push(`<span class="tag plain">${i.source === 'my_trip' ? 'My trip' : 'Community'}</span>`);
    } else {
      if (i.stage === 'confirmed') t.push('<span class="tag ok">Confirmed 1¢</span>');
      if (i.stage === 'hidden') t.push('<span class="tag likely">Likely penny · hidden price</span>');
      if (i.stage === 'late') t.push('<span class="tag likely">Late clearance · trip-worthy</span>');
    }
    if (S.run[i.id]) t.push('<span class="tag ok">On run list</span>');
    return t.join('');
  }
  const initial = i => esc(((i.title || '?')[0] || '?').toUpperCase());
  const thumb = i => `<div class="tw">${i.stage === 'confirmed' || i.confirmed ? '<span class="coin">1¢</span>' : ''}<div class="thumb">${initial(i)}${i.thumb ? `<img src="${esc(i.thumb.replace(/_(\d+)\.jpg$/, '_145.jpg'))}" alt="" loading="lazy" onerror="this.remove()">` : ''}</div></div>`;
  function card(i) {
    if (i.kind === 'lead') {
      return `<button class="card${i.confirmed ? ' confirmed' : ''}" data-item="${esc(i.id)}">${thumb(i)}
        <div class="body"><div class="title">${esc(i.title)}</div>
          <div class="meta">${i.sku ? 'SKU <b>' + esc(i.sku) + '</b>' : ''}${i.upc ? (i.sku ? '<br>' : '') + 'UPC ' + esc(i.upc) : ''}</div>
          <div class="meta">${esc([(i.stores || []).map(storeName).join(', ') || 'Any store', i.reported_at ? 'Reported ' + niceDate(i.reported_at) : ''].filter(Boolean).join(' · '))}</div>
          <div class="tags">${tagsFor(i)}</div></div>
        <div class="side"><div class="price">${money(i.price) || '—'}</div></div></button>`;
    }
    const at = i.at || [i];
    const where = at.length > 1 ? 'at ' + at.length + ' stores: ' + at.map(x => storeName(x.store_id)).join(', ') : storeName(i.store_id);
    const prices = [...new Set(at.map(x => x.price))];
    const seen = (i.gone_on ? 'gone ' + niceDate(i.gone_on) + ', last seen ' : 'seen ') + niceDate(i.last_seen);
    const stock = i.gone_on ? '' : stockLine(i);
    const why = i.why && i.why.length && i.stage !== '' && i.stage !== 'weak' ? i.why.filter(w => !/^0 in stock/.test(w)).join(' · ') : '';
    const ids = [i.sku ? 'SKU <b>' + esc(i.sku) + '</b>' : '', i.upc ? 'UPC ' + esc(i.upc) : ''].filter(Boolean).join(' · ');
    return `<button class="card deal ${i.stage ? 'st-' + i.stage : ''}" data-item="${esc(i.id)}">
      <div class="top">${thumb(i)}<div class="title">${esc(i.title)}</div>
        <div class="side"><div class="price">${money(i.price) || '—'}</div>${i.was ? `<div class="was">${money(i.was)}</div>` : ''}${prices.length > 1 ? '<div class="was">low</div>' : ''}${i.pct ? `<div class="pct">${i.pct}% off</div>` : ''}</div></div>
      ${ids ? `<div class="meta ids">${ids}</div>` : ''}
      <div class="meta dim">${esc(where)} · ${esc(seen)}</div>
      ${stock ? `<div class="meta dim stock">${esc(stock)}</div>` : ''}
      ${why ? `<div class="why">${esc(why)}</div>` : ''}
      <div class="tags">${tagsFor(i)}</div></button>`;
  }
  const sec = (title, n, sub) => `<div class="sec"><h2>${title}</h2><span>${n}</span></div>${sub ? `<p class="sub">${sub}</p>` : ''}`;
  function list(items, max, moreKey) {
    let h = items.slice(0, max).map(card).join('');
    if (items.length > max) h += `<button class="more" ${moreKey}>See all ${items.length}</button>`;
    return h;
  }
  function emptyLinks() {
    return `<div class="two"><a class="btn out" href="${PENNY_LIST}" target="_blank" rel="noopener">PennyCentral list</a><a class="btn out" href="${PAYDIRT}" target="_blank" rel="noopener">Paydirt list</a></div>`;
  }

  function todayView() {
    const ld = leads();
    const conf = grouped({ likely: false, stock: false }).filter(g => g.stage === 'confirmed');
    const confLeads = ld.filter(l => l.confirmed);
    const openLeads = ld.filter(l => !l.confirmed);
    const all = grouped({ likely: false });
    const hidden = grouped({ likely: false, stock: false }).filter(g => g.stage === 'hidden');
    const lateG = all.filter(g => g.stage === 'late');
    const rest = all.filter(g => g.stage === '' || g.stage === 'weak');
    const si = scanInfo();
    const paused = !!(S.data.status && S.data.status.ok === false);
    const confN = conf.length + confLeads.length;
    let h = `<p class="notice"><b>Pennies only show at the register.</b> Home Depot never posts $0.01 online, so these are candidates. The store may refuse; be polite.</p>`;
    h += filtersUI();
    if (confN) {
      h += sec('Confirmed 1¢', confN, 'Rang $0.01 at a register (your "Rang 1¢" marks).');
      h += list([...confLeads, ...conf], 6, 'data-goto="run"');
    } else h += `<p class="oneline"><b>Confirmed 1¢</b> · 0 — mark Rang 1¢ on a run to fill this <button type="button" class="textlink" id="emptyadd">Paste finds</button></p>`;
    if (openLeads.length) h += sec('Penny leads', openLeads.length, 'Your pasted community reports and trip notes. Unconfirmed until it rings up.') + list(openLeads, 6, 'data-goto="browse"');
    if (hidden.length) {
      h += sec('Likely penny · hidden price', hidden.length, 'Was deep clearance, then vanished from that store\'s list in a full scan. Best online sign of a penny (or it sold out).');
      h += list(hidden, 6, 'data-goto="browse" data-likely="1"');
    } else if (paused) h += `<p class="oneline"><b>Likely penny · hidden price</b> · 0</p>`;
    else h += `<p class="oneline"><b>Likely penny · hidden price</b> · 0 — fills in when a full scan drops an item</p>`;
    const shown = S.likely ? all.filter(g => g.stage === 'confirmed' || g.stage === 'hidden' || g.stage === 'late') : all;
    if (S.q && !shown.length && !ld.length) return h + `<div class="empty"><h3>Nothing matches "${esc(S.q)}"</h3><button class="btn tonal" id="clearq2">Clear search</button></div>`;
    h += sec('Late clearance · trip-worthy', lateG.length, `${CFG.minPct}%+ off or under ${money(CFG.maxPrice)}, after a markdown we saw or at ${CFG.noStepPct}%+ off. Tune it in Settings.`);
    h += lateG.length ? list(lateG, 6, 'data-goto="browse" data-likely="1"') : '<p class="sub empty-line">Nothing matches your filters.</p>';
    // Penny signals only: hide deep clearance, keep confirmed / hidden / late.
    if (!S.likely) {
      h += sec('Deep clearance', rest.length, `Store clearance ${S.data.feed?.min_pct || 50}%+ off from each store's last scan. Not pennies. "Likely sold out" items sit at the bottom.`);
      h += rest.length ? list(rest, S.limit, 'id="morebtn"') : '<p class="sub empty-line">Nothing else matches your filters.</p>';
    }
    if (si.unscanned.length) h += `<div class="tip"><b>${esc(si.unscanned.map(s => s.short).join(', '))}:</b> not scanned yet. It's next in line when the free scan credit renews.</div>`;
    return h;
  }

  function browse() {
    const g = grouped();
    const ld = S.likely ? leads().filter(l => !l.confirmed) : leads();
    let h = filtersUI() + sec((g.length + ld.length) + ' item' + (g.length + ld.length === 1 ? '' : 's'), '');
    if (!g.length && !ld.length) return h + (S.q ? `<div class="empty"><h3>Nothing matches "${esc(S.q)}"</h3><button class="btn tonal" id="clearq2">Clear search</button></div>` : '<div class="empty"><h3>Nothing matches these filters</h3></div>');
    const items = [...ld, ...g];
    h += items.slice(0, S.limit).map(card).join('');
    if (items.length > S.limit) h += `<button class="more" id="morebtn">Show more (${items.length - S.limit} left)</button>`;
    return h;
  }

  function runList() {
    const ids = Object.keys(S.run);
    const mine = ids.map(findItem).filter(Boolean);
    if (!mine.length) return `<div class="empty"><h3>Your run list is empty</h3><p>Open any item and tap "Add to run list" to plan a trip.</p><button class="btn tonal" data-tab="today">See today</button></div>`;
    const done = mine.filter(i => S.run[i.id] !== 'todo').length;
    let h = `<div class="sec"><h2>Store run</h2><span>${done} of ${mine.length} checked</span></div><div class="prog"><div style="width:${done / mine.length * 100}%"></div></div>
      <p class="sub">Scan the barcode on the box at self-checkout. "Stop-sale / blocked" means the register wouldn't sell it, which is not the same as "Not a penny".</p>`;
    const by = {};
    mine.forEach(i => { const k = i.store_id || ''; (by[k] = by[k] || []).push(i); });
    for (const [sid, group] of Object.entries(by)) {
      const st = S.data.stores.find(s => s.id === sid);
      h += `<div class="sec"><h2>${esc(st ? st.short : 'No store set')}</h2>${st && st.maps ? `<a class="textbtn" href="${esc(st.maps)}" target="_blank" rel="noopener">Directions</a>` : ''}</div>`;
      h += group.map(runRow).join('');
    }
    return h + '<button class="btn out" id="clearrun">Clear run list</button>';
  }
  function runRow(i) {
    const v = S.run[i.id];
    return `<div class="runitem"><button class="top" data-item="${esc(i.id)}">${thumb(i)}<div class="body"><div class="title">${esc(i.title)}</div>
      <div class="meta">${i.sku ? 'SKU <b>' + esc(i.sku) + '</b> · ' : ''}${money(i.price) || 'no price'}${i.pct ? ' · ' + i.pct + '% off' : ''}${i.last_seen ? ' · as of ' + niceDate(i.last_seen) : ''}</div></div></button>
      <div class="seg">${Object.entries(MARKS).map(([k, l]) =>
      `<button class="${k} ${v === k ? 'on' : ''}" data-mark="${esc(i.id)}" data-val="${k}" data-tripstore="${esc(i.store_id || '')}">${l}</button>`).join('')}</div></div>`;
  }

  function history() {
    const b = book();
    const trips = b.trips.slice().sort((a, c) => (c.date || '').localeCompare(a.date || ''));
    let h = `<div class="sec"><h2>Trip log</h2><span>${trips.length}</span></div><p class="sub">Marks stay on this phone until you export them.</p>`;
    h += !trips.length ? '<div class="empty small"><p>No trips recorded yet. Add items to your run list and mark what the register said.</p></div>'
      : '<div class="log">' + trips.map(t => {
        const it = findItem(t.lead_id);
        return `<div><span>${esc(niceDate(t.date))}${t.store_id ? ' · ' + esc(storeName(t.store_id)) : ''}<small>${esc(it ? it.title : t.lead_id)}</small></span><span>${esc(MARKS[t.mark] || t.mark)}</span></div>`;
      }).join('') + '</div>';
    h += `<div class="sec"><h2>Save / restore my marks</h2></div><div class="actions"><button class="btn fill" id="exportbtn">Export leads and trips</button>
      <button class="btn tonal" id="importbtn">Import JSON or a pasted list</button></div>`;
    const log = S.data.log || [];
    if (log.length) h += '<div class="sec"><h2>Recent builds</h2></div><div class="log">' + log.slice(-10).reverse().map(l =>
      `<div><span>${esc(niceDate(l.date))} · ${esc(l.store || '')}<small>${esc(l.note || '')}</small></span><span>${esc(l.source || '')}</span></div>`).join('') + '</div>';
    return h;
  }

  function draw() {
    applyTheme();
    header();
    $('#addfind').hidden = S.tab === 'run';
    view.innerHTML = ({ today: todayView, browse, run: runList, history })[S.tab]();
  }

  // ---------- sheets ----------
  function showSheet(html, state) {
    const swapping = !$('#sheet').hidden;
    $('#sheet').classList.toggle('guide', state === 'guide');
    $('#sheet').innerHTML = '<div class="grab"></div>' + html;
    $('#sheet').hidden = $('#scrim').hidden = false;
    $('#sheet').scrollTop = 0;
    const url = state && String(state).startsWith('item=') ? '#' + state : (location.hash || ' ');
    // Replacing the open sheet (Settings → How to use) must not history.back():
    // that popstate would run closeSheet and hide the guide immediately.
    if (swapping) window.history.replaceState({ sheet: state }, '', url);
    else window.history.pushState({ sheet: state }, '', url);
  }
  function closeSheet(fromPop) {
    if ($('#sheet').hidden) return;
    $('#sheet').hidden = $('#scrim').hidden = true;
    if (location.hash.startsWith('#item=')) window.history.replaceState(null, '', base());
    if (!fromPop && window.history.state && window.history.state.sheet) window.history.back();
  }
  window.addEventListener('popstate', () => closeSheet(true));
  const box = (label, val) => val ? `<button class="idbox" data-copy="${esc(val)}"><small>${label} · tap to copy</small><b>${esc(val)}</b></button>` : '';

  function openItem(id) {
    const i = findItem(id); if (!i) { toast('That item is no longer in the data'); return; }
    const runBtn = (rid, label) => `<button class="btn ${S.run[rid] ? 'tonal' : 'fill'}" data-run="${esc(rid)}">${S.run[rid] ? 'Remove from run list' : label || 'Add to run list'}</button>`;
    if (i.kind === 'lead') {
      const st = (i.stores || []).map(storeFull).join(', ');
      return showSheet(`<h2>${esc(i.title)}</h2><div class="meta">${esc([i.source === 'my_trip' ? 'My trip' : 'Community', st].filter(Boolean).join(' · '))}</div>
        <div class="big"><span class="price">${money(i.price) || '—'}</span></div>
        <div class="notice">${i.confirmed ? '<b>Rang 1¢ at the register.</b>' : '<b>Lead: unconfirmed until it rings up 1¢.</b> Check it in the HD app for your store, then scan the box at self-checkout.'}</div>
        ${i.notes ? `<p>${esc(i.notes)}</p>` : ''}<div class="ids">${box('SKU', i.sku)}${box('UPC', i.upc)}</div>${runBtn(i.id)}
        <div class="two"><a class="btn out" href="https://www.homedepot.com/s/${encodeURIComponent(i.sku || i.upc || i.title)}" target="_blank" rel="noopener">Home Depot</a><a class="btn out" href="${PENNY_LIST}" target="_blank" rel="noopener">Penny list</a></div>
        <div class="two"><button class="btn out" data-share="${esc(i.id)}">Share</button><button class="btn out" data-copyline="${esc(i.id)}">Copy line</button></div>
        <div class="hist"><div><span>Reported</span><span>${esc(niceDate(i.reported_at) || '—')}</span></div>${(i.trips || []).map(t => `<div><span>${esc(niceDate(t.date))}${t.store_id ? ' · ' + esc(storeName(t.store_id)) : ''}</span><span>${esc(MARKS[t.mark] || t.mark)}</span></div>`).join('')}</div>`, 'item=' + id);
    }
    const at = i.at || [i];
    const hist = (i.history || []).map(x => `${niceDate(x[0])} ${money(x[1])}`).join(' → ');
    showSheet(`<h2>${esc(i.title)}</h2>
      <div class="big"><span class="price">${money(i.price) || '—'}</span>${i.was ? `<span class="was">${money(i.was)}</span>` : ''}${i.pct ? `<span class="pct">${i.pct}% off</span>` : ''}</div>
      <div class="asof big2">Price as of ${esc(niceDate(i.last_seen))} (${esc(ago(i.last_seen))})</div>
      <div class="tags">${tagsFor(i)}</div>
      ${i.why && i.why.length ? `<ul class="whylist">${i.why.map(w => `<li>${esc(w)}</li>`).join('')}</ul>` : ''}
      ${i.stage === 'confirmed' ? '' : `<div class="notice"><b>Not a confirmed penny.</b> This is Home Depot's online store price from the last scan; pennies only show at the register. Scan the box, not the shelf tag. The store may refuse; be polite.</div>`}
      <div class="ids">${box('SKU', i.sku)}${box('UPC', i.upc)}</div>
      <div class="sec"><h2>At your stores</h2><span>${at.length}</span></div>
      <div class="atlist">${at.map(d => `<div class="atrow"><div class="atmain"><div class="athead"><b>${esc(storeName(d.store_id))}</b><button class="chip ${S.run[d.id] ? 'on' : ''}" data-run="${esc(d.id)}" data-keep="1">${S.run[d.id] ? 'On run' : '+ Run'}</button></div><span class="atprice">${money(d.price)}${d.pct ? ' · ' + d.pct + '% off' : ''}</span><small>${esc([d.gone_on ? 'dropped off ' + niceDate(d.gone_on) : 'seen ' + niceDate(d.last_seen), d.gone_on ? '' : stockLine(d)].filter(Boolean).join(' · '))}</small></div></div>`).join('')}</div>
      <div class="two">${i.link ? `<a class="btn out" href="${esc(i.link)}" target="_blank" rel="noopener">Home Depot page</a>` : '<span></span>'}<a class="btn out" href="${PENNY_LIST}" target="_blank" rel="noopener">Penny list</a></div>
      <div class="two"><button class="btn out" data-share="${esc(i.id)}">Share</button><button class="btn out" data-copyline="${esc(i.id)}">Copy line</button></div>
      <div class="hist">${[['Brand', i.brand], ['Model', i.model], ['Department', [i.group, i.dept].filter(Boolean).join(' · ')], ['First seen 50%+ off', niceDate(i.first_seen)], ['Price history', hist]].filter(r => r[1]).map(r => `<div><span>${esc(r[0])}</span><span>${esc(r[1])}</span></div>`).join('')}</div>`, 'item=' + id);
  }

  function openSettings() {
    const si = scanInfo(), f = S.data.feed || {}, cr = f.credit || {}, plan = f.plan || {};
    const opts = [{ id: 'all', name: 'All stores' }, ...stores()].map(s => `<option value="${esc(s.id)}" ${CFG.defStore === s.id ? 'selected' : ''}>${esc(s.name)}</option>`).join('');
    const rows = stores().map(s => { const p = si.per[s.id] || {}; return `<div><span>${esc(s.short)}</span><span>${p.last_scan ? niceDate(p.last_scan) + ' · ' + daysAgo(p.last_scan) + 'd · ' + (p.count || 0) + ' items' : 'not scanned yet'}</span></div>`; }).join('');
    showSheet(`<h2>Settings</h2>
      <div class="sec"><h2>Late clearance rule</h2><span id="latecount">${groups(deals().filter(late)).length} items</span></div>
      <div class="field"><label for="set-pct">Min % off</label><input id="set-pct" type="number" inputmode="numeric" min="50" max="99" value="${CFG.minPct}"></div>
      <div class="field"><label for="set-price">Or under this price ($)</label><input id="set-price" type="number" inputmode="decimal" step="0.05" min="0" value="${CFG.maxPrice}"></div>
      <div class="field"><label for="set-nostep">With no markdown seen yet, need at least this % off</label><input id="set-nostep" type="number" inputmode="numeric" min="50" max="99" value="${CFG.noStepPct}"></div>
      <div class="field"><label for="set-stale">Warn when data is this many days old</label><input id="set-stale" type="number" inputmode="numeric" min="1" max="30" value="${CFG.staleDays}"></div>
      <div class="field"><label for="set-store">Default store</label><select id="set-store">${opts}</select></div>
      <div class="setrow"><span>In stock only by default</span><button class="switch" id="set-stock" role="switch" aria-checked="${!!CFG.stockDef}"><i></i></button></div>
      <div class="setrow"><span>Light theme</span><button class="switch" id="set-light" role="switch" aria-checked="${!!CFG.light}"><i></i></button></div>
      <div class="sec"><h2>Data status</h2></div>
      <div class="hist">${rows}
        <div><span>Feed</span><span>${S.data.status && S.data.status.ok === false ? 'Paused' : 'On'}</span></div>
        ${settingsNote(S.data.status && S.data.status.note, cr)}
        ${plan.scans_per_month ? `<div><span>Cost plan</span><span>${plan.scans_per_month} scans/mo × $${plan.cap_per_scan.toFixed(2)} cap = $${plan.worst_case_usd.toFixed(2)} max (free credit $5). Each store about every ${plan.every_n_days} days.</span></div>` : ''}
        <div><span>Data built</span><span>${esc(niceDate(S.data.generated_at))}</span></div></div>
      <div class="sec"><h2>App</h2></div>
      <button class="btn out" id="shareapp">Share the app</button>
      <button class="btn out" id="guidebtn">How to use</button>
      <p class="sub">Install: tap Install at the top, or in Chrome open the ⋮ menu and choose "Add to Home screen".</p>
      <button class="btn out danger" id="resetmarks">Reset my marks and run list</button>`, 'settings');
  }
  function settingsNote(note, cr) {
    const raw = note || '';
    const usedUp = /apify credit/i.test(raw);
    if (usedUp) return `<div><span>Scan credit</span><span>Free scan credit used up for this month; scans resume when it renews</span></div>`;
    return `${raw ? `<div><span>Note</span><span>${esc(raw)}</span></div>` : ''}${cr && cr.used != null ? `<div><span>Scan credit</span><span>$${Number(cr.used).toFixed(2)} of $${Number(cr.cap || 5).toFixed(2)} used${cr.renews ? ', renews ' + niceDate(cr.renews) : ''}</span></div>` : ''}`;
  }
  function openGuide() {
    showSheet(`<h2>How to use Penny Run</h2><ol class="guide">
      <li><b>Pennies never show online.</b> Home Depot only shows $0.01 at the register. Everything here is a candidate until it scans.</li>
      <li><b>Confirmed 1¢</b> only comes from your own register mark ("Rang 1¢"). <b>Penny leads</b> are SKUs you paste from PennyCentral, Paydirt or a Facebook group (tap +).</li>
      <li><b>Likely penny · hidden price</b> = was deep clearance, then vanished from that store's list. <b>Late clearance</b> = 75%+ off or under $1 after a markdown, or 90%+ off. Deep clearance is everything else at 50%+ off.</li>
      <li>Check the SKU in the Home Depot app for your store, add it to your <b>Run List</b>, then scan the <b>box</b> barcode at self-checkout. Mark Rang 1¢, Stop-sale / blocked, Not a penny, Not there or Found.</li>
      <li>Every price shows the date it was seen. The store may refuse a penny; be polite and don't ask staff to hunt for it.</li></ol>
      <button class="btn fill" id="scrimclose">Got it</button>`, 'guide');
  }

  function openAdd() {
    const storeOpts = ['<option value="">Any store</option>'].concat(stores().map(s => `<option value="${esc(s.id)}" ${S.store === s.id ? 'selected' : ''}>${esc(s.name)}</option>`)).join('');
    showSheet(`<h2>Add a find</h2><p>Paste a SKU from a penny list, a Facebook post or your receipt. It stays on this phone.</p>
      <form id="findform">
        <div class="field"><label for="find-sku">SKU or UPC</label><input id="find-sku" maxlength="40" autocapitalize="off" inputmode="numeric"></div>
        <div class="field"><label for="find-name">Name</label><input id="find-name" maxlength="200"></div>
        <div class="field"><label for="find-store">Store</label><select id="find-store">${storeOpts}</select></div>
        <div class="field"><label for="find-date">Reported on</label><input id="find-date" type="date" value="${today()}"></div>
        <div class="field"><label for="find-source">Source</label><select id="find-source"><option value="community">Community list / group</option><option value="my_trip">My trip / receipt</option></select></div>
        <div class="field"><label for="find-price">Price reported</label><input id="find-price" inputmode="decimal" placeholder="0.01" value="0.01"></div>
        <div class="field"><label for="find-notes">Note</label><textarea id="find-notes" maxlength="500" placeholder="Where you saw it, state, receipt…"></textarea></div>
        <div class="field"><label for="find-paste">Or paste a whole list (one per line: SKU, price, name)</label><textarea id="find-paste" placeholder="1006-374-596, 0.01, Husky work light"></textarea></div>
        <button class="btn fill" type="submit">Save on this phone</button>
        ${emptyLinks()}
        <button class="btn out" id="find-cancel" type="button">Cancel</button></form>`, 'add');
  }
  function formLead() {
    const tok = $('#find-sku').value.trim(), name = $('#find-name').value.trim();
    const digits = tok.replace(/\D/g, '');
    const upc = digits.length >= 12 && digits === tok.replace(/[\s-]/g, '') && !tok.includes('-') ? digits : '';
    const sku = upc ? '' : tok.replace(/\s+/g, '');
    if (!sku && !upc && !name) { toast('Add a SKU, UPC, or name'); return null; }
    const pr = $('#find-price').value.trim(), price = pr === '' ? null : Number(pr.replace('$', ''));
    if (pr && Number.isNaN(price)) { toast('Price looks off'); return null; }
    const st = $('#find-store').value;
    return { id: nid(), sku, upc, name, stores: st ? [st] : [], source: $('#find-source').value, reported_price: price,
      reported_at: $('#find-date').value || today(), confirmed_at_register: false, notes: $('#find-notes').value.trim(), local: true, added_at: new Date().toISOString() };
  }
  function parsePaste(text, source, st) {
    const rows = [];
    for (const raw of (text || '').split(/\n+/)) {
      const line = raw.trim();
      if (!line || line.startsWith('#') || (/^(sku|upc|item)\b/i.test(line) && !/\d{3,}/.test(line))) continue;
      const parts = line.includes(',') ? line.split(',') : line.includes('\t') ? line.split('\t') : line.split(/\s{2,}|\s+(?=\$|\d+\.\d{2}\b)/);
      const p = parts.map(s => s.trim()).filter((s, i) => s || i);
      if (!p.length) continue;
      const tok = p[0], digits = tok.replace(/\D/g, '');
      let price = p[1] != null && p[1] !== '' ? Number(String(p[1]).replace(/[$,]/g, '')) : null;
      if (Number.isNaN(price)) price = null;
      const upc = (digits.length === 12 || digits.length === 13) && !tok.includes('-') ? digits : '';
      rows.push({ id: nid(), sku: upc ? '' : tok.replace(/\s+/g, ''), upc, name: p[2] || '', stores: st ? [st] : [], source: source || 'community',
        reported_price: price, reported_at: today(), confirmed_at_register: false, notes: p.slice(3).join(', '), local: true, added_at: new Date().toISOString() });
    }
    return rows;
  }
  function saveLeads(ls) {
    const b = localBook();
    b.leads = b.leads || [];
    for (const l of ls) { const i = b.leads.findIndex(x => x.id === l.id); if (i >= 0) b.leads[i] = l; else b.leads.push(l); }
    saveLocalBook(b);
  }
  function copyLine(i) {
    const line = i.kind === 'deal'
      ? `${i.title} | SKU ${i.sku || '-'} | UPC ${i.upc || '-'} | ${money(i.price)} (${i.pct || 0}% off) as of ${i.last_seen} | ${(i.at || [i]).map(x => storeName(x.store_id)).join(', ')}`
      : JSON.stringify(toLead(i));
    if (navigator.clipboard) navigator.clipboard.writeText(line).then(() => toast('Copied'), () => toast('Copy failed'));
    else toast(line);
  }

  function markTrip(id, val, sid) {
    const b = localBook(); b.trips = b.trips || []; b.leads = b.leads || [];
    const day = today(), cur = S.run[id] === val ? 'todo' : val;
    S.run[id] = cur; store.set('run', S.run);
    b.trips = b.trips.filter(t => !(t.lead_id === id && (t.store_id || '') === (sid || '') && t.date === day));
    if (cur !== 'todo') b.trips.push({ lead_id: id, store_id: sid || '', mark: cur, date: day });
    saveLocalBook(b);
    if (navigator.vibrate) navigator.vibrate(12);
    toast(cur === 'todo' ? 'Cleared today\'s mark' : MARKS[cur]);
    draw();
  }
  function exportBook() {
    const b = book();
    const blob = new Blob([JSON.stringify({ version: 1, leads: b.localLeads, trips: b.trips }, null, 2)], { type: 'application/json' });
    const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'penny-run-' + today() + '.json'; a.click();
    URL.revokeObjectURL(a.href); toast('Exported leads and trips');
  }
  function importPayload(text, name) {
    const tr = text.trim(); if (!tr) return toast('That file was empty');
    let ls = [], trips = [];
    try {
      if (tr.startsWith('{') || tr.startsWith('[')) { const d = JSON.parse(tr); if (Array.isArray(d)) ls = d; else { ls = d.leads || []; trips = d.trips || []; } }
      else ls = parsePaste(tr, 'community');
    } catch { return toast('Could not read that file'); }
    saveLeads(ls.map(l => ({ ...toLead({ ...l, id: l.id || nid() }), local: true })));
    const b = localBook(); const key = t => [t.lead_id, t.store_id || '', t.date].join('|');
    const m = new Map((b.trips || []).map(t => [key(t), t])); trips.forEach(t => m.set(key(t), t)); b.trips = [...m.values()]; saveLocalBook(b);
    toast('Imported ' + ls.length + ' from ' + (name || 'the paste')); S.tab = 'today'; closeSheet(); draw();
  }
  function share(title, text, url) {
    if (navigator.share) navigator.share({ title, text, url }).catch(() => { });
    else if (navigator.clipboard) navigator.clipboard.writeText(url).then(() => toast('Link copied'));
  }

  // ---------- routing (#item=…, #tab=run) ----------
  function route() {
    const h = decodeURIComponent(location.hash.slice(1));
    if (h.startsWith('tab=')) { const t = h.slice(4); if (['today', 'browse', 'run', 'history'].includes(t)) { S.tab = t; draw(); } }
    else if (h.startsWith('item=') && $('#sheet').hidden) openItem(h.slice(5));
  }
  window.addEventListener('hashchange', () => S.data && route());

  // ---------- events ----------
  document.addEventListener('click', e => {
    const t = e.target.closest('button,a[data-tab]');
    if (!t && e.target.id === 'scrim') return closeSheet();
    if (!t) return;
    const ds = t.dataset;
    if (t.id === 'retry' || t.id === 'refresh') { t.classList.add('spin'); return load().then(() => { t.classList.remove('spin'); if (t.id === 'refresh') toast(S.offline ? 'Offline. Showing saved data.' : 'Up to date'); }); }
    if (t.id === 'find-cancel' || t.id === 'scrimclose') return closeSheet();
    if (t.id === 'addfind' || t.id === 'emptyadd') return openAdd();
    if (t.id === 'settingsbtn') return openSettings();
    if (t.id === 'guidebtn') return openGuide();
    if (t.id === 'shareapp') return share('Penny Run', 'Home Depot penny candidates at my stores', base());
    if (t.id === 'resetmarks') { if (confirm('Clear all your marks, run list and pasted finds on this phone?')) { store.set('book', { leads: [], trips: [] }); S.run = {}; store.set('run', {}); closeSheet(); draw(); toast('Reset'); } return; }
    if (t.id === 'set-stock') { CFG.stockDef = !CFG.stockDef; S.stock = CFG.stockDef; saveCfg(); t.setAttribute('aria-checked', CFG.stockDef); return draw(); }
    if (t.id === 'set-light') { CFG.light = !CFG.light; saveCfg(); t.setAttribute('aria-checked', CFG.light); return applyTheme(); }
    if (t.id === 'exportbtn') return exportBook();
    if (t.id === 'importbtn') return $('#importfile').click();
    if (t.id === 'likelytog') { S.likely = !S.likely; S.limit = 12; return draw(); }
    if (t.id === 'stocktog') { S.stock = !S.stock; S.limit = 12; return draw(); }
    if (t.id === 'clearq' || t.id === 'clearq2') { S.q = ''; return draw(); }
    if (t.id === 'morebtn') { S.limit += 12; return draw(); }
    if (t.id === 'clearrun') { S.run = {}; store.set('run', S.run); toast('Run list cleared'); return draw(); }
    if (ds.group) { S.group = ds.group; S.limit = 12; return draw(); }
    if (ds.store) { S.store = ds.store; S.limit = 12; return draw(); }
    if (ds.goto) { S.tab = ds.goto; if (ds.likely) S.likely = true; S.limit = 12; draw(); return window.scrollTo(0, 0); }
    if (ds.tab) { S.tab = ds.tab; S.limit = 12; draw(); history_set(); return window.scrollTo(0, 0); }
    if (ds.mark) return markTrip(ds.mark, ds.val, ds.tripstore);
    if (ds.item) return openItem(ds.item);
    if (ds.run) {
      const id = ds.run;
      if (S.run[id]) { delete S.run[id]; toast('Removed from run list'); } else { S.run[id] = 'todo'; toast('Added to run list'); }
      store.set('run', S.run);
      if (ds.keep) { t.classList.toggle('on', !!S.run[id]); t.textContent = S.run[id] ? 'On run' : '+ Run'; header(); return; }
      closeSheet(); return draw();
    }
    if (ds.copy) { navigator.clipboard && navigator.clipboard.writeText(ds.copy).then(() => toast('Copied ' + ds.copy), () => toast(ds.copy)); return; }
    if (ds.copyline) { const i = findItem(ds.copyline); if (i) copyLine(i); return; }
    if (ds.share) {
      const i = findItem(ds.share); if (!i) return;
      const where = (i.at || [i]).map(x => storeName(x.store_id)).filter(Boolean).join(', ');
      return share('Penny Run', `${i.title}: ${money(i.price) || 'penny lead'}${i.pct ? ' (' + i.pct + '% off)' : ''}${i.last_seen ? ' as of ' + niceDate(i.last_seen) : ''}${where ? ' at ' + where : ''}. Confirm at the register.`, base() + '#item=' + encodeURIComponent(i.id));
    }
  });
  function history_set() { window.history.replaceState(null, '', S.tab === 'today' ? base() : base() + '#tab=' + S.tab); }
  document.addEventListener('change', e => {
    const id = e.target.id;
    if (id === 'sort') { S.sort = e.target.value; store.set('sort', S.sort); return draw(); }
    if (id === 'set-pct' || id === 'set-price' || id === 'set-stale' || id === 'set-store' || id === 'set-nostep') {
      const v = e.target.value;
      if (id === 'set-pct') CFG.minPct = Math.min(99, Math.max(50, Number(v) || DEF.minPct));
      if (id === 'set-price') CFG.maxPrice = Math.max(0, Number(v) || 0);
      if (id === 'set-nostep') CFG.noStepPct = Math.min(99, Math.max(50, Number(v) || DEF.noStepPct));
      if (id === 'set-stale') CFG.staleDays = Math.max(1, Number(v) || DEF.staleDays);
      if (id === 'set-store') { CFG.defStore = v; S.store = v; }
      saveCfg(); draw();
      const lc = $('#latecount'); if (lc) lc.textContent = groups(deals().filter(late)).length + ' items';
    }
  });
  document.addEventListener('input', e => {
    if (e.target.id === 'q') {
      S.q = e.target.value; S.limit = 12;
      clearTimeout(S.qt); S.qt = setTimeout(() => { draw(); const q = $('#q'); if (q) { q.focus(); q.setSelectionRange(q.value.length, q.value.length); } }, 200);
    }
    if (['set-pct', 'set-price', 'set-nostep'].includes(e.target.id)) {
      const keep = [CFG.minPct, CFG.maxPrice, CFG.noStepPct];
      CFG.minPct = Number($('#set-pct').value) || CFG.minPct;
      const pr = Number($('#set-price').value); if (Number.isFinite(pr)) CFG.maxPrice = pr;
      CFG.noStepPct = Number($('#set-nostep').value) || CFG.noStepPct;
      $('#latecount').textContent = groups(deals().filter(late)).length + ' items';
      [CFG.minPct, CFG.maxPrice, CFG.noStepPct] = keep;
    }
  });
  document.addEventListener('submit', e => {
    if (e.target.id !== 'findform') return;
    e.preventDefault();
    const paste = $('#find-paste').value;
    let ls = paste.trim() ? parsePaste(paste, $('#find-source').value, $('#find-store').value) : [];
    if (!ls.length) { const l = formLead(); if (!l) return; ls = [l]; }
    saveLeads(ls);
    toast(ls.length === 1 ? 'Saved on this phone' : 'Saved ' + ls.length + ' leads');
    closeSheet(); S.tab = 'today'; draw();
  });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeSheet(); });
  $('#importfile').addEventListener('change', ev => {
    const f = ev.target.files && ev.target.files[0]; ev.target.value = '';
    if (f) f.text().then(t => importPayload(t, f.name)).catch(() => toast('Could not read that file'));
  });
  document.addEventListener('visibilitychange', () => { if (!document.hidden && S.data && Date.now() - (S.loaded || 0) > 6e5) load(); });

  let deferred;
  window.addEventListener('beforeinstallprompt', e => { e.preventDefault(); deferred = e; $('#install').hidden = false; });
  $('#install').addEventListener('click', async () => { if (!deferred) return; deferred.prompt(); await deferred.userChoice; deferred = null; $('#install').hidden = true; });
  if ('serviceWorker' in navigator) navigator.serviceWorker.register('sw.js').catch(() => { });
  applyTheme();
  load();
})();
