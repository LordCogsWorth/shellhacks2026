const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert/strict');
const jsQR=require('../dashboard/vendor/jsQR.js');
const context={document:{documentElement:{tagName:'html'}},navigator:{userAgent:'node'},window:{}};
vm.createContext(context);vm.runInContext(fs.readFileSync('dashboard/vendor/qrcode.min.js','utf8'),context);
const label={childNodes:[{offsetWidth:224,offsetHeight:224,style:{}}]};
const payload='GUIDEDOG:OBJECT:0123456789abcdef0123456789abcdef';
const qr=new context.QRCode(label,{text:payload,width:224,height:224,correctLevel:context.QRCode.CorrectLevel.M});
const matrix=qr._oQRCode, modules=matrix.getModuleCount(),scale=6, border=4,size=(modules+border*2)*scale;
const pixels=new Uint8ClampedArray(size*size*4);pixels.fill(255);
for(let y=0;y<modules;y++)for(let x=0;x<modules;x++)if(matrix.isDark(y,x))for(let dy=0;dy<scale;dy++)for(let dx=0;dx<scale;dx++){
 const pos=(((y+border)*scale+dy)*size+(x+border)*scale+dx)*4;pixels[pos]=pixels[pos+1]=pixels[pos+2]=0;
}
const decoded=jsQR(pixels,size,size,{inversionAttempts:'dontInvert'});assert.equal(decoded.data,payload);
console.log('Printed-label generator → camera QR decoder round trip passed (isolated generated image).');
