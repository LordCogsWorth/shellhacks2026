// dog.js — guide-dog features for the VL-ADK dashboard.
// Loads after app.js and reuses its globals: map, meMarker, miniCoords, pushMsg, lin, ang.
// Works in two modes:
//   * ROBOT mode (page served by bridge.py on the Pi): drives the car, real GPS, real barks.
//   * DEMO mode (opened from your laptop): everything visual still works — webcam, barks, minimap.

(() => {
  // ---------------------------------------------------------------- config
  const DISLIKE = ['cat', 'dog', 'bicycle', 'skateboard', 'motorcycle'];  // things the dog barks at
  const HAZARDS = ['bicycle', 'car', 'motorcycle', 'bus', 'truck', 'fire hydrant', 'bench', 'stop sign'];
  const BARK_COOLDOWN_MS = 6000;
  const barkSfx = new Audio('sounds/bark.mp3');   // put any short bark clip here

  // ---------------------------------------------------------------- robot connection
  let ws = null, connected = false;
  const status = document.createElement('span');
  status.className = 'robot-status';
  status.textContent = '● ROBOT OFFLINE (demo mode)';
  document.querySelector('.brand').appendChild(status);

  function send(obj){ if (connected) ws.send(JSON.stringify(obj)); }

  function connect(){
    if (!['8000', '8443'].includes(location.port)) return;   // demo mode: no robot
    ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`);
    ws.onopen = () => {
      connected = true;
      status.textContent = '● ROBOT ONLINE'; status.classList.add('on');
      send({ type: 'dislike', labels: DISLIKE });
      pushMsg('Robot connected.', 'bot');
    };
    ws.onclose = () => {
      connected = false;
      setManual(false);
      status.textContent = '● ROBOT OFFLINE'; status.classList.remove('on');
      setTimeout(connect, 2000);
    };
    ws.onmessage = e => {
      const m = JSON.parse(e.data);
      if (m.type === 'telemetry') onTelemetry(m);
      if (m.type === 'bark') barkFx(m.label);
      if (m.type === 'object_event' && window.OBJECTS) OBJECTS.event(m);
      if (m.type === 'error') pushMsg(m.message, 'bot');
      if (m.type === 'manual_status'){ setManual(m.enabled, false); manualHint.textContent = m.message; }
    };
  }
  connect();

  // ---------------------------------------------------------------- manual test controls
  const held = new Set();
  const DRIVE_KEYS = ['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'];
  const manualToggle = document.getElementById('manual-toggle');
  const manualHint = document.getElementById('manual-hint');
  let manualEnabled = false;

  function stopManual(){
    held.clear();
    send({ type: 'manual_stop' });
  }
  function setManual(enabled, notify = true){
    manualEnabled = enabled && connected;
    manualToggle.setAttribute('aria-pressed', String(manualEnabled));
    manualToggle.textContent = manualEnabled ? 'MANUAL ON' : 'MANUAL OFF';
    manualToggle.classList.toggle('active', manualEnabled);
    manualHint.textContent = manualEnabled
      ? 'Hold arrow keys to drive. Release to stop. Space / Esc stops and turns manual off.'
      : 'Testing only. Turn on to use arrow keys. Controls turn off when this window loses focus.';
    document.getElementById('manual-keys').classList.toggle('manual-disabled', !manualEnabled);
    if (!manualEnabled) stopManual();
    if (notify) send({type: "manual", enabled: manualEnabled});
  }
  manualToggle.addEventListener('click', () => {
    if (!connected){ pushMsg('Connect to the robot before enabling manual controls.', 'bot'); return; }
    setManual(!manualEnabled);
    manualToggle.blur();
  });
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape'){ estop(); e.preventDefault(); return; }
    if (e.target.closest('input,textarea,select,button,[contenteditable=true]')) return;
    if (e.key === ' '){ estop(); e.preventDefault(); return; }
    if (!manualEnabled || !connected || e.metaKey || e.ctrlKey || e.altKey) return;
    if (DRIVE_KEYS.includes(e.key)){ held.add(e.key); e.preventDefault(); }
  });
  document.addEventListener('keyup', e => {
    if (!DRIVE_KEYS.includes(e.key)) return;
    const wasHeld = held.delete(e.key);
    if (wasHeld){ e.preventDefault(); if (!held.size) stopManual(); }
  });
  document.addEventListener('focusin', e => {
    if (held.size && e.target.closest('input,textarea,select,button,[contenteditable=true]')) stopManual();
  });
  window.addEventListener('blur', () => { if (manualEnabled) setManual(false); });
  document.addEventListener('visibilitychange', () => {
    if (document.hidden && manualEnabled) setManual(false);
  });

  setInterval(() => {
    if (!manualEnabled || !connected || !held.size) return;
    const forward = (held.has('ArrowUp') ? 1 : 0) - (held.has('ArrowDown') ? 1 : 0);
    const turn = (held.has('ArrowRight') ? 1 : 0) - (held.has('ArrowLeft') ? 1 : 0);
    send({ type: 'drive', lin: forward * +lin.value, ang: turn * +ang.value, strafe: 0 });
  }, 100);

  function estop(){
    setManual(false);
    send({type: 'estop'});
    pushMsg('EMERGENCY STOP sent to robot; manual controls off.', 'bot');
  }
  document.getElementById('estop').addEventListener('click', estop);

  // ---------------------------------------------------------------- minimap upgrades
  const mini = document.getElementById('minimap');
  const hud = document.getElementById('miniHud');
  document.querySelector('.minimap-title').addEventListener('click', () => {
    mini.classList.toggle('big');
    setTimeout(() => map.invalidateSize(), 300);
  });

  // heading arrow replaces the dot
  const arrowIcon = L.divIcon({ className: '', html: '<div class="heading-arrow" id="hdg"></div>',
                                iconSize: [16, 18], iconAnchor: [8, 11] });
  meMarker.setIcon(arrowIcon);
  const setHeading = deg => { const el = document.getElementById('hdg'); if (el) el.style.transform = `rotate(${deg}deg)`; };

  // breadcrumb trail + planned route + destination
  const trail = L.polyline([], { color: '#39ff88', weight: 2, opacity: .6, dashArray: '2 6' }).addTo(map);
  const routeLine = L.polyline([], { color: '#ffcc00', weight: 4, opacity: .9 }).addTo(map);
  let destMarker = null, route = [], here = null;

  function updatePosition(lat, lon){
    here = [lat, lon];
    if (!map.hasLayer(meMarker)) meMarker.addTo(map);
    meMarker.setLatLng(here);
    miniCoords.textContent = `${lat.toFixed(5)}, ${lon.toFixed(5)}`;
    const pts = trail.getLatLngs();
    const last = pts[pts.length - 1];
    if (!last || map.distance(last, here) > 1.5) trail.addLatLng(here);
    if (!mini.matches(':hover')) map.panTo(here, { animate: true });
  }

  // in demo mode, follow the browser's own location
  if (!['8000', '8443'].includes(location.port) && navigator.geolocation){
    navigator.geolocation.watchPosition(p => updatePosition(p.coords.latitude, p.coords.longitude),
      () => {}, { enableHighAccuracy: true });
    window.addEventListener('deviceorientationabsolute', e => e.alpha != null && setHeading(360 - e.alpha));
  }

  function onTelemetry(m){
    if (!m.arduino_connected && manualEnabled) setManual(false);
    if (manualEnabled && m.manual_feedback) manualHint.textContent = m.manual_feedback;
    if (window.NAV) NAV.telemetry(m);
    if (!m.camera_connected) window.robotCameraFresh = false;
    else window.robotCameraFresh = true;
    status.textContent = m.arduino_connected ? '● ROBOT ONLINE' : '● BRIDGE ONLINE · ARDUINO OFFLINE';
    status.classList.toggle('on', !!m.arduino_connected);
    if (m.gps && m.gps_ok){
      updatePosition(m.gps.lat, m.gps.lon);
      miniCoords.textContent += ` · 📱 ±${Math.round(m.gps.acc ?? 0)} m`;
    } else if (m.gps === null || m.gps_ok === false){
      here = null;
      meMarker.remove();
      miniCoords.textContent = 'NO GPS — open /setup.html on the iPhone';
    }
    if (m.heading != null) setHeading(m.heading);
    (m.alerts || []).forEach(a => pushMsg('⚠ ' + a, 'bot'));
    if (route.length && here){
      const next = route[Math.min(m.wp_index, route.length - 1)];
      const left = route.slice(m.wp_index).reduce((acc, p, i, arr) =>
        acc + (i ? map.distance(arr[i - 1], p) : map.distance(here, p)), 0);
      hud.textContent = m.mode === 'route'
        ? `→ next point ${Math.round(map.distance(here, next))} m · ${Math.round(left)} m to go`
        : (m.wp_index >= route.length ? '★ arrived' : 'route paused');
    }
    if (m.dist != null && m.dist > 0 && m.dist < 40) hud.textContent = `⚠ obstacle ${Math.round(m.dist)} cm`;
  }

  // Destinations are selected by name in chat; map clicks never command motion.
  map.on('click', () => pushMsg('Ask chat for a preset destination, for example “take me to the grocery store”.', 'bot'));

  // ---------------------------------------------------------------- barking + hazard pins
  let lastBark = 0, lastDetectionSend = 0;
  const pinned = {};
  function barkFx(label){
    barkSfx.currentTime = 0; barkSfx.play().catch(() => {});
    const wrap = document.querySelector('.video-wrap');
    wrap.classList.remove('barking'); void wrap.offsetWidth; wrap.classList.add('barking');
    setTimeout(() => wrap.classList.remove('barking'), 1200);
    pushMsg(`WOOF! WOOF! (${label})`, 'bot');
  }

  window.DOG = {
    onDetections(preds){
      if (ON_ROBOT && !window.robotCameraFresh) return;
      const labels = preds.filter(p => p.score > 0.75).map(p => p.class);
      if (!labels.length) return;
      if (connected && Date.now() - lastDetectionSend > 1000){
        lastDetectionSend = Date.now();
        send({ type: 'detections', labels });           // robot decides & barks out loud
      } else if (Date.now() - lastBark > BARK_COOLDOWN_MS){
        const hit = labels.find(l => DISLIKE.includes(l));
        if (hit){ lastBark = Date.now(); barkFx(hit); }
      }

    }
  };
})();
