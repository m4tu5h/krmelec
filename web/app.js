let meals=[];
let menuDateLabel="";
const state={restaurant:new Set(),labels:new Set()};
const $=id=>document.getElementById(id);
const money=n=>typeof n==='number'&&Number.isFinite(n)&&n>=0?new Intl.NumberFormat('sk-SK',{style:'currency',currency:'EUR'}).format(n):'Cena neuvedená';
const escapeHTML=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let restaurants=[];
let labels=[];
const colors=['#e7eab1','#f4d8bf','#dcdcf0','#eecddd','#d6e4d0'];
function filteredMeals(){return meals.filter(m=>(!state.restaurant.size||state.restaurant.has(m.restaurant))&&(!state.labels.size||m.labels.some(l=>state.labels.has(l))));}
function chipGroup(id,items,key){$(id).replaceChildren(...items.map((item,i)=>{const b=document.createElement('button');b.className='chip';b.style.setProperty('--chip',colors[i%colors.length]);b.setAttribute('aria-pressed',state[key].has(item));b.innerHTML=`<span class="check" aria-hidden="true">${state[key].has(item)?'✓':'+'}</span>${escapeHTML(item)}`;b.onclick=()=>{state[key].has(item)?state[key].delete(item):state[key].add(item);render();$(id).children[i].focus();};return b;}));}
function render(){const filtered=filteredMeals();$('result-count').textContent=`${filtered.length} / ${meals.length} jedál`;$('show-results').textContent=`Zobraziť jedlá (${filtered.length}) →`;
$('meals').replaceChildren(...filtered.map(m=>{const b=document.createElement('button');b.className='meal';b.innerHTML=`<span class="meal-name">${escapeHTML(m.name)}</span><span class="meal-price">${money(m.price_eur)}</span>`;b.onclick=()=>openDetail(m);return b;}));$('empty').hidden=!!filtered.length;
const count=state.restaurant.size+state.labels.size;$('filter-count').textContent=count;$('filter-count').hidden=!count;
$('active-filters').replaceChildren(...Object.entries(state).flatMap(([key,set])=>[...set].map(item=>{const b=document.createElement('button');b.className='active-chip';b.textContent=item+' ×';b.setAttribute('aria-label','Odstrániť filter '+item);b.onclick=()=>{set.delete(item);render();$('menu').focus();};return b;})));
chipGroup('restaurant-chips',restaurants,'restaurant');chipGroup('label-chips',labels,'labels');}
function show(dialog){dialog.showModal();document.body.style.overflow='hidden';}
function safeUrl(url){try{const u=new URL(url);return ['https:','http:'].includes(u.protocol)?u.href:null;}catch{return null;}}
function openDetail(m){const url=safeUrl(m.source_url);$('detail-content').innerHTML=`<div class="eyebrow">${escapeHTML(menuDateLabel)}</div><h2 id="detail-title">${escapeHTML(m.name)}</h2>${m.date_assumed?`<p class="source-note" role="note">${escapeHTML(m.date_note||"Rok menu je predpokladaný podľa aktuálneho roka.")}</p>`:""}<div class="detail-labels">${m.labels.map(l=>`<span>${escapeHTML(l)}</span>`).join('')}</div><div class="price-line"><strong>${money(m.price_eur)}</strong><span>${escapeHTML(m.portion||'')}</span></div><div class="restaurant-block"><h3>${escapeHTML(m.restaurant)}</h3><p>${escapeHTML(m.address||'Adresa nie je uvedená')}</p></div><h4>Polievka k obedu</h4>${m.soups.length?m.soups.map(s=>`<div class="soup">${escapeHTML(s.name)}<div><span>${escapeHTML(s.portion||'')}</span><strong>${s.additional_price_eur===0?'V cene':typeof s.additional_price_eur==='number'?'+ '+money(s.additional_price_eur):'Cena neuvedená'}</strong></div></div>`).join(''):'<p class="muted">K tomuto jedlu nie je uvedená polievka.</p>'}${url?`<a class="primary source-link" href="${escapeHTML(url)}" target="_blank" rel="noopener noreferrer">Pôvodné menu reštaurácie ↗</a><p class="source-note">Zdrojová ponuka reštaurácie. Dostupnosť jedla a cenu si overte priamo u reštaurácie.</p>`:'<p class="source-note">Odkaz na pôvodné menu nie je uvedený.</p>'}`;show($('detail'));}
function reset(){state.restaurant.clear();state.labels.clear();render();}
$('reset').onclick=reset;$('empty-reset').onclick=()=>{reset();$('menu').focus();};function toggleFilters(open){
 $('filters').hidden=!open;
 $('menu-label').textContent=open?'Zatvoriť filtre':'Filtre';
 $('menu-icon').textContent=open?'×':'☷';
 $('menu').setAttribute('aria-label',open?'Zatvoriť filtre':'Otvoriť filtre');
 $('menu').setAttribute('aria-expanded',String(open));
 window.scrollTo({top:0,behavior:'instant'});
 $('menu').focus({preventScroll:true});
}
$('menu').onclick=()=>toggleFilters($('filters').hidden);
$('show-results').onclick=()=>toggleFilters(false);
document.addEventListener('keydown',event=>{if(event.key==='Escape'&&!$('filters').hidden&&!$('detail').open){event.preventDefault();toggleFilters(false);}});
for(const dialog of document.querySelectorAll('dialog')){dialog.querySelector('.close').onclick=()=>dialog.close();dialog.addEventListener('close',()=>{document.body.style.overflow='';});dialog.addEventListener('click',e=>{if(e.target===dialog){const r=dialog.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)dialog.close();}});}
async function loadMenus(){
 $('menu').disabled=true;
 try{
  const response=await fetch('/menus.json',{cache:'no-store'});
  if(!response.ok)throw new Error(`HTTP ${response.status}`);
  const data=await response.json();
  if(!Array.isArray(data.meals)||!/^\d{4}-\d{2}-\d{2}$/.test(data.requested_date))throw new Error('Neplatný formát menus.json');
  meals=data.meals.map(m=>({...m,labels:Array.isArray(m.labels)?m.labels:[],soups:Array.isArray(m.soups)?m.soups:[]}));
  restaurants=[...new Set(meals.map(m=>m.restaurant))];
  labels=[...new Set(meals.flatMap(m=>m.labels))];
  const date=new Date(data.requested_date+'T12:00:00Z');
  if(Number.isNaN(date.getTime()))throw new Error('Neplatný dátum menu');
  menuDateLabel='Menu · '+new Intl.DateTimeFormat('sk-SK',{day:'numeric',month:'numeric',year:'numeric',timeZone:'Europe/Bratislava'}).format(date);
  const parts=new Intl.DateTimeFormat('en-CA',{year:'numeric',month:'2-digit',day:'2-digit',timeZone:'Europe/Bratislava'}).formatToParts(new Date());
  const part=type=>parts.find(p=>p.type===type).value;
  const today=`${part('year')}-${part('month')}-${part('day')}`;
  $('menu-status').textContent=menuDateLabel+(data.requested_date===today?' · Dnešná ponuka':' · Uložená ponuka nie je na dnešný deň');
  render();
  $('menu').disabled=false;
 }catch(error){
  $('menu-status').textContent='Menu sa nepodarilo načítať. Skontrolujte menus.json a obnovte stránku.';
  $('menu-status').setAttribute('role','alert');
  $('result-count').textContent='Ponuka nie je dostupná';
  $('meals').replaceChildren();
 }finally{
  $('meals').setAttribute('aria-busy','false');
 }
}
loadMenus();
