// Capy Tower screen. Plain JS, no dependencies, no network beyond the board's own app server.
// The browser is only the sensor and the display: it sends runway frames (laptop camera or the
// simulated runway) to the board, and polls the board for decisions, actions and radio calls.
(() => {
  const $ = (s) => document.querySelector(s);
  const W = 640, H = 400, RY = 200, RHW = 34; // runway centerline y and half width
  const view = $('#view'), vctx = view.getContext('2d');
  const scene = document.createElement('canvas'); scene.width = W; scene.height = H;
  const sctx = scene.getContext('2d');
  const video = $('#video');
  const capyImg = new Image(); capyImg.src = '/static/img/capybara.png';

  let mode = 'sim', camOn = false, sending = false, lastDecisionT = null;
  let lastRadioT = null, d1Since = null, lastCounts = { decisions: 0, skipped: 0 };
  const sim = { capy: null, cone: null, photo: null };
  const phases = { departure: { phase: null, start: 0 }, arrival: { phase: null, start: 0 } };

  // ---------- simulated runway (what the board sees in SIM mode) ----------
  const grass = document.createElement('canvas'); grass.width = W; grass.height = H;
  (() => {
    const g = grass.getContext('2d');
    g.fillStyle = '#4f7f3a'; g.fillRect(0, 0, W, H);
    for (let i = 0; i < 2600; i++) {
      g.fillStyle = Math.random() < 0.5 ? 'rgba(30,70,25,.35)' : 'rgba(120,160,80,.25)';
      g.fillRect(Math.random() * W, Math.random() * H, 2, 2 + Math.random() * 3);
    }
  })();

  function drawRunway(c) {
    c.drawImage(grass, 0, 0);
    // taxiway to the hold-short line near the east end
    c.fillStyle = '#56595e'; c.fillRect(540, RY, 40, 130);
    c.fillStyle = '#e6c229'; c.fillRect(558, RY + RHW, 4, 96);
    c.fillRect(540, RY + RHW + 18, 40, 3); c.fillRect(540, RY + RHW + 24, 40, 3);
    // runway
    c.fillStyle = '#5c5f64'; c.fillRect(20, RY - RHW, W - 40, RHW * 2);
    c.fillStyle = '#f2f2f2';
    for (let x = 70; x < 500; x += 44) c.fillRect(x, RY - 2, 26, 4);
    for (let i = 0; i < 6; i++) { c.fillRect(592, RY - RHW + 6 + i * 11, 18, 6); c.fillRect(30, RY - RHW + 6 + i * 11, 18, 6); }
    c.save(); c.translate(540, RY); c.rotate(-Math.PI / 2);
    c.font = 'bold 34px system-ui, sans-serif'; c.textAlign = 'center'; c.textBaseline = 'middle';
    c.fillText('28', 0, 0); c.restore();
    c.save(); c.translate(92, RY); c.rotate(Math.PI / 2);
    c.font = 'bold 34px system-ui, sans-serif'; c.textAlign = 'center'; c.textBaseline = 'middle';
    c.fillText('10', 0, 0); c.restore();
  }

  function drawCone(c, x, y) {
    c.fillStyle = '#222'; c.fillRect(x - 20, y + 16, 40, 7);
    c.fillStyle = '#ff7a00';
    c.beginPath(); c.moveTo(x, y - 30); c.lineTo(x + 15, y + 17); c.lineTo(x - 15, y + 17); c.closePath(); c.fill();
    c.fillStyle = '#fff'; c.fillRect(x - 8, y - 6, 16, 6); c.fillRect(x - 11, y + 5, 22, 5);
  }

  function drawPhoto(c) {
    const p = sim.photo; if (!p) return;
    c.save();
    c.shadowColor = 'rgba(0,0,0,.45)'; c.shadowBlur = 10; c.shadowOffsetY = 4;
    c.drawImage(p.img, p.x - p.w / 2, p.y - p.h / 2, p.w, p.h);
    c.restore();
  }

  function stepCapy(dt) {
    const k = sim.capy; if (!k) return;
    const dx = k.tx - k.x, dy = k.ty - k.y, d = Math.hypot(dx, dy);
    if (d > 1) {
      const m = Math.min(d, k.speed * dt);
      k.x += (dx / d) * m; k.y += (dy / d) * m; k.flip = dx > 0; k.walk += dt;
    } else if (k.leaving) sim.capy = null;
  }

  function drawCapy(c) {
    const k = sim.capy; if (!k || !capyImg.complete || !capyImg.naturalWidth) return;
    const w = 150, h = w * capyImg.naturalHeight / capyImg.naturalWidth;
    const bob = Math.sin(k.walk * 9) * 1.5;
    c.save(); c.translate(k.x, k.y + bob);
    if (k.flip) c.scale(-1, 1);
    c.drawImage(capyImg, -w / 2, -h / 2, w, h); c.restore();
  }

  function drawCamera(c) {
    const vw = video.videoWidth, vh = video.videoHeight;
    if (!vw) { c.fillStyle = '#000'; c.fillRect(0, 0, W, H); return; }
    const s = Math.max(W / vw, H / vh), dw = vw * s, dh = vh * s;
    c.drawImage(video, (W - dw) / 2, (H - dh) / 2, dw, dh);
  }

  // ---------- overlay (display only, never sent to the board) ----------
  function plane(c, x, y, ang, s, color, alpha = 1, alt = 0) {
    for (const pass of [0, 1]) {
      if (pass === 0 && alt <= 0) continue;
      c.save(); c.globalAlpha = alpha * (pass === 0 ? 0.35 : 1);
      c.translate(pass === 0 ? x + 16 * alt : x, pass === 0 ? y + 22 * alt : y); c.rotate(ang); c.scale(s, s);
      c.fillStyle = pass === 0 ? '#000' : color; c.strokeStyle = 'rgba(0,0,0,.55)'; c.lineWidth = 1;
      c.beginPath(); c.ellipse(0, 0, 24, 4.5, 0, 0, Math.PI * 2); c.fill(); if (pass) c.stroke();
      c.beginPath(); c.rect(3, -28, 7, 56); c.fill(); if (pass) c.stroke();
      c.beginPath(); c.rect(-21, -10, 5, 20); c.fill(); if (pass) c.stroke();
      c.restore();
    }
  }
  const lerp = (a, b, u) => a + (b - a) * Math.max(0, Math.min(1, u));
  const seg = (u, a, b) => Math.max(0, Math.min(1, (u - a) / (b - a)));

  function drawTraffic(c, now) {
    const d = phases.departure, a = phases.arrival;
    if (d.phase === 'holding_short' || d.phase === 'waiting') plane(c, 560, 292, -Math.PI / 2, 1, '#ffffff');
    if (d.phase === 'cleared_takeoff') {
      const u = (now - d.start) / 12000;
      if (u < 0.2) { const v = seg(u, 0, 0.2); plane(c, 560, lerp(292, RY, v), lerp(-Math.PI / 2, -Math.PI, v), 1, '#ffffff'); }
      else { const v = seg(u, 0.2, 1); const alt = seg(v, 0.55, 1);
        plane(c, lerp(560, -90, v * v), RY - 30 * alt, Math.PI, 1 + 0.5 * alt, '#ffffff', 1, alt); }
    }
    if (a.phase === 'cleared_land') {
      const u = (now - a.start) / 14000;
      if (u < 0.45) { const v = seg(u, 0, 0.45); plane(c, lerp(720, 560, v), RY, Math.PI, lerp(1.8, 1, v), '#9fd3ff', 1, 1 - v); }
      else { const v = seg(u, 0.45, 1); plane(c, lerp(560, 220, 1 - (1 - v) * (1 - v)), RY, Math.PI, 1, '#9fd3ff'); }
    }
    if (a.phase === 'landed') {
      const v = seg(now - a.start, 0, 4000);
      if (v < 1) plane(c, 220, lerp(RY, 330, v), lerp(Math.PI, Math.PI / 2, Math.min(1, v * 3)), 1, '#9fd3ff', 1 - seg(v, 0.7, 1));
    }
    if (a.phase === 'go_around') {
      const u = (now - a.start) / 9000;
      const v = seg(u, 0, 1);  // climb away from short final
      plane(c, lerp(600, 250, v), lerp(RY, 110, v), Math.PI - 0.25 * v, lerp(1.25, 2.4, v), '#9fd3ff', 1 - seg(v, 0.6, 1), lerp(0.4, 1.4, v));
    }
  }

  let lastT = performance.now();
  function frame(now) {
    const dt = Math.min(0.1, (now - lastT) / 1000); lastT = now;
    if (mode === 'sim') {
      stepCapy(dt); drawRunway(sctx);
      if (sim.cone) drawCone(sctx, sim.cone.x, sim.cone.y);
      drawPhoto(sctx);
      drawCapy(sctx);
    } else drawCamera(sctx);
    vctx.drawImage(scene, 0, 0);
    if (mode === 'sim') drawTraffic(vctx, now);
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);

  // ---------- pipeline strip ----------
  const pulse = (id, cls = 'flash', ms = 700) => {
    const el = $(id); el.classList.add(cls); clearTimeout(el._t); el._t = setTimeout(() => el.classList.remove(cls), ms);
  };

  // ---------- frames to the board ----------
  function sendFrame() {
    if (sending || (mode === 'camera' && !camOn)) return;
    sending = true;
    scene.toBlob(async (blob) => {
      try {
        await fetch('/api/frame?source=' + mode, { method: 'POST', headers: { 'Content-Type': 'image/jpeg' }, body: blob });
        pulse('#p-cam', 'flash', 350);
      } catch (e) { /* board unreachable; the poll shows it */ }
      sending = false;
    }, 'image/jpeg', 0.82);
  }
  setInterval(sendFrame, 1000);

  async function startCamera() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: { width: { ideal: 1280 }, height: { ideal: 720 } }, audio: false });
      video.srcObject = stream; await video.play(); camOn = true;
    } catch (e) {
      camOn = false; alert('Camera unavailable: ' + e.message + '\nOpen this page as http://127.0.0.1:8000 (SSH tunnel) so the browser allows the camera.');
      setMode('sim');
    }
  }
  function setMode(m) {
    mode = m;
    $('#m-sim').classList.toggle('on', m === 'sim'); $('#m-cam').classList.toggle('on', m === 'camera');
    $('#simctl').classList.toggle('hidden', m !== 'sim'); $('#simbadge').classList.toggle('hidden', m !== 'sim');
    $('#p-cam small').textContent = m === 'sim' ? 'simulated runway' : 'laptop camera';
    if (m === 'camera' && !camOn) startCamera();
  }

  // ---------- a photo of anything, placed on the runway ----------
  function placeImage(src) {
    const img = new Image();
    img.onload = () => {
      const h = 130, w = Math.min(230, h * img.naturalWidth / img.naturalHeight);
      sim.photo = { img, x: 320, y: RY, w, h: w * img.naturalHeight / img.naturalWidth };
      setMode('sim');
    };
    img.src = src;
  }
  function placePhoto(file) {
    if (!file || !file.type.startsWith('image/')) return;
    placeImage(URL.createObjectURL(file));
  }
  $('#s-photo').onchange = (e) => { placePhoto(e.target.files[0]); e.target.value = ''; };

  // Preset photos, each checked with d1-2B on the board beforehand (static/presets.json).
  const PRESETS = [
    ['capy_baby', 'Baby capybara'], ['capy_family', 'Capybara family'], ['capy_portrait', 'Capybara'],
    ['dog', 'Dog'], ['deer', 'Deer'], ['goose', 'Goose'], ['car', 'Car'], ['cone', 'Traffic cone'],
  ];
  async function loadPresets() {
    let checked = {};
    try { checked = await (await fetch('/static/presets.json', { cache: 'no-store' })).json(); } catch (e) { /* not checked yet */ }
    $('#presets').innerHTML = PRESETS.map(([id, label]) => {
      const c = checked[id];
      const note = c ? `${Math.round(c.p_blocked * 100)}% blocked · ${c.what} ${Math.round((c.what_probs[c.what] || 0) * 100)}%` : 'not checked yet';
      return `<button class="preset" data-id="${id}"><img src="/static/img/presets/${id}.jpg" alt=""><b>${label}</b><small>d1: ${note}</small></button>`;
    }).join('');
    document.querySelectorAll('.preset').forEach((b) => { b.onclick = () => placeImage(`/static/img/presets/${b.dataset.id}.jpg`); });
  }
  loadPresets();
  const wrap = $('#viewwrap');
  wrap.addEventListener('dragover', (e) => { e.preventDefault(); wrap.classList.add('dragging'); });
  wrap.addEventListener('dragleave', () => wrap.classList.remove('dragging'));
  wrap.addEventListener('drop', (e) => { e.preventDefault(); wrap.classList.remove('dragging'); placePhoto(e.dataTransfer.files[0]); });

  // ---------- controls ----------
  const post = (url, body) => fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });
  $('#m-sim').onclick = () => setMode('sim');
  $('#m-cam').onclick = () => setMode('camera');
  $('#s-capy').onclick = () => {
    if (!sim.capy) sim.capy = { x: 250, y: 380, tx: 330, ty: RY, speed: 70, walk: 0, flip: true, leaving: false };
    else Object.assign(sim.capy, { tx: 330, ty: RY, leaving: false });
  };
  $('#s-cone').onclick = () => { sim.cone = { x: 230, y: RY - 4 }; };
  $('#s-clear').onclick = () => {
    sim.cone = null; sim.photo = null;
    if (sim.capy) Object.assign(sim.capy, { tx: 420, ty: 395, leaving: true });
  };
  $('#s-base').onclick = () => post('/api/baseline');
  $('#r-takeoff').onclick = () => post('/api/request', { kind: 'takeoff' });
  $('#r-landing').onclick = () => post('/api/request', { kind: 'landing' });

  // ---------- state from the board ----------
  const PH = {
    holding_short: ['holding short', 'wait'], waiting: ['told to hold', 'stop'], cleared_takeoff: ['cleared for takeoff', 'go'],
    departed: ['departed', ''], inbound: ['inbound', ''], holding: ['circling, wants to land', 'wait'],
    cleared_land: ['cleared to land', 'go'], go_around: ['GO AROUND', 'stop'], landed: ['landed', ''],
  };
  const NICE = { capybara: 'a capybara', wildlife: 'an animal', person: 'a person', vehicle: 'a vehicle', debris: 'debris', unknown: 'something' };
  const esc = (t) => String(t ?? '').replace(/[&<>"]/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[ch]));
  const fmt = (v, unit = '') => (v === null || v === undefined) ? '–' : `${v}${unit}`;

  function badge(el, text, cls) { el.textContent = text; el.className = el.className.includes('big') ? 'badge big ' + (cls || '') : 'badge ' + (cls || ''); }

  function render(s) {
    const pollNow = performance.now();
    // badges
    const wifiUp = (s.network.wifi || []).some((w) => w.state === 'up');
    badge($('#b-net'), s.network.uplink ? (wifiUp ? 'ONLINE · Wi-Fi on' : 'ONLINE · uplink present') : '✈ OFFLINE · no route off the board', s.network.uplink ? 'warn' : 'ok');
    badge($('#b-lfm'), s.lfm && s.lfm.ready ? `LFM3-1.7B · ${String(s.lfm.compute || '').toUpperCase()} · GenieX` : 'LFM3 server not reachable', s.lfm && s.lfm.ready ? 'ok' : 'bad');
    const g = s.status === 'starting' ? ['loading ' + (s.detail || ''), 'warn'] : s.gate === 'd1' ? ['d1-2B · CPU', 'ok'] : ['rule gate (fallback)', 'warn'];
    badge($('#b-gate'), g[0], g[1]);
    $('#rulectl').classList.toggle('hidden', s.gate !== 'rule');
    $('#p-d1 b').textContent = s.gate === 'rule' ? 'Pixel rule' : '👀 d1-2B';

    // pipeline
    $('#p-d1').classList.toggle('on', s.busy === 'd1');
    $('#p-lfm').classList.toggle('on', s.busy === 'lfm');
    const m = s.metrics;
    if (m.decisions !== lastCounts.decisions || m.skipped !== lastCounts.skipped) pulse('#p-gate');
    lastCounts = { decisions: m.decisions, skipped: m.skipped };

    // d1 progress
    if (s.busy === 'd1') {
      if (d1Since === null) d1Since = pollNow;
      const est = m.gate_ms_median || 7600;
      $('#d1prog').style.width = Math.min(96, ((pollNow - d1Since) / est) * 100) + '%';
      $('#d1wait').classList.remove('hidden');
    } else { d1Since = null; $('#d1prog').style.width = '0'; $('#d1wait').classList.add('hidden'); }

    // runway ribbon
    const r = s.runway, rib = $('#ribbon');
    if (r.status === 'clear') { rib.className = 'ribbon clear'; rib.textContent = 'RUNWAY 28 CLEAR'; }
    else if (r.status === 'closed') { rib.className = 'ribbon closed'; rib.textContent = 'RUNWAY 28 CLOSED · ' + String(r.obstruction || 'obstruction').toUpperCase() + ' ON THE RUNWAY'; }
    else { rib.className = 'ribbon wait'; rib.textContent = s.status === 'starting' ? 'CAPY IS WAKING UP: ' + (s.detail || '') : 'WAITING FOR THE RUNWAY CAMERA'; }

    // traffic phases for the overlay
    for (const t of r.traffic) {
      const p = phases[t.role];
      if (p.phase !== t.phase) { p.phase = t.phase; p.start = pollNow - t.age_s * 1000; }
    }
    $('#traffic').innerHTML = r.traffic.map((t) => {
      const [label, cls] = PH[t.phase] || [t.phase, ''];
      return `<div class="ac"><span><b>${esc(t.callsign)}</b> <small>${t.role}</small></span><span class="pill ${cls}">${esc(label)}</span></div>`;
    }).join('');

    // Capy
    const tower = s.radio.filter((x) => x.who.startsWith('TOWER'));
    const last = tower[tower.length - 1];
    let mood = 'chill';
    if (s.status === 'starting' || (s.busy === 'd1' && r.status !== 'closed')) mood = 'alert';
    else if (r.status === 'closed') mood = 'alarmed';
    else if (last && /clear_for_takeoff|clear_to_land|reopen_runway/.test(last.action || '') && Date.now() - Date.parse(last.t) < 10000) mood = 'happy';
    $('#capy').setAttribute('class', 'mood-' + mood);
    if (last) {
      $('#say').textContent = last.text;
      $('#saymeta').textContent = last.source === 'lfm3'
        ? `written by LFM3-1.7B on the NPU · ${fmt(last.ms, ' ms')} · ${fmt(last.tokens)} tokens`
        : 'template call' + (last.ok === false ? ' (LFM3 text failed the safety check)' : '');
    } else if (s.status !== 'starting') $('#say').textContent = 'Capy Tower online. Watching runway two-eight.';
    if (s.busy === 'd1') $('#saymeta').textContent = '👀 looking at the runway (d1-2B on the CPU)…';
    else if (s.busy === 'lfm') $('#saymeta').textContent = '📻 writing the radio call (LFM3-1.7B on the NPU)…';

    // radio transcript
    const newest = s.radio.length ? s.radio[s.radio.length - 1].t : null;
    if (newest && newest !== lastRadioT) { if (lastRadioT !== null) pulse('#p-radio'); lastRadioT = newest; }
    $('#radio').innerHTML = s.radio.slice().reverse().map((x, i) => {
      const meta = x.source === 'lfm3' ? `LFM3 · ${fmt(x.ms, ' ms')}` : x.source === 'pilot' ? 'pilot' : 'template';
      const fresh = Date.now() - Date.parse(x.t) < 2500 ? ' fresh' : '';
      return `<div class="msg ${x.who.startsWith('TOWER') ? 'tower' : ''}${fresh}"><span class="who">${esc(x.who)}</span>${esc(x.text)}<span class="meta">${esc(x.t.slice(11, 19))} · ${meta}</span></div>`;
    }).join('');

    // decision
    const d = s.decision;
    if (d) {
      if (d.t !== lastDecisionT) { lastDecisionT = d.t; $('#d-img').src = '/api/decided.jpg?t=' + encodeURIComponent(d.t); pulse('#p-pol'); }
      $('#d-meta').textContent = `${d.gate === 'd1' ? 'd1-2B' : 'rule'} · ${fmt(d.gate_ms, ' ms')} · ${d.t.slice(11, 19)} UTC`;
      const pb = d.p_blocked ?? 0, blocked = pb >= r.threshold;
      const verdict = blocked ? `🚫 ${(NICE[d.what] || 'something').replace(/^./, (c) => c.toUpperCase())} on the runway` : '✅ Runway looks empty';
      let html = `<div class="verdict ${blocked ? 'bad' : 'ok'}">${esc(verdict)}</div>
        <div class="bar main ${blocked ? '' : 'okfill'}"><div class="lbl"><span>P(something on the runway)</span><span>${(pb * 100).toFixed(0)}%</span></div>
        <div class="trk"><div class="fill" style="width:${pb * 100}%"></div><div class="mark" style="left:${r.threshold * 100}%"></div></div></div>`;
      const probs = Object.entries(d.what_probs || {}).sort((x, y) => y[1] - x[1]).slice(0, 4);
      for (const [k, v] of probs) {
        html += `<div class="bar"><div class="lbl"><span>${esc(k)}</span><span>${(v * 100).toFixed(0)}%</span></div><div class="trk"><div class="fill" style="width:${v * 100}%"></div></div></div>`;
      }
      $('#bars').innerHTML = html;
    }

    // metrics
    const skipped = m.frames_in ? Math.round((m.skipped / m.frames_in) * 100) : 0;
    const tiles = [
      ['d1 decision · CPU', `${fmt(m.gate_ms_median, '')}<small> ms median</small>`],
      ['LFM3 radio call · NPU', `${fmt(m.lfm_ms_median, '')}<small> ms · ${fmt(m.lfm_tokens_median)} tok</small>`],
      ['Frames → decisions', `${m.frames_in} → ${m.decisions}<small> (${skipped}% skipped)</small>`],
      ['Radio calls', `${m.radio_calls}<small> · ${m.fallbacks} template fallbacks</small>`],
      ['Last loop', `${fmt(m.loop_ms_last, '')}<small> ms</small>`],
      ['App memory', `${fmt(m.rss_mb)}<small> MB · peak ${fmt(m.peak_rss_mb)}</small>`],
      ['Uptime', `${Math.floor(m.uptime_s / 60)}<small> min ${m.uptime_s % 60} s</small>`],
      ['Off-board traffic', `${s.network.uplink ? 'possible' : 'none'}<small> ${s.network.uplink ? '(uplink up)' : '(no route)'}</small>`],
    ];
    $('#metrics').innerHTML = tiles.map(([k, v]) => `<div class="tile"><div class="k">${k}</div><div class="v">${v}</div></div>`).join('');

    // log tail
    $('#log').textContent = s.events.slice().reverse().map((e) => JSON.stringify(e)).join('\n');
  }

  async function poll() {
    try {
      const res = await fetch('/api/state', { cache: 'no-store' });
      render(await res.json());
    } catch (e) {
      badge($('#b-net'), 'board unreachable', 'bad');
    }
  }
  setInterval(poll, 800); poll();
  setMode('sim');
})();
