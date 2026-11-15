const $=s=>document.querySelector(s);
const esc=s=>String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
async function api(port,path,method='GET',body){
  try{const r=await fetch(`/api/${port}${path}`,{method,headers:{'content-type':'application/json'},body:body?JSON.stringify(body):undefined});
    let d=null;try{d=await r.json()}catch(e){}return{ok:r.ok,status:r.status,data:d}}catch(e){return{ok:false,status:0,data:null}}
}
const names={};
async function nameMap(skus){
  const need=[...new Set(skus)].filter(s=>!(s in names));
  if(need.length){const r=await api(8002,'/v1/products/batch','POST',{skus:need});if(r.ok)r.data.forEach(p=>names[p.sku]=p.name)}
  return names;
}
const cls=s=>['DELIVERED','COMMITTED','IDLE'].includes(s)?'ok':['RELEASED','EXPIRED','TERMINATED'].includes(s)?'err':'warn';
const pill=s=>`<span class="pill ${cls(s)}">${esc(s)}</span>`;
function drawMap(el,stores,orders,focus){
  stores=stores.filter(s=>s.isActive);if(!stores.length){el.innerHTML='';return}
  const pts=[];stores.forEach(s=>s.servicableGeofence.forEach(p=>pts.push(p)));
  orders.forEach(o=>{if(o.dropLat!=null)pts.push([o.dropLat,o.dropLng])});
  const la=pts.map(p=>p[0]),ln=pts.map(p=>p[1]),a=Math.min(...la),b=Math.max(...la),c=Math.min(...ln),d=Math.max(...ln),W=420,H=300,P=16;
  const X=g=>P+(g-c)/((d-c)||1)*(W-2*P),Y=t=>P+(b-t)/((b-a)||1)*(H-2*P),col=['#6a1b9a','#00897b','#ef6c00'];
  let h=`<svg viewBox="0 0 ${W} ${H}" style="width:100%;color:var(--tx);background:var(--bg);border-radius:10px">`;
  stores.forEach((s,i)=>{const k=col[i%3],on=!focus||focus===s.id;
    h+=`<polygon points="${s.servicableGeofence.map(p=>X(p[1])+','+Y(p[0])).join(' ')}" fill="${k}" fill-opacity="${on?.18:.06}" stroke="${k}" stroke-dasharray="4 3"/>`
     +`<rect x="${X(s.lng)-6}" y="${Y(s.lat)-6}" width="12" height="12" fill="${k}"/><text x="${X(s.lng)+9}" y="${Y(s.lat)+4}" font-size="11" fill="currentColor">${esc(s.name)}</text>`});
  orders.forEach(o=>{if(o.dropLat==null)return;const s=stores.find(x=>x.id===o.storeId);if(!s)return;
    const sx=X(s.lng),sy=Y(s.lat),dx=X(o.dropLng),dy=Y(o.dropLat),done=o.status==='DELIVERED';
    h+=`<line x1="${sx}" y1="${sy}" x2="${dx}" y2="${dy}" stroke="currentColor" stroke-opacity=".3" stroke-dasharray="3 3"/>`
     +`<circle cx="${dx}" cy="${dy}" r="6" fill="${done?'#999':'#c62828'}"/><text x="${dx+8}" y="${dy+4}" font-size="10" fill="currentColor">#${esc(o.orderId.slice(0,4))}</text>`;
    if(o.riderName&&!done){const t=o.status==='PICKED_UP'?.5:0;
      h+=`<circle cx="${sx+(dx-sx)*t}" cy="${sy+(dy-sy)*t+(t?0:-10)}" r="5" fill="#1b8a3a"/><text x="${sx+(dx-sx)*t+8}" y="${sy+(dy-sy)*t+(t?0:-10)}" font-size="10" fill="currentColor">${esc(o.riderName)}</text>`}});
  el.innerHTML=h+'</svg><div class="mut">Square = dark store · red dot = drop point · green dot = rider</div>';
}
