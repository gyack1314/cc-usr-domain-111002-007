const $=(s,root=document)=>root.querySelector(s);
const $$=(s,root=document)=>[...root.querySelectorAll(s)];
const data=await fetch('/data.json').then(r=>r.json());
const runtime=()=>fetch('/api/runtime').then(r=>r.json());
const action=(name,fields={})=>fetch('/api/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,...fields})}).then(r=>r.json());
const tick=()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
const html=(value)=>String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
const show=(s)=>{$('#status').textContent=s;};

$('#space').value=localStorage.getItem('workspace')||'A';
function navigation(){$('#navigation').textContent='demo-user | '+$('#space').value;$('#navigation').dataset.space=$('#space').value;localStorage.setItem('workspace',$('#space').value);}
$('#space').onchange=navigation;
$('#load').onclick=async()=>{const state=await runtime();const wanted=$('#space').value;const actual=state.phase==='stale-list'?(wanted==='A'?'B':'A'):wanted;$('#list').dataset.space=actual;$('#list').innerHTML=`<article data-record-id="R-17" data-space="${actual}">公司${actual}资料 <button id="open-detail">详情</button><button id="new-tab">新标签详情</button></article>`;$('#open-detail').onclick=async()=>{const now=await runtime();const owner=now.phase==='wrong-detail'?(actual==='A'?'B':'A'):actual;$('#detail').dataset.space=owner;$('#detail').innerHTML=`<p data-record-id="R-17" data-space="${owner}">公司${owner}的正文</p>`;};$('#new-tab').onclick=()=>window.open('/?detail='+actual,'_blank');await action('list',{space:actual});show('列表已打开');};
const detailSpace=new URLSearchParams(location.search).get('detail');if(detailSpace){$('#detail').dataset.space=detailSpace;$('#detail').innerHTML=`<p data-record-id="R-17" data-space="${detailSpace}">公司${detailSpace}的正文</p>`;}navigation();show('工作空间已选择');
