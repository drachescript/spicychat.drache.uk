(()=>{
'use strict';
function imageHidden(b){return typeof b?.imageHidden==='boolean'?b.imageHidden:!!b?.nsfw}
const $=s=>document.querySelector(s),grid=$('#archive-grid'),count=$('#archive-count');
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const slug=s=>String(s||'').toLowerCase().normalize('NFKD').replace(/[\u0300-\u036f]/g,'').replace(/[^a-z0-9]+/g,'-').replace(/^-+|-+$/g,'');
const date=v=>{if(!v)return 'Unknown';const d=new Date(v);return Number.isNaN(d.getTime())?v:d.toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric'})};
const num=v=>v==null?'—':Number(v).toLocaleString('en-GB');
const detailUrl=b=>`/chatbots/stats/bot/?id=${encodeURIComponent(b.id)}`;
function bindCards(){
  grid.addEventListener('click',e=>{const card=e.target.closest('[data-bot-url]');if(!card||e.target.closest('a,button'))return;location.href=card.dataset.botUrl});
  grid.addEventListener('keydown',e=>{if(e.key!=='Enter'&&e.key!==' ')return;const card=e.target.closest('[data-bot-url]');if(!card)return;e.preventDefault();location.href=card.dataset.botUrl});
}
async function load(){try{
 const doc=await fetch('/assets/data/archived-bots.json',{cache:'no-store'}).then(r=>r.ok?r.json():Promise.reject(new Error('archive data')));
 const archived=(doc.bots||[]).slice().sort((a,b)=>new Date(b.archivedAt||0)-new Date(a.archivedAt||0));
 count.textContent=archived.length;
 if(!archived.length){grid.innerHTML='<p class="load-error">Nothing has been archived.</p>';return}
 grid.innerHTML=archived.map(b=>{const s=b.lastStats||{},p=b.publication||{},img=b.image&&!imageHidden(b)?`<img src="${esc(b.image)}" alt="${esc(b.name)}" loading="lazy">`:`<span class="bot-art-fallback">${esc((b.name||'?')[0])}</span>`;const publicLabel=p.publicSinceAccuracy==='confirmed'?'Published':'First seen public';return `<article class="bot-card archive-card bot-row-clickable" role="link" tabindex="0" data-bot-url="${esc(detailUrl(b))}"><div class="bot-art">${img}<span class="archive-badge">Archived</span></div><div class="bot-card-body"><div class="bot-card-topline"><h3><a class="archive-card-link" href="${esc(detailUrl(b))}">${esc(b.name)}</a></h3><div class="card-badges">${Number.isFinite(Number(b.favoriteOrder))?'<span class="card-badge favorite-badge">Favorite</span>':''}${b.origin==='requested'?'<span class="card-badge requested-badge">Requested</span>':''}</div></div><p class="bot-title">${esc(b.title||b.blurb||'')}</p><p class="archive-note">${esc(b.archiveReason||'Archived bot')}</p><div class="archive-meta"><span><b>${num(s.messages)}</b> messages</span><span><b>${num(s.tokens)}</b> tokens</span><span>Last rank: <b>${s.rank?`#${num(s.rank)}`:'—'}</b></span><span>${publicLabel}: <b>${date(p.publicSinceAt||p.firstPublicObservedAt)}</b></span><span>Archived: <b>${date(b.archivedAt)}</b></span></div><p class="archive-open-hint">View old stats →</p></div></article>`}).join('');
}catch(e){console.error(e);grid.innerHTML='<p class="load-error">Couldn\'t load the archive.</p>'}}
bindCards();load();
})();
