const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('dashboard/dog.js','utf8');
const code=source.slice(source.indexOf('  // ---------------------------------------------------------------- manual test controls'),source.indexOf('  // ---------------------------------------------------------------- minimap'));
const handlers={},win={},elements={},sent=[];let tick;
function element(id){return elements[id]??=( {setAttribute(k,v){this[k]=v},classList:{toggle(){}},addEventListener(k,f){this[k]=f},blur(){}});}
const context={connected:true,send:m=>sent.push(m),pushMsg(){},lin:{value:.5},ang:{value:.4},
 document:{getElementById:element,addEventListener:(k,f)=>handlers[k]=f,hidden:false},
 window:{addEventListener:(k,f)=>win[k]=f},setInterval:f=>tick=f};
vm.createContext(context);vm.runInContext(code,context);
function key(key,editable=false){return {key,target:{closest:()=>editable},preventDefault(){this.prevented=true}};}
handlers.keydown(key('ArrowUp'));tick();assert.equal(sent.length,0,'off by default');
elements['manual-toggle'].click();sent.length=0;
handlers.keydown(key('w'));tick();assert.equal(sent.length,0,'WASD removed');
handlers.keydown(key('ArrowUp',true));tick();assert.equal(sent.length,0,'typing does not drive');
let up=key('ArrowUp');handlers.keydown(up);tick();assert.equal(sent.at(-1).lin,.5);assert.equal(up.prevented,true);
handlers.keyup(key('ArrowUp'));assert.equal(sent.at(-1).type,'manual_stop','release stops');
handlers.keydown(key('ArrowLeft'));tick();assert.equal(sent.at(-1).ang,-.4);
elements['manual-toggle'].click();assert.equal(sent.at(-1).enabled,false,'toggle off disables session');
let count=sent.length;tick();assert.equal(sent.length,count);
elements['manual-toggle'].click();handlers.keydown(key('ArrowDown'));tick();assert.equal(sent.at(-1).lin,-.5);
win.blur();assert.equal(elements['manual-toggle']['aria-pressed'],'false');assert.equal(sent.at(-1).enabled,false);
elements['manual-toggle'].click();handlers.keydown(key('Escape',true));assert.equal(elements['manual-toggle']['aria-pressed'],'false');
console.log('Manual control checks passed: default off, arrows, no WASD, typing guard, key release, toggle off, blur, Escape.');
