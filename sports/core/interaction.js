'use strict';
const model=JSON.parse(document.getElementById('tournament-data').textContent);
const cards=[...document.querySelectorAll('[data-match-id]')];
const sections=[...document.querySelectorAll('.round, .draw')];
const byId=new Map(model.matches.map(m=>[m.id,m]));
const entryById=new Map(model.entries.map(e=>[e.id,e]));
function filter(){
 const query=document.getElementById('search').value.toLocaleLowerCase();
 const draw=document.getElementById('draw-filter')?.value||'';
 const china=document.getElementById('china-only').checked;
 cards.forEach(card=>{const m=byId.get(card.dataset.matchId);card.hidden=!((!draw||(m.draw||'main')===draw)&&(card.textContent+' '+m.round).toLocaleLowerCase().includes(query)&&(!china||m.players.some(p=>entryById.get(p)?.team==='CHN')));});
 sections.forEach(section=>{section.hidden=!section.querySelector('.match:not([hidden])');});
 document.getElementById('empty').hidden=cards.some(c=>!c.hidden);
}
function dependencies(m){
 return m.slots.flatMap(s=>s.winner?[s.winner]:s.group_rank?model.matches.filter(x=>x.group===s.group_rank[0]).map(x=>x.id):[]);
}
function route(id){
 const linked=new Set([id]);
 function parents(key){dependencies(byId.get(key)).forEach(p=>{if(!linked.has(p)){linked.add(p);parents(p);}});}
 parents(id);
 const queue=[id], seen=new Set(queue);
 while(queue.length){const child=queue.shift();model.matches.filter(m=>dependencies(m).includes(child)).forEach(m=>{linked.add(m.id);if(!seen.has(m.id)){seen.add(m.id);queue.push(m.id);}});}
 cards.forEach(c=>c.classList.toggle('selected',linked.has(c.dataset.matchId)));
}

cards.forEach(c=>c.querySelector('.route').addEventListener('click',()=>route(c.dataset.matchId)));
document.getElementById('search').addEventListener('input',filter);
document.getElementById('china-only').addEventListener('change',filter);
document.getElementById('clear').addEventListener('click',()=>{if(document.getElementById('draw-filter'))document.getElementById('draw-filter').value='';document.getElementById('search').value='';document.getElementById('china-only').checked=false;cards.forEach(c=>c.classList.remove('selected'));filter();});

document.getElementById('draw-filter')?.addEventListener('change',filter);
