// --- Sliders ---
const lin = document.getElementById('lin');
const ang = document.getElementById('ang');
const linv = document.getElementById('linv');
const angv = document.getElementById('angv');
lin.addEventListener('input', () => linv.textContent = (+lin.value).toFixed(2));
ang.addEventListener('input', () => angv.textContent = (+ang.value).toFixed(2));

// --- YOLO prompt chips ---
const prompts = document.getElementById('prompts');
const newPrompt = document.getElementById('newPrompt');
prompts.addEventListener('click', e => {
  if (e.target.tagName === 'B') e.target.parentElement.remove();
});
newPrompt.addEventListener('keydown', e => {
  if (e.key === 'Enter' && newPrompt.value.trim()) {
    const chip = document.createElement('span');
    chip.className = 'chip';
    chip.innerHTML = `${newPrompt.value.trim()} <b>×</b>`;
    prompts.appendChild(chip);
    newPrompt.value = '';
  }
});

// --- Chat ---
const chatLog = document.getElementById('chatLog');
const chatBox = document.getElementById('chatBox');
const sendBtn = document.getElementById('sendBtn');
function pushMsg(text, who='user'){
  const d = document.createElement('div');
  d.className = `msg ${who}`;
  d.textContent = (who==='user'?'> ':'◆ ') + text;
  chatLog.appendChild(d); chatLog.scrollTop = chatLog.scrollHeight;
}
function send(){
  const t = chatBox.value.trim(); if(!t) return;
  pushMsg(t, 'user'); chatBox.value='';
  setTimeout(()=>pushMsg('Acknowledged: '+t, 'bot'), 400);
}
sendBtn.addEventListener('click', send);
chatBox.addEventListener('keydown', e => { if(e.key==='Enter') send(); });

// --- Emergency buttons ---
document.getElementById('estop').addEventListener('click', () => pushMsg('EMERGENCY STOP triggered', 'bot'));
document.getElementById('reset').addEventListener('click', () => { chatLog.innerHTML=''; pushMsg('Session reset', 'bot'); });

// --- Camera activation ---
const video = document.getElementById('cam');
const overlay = document.getElementById('overlay');
const fallback = document.getElementById('fallback');
const ctx = overlay.getContext('2d');

async function startCamera(){
  try{
    const stream = await navigator.mediaDevices.getUserMedia({
      video: { width: {ideal:1280}, height:{ideal:720}, facingMode:'user' },
      audio: false
    });
    video.srcObject = stream;
    await video.play();
    fallback.classList.add('hide');
    resizeOverlay();
    drawLoop();
  }catch(err){
    fallback.textContent = 'Camera error: ' + err.message;
    console.error(err);
  }
}

function resizeOverlay(){
  overlay.width = overlay.clientWidth;
  overlay.height = overlay.clientHeight;
}
window.addEventListener('resize', resizeOverlay);

// Real-time object detection via COCO-SSD
let model = null;
let latestPredictions = [];

async function loadModel(){
  pushMsg('Loading detector model…', 'bot');
  try{
    model = await cocoSsd.load({ base: 'lite_mobilenet_v2' });
    pushMsg('Detector ready.', 'bot');
    detectLoop();
  }catch(err){
    pushMsg('Model load failed: ' + err.message, 'bot');
    console.error(err);
  }
}

async function detectLoop(){
  if (!model || video.readyState < 2){
    return requestAnimationFrame(detectLoop);
  }
  try{
    // Filter by active YOLO prompt chips (labels). If empty, show all.
    const active = [...document.querySelectorAll('.chip')]
      .map(c => c.firstChild.textContent.trim().toLowerCase());
    const preds = await model.detect(video);
    latestPredictions = active.length
      ? preds.filter(p => active.includes(p.class.toLowerCase()))
      : preds;
  }catch(e){ console.error(e); }
  requestAnimationFrame(detectLoop);
}

function drawLoop(){
  const W = overlay.width, H = overlay.height;
  ctx.clearRect(0,0,W,H);
  ctx.lineWidth = 2;
  ctx.strokeStyle = '#39ff88';
  ctx.font = '12px ui-monospace, monospace';

  // Video is object-fit:cover → compute mapping from video px to canvas px
  const vw = video.videoWidth || 1, vh = video.videoHeight || 1;
  const scale = Math.max(W / vw, H / vh);
  const dw = vw * scale, dh = vh * scale;
  const ox = (W - dw) / 2, oy = (H - dh) / 2;

  latestPredictions.forEach(p => {
    const [x, y, w, h] = p.bbox;
    const rx = ox + x * scale;
    const ry = oy + y * scale;
    const rw = w * scale;
    const rh = h * scale;
    ctx.strokeStyle = '#39ff88';
    ctx.strokeRect(rx, ry, rw, rh);
    const tag = `${p.class} ${p.score.toFixed(2)}`;
    const tw = ctx.measureText(tag).width + 8;
    ctx.fillStyle = '#39ff88';
    ctx.fillRect(rx, ry - 16, tw, 16);
    ctx.fillStyle = '#04120a';
    ctx.fillText(tag, rx + 4, ry - 4);
  });
  requestAnimationFrame(drawLoop);
}

startCamera().then(loadModel);
pushMsg('VL-ADK dashboard online.', 'bot');
