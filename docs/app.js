/* Penny Run — daily Home Depot deep-clearance feed plus community and trip leads. No build step, no server. */
(() => {
  const $ = (s, el = document) => el.querySelector(s);
  const view = $('#view');
  const store = {
    get(k, d) { try { const v = localStorage.getItem('pr_' + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
    set(k, v) { try { localStorage.setItem('pr_' + k, JSON.stringify(v)); } catch { /* private mode */ } }
  };
  const S = {
    data: null, tab: 'today', store: store.get('store', 'all'), q: '',
    retailer: store.get('retailer', 'homedepot'), picks: store.get('picks', {}),
    run: store.get('run', {}), limit: 30, offline: false, showDemoted: store.get('showDemoted', true)
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
  const RNAME = { homedepot: 'Home Depot', walmart: 'Walmart' };
  const kind = s => s.retailer || 'homedepot';
  const myStores = () => (S.data.stores || []).filter(s => kind(s) === S.retailer);
  const pickStore = () => {
    const m = myStores();
    const want = S.picks[S.retailer];
    S.store = m.length === 1 ? m[0].id : (m.some(s => s.id === want) ? want : (want === 'all' || !want ? 'all' : 'all'));
  };
  const storeName = id => (S.data.stores.find(s => s.id === id) || {}).short || id;
  const storeFull = id => (S.data.stores.find(s => s.id === id) || {}).name || id;

  function toast(msg) {
    const t = $('#toast'); t.textContent = msg; t.hidden = false;
    clearTimeout(toast.t); toast.t = setTimeout(() => (t.hidden = true), 1800);
  }

  const MARKS = {
    found: 'Found',
    gone: 'Not there',
    full: 'Full price',
    penny: 'Rang up 1¢'
  };

  function localBook() { return store.get('book', { leads: [], trips: [] }); }
  function saveLocalBook(b) { store.set('book', b); }

  function toLead(i) {
    return {
      id: i.id,
      sku: i.sku || '',
      upc: i.upc || '',
      name: i.name || i.title || '',
      stores: i.stores || (i.store_id ? [i.store_id] : []),
      source: i.source || 'community',
      reported_price: i.reported_price != null ? i.reported_price : i.price,
      reported_at: i.reported_at || i.first_seen || '',
      confirmed_at_register: !!i.confirmed_at_register,
      notes: i.notes || '',
      retailer: i.retailer || 'homedepot',
      preview: !!i.preview,
      local: !!i.local,
      ...(i.feed ? {
        feed: true, pid: i.pid || '', brand: i.brand || '', model: i.model || '', was: i.was, pct: i.pct,
        qty: i.qty, thumb: i.thumb || '', hd_link: i.link || '', aisle: i.aisle || '', bay: i.bay || '',
        dept: i.dept || '', first_seen: i.first_seen || '', last_seen: i.last_seen || '', stage: i.stage || ''
      } : {})
    };
  }
  function dealLead(d) {
    return toLead({ ...d, feed: true, name: d.title, stores: [d.store_id], source: 'feed', reported_price: d.price, reported_at: d.last_seen });
  }

  function mergeBook() {
    const baseLeads = (S.data.deals || []).map(dealLead).concat((S.data.items || []).map(toLead));
    const baseTrips = S.data.trips ? S.data.trips.slice() : [];
    (S.data.items || []).forEach(i => {
      (i.trips || []).forEach(t => baseTrips.push({ ...t, lead_id: t.lead_id || i.id }));
    });
    const loc = localBook();
    const leads = new Map();
    baseLeads.forEach(l => leads.set(l.id, l));
    (loc.leads || []).forEach(l => {
      const base = leads.get(l.id);
      if (base && base.feed) leads.set(l.id, { ...base, confirmed_at_register: base.confirmed_at_register || !!l.confirmed_at_register });
      else leads.set(l.id, { ...base, ...toLead(l), local: true });
    });
    const tripKey = t => [t.lead_id, t.store_id || '', t.date].join('|');
    const trips = new Map();
    baseTrips.forEach(t => trips.set(tripKey(t), t));
    (loc.trips || []).forEach(t => trips.set(tripKey(t), t));
    return { leads: [...leads.values()], trips: [...trips.values()] };
  }

  function tripsFor(book, id) { return book.trips.filter(t => t.lead_id === id); }
  function notThereDates(trips) { return new Set(trips.filter(t => t.mark === 'gone' && t.date).map(t => t.date)); }
  function latestTrip(trips) {
    return trips.slice().sort((a, b) => (b.date || '').localeCompare(a.date || '')).at(0);
  }
  function isConfirmed(lead, trips) {
    return !!(lead.confirmed_at_register || trips.some(t => t.mark === 'penny'));
  }
  function isDemoted(lead, trips) {
    if (isConfirmed(lead, trips)) return false;
    if (notThereDates(trips).size < 2) return false;
    const last = latestTrip(trips);
    if (last && (last.mark === 'found' || last.mark === 'penny')) return false;
    return true;
  }
  function searchLink(lead) {
    const q = lead.sku || lead.upc || lead.name || '';
    if (!q) return '';
    return (lead.retailer === 'walmart')
      ? 'https://www.walmart.com/search?q=' + encodeURIComponent(q)
      : 'https://www.homedepot.com/s/' + encodeURIComponent(q);
  }
  function decorate(lead, book) {
    const trips = tripsFor(book, lead.id).sort((a, b) => (b.date || '').localeCompare(a.date || ''));
    const confirmed = isConfirmed(lead, trips);
    return {
      ...lead,
      title: lead.name || lead.sku || lead.upc || 'Untitled find',
      price: lead.reported_price,
      link: lead.feed ? (lead.hd_link || searchLink(lead)) : searchLink(lead),
      confirmed,
      demoted: isDemoted(lead, trips),
      not_there_count: notThereDates(trips).size,
      trips,
      store_id: (lead.stores || [])[0] || '',
      isNew: isNew(lead)
    };
  }
  function isNew(lead) {
    const last = store.get('lastVisit', null);
    if (!last) return false;
    if (lead.feed) return !!lead.first_seen && new Date(lead.first_seen + 'T23:59:00').getTime() > last;
    const day = (lead.reported_at || '').slice(0, 10);
    const added = lead.added_at || (lead.local && day);
    const when = lead.added_at || (day ? day + 'T12:00:00' : '');
    if (!when) return false;
    return new Date(when).getTime() > last;
  }
  function allItems() {
    const book = mergeBook();
    return book.leads
      .filter(l => (l.retailer || 'homedepot') === S.retailer)
      .map(l => decorate(l, book));
  }
  function inStore() {
    const items = allItems();
    if (S.store === 'all') return items;
    return items.filter(i => (i.stores || []).includes(S.store) || !(i.stores || []).length);
  }
  function sortItems(list) {
    const pref = S.store === 'all' ? myStores().map(s => s.id) : [S.store];
    const mine = i => {
      const stores = i.stores || [];
      if (stores.some(s => pref.includes(s))) return 0;
      if (!stores.length) return 1;
      return 2;
    };
    const ord = d => { const t = Date.parse((d || '') + (d && d.length === 10 ? 'T12:00:00' : '')); return Number.isNaN(t) ? 0 : t; };
    return list.slice().sort((a, b) =>
      ((b.feed ? 1 : 0) - (a.feed ? 1 : 0)) ||
      (a.feed && b.feed ? ((b.pct || 0) - (a.pct || 0)) || ((a.price ?? 1e9) - (b.price ?? 1e9)) : 0) ||
      (a.demoted - b.demoted) ||
      ((b.confirmed ? 1 : 0) - (a.confirmed ? 1 : 0)) ||
      (ord(b.reported_at) - ord(a.reported_at)) ||
      (mine(a) - mine(b))
    );
  }

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
      view.innerHTML = '<div class="empty"><h3>Can\'t load right now</h3><p>Check your signal and pull down to try again.</p></div>';
      $('#updated').textContent = 'No data yet';
      return;
    }
    if (!S.data.walmart_enabled) S.retailer = 'homedepot';
    if (!S.data.stores.some(s => kind(s) === S.retailer)) S.retailer = kind(S.data.stores[0] || {});
    pickStore();
    draw();
  }

  function header() {
    const d = S.data;
    $('#updated').textContent = d.generated_at ? 'Updated ' + ago(d.generated_at) : 'Waiting for the first build';
    const b = $('#banner');
    let msg = '';
    if (S.offline) msg = 'Offline. Showing saved data from ' + niceDate(d.generated_at) + '.';
    else if (d.status && d.status.ok === false && d.status.note) msg = d.status.note;
    b.textContent = msg; b.hidden = !msg;
    const kinds = [...new Set(d.stores.map(kind))];
    $('#retailers').hidden = kinds.length < 2;
    $('#retailers').innerHTML = kinds.map(k => `<button class="${S.retailer === k ? 'on' : ''}" data-retailer="${esc(k)}">${esc(RNAME[k] || k)}</button>`).join('');
    const mine = myStores();
    $('#stores').hidden = mine.length < 2;
    $('#stores').innerHTML = [{ id: 'all', short: 'All ' + mine.length + ' stores' }, ...mine].map(s =>
      `<button class="chip ${S.store === s.id ? 'on' : ''}" data-store="${esc(s.id)}">${esc(s.short)}</button>`).join('');
    const items = allItems();
    const nNew = items.filter(i => i.isNew).length;
    const nc = $('#newcount'); nc.hidden = !nNew; nc.textContent = nNew;
    const mineIds = new Set(items.map(i => i.id));
    const n = Object.keys(S.run).filter(id => mineIds.has(id)).length, rc = $('#runcount');
    rc.hidden = !n; rc.textContent = n;
    document.querySelectorAll('.nav button').forEach(b => b.classList.toggle('on', b.dataset.tab === S.tab));
  }

  const STAGE = { penny: '1¢ in the data', near: 'Near penny' };
  const shelf = i => i.qty > 0 ? i.qty + ' on the shelf' : i.qty === 0 ? '0 for pickup' : '';
  const spot = i => [i.aisle && 'Aisle ' + i.aisle, i.bay && 'Bay ' + i.bay].filter(Boolean).join(' · ');
  function dealTags(i) {
    const t = [];
    if (i.isNew) t.push('<span class="tag new">New</span>');
    if (i.confirmed) t.push('<span class="tag ok">Rang up 1¢</span>');
    if (i.stage) t.push(`<span class="tag penny">${STAGE[i.stage]}</span>`);
    if (spot(i)) t.push(`<span class="tag ok">${esc(spot(i))}</span>`);
    if (S.store === 'all' && !S.grouped) t.push(`<span class="tag plain">${esc(storeName(i.store_id))}</span>`);
    if (i.demoted) t.push('<span class="tag demoted">Missed ' + i.not_there_count + ' trips</span>');
    if (S.run[i.id]) t.push('<span class="tag ok">On run list</span>');
    return t.join('');
  }
  function tags(i) {
    if (i.feed) return dealTags(i);
    const t = [];
    if (i.isNew) t.push('<span class="tag new">New</span>');
    if (i.confirmed) t.push('<span class="tag ok">Confirmed at register</span>');
    else t.push('<span class="tag unconfirmed">Unconfirmed until it rings up at the register</span>');
    if (i.demoted) t.push('<span class="tag demoted">Demoted · missed ' + i.not_there_count + ' trips</span>');
    if (i.source === 'my_trip') t.push('<span class="tag ok">My trip</span>');
    else t.push('<span class="tag community">Community</span>');
    if (i.preview) t.push('<span class="tag plain">Preview example</span>');
    const stores = i.stores || [];
    if (S.store === 'all' && stores.length) t.push(`<span class="tag plain">${esc(stores.map(storeName).join(', '))}</span>`);
    if (S.run[i.id]) t.push('<span class="tag ok">On run list</span>');
    return t.join('');
  }
  const initial = i => esc(((i.title || '?')[0] || '?').toUpperCase());
  const coin = i => i.confirmed ? '<span class="coin" aria-label="Confirmed penny">1¢</span>' : '';
  const thumb = i => `<div class="tw">${coin(i)}<div class="thumb">${initial(i)}${i.thumb ? `<img src="${esc(i.thumb.replace(/_(\d+)\.jpg$/, '_145.jpg'))}" alt="" loading="lazy" onerror="this.remove()">` : ''}</div></div>`;
  function dealCard(i) {
    return `<button class="card deal${i.confirmed ? ' confirmed pennycard' : ''}${i.demoted ? ' demoted' : ''}" data-item="${esc(i.id)}">${thumb(i)}
      <div class="body"><div class="title">${esc(i.title)}</div>
        <div class="meta">${i.sku ? 'SKU <b>' + esc(i.sku) + '</b>' : ''}${i.upc ? ' · UPC ' + esc(i.upc) : ''}</div>
        <div class="meta">${esc(['Seen ' + niceDate(i.last_seen), shelf(i)].filter(Boolean).join(' · '))}</div>
        <div class="tags">${tags(i)}</div></div>
      <div class="side"><div class="price">${money(i.price) || '—'}</div>${i.was ? `<div class="was">${money(i.was)}</div>` : ''}${i.pct ? `<div class="pct">${i.pct}% off</div>` : ''}</div></button>`;
  }
  function card(i) {
    if (i.feed) return dealCard(i);
    return `<button class="card${i.confirmed ? ' confirmed pennycard' : ''}${i.demoted ? ' demoted' : ''}" data-item="${esc(i.id)}">${thumb(i)}
      <div class="body"><div class="title">${esc(i.title)}</div>
        <div class="meta">${i.source === 'my_trip' ? 'My trip' : 'Community'}${i.sku ? ' · <b>' + esc(i.sku) + '</b>' : ''}${i.reported_at ? ' · ' + niceDate(i.reported_at) : ''}</div>
        <div class="tags">${tags(i)}</div></div>
      <div class="side"><div class="price">${money(i.price) || '—'}</div></div></button>`;
  }
  const section = (title, list, sub, max = 12) => !list.length ? '' :
    `<div class="sec"><h2>${title}</h2><span>${list.length}</span></div>${sub ? `<p class="sub">${sub}</p>` : ''}` +
    list.slice(0, max).map(card).join('') +
    (list.length > max ? `<button class="more" data-goto="${title}">See all ${list.length}</button>` : '');

  function feedView(deals) {
    const f = S.data.feed || {}, per = f.stores || {};
    const scanned = id => (per[id] || {}).last_scan;
    const pickNote = id => scanned(id) ? 'Last scan ' + niceDate(scanned(id)) + ' (' + ago(scanned(id)) + ')' : 'Not scanned yet';
    let h = `<div class="sec"><h2>Deep clearance</h2><span>${deals.length} items ${f.min_pct || 50}%+ off</span></div>
      <p class="sub">Home Depot's own store clearance prices, deepest discount first. Each store refreshes every few days.</p>`;
    if (S.store !== 'all') {
      h += `<p class="sub">${esc(storeFull(S.store))} · ${esc(pickNote(S.store))}</p>`;
      if (!deals.length) return h + '<div class="empty"><h3>Nothing 50%+ off here right now</h3><p>This store gets checked again within a few days.</p></div>';
      h += deals.slice(0, S.limit).map(card).join('');
      if (deals.length > S.limit) h += `<button class="more" id="morebtn">Show more (${deals.length - S.limit} left)</button>`;
      return h;
    }
    for (const st of myStores()) {
      const list = deals.filter(i => i.store_id === st.id);
      h += `<div class="sec store"><h2>${esc(st.short)}</h2><span>${list.length ? list.length + ' items · ' : ''}${esc(pickNote(st.id))}</span></div>`;
      if (!list.length) { h += '<p class="sub">Nothing 50%+ off in the last scan window yet.</p>'; continue; }
      S.grouped = true; h += list.slice(0, 5).map(card).join(''); S.grouped = false;
      if (list.length > 5) h += `<button class="more" data-store="${esc(st.id)}">See all ${list.length} at ${esc(st.short)}</button>`;
    }
    return h;
  }

  function todayView() {
    const every = sortItems(inStore());
    const deals = every.filter(i => i.feed);
    const all = every.filter(i => !i.feed);
    const fresh = all.filter(i => i.isNew);
    const confirmed = all.filter(i => i.confirmed && !i.demoted && !i.isNew);
    const open = all.filter(i => !i.confirmed && !i.demoted && !i.isNew);
    const demoted = all.filter(i => i.demoted && !i.isNew);
    let h = '';
    const newDeals = deals.filter(i => i.isNew).length;
    if (fresh.length + newDeals) h += `<div class="badge-row" id="newbanner">${fresh.length + newDeals} new since your last visit</div>`;
    h += `<p class="notice"><b>Unconfirmed until it scans at the register.</b> Online clearance prices lag the store. Scan the barcode on the box, not the shelf tag.</p>`;
    h += feedView(deals);
    if (!all.length) {
      h += `<div class="sec"><h2>Community and trip leads</h2></div><div class="empty"><h3>No leads yet</h3><p>Tap <b>Add a find</b> to save a SKU from a trip, or paste a shortlist of SKUs and prices.</p>
        <button class="btn fill" id="emptyadd">Add a find</button>
        <a class="btn out" href="https://www.pennycentral.com/penny-list" target="_blank" rel="noopener">Open PennyCentral's penny list</a></div>`;
      return h;
    }
    h += section('New since last visit', fresh, '', 10);
    h += section('Confirmed at the register', confirmed, 'These already rang up at a penny on a trip.', 10);
    h += section('Leads to check', open, 'Community reports and your own trip notes. Still unconfirmed.', 20);
    if (demoted.length) h += section('Demoted', demoted, 'Not there on two or more trips. Worth skipping unless you want another look.', 10);
    h += `<div class="tip"><b>In the store:</b> scan the barcode on the box at self-checkout, not the shelf tag. The register price is the only proof of a penny.</div>`;
    return h;
  }

  function browse() {
    const q = S.q.trim().toLowerCase();
    let list = sortItems(inStore()).filter(i => !q || (i.title + ' ' + i.sku + ' ' + i.upc + ' ' + (i.brand || '') + ' ' + (i.dept || '') + ' ' + (i.notes || '')).toLowerCase().includes(q));
    return `<input class="search" id="q" type="search" placeholder="Search name, SKU, UPC or brand" value="${esc(S.q)}" autocomplete="off">
      <div class="sec"><h2>${list.length} item${list.length === 1 ? '' : 's'}</h2></div>
      <div id="list">${list.slice(0, S.limit).map(card).join('') || '<div class="empty"><h3>Nothing matches</h3></div>'}</div>
      ${list.length > S.limit ? `<button class="more" id="morebtn">Show more (${list.length - S.limit} left)</button>` : ''}`;
  }

  function runList() {
    const ids = Object.keys(S.run), byId = Object.fromEntries(allItems().map(i => [i.id, i]));
    const mine = ids.map(id => byId[id]).filter(Boolean).filter(i => S.store === 'all' || (i.stores || []).includes(S.store) || !(i.stores || []).length);
    if (!mine.length) return `<div class="empty"><h3>Your run list is empty</h3><p>Open any item and tap "Add to run list" to plan a store trip.</p><button class="btn tonal" data-tab="today">See today's leads</button></div>`;
    const done = mine.filter(i => S.run[i.id] !== 'todo').length;
    let h = `<div class="sec"><h2>Store run</h2><span>${done} of ${mine.length} checked</span></div><div class="prog"><div style="width:${done / mine.length * 100}%"></div></div>`;
    const groups = [];
    for (const st of myStores()) {
      const group = mine.filter(i => (i.stores || []).includes(st.id) || (!(i.stores || []).length && S.store === st.id));
      if (group.length) groups.push([st, group]);
    }
    const unassigned = mine.filter(i => !(i.stores || []).length && S.store === 'all');
    if (!groups.length && mine.length) {
      h += mine.map(runRow).join('');
    } else {
      for (const [st, group] of groups) {
        h += `<div class="sec"><h2>${esc(st.short)}</h2>${st.maps ? `<a class="textbtn" href="${esc(st.maps)}" target="_blank" rel="noopener">Directions</a>` : ''}</div>`;
        h += group.map(i => runRow(i, st.id)).join('');
      }
      if (unassigned.length) {
        h += `<div class="sec"><h2>No store assigned</h2></div>` + unassigned.map(i => runRow(i)).join('');
      }
    }
    return h + '<button class="btn out" id="clearrun">Clear run list</button>';
  }
  function runRow(i, storeId) {
    const v = S.run[i.id];
    const sid = storeId || i.store_id || '';
    return `<div class="runitem" data-lead="${esc(i.id)}"><button class="top" data-item="${esc(i.id)}">${thumb(i)}<div class="body"><div class="title">${esc(i.title)}</div>
      <div class="meta">${i.sku ? '<b>' + esc(i.sku) + '</b> · ' : ''}${money(i.price) || 'no price'}${i.pct ? ' · ' + i.pct + '% off' : ''}${spot(i) ? ' · ' + esc(spot(i)) : ''}</div>
      <div class="tags">${i.confirmed ? '<span class="tag ok">Confirmed</span>' : '<span class="tag unconfirmed">Unconfirmed until it scans</span>'}</div></div></button>
      <div class="seg">${[['found', 'Found'], ['gone', 'Not there'], ['full', 'Full price'], ['penny', 'Rang up 1¢']].map(([k, l]) =>
      `<button class="${k} ${v === k ? 'on' : ''}" data-mark="${esc(i.id)}" data-val="${k}" data-tripstore="${esc(sid)}">${l}</button>`).join('')}</div></div>`;
  }

  function history() {
    const book = mergeBook();
    const trips = book.trips.slice().sort((a, b) => (b.date || '').localeCompare(a.date || '') || a.lead_id.localeCompare(b.lead_id));
    const byId = Object.fromEntries(allItems().map(i => [i.id, i]));
    let h = `<div class="sec"><h2>Trip log</h2><span>${trips.length}</span></div>
      <p class="sub">Marks stay on this phone until you export them. Two "Not there" trips demote a lead.</p>`;
    if (!trips.length) h += '<div class="empty"><h3>No trips recorded yet</h3><p>Add a lead to your run list and mark what you found.</p></div>';
    else {
      h += '<div class="log">' + trips.map(t => {
        const item = byId[t.lead_id];
        const name = item ? item.title : t.lead_id;
        return `<div><span>${esc(niceDate(t.date))}${t.store_id ? ' · ' + esc(storeName(t.store_id)) : ''}<small>${esc(name)}</small></span><span>${esc(MARKS[t.mark] || t.mark)}</span></div>`;
      }).join('') + '</div>';
    }
    h += `<div class="sec"><h2>Backup</h2></div>
      <div class="actions">
        <button class="btn fill" id="exportbtn">Export leads and trips</button>
        <button class="btn tonal" id="importbtn">Import JSON or a pasted list</button>
      </div>
      <p class="sub">Export saves a file you can keep or commit to the repo as data/leads.json. Import merges into this phone.</p>`;
    const log = S.data.log || [];
    if (log.length) h += '<div class="sec"><h2>Recent builds</h2></div><div class="log">' + log.slice().reverse().map(l =>
      `<div><span>${esc(niceDate(l.date))} · ${esc(l.store || '')}<small>${esc(l.note || '')}</small></span><span>${esc(l.source || '')}</span></div>`).join('') + '</div>';
    h += `<div class="tip"><b>Community lists:</b> PennyCentral has no public feed we are allowed to copy automatically, and its terms forbid scraping. Open the list, copy SKUs and prices you want to check, then paste them under Add a find.
      <a class="btn out" href="https://www.pennycentral.com/penny-list" target="_blank" rel="noopener" style="margin-top:12px">Open PennyCentral's penny list</a></div>`;
    return h;
  }

  function draw() {
    header();
    view.innerHTML = ({ today: todayView, browse, run: runList, history })[S.tab]();
  }

  function nid() { return 'ld_' + Math.random().toString(16).slice(2, 12); }

  function openAdd(opts = {}) {
    const stores = myStores();
    const storeOpts = ['<option value="">Not assigned yet</option>'].concat(stores.map(s =>
      `<option value="${esc(s.id)}" ${S.store === s.id ? 'selected' : ''}>${esc(s.name)}</option>`)).join('');
    $('#sheet').innerHTML = `<div class="grab"></div>
      <h2>Add a find</h2>
      <p>Paste a SKU or UPC from a trip or a community list. Nothing is sent to a paid service.</p>
      <form id="findform">
        <div class="field"><label for="find-name">Name</label><input id="find-name" name="name" maxlength="200" value="${esc(opts.name || '')}"></div>
        <div class="field"><label for="find-sku">SKU</label><input id="find-sku" name="sku" maxlength="40" autocapitalize="off" value="${esc(opts.sku || '')}"></div>
        <div class="field"><label for="find-upc">UPC</label><input id="find-upc" name="upc" inputmode="numeric" maxlength="14" value="${esc(opts.upc || '')}"></div>
        <div class="field"><label for="find-price">Reported price</label><input id="find-price" name="price" inputmode="decimal" placeholder="0.01" value="${esc(opts.price || '')}"></div>
        <div class="field"><label for="find-store">Store</label><select id="find-store" name="store">${storeOpts}</select></div>
        <div class="field"><label for="find-source">Source</label><select id="find-source" name="source">
          <option value="my_trip">My trip</option>
          <option value="community" ${opts.source === 'community' ? 'selected' : ''}>Community</option>
        </select></div>
        <div class="field"><label for="find-notes">Notes</label><textarea id="find-notes" name="notes" maxlength="500">${esc(opts.notes || '')}</textarea></div>
        <div class="field"><label for="find-paste">Or paste a list of SKUs and prices</label>
          <textarea id="find-paste" placeholder="564-184, 0.01, Wire shelf"></textarea></div>
        <button class="btn fill" id="find-save" type="submit">Save on this phone</button>
        <button class="btn tonal" id="find-copy" type="button">Copy as JSON line</button>
        <button class="btn out" id="find-cancel" type="button">Cancel</button>
      </form>`;
    $('#sheet').hidden = $('#scrim').hidden = false;
    window.history.pushState({ sheet: 'add' }, '');
    $('#find-sku').focus();
  }

  function formLead() {
    const sku = $('#find-sku').value.trim();
    const upc = $('#find-upc').value.replace(/\D/g, '');
    const name = $('#find-name').value.trim();
    const priceRaw = $('#find-price').value.trim();
    const price = priceRaw === '' ? null : Number(String(priceRaw).replace('$', ''));
    if (!sku && !upc && !name) { toast('Add a SKU, UPC, or name'); return null; }
    if (priceRaw && Number.isNaN(price)) { toast('Price looks off'); return null; }
    const st = $('#find-store').value;
    return {
      id: nid(),
      sku, upc, name,
      stores: st ? [st] : [],
      source: $('#find-source').value || 'my_trip',
      reported_price: Number.isFinite(price) ? price : null,
      reported_at: today(),
      confirmed_at_register: false,
      notes: $('#find-notes').value.trim(),
      retailer: S.retailer,
      local: true,
      added_at: new Date().toISOString()
    };
  }

  function parsePaste(text, source) {
    const rows = [];
    for (const raw of (text || '').split(/\n+/)) {
      const line = raw.trim();
      if (!line || line.startsWith('#')) continue;
      if (/^(sku|upc|item)\b/i.test(line) && !/\d{3,}/.test(line)) continue;
      let parts;
      if (line.includes(',')) parts = line.split(',').map(s => s.trim());
      else if (line.includes('\t')) parts = line.split('\t').map(s => s.trim());
      else parts = line.split(/\s{2,}|\s+(?=\$|\d+\.\d{2}\b)/).map(s => s.trim()).filter(Boolean);
      if (!parts.length) continue;
      const token = parts[0];
      let price = parts[1] != null && parts[1] !== '' ? Number(String(parts[1]).replace(/[$,]/g, '')) : null;
      if (Number.isNaN(price)) price = null;
      const name = parts[2] || '';
      const notes = parts.slice(3).join(', ');
      const digits = token.replace(/\D/g, '');
      const upc = (digits.length === 12 || digits.length === 13) && digits === token.replace(/\D/g, '') ? digits : '';
      const sku = upc ? '' : token.replace(/\s+/g, '');
      rows.push({
        id: nid(), sku, upc, name, stores: [], source: source || 'community',
        reported_price: price, reported_at: today(), confirmed_at_register: false,
        notes, retailer: S.retailer, local: true, added_at: new Date().toISOString()
      });
    }
    return rows;
  }

  function saveLeads(leads) {
    const book = localBook();
    for (const lead of leads) {
      const i = book.leads.findIndex(x => x.id === lead.id);
      if (i >= 0) book.leads[i] = lead; else book.leads.push(lead);
    }
    saveLocalBook(book);
  }

  function copyLine(lead) {
    const line = JSON.stringify({
      id: lead.id, sku: lead.sku, upc: lead.upc, name: lead.name, stores: lead.stores,
      source: lead.source, reported_price: lead.reported_price, reported_at: lead.reported_at,
      confirmed_at_register: !!lead.confirmed_at_register, notes: lead.notes
    });
    if (navigator.clipboard) navigator.clipboard.writeText(line).then(() => toast('Copied JSON line'), () => toast('Copy failed'));
    else toast(line);
    return line;
  }

  function openDeal(i) {
    const box = (label, val) => val ? `<button class="idbox" data-copy="${esc(val)}"><small>${label} · tap to copy</small><b>${esc(val)}</b></button>` : '';
    const st = S.data.stores.find(s => s.id === i.store_id);
    const rows = [['Store', storeFull(i.store_id)], ['Brand', i.brand], ['Model', i.model], ['Department', i.dept],
      ['Aisle / bay', spot(i) || 'Not listed online'], ['Units', i.qty > 0 ? i.qty + ' listed for pickup' : i.qty === 0 ? '0 listed for pickup online. Check the shelf.' : 'Not shown online'],
      ['First seen 50%+ off', niceDate(i.first_seen)], ['Last seen', i.last_seen ? niceDate(i.last_seen) + ' (' + ago(i.last_seen) + ')' : '']].filter(r => r[1]);
    $('#sheet').innerHTML = `<div class="grab"></div><h2>${esc(i.title)}</h2>
      <div class="big"><span class="price">${money(i.price) || '—'}</span>${i.was ? `<span class="was">${money(i.was)}</span>` : ''}${i.pct ? `<span class="pct">${i.pct}% off</span>` : ''}</div>
      <div class="notice">${i.confirmed ? '<b>Rang up 1¢ on your trip.</b>' : '<b>Unconfirmed until it scans at the register.</b> This is Home Depot\'s store price from the last scan. Scan the barcode on the box, not the shelf tag.'}</div>
      <div class="ids">${box('SKU', i.sku)}${box('UPC', i.upc)}</div>
      <button class="btn ${S.run[i.id] ? 'tonal' : 'fill'}" data-run="${esc(i.id)}">${S.run[i.id] ? 'Remove from run list' : 'Add to run list'}</button>
      <div class="two">${i.link ? `<a class="btn out" href="${esc(i.link)}" target="_blank" rel="noopener">Home Depot page</a>` : '<span></span>'}
        ${st && st.maps ? `<a class="btn out" href="${esc(st.maps)}" target="_blank" rel="noopener">Directions</a>` : '<span></span>'}</div>
      <button class="btn out" data-share="${esc(i.id)}">Share</button>
      <div class="hist">${rows.map(r => `<div><span>${esc(r[0])}</span><span>${esc(r[1])}</span></div>`).join('')}
        ${(i.trips || []).map(t => `<div><span>${esc(niceDate(t.date))}${t.store_id ? ' · ' + esc(storeName(t.store_id)) : ''}</span><span>${esc(MARKS[t.mark] || t.mark)}</span></div>`).join('')}</div>`;
    $('#sheet').hidden = $('#scrim').hidden = false;
    window.history.pushState({ sheet: i.id }, '');
  }

  function openSheet(id) {
    const i = allItems().find(x => x.id === id); if (!i) return;
    if (i.feed) return openDeal(i);
    const st = (i.stores || []).map(storeFull).join(', ');
    const box = (label, val) => val ? `<button class="idbox" data-copy="${esc(val)}"><small>${label} · tap to copy</small><b>${esc(val)}</b></button>` : '';
    const maps = (i.stores || []).map(id => S.data.stores.find(s => s.id === id)).filter(s => s && s.maps);
    $('#sheet').innerHTML = `<div class="grab"></div><h2>${esc(i.title)}</h2>
      <div class="meta">${esc([i.source === 'my_trip' ? 'My trip' : 'Community', st].filter(Boolean).join(' · '))}</div>
      <div class="big"><span class="price">${money(i.price) || '—'}</span></div>
      <div class="notice">${i.confirmed
        ? '<b>Confirmed at the register.</b> Keep the receipt note in your trip log.'
        : '<b>Unconfirmed until it rings up at the register.</b> Scan the barcode on the box, not the shelf tag.'}</div>
      ${i.demoted ? '<p>Demoted after two or more "Not there" trips.</p>' : ''}
      ${i.notes ? `<p>${esc(i.notes)}</p>` : ''}
      <div class="ids">${box('SKU', i.sku)}${box('UPC', i.upc)}</div>
      <button class="btn ${S.run[i.id] ? 'tonal' : 'fill'}" data-run="${esc(i.id)}">${S.run[i.id] ? 'Remove from run list' : 'Add to run list'}</button>
      <div class="two">${i.link ? `<a class="btn out" href="${esc(i.link)}" target="_blank" rel="noopener">Search the item</a>` : '<span></span>'}
        ${maps[0] ? `<a class="btn out" href="${esc(maps[0].maps)}" target="_blank" rel="noopener">Directions</a>` : '<span></span>'}</div>
      <div class="two"><a class="btn out" href="https://www.pennycentral.com/penny-list" target="_blank" rel="noopener">Penny list</a>
        <button class="btn out" data-share="${esc(i.id)}">Share</button></div>
      <button class="btn out" data-copyline="${esc(i.id)}">Copy as JSON line</button>
      <div class="hist"><div><span>Reported</span><span>${esc(niceDate(i.reported_at) || '—')}</span></div>
        ${(i.trips || []).map(t => `<div><span>${esc(niceDate(t.date))}${t.store_id ? ' · ' + esc(storeName(t.store_id)) : ''}</span><span>${esc(MARKS[t.mark] || t.mark)}</span></div>`).join('')}</div>`;
    $('#sheet').hidden = $('#scrim').hidden = false;
    window.history.pushState({ sheet: id }, '');
  }

  function closeSheet(fromPop) {
    if ($('#sheet').hidden) return;
    $('#sheet').hidden = $('#scrim').hidden = true;
    if (!fromPop && window.history.state && window.history.state.sheet) window.history.back();
  }
  window.addEventListener('popstate', () => closeSheet(true));

  function markTrip(leadId, val, storeId) {
    const book = localBook();
    const day = today();
    const sid = storeId || '';
    const cur = S.run[leadId] === val ? 'todo' : val;
    S.run[leadId] = cur;
    store.set('run', S.run);
    // Replace the same day's mark for this lead+store; keep other dates.
    book.trips = (book.trips || []).filter(t => !(t.lead_id === leadId && (t.store_id || '') === sid && t.date === day));
    if (cur !== 'todo') {
      const trip = { lead_id: leadId, store_id: sid, mark: cur, date: day };
      book.trips.push(trip);
      if (cur === 'penny') {
        const leads = book.leads || [];
        const i = leads.findIndex(l => l.id === leadId);
        if (i >= 0) leads[i] = { ...leads[i], confirmed_at_register: true };
        else {
          const item = allItems().find(x => x.id === leadId);
          if (item) book.leads.push({ ...toLead(item), confirmed_at_register: true, local: true });
        }
      }
    }
    saveLocalBook(book);
    if (navigator.vibrate) navigator.vibrate(12);
    toast(cur === 'todo' ? 'Cleared today\'s mark' : MARKS[cur]);
    draw();
  }

  function exportBook() {
    const book = mergeBook();
    const payload = { version: 1, leads: book.leads.map(toLead), trips: book.trips };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'leads-' + today() + '.json';
    a.click();
    URL.revokeObjectURL(a.href);
    toast('Exported leads and trips');
  }

  function importPayload(text, name) {
    const trimmed = text.trim();
    if (!trimmed) { toast('That file was empty'); return; }
    let leads = [], trips = [];
    if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
      const data = JSON.parse(trimmed);
      if (Array.isArray(data)) leads = data;
      else { leads = data.leads || []; trips = data.trips || []; }
    } else {
      leads = parsePaste(trimmed, 'community');
    }
    const book = localBook();
    for (const raw of leads) {
      const lead = toLead({ ...raw, id: raw.id || nid(), local: true, added_at: raw.added_at || new Date().toISOString() });
      const i = book.leads.findIndex(x => x.id === lead.id);
      if (i >= 0) book.leads[i] = { ...book.leads[i], ...lead };
      else book.leads.push(lead);
    }
    const key = t => [t.lead_id, t.store_id || '', t.date].join('|');
    const map = new Map((book.trips || []).map(t => [key(t), t]));
    for (const t of trips) map.set(key(t), t);
    book.trips = [...map.values()];
    saveLocalBook(book);
    toast('Imported ' + leads.length + ' lead' + (leads.length === 1 ? '' : 's') + ' from ' + (name || 'the paste'));
    S.tab = 'today';
    closeSheet();
    draw();
  }

  document.addEventListener('click', e => {
    const t = e.target.closest('[data-retailer],[data-store],[data-tab],[data-item],[data-run],[data-mark],[data-copy],[data-share],[data-copyline],[data-goto],#morebtn,#clearrun,#scrim,#refresh,#addfind,#emptyadd,#exportbtn,#importbtn,#find-copy,#find-cancel,#newbanner');
    if (!t) return;
    if (t.id === 'scrim' || t.id === 'find-cancel') return closeSheet();
    if (t.id === 'refresh') { t.classList.add('spin'); return load().then(() => { S.loaded = Date.now(); t.classList.remove('spin'); toast(S.offline ? 'Offline. Showing saved data.' : 'Up to date'); }); }
    if (t.id === 'addfind' || t.id === 'emptyadd') { closeSheet(); return openAdd(); }
    if (t.id === 'exportbtn') return exportBook();
    if (t.id === 'importbtn') return $('#importfile').click();
    if (t.id === 'find-copy') { const lead = formLead(); if (lead) copyLine(lead); return; }
    if (t.dataset.retailer) { S.retailer = t.dataset.retailer; store.set('retailer', S.retailer); S.q = ''; S.limit = 30; pickStore(); draw(); return window.scrollTo(0, 0); }
    if (t.dataset.mark) return markTrip(t.dataset.mark, t.dataset.val, t.dataset.tripstore);
    if (t.dataset.store) { S.store = t.dataset.store; S.picks[S.retailer] = S.store; store.set('picks', S.picks); S.limit = 30; draw(); return t.classList.contains('more') && window.scrollTo(0, 0); }
    if (t.dataset.tab) { S.tab = t.dataset.tab; S.limit = 30; draw(); return window.scrollTo(0, 0); }
    if (t.dataset.goto) { S.tab = 'browse'; S.q = ''; draw(); return window.scrollTo(0, 0); }
    if (t.dataset.item) return openSheet(t.dataset.item);
    if (t.dataset.run) {
      const id = t.dataset.run;
      if (S.run[id]) { delete S.run[id]; toast('Removed from run list'); } else { S.run[id] = 'todo'; toast('Added to run list'); }
      store.set('run', S.run); closeSheet(); return draw();
    }
    if (t.dataset.copy) { navigator.clipboard && navigator.clipboard.writeText(t.dataset.copy).then(() => toast('Copied ' + t.dataset.copy), () => toast(t.dataset.copy)); return; }
    if (t.dataset.copyline) { const i = allItems().find(x => x.id === t.dataset.copyline); if (i) copyLine(toLead(i)); return; }
    if (t.dataset.share) {
      const i = allItems().find(x => x.id === t.dataset.share);
      const text = `${i.title} — ${money(i.price) || 'penny lead'} at ${ (i.stores || []).map(storeName).join(', ') || 'my stores' }`;
      if (navigator.share) navigator.share({ title: 'Penny Run', text, url: i.link || location.href }).catch(() => { });
      else navigator.clipboard && navigator.clipboard.writeText(text).then(() => toast('Copied'));
      return;
    }
    if (t.id === 'morebtn') { S.limit += 30; return draw(); }
    if (t.id === 'clearrun') { for (const i of allItems()) delete S.run[i.id]; store.set('run', S.run); toast('Run list cleared'); return draw(); }
  });
  document.addEventListener('submit', e => {
    if (e.target.id !== 'findform') return;
    e.preventDefault();
    const paste = ($('#find-paste') || {}).value || '';
    let leads = [];
    if (paste.trim()) leads = parsePaste(paste, $('#find-source').value || 'community');
    if (!leads.length) {
      const lead = formLead();
      if (!lead) return;
      leads = [lead];
    } else if ($('#find-store').value) {
      leads.forEach(l => { l.stores = [$('#find-store').value]; });
    }
    saveLeads(leads);
    toast(leads.length === 1 ? 'Saved on this phone' : 'Saved ' + leads.length + ' leads on this phone');
    closeSheet();
    S.tab = 'today';
    draw();
  });
  document.addEventListener('input', e => {
    if (e.target.id === 'q') {
      S.q = e.target.value; S.limit = 30;
      clearTimeout(S.qt); S.qt = setTimeout(() => { draw(); const q = $('#q'); q.focus(); q.setSelectionRange(q.value.length, q.value.length); }, 180);
    }
  });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeSheet(); });
  let hideTimer;
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
      hideTimer = setTimeout(() => store.set('lastVisit', Date.now()), 2000);
    } else {
      clearTimeout(hideTimer);
      if (S.data && Date.now() - (S.loaded || 0) > 6e5) load();
    }
  });
  $('#importfile').addEventListener('change', ev => {
    const f = ev.target.files && ev.target.files[0];
    ev.target.value = '';
    if (!f) return;
    f.text().then(t => importPayload(t, f.name)).catch(() => toast('Could not read that file'));
  });

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
