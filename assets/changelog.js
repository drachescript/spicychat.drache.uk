(()=>{
const root=document.querySelector('#changelog-content');
const inline=text=>{
  const frag=document.createDocumentFragment();
  const parts=String(text).split(/(`[^`]+`)/g);
  for(const part of parts){
    if(part.startsWith('`')&&part.endsWith('`')){const code=document.createElement('code');code.textContent=part.slice(1,-1);frag.append(code)}
    else frag.append(document.createTextNode(part));
  }
  return frag;
};
function render(md){
  root.replaceChildren();
  let list=null;
  for(const raw of md.replace(/\r/g,'').split('\n')){
    const line=raw.trimEnd();
    if(!line.trim()){list=null;continue}
    if(line.startsWith('# ')){const h=document.createElement('h1');h.append(inline(line.slice(2)));root.append(h);list=null;continue}
    if(line.startsWith('## ')){const h=document.createElement('h2');h.append(inline(line.slice(3)));root.append(h);list=null;continue}
    if(line.startsWith('- ')){
      if(!list){list=document.createElement('ul');root.append(list)}
      const li=document.createElement('li');li.append(inline(line.slice(2)));list.append(li);continue
    }
    const p=document.createElement('p');p.append(inline(line));root.append(p);list=null;
  }
}
fetch('/assets/changelog.md',{cache:'no-store'}).then(r=>r.ok?r.text():Promise.reject()).then(render).catch(()=>{root.innerHTML='<p>Could not load the changelog.</p>'});
})();
