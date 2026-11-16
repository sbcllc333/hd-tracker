/* Penny Run — reads data.json and draws the app. No build step, no server. */
(() => {
  const $ = (s, el = document) => el.querySelector(s);
  const view = $('#view');
  const store = {
    get(k, d) { try { const v = localStorage.getItem('pr_' + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
    set(k, v) { try { localStorage.setItem('pr_' + k, JSON.stringify(v)); } catch { /* private mode */ } }
  };
  const S = {
    data: null, tab: 'today', store: store.get('store', 'all'), dept: 'all', sort: 'score', q: '',
    retailer: store.get('retailer', 'homedepot'), picks: store.get('picks', {}), run: store.get('run', {}), limit: 30, offline: false, pennyOnly: false, stock: store.get('stock', true)
  };
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const money = v => v == null ? '' : '$' + Number(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const dayMs = 864e5;
  const daysAgo = iso => iso ? Math.max(0, Math.round((Date.now() - new Date(iso.length > 10 ? iso : iso + 'T12:00:00').getTime()) / dayMs)) : null;
  const ago = iso => { const d = daysAgo(iso); return d == null ? 'never' : d === 0 ? 'today' : d === 1 ? 'yesterday' : d + ' days ago'; };
  const niceDate = iso => iso ? new Date(iso.length > 10 ? iso : iso + 'T12:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) : '';
  const RNAME = { homedepot: 'Home Depot', walmart: 'Walmart', bestbuy: 'Best Buy' };
  const kind = s => s.retailer || 'homedepot';
  const myStores = () => S.data.stores.filter(s => kind(s) === S.retailer);
  const myItems = () => { const ids = new Set(myStores().map(s => s.id)); return S.data.items.filter(i => ids.has(i.store_id)); };
  const pickStore = () => { const m = myStores(); const want = S.picks[S.retailer]; S.store = m.length === 1 ? m[0].id : (m.some(s => s.id === want) ? want : 'all'); };
  const storeName = id => (S.data.stores.find(s => s.id === id) || {}).short || id;
  const cap = s => s ? s[0].toUpperCase() + s.slice(1) : '';

  function toast(msg) {
    const t = $('#toast'); t.textContent = msg; t.hidden = false;
    clearTimeout(toast.t); toast.t = setTimeout(() => (t.hidden = true), 1800);
  }

  // ---------- data ----------
  async function load() {
    if (!S.data) view.innerHTML = '<div class="skel"></div>'.repeat(5);
    try {
      const r = await fetch('data.json?t=' + Math.floor(Date.now() / 6e4), { cache: 'no-store' });
      if (!r.ok) throw new Error(r.status);
      S.data = await r.json(); S.offline = false; store.set('cache', S.data);
    } catch {
      S.data = store.get('cache', null); S.offline = true;
    }
    if (!S.data) {
      view.innerHTML = '<div class="empty"><h3>Can\'t load right now</h3><p>Check your signal and pull down to try again.</p></div>';
      $('#updated').textContent = 'No data yet';
      return;
    }
    if (!S.data.stores.some(s => kind(s) === S.retailer)) S.retailer = kind(S.data.stores[0] || {});
    if (S.picks[S.retailer] == null && S.retailer === 'homedepot') S.picks.homedepot = store.get('store', 'all');
    pickStore();
    draw();
  }
  const inStore = () => myItems().filter(i => S.store === 'all' || i.store_id === S.store);
  const items = () => inStore().filter(i => (!S.stock || i.qty !== 0) && (S.dept === 'all' || i.dept === S.dept));
  const deptChips = () => {
    const have = new Set(inStore().map(i => i.dept));
    const depts = ['all', ...S.data.departments.filter(d => have.has(d) || d === S.dept)];
    return `<div class="chips row">${depts.map(d => `<button class="chip ${S.dept === d ? 'on' : ''}" data-dept="${esc(d)}">${d === 'all' ? 'All' : esc(cap(d))}</button>`).join('')}</div>`;
  };

  // ---------- pieces ----------
  function header() {
    const d = S.data, age = daysAgo(d.generated_at);
    const scans = myStores().map(s => s.last_scan).filter(Boolean).sort();
    const newest = scans[scans.length - 1];
    $('#updated').textContent = newest ? 'Last store scan ' + ago(newest) : 'Waiting for the first scan';
    const b = $('#banner'); let msg = '';
    if (S.offline) msg = 'Offline. Showing saved data from ' + niceDate(d.generated_at) + '.';
    else if (d.status && d.status.ok === false && d.status.note) msg = d.status.note;
    else if (age != null && age > 2) msg = 'Data is ' + age + ' days old. The daily scan may not be running.';
    else if (S.store !== 'all') {
      const st = d.stores.find(s => s.id === S.store);
      if (st && daysAgo(st.last_scan) > 6) msg = st.short + ' was last scanned ' + ago(st.last_scan) + '.';
    }
    b.textContent = msg; b.hidden = !msg;
    const kinds = [...new Set(d.stores.map(kind))];
    $('#retailers').hidden = kinds.length < 2;
    $('#retailers').innerHTML = kinds.map(k => `<button class="${S.retailer === k ? 'on' : ''}" data-retailer="${esc(k)}">${esc(RNAME[k] || k)}</button>`).join('');
    const mine = myStores();
    $('#stores').hidden = mine.length < 2;
    $('#stores').innerHTML = [{ id: 'all', short: 'All ' + mine.length + ' stores' }, ...mine].map(s =>
      `<button class="chip ${S.store === s.id ? 'on' : ''}" data-store="${esc(s.id)}">${esc(s.short)}</button>`).join('');
    const hidden = inStore().filter(i => i.qty === 0).length;
    $('#stockrow').hidden = S.tab === 'run' || S.tab === 'history';
    $('#stock').setAttribute('aria-checked', S.stock);
    $('#stocknote').textContent = S.stock ? (hidden ? hidden + ' with 0 in the system hidden' + (S.tab === 'today' && S.retailer !== 'walmart' ? ', except possible pennies' : '') : 'Nothing hidden') : 'Showing everything';
    const mineIds = new Set(myItems().map(i => i.id));
    const n = Object.keys(S.run).filter(id => mineIds.has(id)).length, rc = $('#runcount');
    rc.hidden = !n; rc.textContent = n;
    document.querySelectorAll('.nav button').forEach(b => b.classList.toggle('on', b.dataset.tab === S.tab));
  }

  // Home Depot only: signs an item may ring up at a penny. A lead to check, never a promise.
  function pennyWhy(i) {
    if (i.retailer === 'walmart') return [];
    const w = [];
    if (i.gone === 'unlisted') w.push('was on clearance and is no longer listed at this store');
    if (i.missed) return w;
    if (i.discontinued) w.push('confirmed discontinued');
    if (i.pct >= 85) w.push(i.pct + '% off, the last markdown step');
    if ((i.ending === 2 || i.ending === 3) && i.clearance) w.push('price ends in .0' + i.ending);
    if (i.price <= 1) w.push('already under $1');
    return w;
  }
  const isPenny = i => pennyWhy(i).length > 0;
  const coin = i => isPenny(i) ? '<span class="coin" aria-label="Possible penny">1¢</span>' : '';

  function tags(i) {
    const t = [];
    if (isPenny(i)) t.push('<span class="tag penny">Possible penny</span>');
    if (i.discontinued) t.push('<span class="tag drop">Discontinued</span>');
    if (i.ending === 3 || i.ending === 2) t.push(`<span class="tag warn">Ends .0${i.ending}</span>`);
    else if (i.ending === 6 || i.ending === 4) t.push(`<span class="tag plain">Ends .0${i.ending}</span>`);
    if (i.qty != null && i.qty > 0 && i.qty <= 5) t.push(`<span class="tag warn">${i.qty} left</span>`);
    else if (i.qty === 0 && i.clearance && !i.missed) t.push('<span class="tag warn">0 in system</span>');
    if (i.gone === 'unlisted') t.push('<span class="tag drop">No longer listed</span>');
    else if (i.gone === 'fullprice') t.push('<span class="tag plain">Back to full price</span>');
    else if (i.missed >= 1) t.push('<span class="tag plain">Missed in last scan</span>');
    if (S.store === 'all') t.push(`<span class="tag plain">${esc(storeName(i.store_id))}</span>`);
    if (S.run[i.id]) t.push('<span class="tag ok">On run list</span>');
    return t.join('');
  }
  const thumb = i => `<div class="tw">${coin(i)}<div class="thumb">${i.thumb ? `<img src="${esc(i.thumb)}" alt="" loading="lazy" onerror="this.remove()">` : ''}${esc((i.dept || '?')[0].toUpperCase())}</div></div>`;
  function card(i) {
    const was = i.was || (i.prev_price > i.price ? i.prev_price : null);
    return `<button class="card${isPenny(i) ? ' pennycard' : ''}" data-item="${esc(i.id)}">${thumb(i)}
      <div class="body"><div class="title">${esc(i.title)}</div>
        <div class="meta">${esc(i.brand || i.cat || cap(i.dept))}${i.model ? ' · <b>' + esc(i.model) + '</b>' : ''}</div>
        <div class="tags">${tags(i)}</div></div>
      <div class="side"><div class="price">${money(i.price)}</div>
        ${was ? `<div class="was">${money(was)}</div>` : ''}
        ${i.pct ? `<div class="pct">−${i.pct}%</div>` : ''}
        ${i.score >= 20 ? `<div class="score">Score ${i.score}</div>` : ''}</div></button>`;
  }
  const section = (title, list, sub, max = 8) => !list.length ? '' :
    `<div class="sec"><h2>${title}</h2><span>${list.length}</span></div>${sub ? `<p class="sub">${sub}</p>` : ''}` +
    list.slice(0, max).map(card).join('') +
    (list.length > max ? `<button class="more" data-goto="${title}">See all ${list.length}</button>` : '');

  // ---------- tabs ----------
  function today() {
    const everything = items();
    const gone = everything.filter(i => i.gone === 'unlisted' && i.missed <= 4).sort((a, b) => (b.missing_since || '').localeCompare(a.missing_since || '') || b.score - a.score);
    const byDept = i => S.dept === 'all' || i.dept === S.dept;
    const pennies = inStore().filter(i => byDept(i) && isPenny(i)).sort((a, b) => (b.gone === 'unlisted') - (a.gone === 'unlisted') || (b.qty > 0) - (a.qty > 0) || (b.pct || 0) - (a.pct || 0));
    const all = everything.filter(i => !i.missed && !isPenny(i));
    const hot = all.filter(i => i.score >= 45);
    const drops = all.filter(i => i.prev_price > i.price && daysAgo(i.price_changed_on) <= 8).sort((a, b) => (b.prev_price - b.price) / b.prev_price - (a.prev_price - a.price) / a.prev_price);
    const disc = all.filter(i => i.discontinued);
    const low = all.filter(i => (i.ending === 3 || i.ending === 2) && i.score < 45);
    const deep = all.filter(i => i.pct >= 40 && i.score < 45 && !(i.ending === 3 || i.ending === 2)).sort((a, b) => b.pct - a.pct);
    const gone2 = gone.filter(i => !isPenny(i));
    let h = deptChips() + section('Possible pennies', pennies, 'Worth a shelf check. Most show 0 in the system, so the shelf may be empty. Scan at the register to know for sure.', 10) + section('No longer listed at the store', gone2, 'Was on clearance, and a direct lookup no longer finds it at this store. Not proof of a penny, but the best lead. Scan it at the register.') +
      section('Highest scores', hot, 'Deep discount, long on clearance, low stock.') +
      section('Price drops', drops, 'Marked down since the last scan.') +
      section('Confirmed discontinued', disc, 'No longer sold. Still on the shelf? Scan it.') +
      section('Ends in .03 or .02', low, 'Often the last markdown before a penny.') +
      section('Deep clearance', deep, '40% off or more.') +
      section('Other clearance', all.filter(i => i.clearance && i.score < 45 && !(i.pct >= 40) && !(i.ending === 3 || i.ending === 2)), 'On clearance at a smaller discount.');
    if (h === deptChips()) {
      const where = (S.dept === 'all' ? '' : cap(S.dept) + ' at ') + (S.store === 'all' ? 'your ' + (RNAME[S.retailer] || '') + ' stores' : storeName(S.store));
      h = deptChips() + `<div class="empty"><h3>Nothing ${S.stock ? 'in stock ' : ''}for ${esc(where)} right now</h3>
        <p>${S.stock ? 'Turn off "In stock only" to see items showing 0 in the system.' : 'Clearance finds show up here after each store scan.'}</p>
        ${everything.length ? `<button class="btn tonal" data-tab="browse">Browse all ${everything.length} tracked items</button>` : ''}</div>`;
    }
    h += `<div class="tip"><b>In the store:</b> scan the barcode on the box at self-checkout, not the shelf tag. The register price is the only proof of a penny.</div>`;
    return h;
  }

  function browse() {
    const q = S.q.trim().toLowerCase();
    const pool = S.pennyOnly ? inStore().filter(isPenny) : items();
    let list = pool.filter(i => (S.dept === 'all' || i.dept === S.dept) &&
      (!q || (i.title + ' ' + i.brand + ' ' + i.model + ' ' + i.pid + ' ' + i.sku + ' ' + i.upc).toLowerCase().includes(q)));
    const by = {
      score: (a, b) => b.score - a.score || (b.pct || 0) - (a.pct || 0),
      pct: (a, b) => (b.pct || 0) - (a.pct || 0),
      low: (a, b) => a.price - b.price, high: (a, b) => b.price - a.price,
      new: (a, b) => (b.first_seen || '').localeCompare(a.first_seen || '')
    };
    list.sort(by[S.sort]);
    return `<input class="search" id="q" type="search" placeholder="Search name, brand, model or SKU" value="${esc(S.q)}" autocomplete="off">
      ${deptChips()}
      ${S.retailer === 'walmart' ? '' : `<div class="row" style="margin-top:0;padding-top:0"><button class="chip pennychip ${S.pennyOnly ? 'on' : ''}" data-penny="1"><span class="coin inline">1¢</span> Possible pennies only</button></div>`}
      <div class="sec"><h2>${list.length} item${list.length === 1 ? '' : 's'}</h2>
        <select id="sort" aria-label="Sort">${[['score', 'Best score'], ['pct', 'Biggest % off'], ['low', 'Price: low'], ['high', 'Price: high'], ['new', 'Newest']]
        .map(([v, l]) => `<option value="${v}" ${S.sort === v ? 'selected' : ''}>${l}</option>`).join('')}</select></div>
      <div id="list">${list.slice(0, S.limit).map(card).join('') || '<div class="empty"><h3>Nothing matches</h3><p>Try a different word or department.</p></div>'}</div>
      ${list.length > S.limit ? `<button class="more" id="morebtn">Show more (${list.length - S.limit} left)</button>` : ''}`;
  }

  function runList() {
    const ids = Object.keys(S.run), byId = Object.fromEntries(myItems().map(i => [i.id, i]));
    const mine = ids.map(id => byId[id]).filter(Boolean).filter(i => S.store === 'all' || i.store_id === S.store);
    if (!mine.length) return `<div class="empty"><h3>Your run list is empty</h3><p>Open any item and tap "Add to run list" to plan a store trip.</p><button class="btn tonal" data-tab="today">See today's finds</button></div>`;
    const done = mine.filter(i => S.run[i.id] !== 'todo').length;
    let h = `<div class="sec"><h2>Store run</h2><span>${done} of ${mine.length} checked</span></div><div class="prog"><div style="width:${done / mine.length * 100}%"></div></div>`;
    for (const st of myStores()) {
      const group = mine.filter(i => i.store_id === st.id);
      if (!group.length) continue;
      h += `<div class="sec"><h2>${esc(st.short)}</h2>${st.maps ? `<a class="textbtn" href="${esc(st.maps)}" target="_blank" rel="noopener">Directions</a>` : ''}</div>`;
      h += group.map(i => {
        const v = S.run[i.id];
        return `<div class="runitem"><button class="top" data-item="${esc(i.id)}">${thumb(i)}<div class="body"><div class="title">${esc(i.title)}</div>
          <div class="meta">${i.model ? '<b>' + esc(i.model) + '</b> · ' : ''}${money(i.price)}${i.pct ? ' · −' + i.pct + '%' : ''}</div></div></button>
          <div class="seg">${[['found', 'Found'], ['gone', 'Not there'], ['full', 'Full price']].map(([k, l]) =>
          `<button class="${k} ${v === k ? 'on' : ''}" data-mark="${esc(i.id)}" data-val="${k}">${l}</button>`).join('')}</div></div>`;
      }).join('');
    }
    return h + '<button class="btn out" id="clearrun">Clear run list</button>';
  }

  function history() {
    const disc = inStore().filter(i => i.discontinued).sort((a, b) => (b.discontinued_on || '').localeCompare(a.discontinued_on || ''));
    const d = S.data;
    let h = disc.length ? section('Discontinued log', disc, 'Newest first.', 50) :
      '<div class="sec"><h2>Discontinued log</h2></div><p class="sub">Nothing confirmed discontinued yet. Items land here once a check confirms it.</p>';
    h += '<div class="sec"><h2>Store scans</h2></div><div class="log">' + myStores().map(s =>
      `<div><span>${esc(s.name)}</span><span>${esc(ago(s.last_scan))}</span></div>`).join('') + '</div>';
    const names = new Set(d.stores.filter(s => kind(s) !== S.retailer).map(s => s.name));
    const log = (d.log || []).filter(l => !names.has(l.store) && (S.retailer === 'homedepot' || myStores().some(s => s.name === l.store)));
    if (log.length) h += '<div class="sec"><h2>Recent runs</h2></div><div class="log">' + log.slice().reverse().map(l =>
      `<div><span>${esc(niceDate(l.date))} · ${esc(l.store)}<small>${esc(l.note || (l.items + ' clearance items'))}${l.discontinued_check ? ' · discontinued: ' + esc(l.discontinued_check) : ''}</small></span><span>${esc(l.source || '')}</span></div>`).join('') + '</div>';
    h += S.retailer === 'walmart'
      ? `<div class="tip">Each Walmart is scanned a few departments a day. Electronics, Home Improvement, Garden, Auto, Video Games, Cell Phones and Office refresh weekly; the rest rotate behind them.</div>`
      : `<div class="tip">One Home Depot store is scanned each day, so each is refreshed about every ${myStores().length} days. Scores run 0 to 100: discount depth, weeks on clearance, low or zero stock, price ending and discontinued status.</div>
      <a class="btn out" href="https://www.pennycentral.com/penny-list" target="_blank" rel="noopener">Open PennyCentral's penny list</a>`;
    return h;
  }

  function draw() {
    header();
    view.innerHTML = ({ today, browse, run: runList, history })[S.tab]();
  }

  // ---------- detail sheet ----------
  function openSheet(id) {
    const i = S.data.items.find(x => x.id === id); if (!i) return;
    const st = S.data.stores.find(s => s.id === i.store_id) || {};
    const was = i.was || (i.prev_price > i.price ? i.prev_price : null);
    const box = (label, val) => val ? `<button class="idbox" data-copy="${esc(val)}"><small>${label} · tap to copy</small><b>${esc(val)}</b></button>` : '';
    $('#sheet').innerHTML = `<div class="grab"></div><h2>${esc(i.title)}</h2>
      <div class="meta">${esc([i.brand, i.cat, st.name].filter(Boolean).join(' · '))}</div>
      <div class="big"><span class="price">${money(i.price)}</span>${was ? `<span class="was">${money(was)}</span>` : ''}${i.pct ? `<span class="pct">−${i.pct}%</span>` : ''}</div>
      ${isPenny(i) ? `<div class="pennybox"><span class="coin big">1¢</span><div><b>Possible penny</b><span>${esc(pennyWhy(i).join('; '))}. Not guaranteed. Scan it at the register.</span></div></div>` : ''}
      <ul class="why">${i.score ? `<li class="tag">Score ${i.score}</li>` : ''}${(i.why || []).map(w => `<li class="tag plain">${esc(w)}</li>`).join('')}</ul>
      <div class="ids">${box('Model', i.model)}${box(i.retailer === 'walmart' ? 'Walmart item #' : 'Internet #', i.pid)}${box('Store SKU', i.sku)}${box('UPC', i.upc)}</div>
      <button class="btn ${S.run[i.id] ? 'tonal' : 'fill'}" data-run="${esc(i.id)}">${S.run[i.id] ? 'Remove from run list' : 'Add to run list'}</button>
      <div class="two"><a class="btn out" href="${esc(i.link)}" target="_blank" rel="noopener">Product page</a>
        ${st.maps ? `<a class="btn out" href="${esc(st.maps)}" target="_blank" rel="noopener">Directions</a>` : '<span></span>'}</div>
      <div class="two">${i.retailer === 'walmart' ? '<span></span>' : '<a class="btn out" href="https://www.pennycentral.com/penny-list" target="_blank" rel="noopener">Penny list</a>'}
        <button class="btn out" data-share="${esc(i.id)}">Share</button></div>
      <div class="hist"><div><span>First tracked</span><span>${esc(niceDate(i.first_seen))}</span></div>
        ${i.first_clearance ? `<div><span>On clearance since</span><span>${esc(niceDate(i.first_clearance))}</span></div>` : ''}
        <div><span>Last seen in a scan</span><span>${esc(ago(i.last_seen))}</span></div>
        ${i.qty != null ? `<div><span>Store system count</span><span>${i.qty}</span></div>` : ''}
        ${i.gone === 'unlisted' ? `<div><span>No longer listed since</span><span>${esc(niceDate(i.missing_since))}</span></div>` : ''}
        ${i.gone === 'fullprice' ? `<div><span>Back to full price</span><span>${money(i.now_price)}</span></div>` : ''}
        ${(i.history || []).slice().reverse().map(([d, p]) => `<div><span>${esc(niceDate(d))}</span><span>${money(p)}</span></div>`).join('')}</div>`;
    $('#sheet').hidden = $('#scrim').hidden = false;
    window.history.pushState({ sheet: 1 }, '');
  }
  function closeSheet(fromPop) {
    if ($('#sheet').hidden) return;
    $('#sheet').hidden = $('#scrim').hidden = true;
    if (!fromPop && window.history.state && window.history.state.sheet) window.history.back();
  }
  window.addEventListener('popstate', () => closeSheet(true));

  // ---------- events ----------
  document.addEventListener('click', e => {
    const t = e.target.closest('[data-penny],[data-retailer],[data-store],[data-tab],[data-item],[data-dept],[data-run],[data-mark],[data-copy],[data-share],[data-goto],#morebtn,#clearrun,#scrim,#stock,#refresh');
    if (!t) return;
    if (t.id === 'scrim') return closeSheet();
    if (t.id === 'refresh') { t.classList.add('spin'); return load().then(() => { S.loaded = Date.now(); t.classList.remove('spin'); toast(S.offline ? 'Offline. Showing saved data.' : 'Up to date'); }); }
    if (t.id === 'stock') { S.stock = !S.stock; store.set('stock', S.stock); S.limit = 30; return draw(); }
    if (t.dataset.retailer) { S.pennyOnly = false; S.retailer = t.dataset.retailer; store.set('retailer', S.retailer); S.dept = 'all'; S.q = ''; S.limit = 30; pickStore(); draw(); return window.scrollTo(0, 0); }
    if (t.dataset.store) { S.store = t.dataset.store; S.picks[S.retailer] = S.store; store.set('picks', S.picks); S.limit = 30; return draw(); }
    if (t.dataset.tab) { S.tab = t.dataset.tab; S.limit = 30; draw(); return window.scrollTo(0, 0); }
    if (t.dataset.goto) { S.pennyOnly = t.dataset.goto === 'Possible pennies'; S.tab = 'browse'; S.sort = t.dataset.goto === 'Deep clearance' ? 'pct' : 'score'; draw(); return window.scrollTo(0, 0); }
    if (t.dataset.item) return openSheet(t.dataset.item);
    if (t.dataset.penny) { S.pennyOnly = !S.pennyOnly; S.limit = 30; return draw(); }
    if (t.dataset.dept) { S.dept = t.dataset.dept; S.limit = 30; return draw(); }
    if (t.dataset.run) {
      const id = t.dataset.run;
      if (S.run[id]) { delete S.run[id]; toast('Removed from run list'); } else { S.run[id] = 'todo'; toast('Added to run list'); }
      store.set('run', S.run); closeSheet(); return draw();
    }
    if (t.dataset.mark) {
      const id = t.dataset.mark; S.run[id] = S.run[id] === t.dataset.val ? 'todo' : t.dataset.val;
      store.set('run', S.run); if (navigator.vibrate) navigator.vibrate(12); return draw();
    }
    if (t.dataset.copy) { navigator.clipboard && navigator.clipboard.writeText(t.dataset.copy).then(() => toast('Copied ' + t.dataset.copy), () => toast(t.dataset.copy)); return; }
    if (t.dataset.share) {
      const i = S.data.items.find(x => x.id === t.dataset.share);
      const text = `${i.title} — ${money(i.price)}${i.pct ? ' (' + i.pct + '% off)' : ''} at ${storeName(i.store_id)}`;
      if (navigator.share) navigator.share({ title: 'Penny Run', text, url: i.link }).catch(() => { });
      else navigator.clipboard && navigator.clipboard.writeText(text + ' ' + i.link).then(() => toast('Copied'));
      return;
    }
    if (t.id === 'morebtn') { S.limit += 30; return draw(); }
    if (t.id === 'clearrun') { for (const i of myItems()) delete S.run[i.id]; store.set('run', S.run); toast('Run list cleared'); return draw(); }
  });
  document.addEventListener('input', e => {
    if (e.target.id === 'q') {
      S.q = e.target.value; S.limit = 30;
      clearTimeout(S.qt); S.qt = setTimeout(() => { draw(); const q = $('#q'); q.focus(); q.setSelectionRange(q.value.length, q.value.length); }, 180);
    }
  });
  document.addEventListener('change', e => { if (e.target.id === 'sort') { S.sort = e.target.value; draw(); } });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeSheet(); });
  document.addEventListener('visibilitychange', () => { if (!document.hidden && S.data && Date.now() - (S.loaded || 0) > 6e5) load(); });

  // install button
  let deferred;
  window.addEventListener('beforeinstallprompt', e => { e.preventDefault(); deferred = e; $('#install').hidden = false; });
  $('#install').addEventListener('click', async () => { if (!deferred) return; deferred.prompt(); await deferred.userChoice; deferred = null; $('#install').hidden = true; });
  const ios = /iphone|ipad|ipod/i.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  const standalone = window.matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
  if (ios && !standalone) {
    $('#install').hidden = false;
    $('#install').addEventListener('click', () => {
      $('#sheet').innerHTML = '<div class="grab"></div><h2>Add Penny Run to your iPhone</h2><p>1. Open this page in Safari.</p><p>2. Tap the Share button (the square with an arrow).</p><p>3. Tap "Add to Home Screen", then "Add".</p><button class="btn fill" id="scrimclose">Got it</button>';
      $('#sheet').hidden = $('#scrim').hidden = false;
      $('#scrimclose').onclick = () => closeSheet();
    });
  }
  if ('serviceWorker' in navigator) navigator.serviceWorker.register('sw.js').catch(() => { });

  load().then(() => (S.loaded = Date.now()));
})();
