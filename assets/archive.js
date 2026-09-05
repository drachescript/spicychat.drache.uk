(()=>{
const $=s=>document.querySelector(s),grid=$('#archive-grid'),count=$('#archive-count');
const esc=s=>String(s??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[c]));
const date=v=>{if(!v)return 'Unknown';const d=new Date(v);return Number.isNaN(d.getTime())?v:d.toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric'})};
const num=v=>v==null?'—':Number(v).toLocaleString('en-GB');
function lastRow(id,snaps){for(let i=snaps.length-1;i>=0;i--){const r=(snaps[i].bots||[]).find(x=>x.id===id);if(r)return {...r,capturedAt:snaps[i].capturedAt}}return null}
async function load(){try{
 const [bd,hd,pd]=await Promise.all(['/assets/data/bots.json','/assets/data/bot-history.json','/assets/data/bot-public.json'].map(u=>fetch(u,{cache:'no-store'}).then(r=>r.ok?r.json():Promise.reject(new Error(u)))));
 const snaps=(hd.snapshots||[]).slice().sort((a,b)=>new Date(a.capturedAt)-new Date(b.capturedAt));
 const pub=new Map((pd.bots||[]).map(x=>[x.id,x]));
 const archived=(bd.bots||[]).filter(b=>b.archived).sort((a,b)=>(a.archivedOrder||999)-(b.archivedOrder||999));
 count.textContent=archived.length;
 if(!archived.length){grid.innerHTML='<p class="load-error">Nothing has been archived.</p>';return}
 grid.innerHTML=archived.map(b=>{const last=lastRow(b.id,snaps),p=pub.get(b.id),img=b.image&&!b.imageHidden?`<img src="${esc(b.image)}" alt="${esc(b.name)}" loading="lazy">`:`<span class="bot-art-fallback">${esc((b.name||'?')[0])}</span>`;const publicLabel=p?.publicSinceAccuracy==='confirmed'?'Published':'First seen public';return `<article class="bot-card archive-card"><div class="bot-art">${img}<span class="archive-badge">Archived</span></div><div class="bot-card-body"><div class="bot-card-topline"><h3>${esc(b.name)}</h3><div class="card-badges">${Number.isFinite(Number(b.favoriteOrder))?'<span class="card-badge favorite-badge">Favorite</span>':''}${b.origin==='requested'?'<span class="card-badge requested-badge">Requested</span>':''}</div></div><p class="bot-title">${esc(b.title||b.blurb||'')}</p><p class="archive-note">${esc(b.archiveReason||'Archived bot')}</p><div class="archive-meta"><span><b>${num(last?.messages)}</b> messages</span><span><b>${num(last?.tokens)}</b> tokens</span><span>${publicLabel}: <b>${date(p?.publicSinceAt)}</b></span><span>Archived: <b>${date(b.archivedAt)}</b></span></div></div></article>`}).join('');
}catch(e){console.error(e);grid.innerHTML='<p class="load-error">Couldn\'t load the archive.</p>'}}
load();
})();
