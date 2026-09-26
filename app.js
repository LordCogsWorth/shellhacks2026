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

// Fake YOLO-style boxes that gently drift, matching the demo aesthetic
const boxes = [
  { x:.30, y:.20, w:.22, h:.55, label:'person', conf:.92 },
  { x:.58, y:.28, w:.14, h:.35, label:'person', conf:.83 },
  { x:.72, y:.32, w:.10, h:.28, label:'person', conf:.64 },
];
function drawLoop(){
  const W = overlay.width, H = overlay.height;
  ctx.clearRect(0,0,W,H);
  ctx.lineWidth = 2;
  ctx.strokeStyle = '#39ff88';
  ctx.fillStyle = '#39ff88';
  ctx.font = '12px ui-monospace, monospace';
  const t = performance.now()/1000;
  boxes.forEach((b,i)=>{
    const dx = Math.sin(t*0.6 + i)*0.005;
    const dy = Math.cos(t*0.4 + i)*0.004;
    const x=(b.x+dx)*W, y=(b.y+dy)*H, w=b.w*W, h=b.h*H;
    ctx.strokeRect(x,y,w,h);
    const tag = `${b.label} ${b.conf.toFixed(2)}`;
    const tw = ctx.measureText(tag).width + 8;
    ctx.fillRect(x, y-16, tw, 16);
    ctx.fillStyle = '#04120a';
    ctx.fillText(tag, x+4, y-4);
    ctx.fillStyle = '#39ff88';
  });
  requestAnimationFrame(drawLoop);
}

startCamera();
pushMsg('VL-ADK dashboard online.', 'bot');
