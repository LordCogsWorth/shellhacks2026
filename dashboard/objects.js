(() => {
  const $=id=>document.getElementById(id);
  let state=null, scanning=false, timer=null, inFlight=false, candidate=null, lastEvent='', activeMap=null;
  const canvas=document.createElement('canvas'), ctx=canvas.getContext('2d',{willReadFrequently:true}), pins=new Map();
  function node(tag,text,cls){const n=document.createElement(tag);if(text)n.textContent=text;if(cls)n.className=cls;return n;}
  async function api(path,body){
    const controller=new AbortController(), timeout=setTimeout(()=>controller.abort(),15000);
    try {const r=await fetch(path,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined,signal:controller.signal});const j=await r.json();if(!r.ok)throw new Error(j.error||'Map memory unavailable');return j;}finally{clearTimeout(timeout);}
  }
  const symbols={monster:'ϟ',bottle:'♧',medicine:'✚',object:'◆',store:'▤',home:'⌂',place:'★'};
  function svg(o){
    const color=o.status==='missing'?'#ffb74d':o.icon==='monster'?'#91ed38':o.kind==='place'?'#ffcf56':'#70d9ff';
    const shape=o.icon==='monster'?'<rect x="13" y="7" width="18" height="26" rx="4" fill="#192516"/><text x="22" y="27" fill="#91ed38" font-size="22" text-anchor="middle">ϟ</text>':o.icon==='bottle'?'<path d="M18 7h8v6l4 5v14H14V18l4-5z" fill="#153f54"/><path d="M17 22h10v6H17z" fill="#70d9ff"/>':`<text x="22" y="29" fill="#132021" font-size="27" text-anchor="middle">${symbols[o.icon]||'◆'}</text>`;
    return `<svg xmlns="http://www.w3.org/2000/svg" width="44" height="52" viewBox="0 0 44 52"><path d="M22 51L7 33A21 21 0 1 1 37 33Z" fill="${color}" stroke="#132021" stroke-width="2"/>${shape}</svg>`;
  }
  function popup(o){
    const box=node('div',null,'memory-popup');box.append(node('strong',o.name));
    if(o.kind==='place'){box.append(node('p',o.title||'Saved phone position'),node('p',o.address||`Phone GPS ±${Math.round(o.accuracy||25)} m`));if(o.source==='google')box.append(node('small','Google Maps'));}
    else{
      box.append(node('p',o.status==='missing'?'MOVED · previous position unconfirmed':o.source==='tag'?'Camera tag observation':'Position reported by you'));
      box.append(node('p',`${o.zone||'Phone position'} · ±${Math.round(o.gps?.acc||25)} m`));
      if(o.last_seen)box.append(node('small',new Date(o.last_seen*1000).toLocaleString()));
      if(o.photo_url){const img=node('img');img.src=o.photo_url+'?t='+o.last_seen;img.alt='Camera frame at saved time';box.append(img);}
      const moved=node('button','I moved it','btn');moved.onclick=()=>{const msg='I moved my '+o.name;pushMsg(msg,'user');NAV.chat(msg);};box.append(moved);
      const tags=node('a','Print object labels');tags.href='/object-tags.html';tags.target='_blank';box.append(tags);
    }
    for(const a of o.attributions||[]){if(a.providerUri?.startsWith('https://')){const link=node('a',a.provider||'Source');link.href=a.providerUri;link.target='_blank';link.rel='noopener';box.append(link);}else box.append(node('small',a.provider||''));}
    return box;
  }
  function clear(){for(const p of pins.values()){if(p.google)p.marker.setMap(null);else p.marker.remove();}pins.clear();}
  function render(data){
    state=data;const gm=window.NAV?.googleMap(), target=gm||map;
    if(activeMap!==target){clear();activeMap=target;}
    const items=[...data.objects.map(o=>({...o,key:'o:'+o.id,lat:o.gps?.lat,lon:o.gps?.lon})),...data.places.map(p=>({...p,key:'p:'+p.id}))];
    const visible=items.filter(o=>Number.isFinite(o.lat)&&Number.isFinite(o.lon)&&(o.source!=='google'||gm));
    for(const [key,p] of pins)if(!visible.some(o=>o.key===key)){if(p.google)p.marker.setMap(null);else p.marker.remove();pins.delete(key);}
    const buckets=new Map();
    for(const o of visible){
      const coord=o.lat.toFixed(5)+','+o.lon.toFixed(5), index=buckets.get(coord)||0;buckets.set(coord,index+1);
      const offset=index*36, signature=JSON.stringify([o,offset]);if(pins.get(o.key)?.signature===signature)continue;
      const old=pins.get(o.key);if(old){if(old.google)old.marker.setMap(null);else old.marker.remove();}
      const content=popup(o);let marker,info;
      if(gm){marker=new google.maps.Marker({map:gm,position:{lat:o.lat,lng:o.lon},title:o.name,icon:{url:'data:image/svg+xml;charset=UTF-8,'+encodeURIComponent(svg(o)),scaledSize:new google.maps.Size(36,43),anchor:new google.maps.Point(18-offset,43)}});info=new google.maps.InfoWindow({content});marker.addListener('click',()=>info.open({map:gm,anchor:marker}));}
      else marker=L.marker([o.lat,o.lon],{title:o.name,icon:L.divIcon({className:'memory-pin',html:svg(o),iconSize:[36,43],iconAnchor:[18-offset,43]})}).bindPopup(content).addTo(map);
      pins.set(o.key,{marker,info,google:!!gm,signature});
    }
    $('memory-count').textContent=`${data.objects.length} things · ${data.places.length} places`;
    if(!scanning)$('memory-status').textContent=items.some(o=>o.source==='google'&&(!gm||o.unresolved))?'Google map configuration needed for saved places':items.some(o=>o.lat==null)?'Some items need a fresh GPS position':'';
  }
  async function refresh(){try{render(await api('/memory'));}catch(e){$('memory-status').textContent=e.message;}}
  function focus(key){const p=pins.get(key);if(!p)return;if(p.google){activeMap.panTo(p.marker.getPosition());p.info.open({map:activeMap,anchor:p.marker});}else{map.panTo(p.marker.getLatLng());p.marker.openPopup();}}
  function setScanning(on){scanning=on;candidate=null;clearTimeout(timer);$('memory-status').textContent=on?'Looking for a registered object label…':'Tag scanner off';if(on)scan();}
  async function scan(){
    if(!scanning||inFlight)return;
    inFlight=true;let bitmap;
    try{
      if(document.hidden)throw new Error('Scanner paused while this tab is hidden.');
      const controller=new AbortController(), timeout=setTimeout(()=>controller.abort(),5000);
      let r;try{r=await fetch('/camera/snapshot.jpg',{cache:'no-store',signal:controller.signal});}finally{clearTimeout(timeout);}
      if(!r.ok)throw new Error('Camera offline. Keep the phone camera page open.');
      const frameId=r.headers.get('X-Frame-Id');bitmap=await createImageBitmap(await r.blob());
      const scale=Math.min(1,640/Math.max(bitmap.width,bitmap.height));canvas.width=Math.round(bitmap.width*scale);canvas.height=Math.round(bitmap.height*scale);
      ctx.drawImage(bitmap,0,0,canvas.width,canvas.height);
      const image=ctx.getImageData(0,0,canvas.width,canvas.height);
      const qr=jsQR(image.data,image.width,image.height,{inversionAttempts:'dontInvert'});
      if(!qr||!qr.data.startsWith('GUIDEDOG:OBJECT:')){candidate=null;$('memory-status').textContent=`Scanning ${state?.zone} — hold one label steady and close enough to read.`;}
      else if(candidate!==qr.data){candidate=qr.data;$('memory-status').textContent='Label found. Hold steady to confirm…';}
      else{
        if(!scanning)return;
        const result=await api('/objects/observe',{tag:qr.data,zone:state?.zone,frame_id:frameId});
        $('memory-status').textContent=`${result.name} confirmed at ${result.zone}.`;
        if(result.changed){await refresh();focus("o:"+result.object_id);}
      }
    }catch(e){candidate=null;$('memory-status').textContent=e.message;}
    finally{bitmap?.close();inFlight=false;if(scanning)timer=setTimeout(scan,650);}
  }
  document.addEventListener('visibilitychange',()=>{if(document.hidden)setScanning(false);});
  window.OBJECTS={async handle(result){if(result.action==='stop_scan')setScanning(false);await refresh();if(result.action==='start_scan')setScanning(true);if(result.object_id)focus('o:'+result.object_id);if(result.place_id)focus('p:'+result.place_id);},highlight(id){refresh().then(()=>focus('o:'+id));},event(e){const key=e.object_id+e.kind+e.zone;if(lastEvent!==key){pushMsg(`${e.name} ${e.kind==='remembered'?'remembered':'found again'} at ${e.zone}.`,'bot');lastEvent=key;}refresh();}};
  async function poll(){await refresh();setTimeout(poll,3000);}poll();
})();
