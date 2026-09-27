// Walking route previews. Google route geometry is rendered only on Google Maps.
(() => {
  const el = id => document.getElementById(id);
  let snapshot = null, busy = false, gmap = null, gpath = null, gposition = null;
  let googleLoading = false, googleFailed = false, lastPlan = null, lastReason = '', currentGPS = null;
  const markers = new Map();
  const localMarkers = new Map();
  const escapeText = text => { const n = document.createElement('span'); n.textContent = text; return n; };
  async function api(path, body){
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 60000);
    try {
      const response = await fetch(path, {method: body ? 'POST' : 'GET',
        headers: body ? {'Content-Type':'application/json'} : {}, body: body ? JSON.stringify(body) : undefined,
        signal:controller.signal});
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'Request failed');
      return result;
    } finally { clearTimeout(timer); }
  }
  function loadGoogle(key){
    if (!key || googleLoading || gmap || googleFailed) return;
    googleLoading = true;
    window.gm_authFailure = () => {
      googleFailed = true;
      el('nav-status').textContent = 'Google map authorization failed. Check browser key restrictions.';
      const panel = el('google-map'); if (panel) panel.style.display = 'none';
      el('map').style.display = ''; map.invalidateSize();
    };
    window.guideDogGoogleReady = () => {
      const panel = document.createElement('div'); panel.id = 'google-map';
      el('map').after(panel); el('map').style.display = 'none';
      gmap = new google.maps.Map(panel, {center: currentGPS ? {lat:currentGPS.lat,lng:currentGPS.lon} : {lat:0,lng:0},
        zoom:currentGPS ? 17 : 2, mapTypeControl:false, streetViewControl:false, fullscreenControl:false});
      gpath = new google.maps.Polyline({map:gmap, strokeColor:'#bb8200', strokeWeight:5});
      googleLoading = false;
      lastPlan = null;
      if (snapshot) render(snapshot);
      if (currentGPS) updateGooglePosition(currentGPS);
    };
    const script = document.createElement('script');
    script.src = 'https://maps.googleapis.com/maps/api/js?' + new URLSearchParams({key, callback:'guideDogGoogleReady', loading:'async', v:'weekly'});
    script.async = true;
    script.onerror = () => { googleLoading = false; googleFailed = true; el('nav-status').textContent = 'Google map could not load. Check internet access.'; };
    document.head.appendChild(script);
  }
  function updateGooglePosition(gps){
    if (!gmap || googleFailed) return;
    const position = {lat:gps.lat,lng:gps.lon};
    if (!gposition) { gposition = new google.maps.Marker({map:gmap, position, title:'Live iPhone location', label:'●'}); gmap.setCenter(position); gmap.setZoom(17); }
    else gposition.setPosition(position);
  }
  function render(data){
    snapshot = data;
    if (data.google_maps_browser_key) loadGoogle(data.google_maps_browser_key);
    const missing = data.configured ? Object.entries(data.configured).filter(([,v])=>!v).map(([k])=>k.replace('_',' ')) : [];
    el('nav-status').textContent = data.hold ? 'ROUTE PAUSED · ' + data.reason :
      (missing.length ? 'Setup needed: ' + missing.join(', ') : 'Route preview ready · manual driving only');
    if (data.configuration_error) el('nav-status').textContent = data.configuration_error;
    if (data.destinations){
      el('nav-presets').replaceChildren();
      if (!data.destinations.length) el('nav-presets').textContent = 'No destinations configured yet.';
      data.destinations.forEach(d => {
        const button = document.createElement('button'); button.className = 'btn'; button.textContent = d.name;
        button.onclick = () => { pushMsg('Take me to ' + d.name, 'user'); chat('Take me to ' + d.name); };
        el('nav-presets').appendChild(button);
      });
    }
    el('nav-review').hidden = !data.hold;
    el('nav-replan').disabled = busy || !data.plan;
    if (data.reason && data.reason !== lastReason){ pushMsg(data.reason, 'bot'); lastReason = data.reason; }
    if (data.plan){
      const plan = data.plan;
      el('nav-summary').textContent = `${plan.destination.name} · ${Math.round(plan.distance_m)} m · ${plan.status.replaceAll('_',' ')} · Google Maps`;
      el('nav-warning').textContent = plan.warnings.join(' ');
      if (plan.id !== lastPlan){
        el('nav-steps').replaceChildren();
        plan.steps.filter(Boolean).forEach(step => { const li=document.createElement('li');li.textContent=step;el('nav-steps').appendChild(li); });
        if (gmap && !googleFailed){
          const path = plan.points.map(([lat,lng])=>({lat,lng})); gpath.setPath(path);
          const bounds=new google.maps.LatLngBounds();path.forEach(p=>bounds.extend(p));gmap.fitBounds(bounds,30);
          lastPlan=plan.id;
        } else {
          el('nav-summary').textContent += ' · Map preview needs a working Google Maps browser key';
        }
      }
      if (gpath) gpath.setOptions({strokeColor:plan.status === 'blocked' || plan.status === 'needs_review' ? '#ff5a5a' : '#bb8200'});
    }
    for (const hazard of data.hazards || []){
      const title = `${hazard.label}: ${hazard.note} (±${Math.round(hazard.radius_m)} m)`;
      if (gmap && !googleFailed){
        if (!markers.has(hazard.id)){
          const marker = new google.maps.Marker({map:gmap, position:{lat:hazard.lat,lng:hazard.lon}, label:hazard.icon, title});
          const circle = new google.maps.Circle({map:gmap,center:{lat:hazard.lat,lng:hazard.lon},radius:hazard.radius_m,strokeColor:'#ee7045',strokeWeight:1,fillColor:'#ee7045',fillOpacity:.12});
          markers.set(hazard.id,{marker,circle});
        }
      } else if (!localMarkers.has(hazard.id)){
        const marker=L.marker([hazard.lat,hazard.lon],{icon:L.divIcon({className:'hazard-pin',html:escapeText(hazard.icon).outerHTML})}).bindTooltip(escapeText(title)).addTo(map);
        const circle=L.circle([hazard.lat,hazard.lon],{radius:hazard.radius_m,color:'#ee7045',weight:1,fillOpacity:.12}).addTo(map);
        localMarkers.set(hazard.id,{marker,circle});
      }
    }
    const ids=new Set((data.hazards||[]).map(h=>h.id));
    for (const [id,item] of markers) if (!ids.has(id)){item.marker.setMap(null);item.circle.setMap(null);markers.delete(id);}
    for (const [id,item] of localMarkers) if (!ids.has(id)){item.marker.remove();item.circle.remove();localMarkers.delete(id);}
  }
  async function chat(message){
    if (busy){pushMsg('A route request is already running. Please wait.', 'bot');return;}
    busy=true; el('sendBtn').disabled=true; el('nav-replan').disabled=true;
    el('nav-status').textContent='Reading your request…';
    try { const result=await api('/chat',{message}); pushMsg(result.reply,'bot'); if(window.OBJECTS) await OBJECTS.handle(result); if(result.place_choices) showChoices(result.place_choices); await refresh(); }
    catch(error){pushMsg(error.message,'bot');el('nav-status').textContent=error.message;}
    finally{busy=false;el('sendBtn').disabled=false;el('nav-replan').disabled=!snapshot?.plan;}
  }
  function showChoices(choices){
    const group=document.createElement('div'); group.className='place-choices';
    const attribution=document.createElement('small');attribution.textContent='Place results · Google Maps';group.append(attribution);
    for(const choice of choices){
      const button=document.createElement('button');button.className='btn';button.textContent=choice.name+' — '+choice.address;
      button.onclick=async()=>{
        group.querySelectorAll('button').forEach(b=>b.disabled=true);
        try{const result=await api('/places/confirm',{token:choice.token});pushMsg(result.reply,'bot');if(window.OBJECTS)await OBJECTS.handle(result);group.remove();}
        catch(e){pushMsg(e.message,'bot');group.querySelectorAll('button').forEach(b=>b.disabled=false);}
      };
      group.append(button);
      for(const a of choice.attributions||[]){const credit=document.createElement('span');credit.textContent=a.provider||'';group.append(credit);}
    }
    document.getElementById('chatLog').append(group);group.scrollIntoView({block:'nearest'});
  }
  async function refresh(){
    try{render(await api('/navigation'));}
    catch(error){el('nav-status').textContent='Route planner offline: '+error.message;}
  }
  el('nav-replan').onclick=()=>snapshot?.plan && chat('Take me to '+snapshot.plan.destination.name);
  el('nav-review').onclick=async()=>{
    try{await api('/navigation/acknowledge',{});await refresh();}
    catch(error){pushMsg(error.message,'bot');}
  };
  window.NAV={chat,googleMap:()=>googleFailed?null:gmap,telemetry(data){
    currentGPS=data.gps_ok?data.gps:null;
    if(currentGPS)updateGooglePosition(currentGPS);
    else if(gposition){gposition.setMap(null);gposition=null;}
  }};
  async function poll(){if(!busy)await refresh();setTimeout(poll,2000);}
  poll();
})();
