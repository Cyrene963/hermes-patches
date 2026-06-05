"""Memory Graph Web Dashboard — HTML+JS single-page app.

Features:
- Multi-user login with session auth
- Tree view with expandable hierarchy
- Full-text search
- Glossary keyword scanning
- Changeset review
"""

LOGIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Memory Graph</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif;background:#0a0c10;color:#8b95a5;min-height:100vh;overflow:hidden;position:relative}
canvas#bg{position:fixed;top:0;left:0;width:100%;height:100%;z-index:0}
.wrap{position:relative;z-index:1;min-height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:20px}
.brand{text-align:center;margin-bottom:40px;position:relative}
.brand h1{font-size:2rem;font-weight:600;color:#e6edf3;letter-spacing:-0.5px;line-height:1.2}
.brand h1 span{color:#c9875a}
.brand p{font-size:13px;color:#484f58;margin-top:8px;letter-spacing:0.5px;text-transform:uppercase}
.card{width:340px;max-width:90vw;background:rgba(13,17,23,0.85);border:1px solid #21262d;border-radius:8px;padding:32px 28px;backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px)}
.field{margin-bottom:16px}
.field label{display:block;font-size:11px;font-weight:500;color:#656d76;margin-bottom:6px;letter-spacing:0.3px;text-transform:uppercase}
.field input{width:100%;padding:10px 12px;background:#0d1117;border:1px solid #21262d;border-radius:6px;color:#e6edf3;font-size:14px;font-family:inherit;transition:border-color 0.15s}
.field input:focus{border-color:#c9875a;outline:none}
.field input::placeholder{color:#30363d}
.btn{width:100%;padding:10px;background:#c9875a;border:none;border-radius:6px;color:#0a0c10;cursor:pointer;font-size:14px;font-weight:600;font-family:inherit;margin-top:4px;transition:background 0.15s}
.btn:hover{background:#d9a074}
.error{color:#f47067;font-size:12px;margin-top:12px;text-align:center;min-height:18px}
.foot{text-align:center;margin-top:24px;font-size:11px;color:#30363d}
</style>
</head>
<body>
<canvas id="bg"></canvas>
<div class="wrap">
  <div class="brand">
    <h1>Memory <span>Graph</span></h1>
    <p>Structured knowledge for agents</p>
  </div>
  <div class="card">
    <form onsubmit="doLogin(event)" autocomplete="on">
      <div class="field">
        <label>Username</label>
        <input id="username" type="text" autocomplete="username" autofocus placeholder="enter username" />
      </div>
      <div class="field">
        <label>Password</label>
        <input id="password" type="password" autocomplete="current-password" placeholder="enter password" />
      </div>
      <button class="btn" type="submit">Sign in</button>
      <div class="error" id="error"></div>
    </form>
  </div>
  <div class="foot">Memory Graph</div>
</div>
<script>
(function(){
  const c=document.getElementById('bg'),x=c.getContext('2d');
  let W,H,nodes=[];
  function resize(){W=c.width=innerWidth;H=c.height=innerHeight}
  resize(); addEventListener('resize',resize);
  const N=Math.min(40,Math.floor(W*H/25000));
  for(let i=0;i<N;i++) nodes.push({
    x:Math.random()*W, y:Math.random()*H,
    vx:(Math.random()-0.5)*0.3, vy:(Math.random()-0.5)*0.3,
    r:Math.random()*1.5+0.8
  });
  function draw(){
    x.clearRect(0,0,W,H);
    for(let i=0;i<nodes.length;i++){
      const a=nodes[i];
      a.x+=a.vx; a.y+=a.vy;
      if(a.x<0||a.x>W) a.vx*=-1;
      if(a.y<0||a.y>H) a.vy*=-1;
      for(let j=i+1;j<nodes.length;j++){
        const b=nodes[j],dx=a.x-b.x,dy=a.y-b.y,d=Math.sqrt(dx*dx+dy*dy);
        if(d<160){
          x.beginPath();x.moveTo(a.x,a.y);x.lineTo(b.x,b.y);
          x.strokeStyle='rgba(201,135,90,'+((1-d/160)*0.15)+')';
          x.lineWidth=0.5;x.stroke();
        }
      }
      x.beginPath();x.arc(a.x,a.y,a.r,0,Math.PI*2);
      x.fillStyle='rgba(201,135,90,0.35)';x.fill();
    }
    requestAnimationFrame(draw);
  }
  draw();
  async function doLogin(e){
    e.preventDefault();
    const u=document.getElementById('username').value.trim();
    const p=document.getElementById('password').value;
    document.getElementById('error').textContent='';
    if(!u||!p){document.getElementById('error').textContent='Required';return}
    try{
      const r=await fetch('/api/auth/login',{
        method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({username:u,password:p})
      });
      if(r.ok){window.location.href='/';return}
      const d=await r.json();
      document.getElementById('error').textContent=d.detail||'Login failed';
    }catch(e){document.getElementById('error').textContent='Network error'}
  }
  window.doLogin=doLogin;
  document.getElementById('password').addEventListener('keydown',e=>{if(e.key==='Enter')doLogin(e)});
})();
</script>
</body>
</html>"""


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Memory Graph</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif;background:#0a0c10;color:#e6edf3;min-height:100vh}
.container{max-width:1200px;margin:0 auto;padding:20px}
header{display:flex;align-items:center;gap:16px;margin-bottom:20px;flex-wrap:wrap}
h1{color:#c9875a;font-size:1.4rem;white-space:nowrap}
.stats{display:flex;gap:12px;flex-wrap:wrap}
.stat{background:rgba(13,17,23,0.85);border:1px solid #21262d;border-radius:8px;padding:8px 14px;backdrop-filter:blur(12px)}
.stat-val{font-size:18px;font-weight:700;color:#c9875a}
.stat-lbl{font-size:11px;color:#8b95a5}
.user-info{margin-left:auto;display:flex;align-items:center;gap:10px;font-size:13px}
.user-info .name{color:#c9875a;font-weight:600}
.user-info .ns{color:#8b95a5;font-size:11px}
.user-info button{background:transparent;border:1px solid #21262d;color:#8b95a5;padding:4px 10px;border-radius:6px;cursor:pointer;font-size:11px;transition:all .15s}
.user-info button:hover{border-color:#c9875a;color:#c9875a}
.tabs{display:flex;gap:0;margin-bottom:16px;border-bottom:1px solid #21262d;overflow-x:auto}
.tab{padding:10px 18px;background:transparent;border:none;border-bottom:2px solid transparent;color:#8b95a5;cursor:pointer;font-size:13px;white-space:nowrap;transition:all .15s}
.tab:hover{color:#e6edf3}
.tab.active{color:#c9875a;border-bottom-color:#c9875a}
.tab-content{display:none;min-height:400px}
.tab-content.active{display:block}
.search-box{display:flex;gap:10px;margin-bottom:16px}
.search-box input{flex:1;padding:10px 14px;background:rgba(13,17,23,0.85);border:1px solid #21262d;border-radius:6px;color:#e6edf3;font-size:14px;backdrop-filter:blur(12px)}
.search-box input:focus{border-color:#c9875a;outline:none}
.search-box button,.btn{padding:10px 20px;background:#c9875a;border:none;border-radius:6px;color:#fff;cursor:pointer;font-size:14px;transition:all .15s}
.search-box button:hover,.btn:hover{background:#d4955e}
.btn-danger{background:#da3633}
.btn-danger:hover{background:#f85149}
.btn-sm{padding:5px 12px;font-size:12px}
.card{background:rgba(13,17,23,0.85);border:1px solid #21262d;border-radius:8px;padding:14px;margin-bottom:10px;transition:border-color .15s;backdrop-filter:blur(12px)}
.card:hover{border-color:#484f58}
.card-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px}
.card-title{color:#c9875a;font-size:14px;cursor:pointer;font-weight:600}
.card-title:hover{text-decoration:underline}
.card-meta{color:#8b95a5;font-size:11px;display:flex;gap:8px;align-items:center}
.content{white-space:pre-wrap;font-family:'SF Mono','Fira Code',monospace;font-size:12.5px;line-height:1.6;color:#e6edf3;background:#0a0c10;padding:10px;border-radius:4px;margin-top:6px;max-height:250px;overflow-y:auto;border:1px solid #21262d}
.badge{display:inline-block;padding:2px 7px;border-radius:10px;font-size:10px;font-weight:600}
.badge-p{background:rgba(201,135,90,0.15);color:#c9875a}
.badge-d{background:rgba(139,149,165,0.15);color:#8b95a5}
.badge-warn{background:rgba(210,153,34,0.15);color:#d29922}
.badge-err{background:rgba(218,54,51,0.15);color:#da3633}
.tree-node{margin-left:0}
.tree-children{margin-left:20px;border-left:1px solid #21262d;padding-left:12px}
.tree-item{padding:6px 10px;cursor:pointer;border-radius:6px;display:flex;align-items:center;gap:8px;font-size:13px;user-select:none;transition:background .15s}
.tree-item:hover{background:rgba(13,17,23,0.85)}
.tree-arrow{width:16px;text-align:center;color:#484f58;font-size:10px;transition:transform .15s;flex-shrink:0}
.tree-arrow.open{transform:rotate(90deg)}
.tree-arrow.leaf{visibility:hidden}
.tree-name{color:#e6edf3;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tree-prio{color:#484f58;font-size:10px}
.tree-panel{display:grid;grid-template-columns:320px 1fr;gap:16px;min-height:500px}
@media(max-width:768px){.tree-panel{grid-template-columns:1fr}.tree-sidebar{max-height:300px;overflow-y:auto}}
.tree-sidebar{background:rgba(13,17,23,0.85);border:1px solid #21262d;border-radius:8px;padding:12px;overflow-y:auto;max-height:600px;backdrop-filter:blur(12px)}
.tree-detail{min-width:0}
.empty{color:#8b95a5;text-align:center;padding:40px;font-size:14px}
.loading{color:#c9875a;text-align:center;padding:20px}
.glossary-input{display:flex;gap:10px;margin-bottom:16px}
.glossary-input textarea{flex:1;padding:10px;background:rgba(13,17,23,0.85);border:1px solid #21262d;border-radius:6px;color:#e6edf3;font-size:13px;min-height:80px;resize:vertical;font-family:inherit;backdrop-filter:blur(12px)}
.glossary-input textarea:focus{border-color:#c9875a;outline:none}
.match-item{display:flex;gap:12px;align-items:flex-start;padding:8px 12px;background:rgba(13,17,23,0.85);border:1px solid #21262d;border-radius:6px;margin-bottom:6px}
.match-kw{color:#c9875a;font-weight:600;min-width:100px;font-size:13px}
.match-uri{color:#8b95a5;font-size:12px;cursor:pointer}
.match-uri:hover{text-decoration:underline;color:#c9875a}
.match-snippet{color:#8b95a5;font-size:12px;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.changeset-item{padding:10px;background:rgba(13,17,23,0.85);border:1px solid #21262d;border-radius:6px;margin-bottom:8px;font-size:12px;backdrop-filter:blur(12px)}
.changeset-item .op{font-weight:600;margin-right:8px}
.changeset-item .op-create{color:#c9875a}
.form-group{margin-bottom:14px}
.form-group label{display:block;font-size:12px;color:#8b95a5;margin-bottom:4px;font-weight:600}
.form-group input,.form-group textarea,.form-group select{width:100%;padding:10px 14px;background:rgba(13,17,23,0.85);border:1px solid #21262d;border-radius:6px;color:#e6edf3;font-size:14px;font-family:inherit;backdrop-filter:blur(12px)}
.form-group input:focus,.form-group textarea:focus{border-color:#c9875a;outline:none}
.form-group textarea{min-height:120px;resize:vertical}
.form-row{display:grid;grid-template-columns:1fr 1fr;gap:12px}
@media(max-width:600px){.form-row{grid-template-columns:1fr}}
.orphan-actions{display:flex;gap:6px;align-items:center;margin-left:auto}
.toast{position:fixed;top:20px;right:20px;padding:12px 20px;border-radius:8px;font-size:13px;z-index:9999;animation:fadeIn .3s;backdrop-filter:blur(12px)}
.toast-ok{background:rgba(13,17,23,0.95);border:1px solid #c9875a;color:#c9875a}
.toast-err{background:rgba(13,17,23,0.95);border:1px solid #da3633;color:#da3633}
@keyframes fadeIn{from{opacity:0;transform:translateY(-10px)}to{opacity:1;transform:translateY(0)}}
.diag-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:12px}
.diag-card{background:rgba(13,17,23,0.85);border:1px solid #21262d;border-radius:8px;padding:14px;backdrop-filter:blur(12px)}
.diag-card h3{font-size:13px;margin-bottom:8px;display:flex;align-items:center;gap:8px}
.diag-card .count{font-size:22px;font-weight:700;color:#c9875a}
.diag-item{padding:6px 0;border-bottom:1px solid #21262d;font-size:12px}
.diag-item:last-child{border-bottom:none}
</style>
</head>
<body>
<div class="container">
<header>
  <h1>🧠 Memory Graph</h1>
  <div class="stats" id="stats"></div>
  <div class="user-info">
    <span class="name" id="userName"></span>
    <span class="ns" id="userNs"></span>
    <button onclick="doLogout()">Logout</button>
  </div>
</header>
<div class="tabs">
  <div class="tab active" data-tab="tree" onclick="switchTab('tree')">🌳 Tree</div>
  <div class="tab" data-tab="search" onclick="switchTab('search')">🔍 Search</div>
  <div class="tab" data-tab="glossary" onclick="switchTab('glossary')">📖 Glossary</div>
  <div class="tab" data-tab="changesets" onclick="switchTab('changesets')">📝 Changesets</div>
  <div class="tab" data-tab="diagnostics" onclick="switchTab('diagnostics')">🩺 Diagnostics</div>
  <div class="tab" data-tab="orphans" onclick="switchTab('orphans')">🧹 Orphans</div>
  <div class="tab" data-tab="create" onclick="switchTab('create')">➕ Create</div>
</div>

<div id="tab-tree" class="tab-content active">
  <div class="tree-panel">
    <div class="tree-sidebar" id="treeSidebar"><div class="loading">Loading tree...</div></div>
    <div class="tree-detail" id="treeDetail"><div class="empty">← Select a node from the tree</div></div>
  </div>
</div>

<div id="tab-search" class="tab-content">
  <div class="search-box">
    <input id="searchInput" placeholder="Search memories..." />
    <button onclick="doSearch()">Search</button>
  </div>
  <div id="searchResults"></div>
</div>

<div id="tab-glossary" class="tab-content">
  <p style="color:#8b95a5;margin-bottom:12px;font-size:13px">Paste text to scan for glossary keywords.</p>
  <div class="glossary-input">
    <textarea id="glossaryText" placeholder="Paste conversation text here..."></textarea>
    <button onclick="doGlossaryScan()" style="align-self:flex-end">Scan</button>
  </div>
  <div id="glossaryResults"></div>
</div>

<div id="tab-changesets" class="tab-content">
  <div id="changesetList"><div class="loading">Loading...</div></div>
</div>

<div id="tab-diagnostics" class="tab-content">
  <div id="diagContent"><div class="loading">Running diagnostics...</div></div>
</div>

<div id="tab-orphans" class="tab-content">
  <div id="orphanList"><div class="loading">Loading orphan memories...</div></div>
</div>

<div id="tab-create" class="tab-content">
  <div class="card" style="max-width:600px">
    <h3 style="color:#c9875a;margin-bottom:16px;font-size:15px">Create New Memory</h3>
    <form id="createForm" onsubmit="return doCreate(event)">
      <div class="form-group">
        <label>Parent URI *</label>
        <input id="createParentUri" placeholder="e.g. core://knowledge/ai" required />
      </div>
      <div class="form-group">
        <label>Title</label>
        <input id="createTitle" placeholder="Optional title" />
      </div>
      <div class="form-group">
        <label>Content *</label>
        <textarea id="createContent" placeholder="Memory content..." required></textarea>
      </div>
      <div class="form-row">
        <div class="form-group">
          <label>Priority (1-10)</label>
          <input id="createPriority" type="number" min="1" max="10" value="5" />
        </div>
        <div class="form-group">
          <label>Disclosure</label>
          <input id="createDisclosure" placeholder="e.g. private, team, public" />
        </div>
      </div>
      <button type="submit" class="btn" style="width:100%">Create Memory</button>
    </form>
    <div id="createResult" style="margin-top:12px"></div>
  </div>
</div>

</div>
<script>
const API = '/api/memory-graph';

function esc(s){const d=document.createElement('div');d.textContent=s;return d.innerHTML}
function toast(msg,ok){
  const t=document.createElement('div');t.className='toast '+(ok?'toast-ok':'toast-err');t.textContent=msg;
  document.body.appendChild(t);setTimeout(()=>t.remove(),3000);
}

async function fetchJSON(url,opt){
  const r=await fetch(url,opt);
  if(r.status===401){window.location.href='/login';return null}
  if(!r.ok)throw new Error(r.status+' '+r.statusText);
  return r.json();
}

function switchTab(name){
  document.querySelectorAll('.tab').forEach(t=>t.classList.toggle('active',t.dataset.tab===name));
  document.querySelectorAll('.tab-content').forEach(c=>c.classList.toggle('active',c.id==='tab-'+name));
  if(name==='changesets')loadChangesets();
  if(name==='diagnostics')loadDiagnostics();
  if(name==='orphans')loadOrphans();
}

async function doLogout(){
  await fetch('/api/auth/logout',{method:'POST'});
  window.location.href='/login';
}

/* ─── User Info ─── */
async function loadUser(){
  try{
    const r=await fetch('/api/auth/me');const d=await r.json();
    if(!d.authenticated){window.location.href='/login';return}
    document.getElementById('userName').textContent=d.display_name||d.username;
    document.getElementById('userNs').textContent=d.namespace?'(ns: '+d.namespace+')':'';
  }catch(e){console.error('loadUser:',e)}
}

/* ─── Stats ─── */
async function loadStats(){
  try{
    const paths=await fetchJSON(API+'/paths');
    if(!paths)return;
    const domains=new Set(paths.map(p=>p.domain));
    document.getElementById('stats').innerHTML=
      '<div class="stat"><div class="stat-val">'+paths.length+'</div><div class="stat-lbl">Paths</div></div>'+
      '<div class="stat"><div class="stat-val">'+domains.size+'</div><div class="stat-lbl">Domains</div></div>';
  }catch(e){console.error('loadStats:',e)}
}

/* ─── Tree ─── */
async function loadTree(){
  const sb=document.getElementById('treeSidebar');
  sb.innerHTML='<div class="loading">Loading tree...</div>';
  try{
    const children=await fetchJSON(API+'/list');
    if(!children)return;
    sb.innerHTML='';
    for(const c of children)sb.appendChild(buildTreeItem(c,0));
    if(!children.length)sb.innerHTML='<div class="empty">No nodes</div>';
  }catch(e){sb.innerHTML='<div class="empty">Error: '+esc(e.message)+'</div>'}
}

function buildTreeItem(node,depth){
  const container=document.createElement('div');container.className='tree-node';
  const item=document.createElement('div');item.className='tree-item';
  item.style.paddingLeft=(depth*16+6)+'px';
  const arrow=document.createElement('span');arrow.className='tree-arrow leaf';arrow.textContent='\u25b6';
  item.appendChild(arrow);
  const name=document.createElement('span');name.className='tree-name';name.textContent=node.name||node.path;
  item.appendChild(name);
  const prio=document.createElement('span');prio.className='tree-prio';prio.textContent=node.priority?'p'+node.priority:'';
  item.appendChild(prio);
  container.appendChild(item);
  const childContainer=document.createElement('div');childContainer.className='tree-children';childContainer.style.display='none';
  container.appendChild(childContainer);
  let loaded=false,open=false;
  item.addEventListener('click',async()=>{
    showDetail(node);
    if(!open){
      arrow.classList.remove('leaf');arrow.classList.add('open');
      childContainer.style.display='block';
      if(!loaded){
        loaded=true;
        try{
          const uri=node.uri||(node.domain+'://'+node.path);
          const children=await fetchJSON(API+'/list?uri='+encodeURIComponent(uri));
          childContainer.innerHTML='';
          if(children&&children.length){
            for(const c of children)childContainer.appendChild(buildTreeItem(c,depth+1));
          }else{
            childContainer.innerHTML='<div style="padding:6px 10px 6px '+((depth+1)*16+10)+'px;color:#484f58;font-size:11px">No children</div>';
          }
        }catch(e){
          childContainer.innerHTML='<div style="padding:6px;color:#da3633;font-size:11px">Error: '+esc(e.message)+'</div>';
        }
      }
      open=true;
    }else{
      arrow.classList.remove('open');childContainer.style.display='none';open=false;
    }
  });
  return container;
}

async function showDetail(node){
  const detail=document.getElementById('treeDetail');
  detail.innerHTML='<div class="loading">Loading...</div>';
  try{
    const uri=node.uri||(node.domain+'://'+node.path);
    const data=await fetchJSON(API+'/read?uri='+encodeURIComponent(uri));
    if(!data)return;
    detail.innerHTML=
      '<div class="card">'+
        '<div class="card-header">'+
          '<span class="card-title">'+esc(data.name||data.path)+'</span>'+
          '<div class="card-meta">'+
            (data.priority?'<span class="badge badge-p">p'+data.priority+'</span>':'')+
            (data.domain?'<span class="badge badge-d">'+esc(data.domain)+'</span>':'')+
          '</div>'+
        '</div>'+
        '<div class="content">'+esc(data.content||'(empty)')+'</div>'+
        ((data.aliases||[]).length>1?'<div style="margin-top:8px;font-size:11px;color:#8b95a5">Aliases: '+data.aliases.map(esc).join(', ')+'</div>':'')+
        (data.created_at?'<div style="margin-top:6px;font-size:11px;color:#484f58">Created: '+esc(data.created_at)+'</div>':'')+
      '</div>';
  }catch(e){detail.innerHTML='<div class="empty">Error: '+esc(e.message)+'</div>'}
}

async function showDetailFromUri(uri){
  switchTab('tree');
  const detail=document.getElementById('treeDetail');
  detail.innerHTML='<div class="loading">Loading...</div>';
  try{
    const data=await fetchJSON(API+'/read?uri='+encodeURIComponent(uri));
    if(!data)return;
    detail.innerHTML=
      '<div class="card">'+
        '<div class="card-header">'+
          '<span class="card-title">'+esc(data.name||data.path)+'</span>'+
          '<div class="card-meta">'+
            (data.priority?'<span class="badge badge-p">p'+data.priority+'</span>':'')+
            '<span class="badge badge-d">'+esc(data.domain)+'</span>'+
          '</div>'+
        '</div>'+
        '<div class="content">'+esc(data.content||'(empty)')+'</div>'+
      '</div>';
  }catch(e){detail.innerHTML='<div class="empty">Error: '+esc(e.message)+'</div>'}
}

/* ─── Search ─── */
async function doSearch(){
  const q=document.getElementById('searchInput').value.trim();
  if(!q)return;
  switchTab('search');
  const el=document.getElementById('searchResults');
  el.innerHTML='<div class="loading">Searching...</div>';
  try{
    const data=await fetchJSON(API+'/search?query='+encodeURIComponent(q));
    if(!data||!data.length){el.innerHTML='<div class="empty">No results for "'+esc(q)+'"</div>';return}
    el.innerHTML=data.map(r=>
      '<div class="card" style="cursor:pointer" onclick="showDetailFromUri(\''+esc(r.uri)+'\')">'+
        '<div class="card-header">'+
          '<span class="card-title">'+esc(r.uri)+'</span>'+
          '<div class="card-meta">'+(r.content_length?r.content_length+'B':'')+'</div>'+
        '</div>'+
        '<div style="font-size:12px;color:#8b95a5;margin-top:4px">'+esc(r.snippet||'')+'</div>'+
      '</div>').join('');
  }catch(e){el.innerHTML='<div class="empty">Error: '+esc(e.message)+'</div>'}
}

/* ─── Glossary ─── */
async function doGlossaryScan(){
  const text=document.getElementById('glossaryText').value.trim();
  if(!text)return;
  const el=document.getElementById('glossaryResults');
  el.innerHTML='<div class="loading">Scanning...</div>';
  try{
    const resp=await fetch(API+'/glossary/scan',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({content:text}),
    });
    if(resp.status===401){window.location.href='/login';return}
    const data=await resp.json();
    if(!data.length){el.innerHTML='<div class="empty">No keywords matched</div>';return}
    el.innerHTML='<div style="margin-bottom:10px;font-size:13px;color:#8b95a5">'+data.length+' keyword(s) matched:</div>'+
      data.map(m=>
        '<div class="match-item">'+
          '<span class="match-kw">'+esc(m.keyword||'?')+'</span>'+
          '<span class="match-uri" onclick="showDetailFromUri(\''+esc(m.uri||'')+'\')">'+esc(m.uri||'?')+'</span>'+
          '<span class="match-snippet">'+esc(m.snippet||'')+'</span>'+
        '</div>').join('');
  }catch(e){el.innerHTML='<div class="empty">Error: '+esc(e.message)+'</div>'}
}

/* ─── Changesets ─── */
async function loadChangesets(){
  const el=document.getElementById('changesetList');
  el.innerHTML='<div class="loading">Loading...</div>';
  try{
    const list=await fetchJSON(API+'/review/list');
    if(!list||!list.length){el.innerHTML='<div class="empty">No changesets</div>';return}
    el.innerHTML=list.map(cs=>
      '<div class="changeset-item">'+
        '<span class="op op-create">'+esc(cs.id||'?')+'</span>'+
        '<span style="color:#8b95a5">'+(cs.changes?cs.changes.length+' changes':'')+' '+(cs.created_at||'')+'</span>'+
      '</div>').join('');
  }catch(e){el.innerHTML='<div class="empty">Error: '+esc(e.message)+'</div>'}
}

/* ─── Diagnostics ─── */
async function loadDiagnostics(){
  const el=document.getElementById('diagContent');
  el.innerHTML='<div class="loading">Running diagnostics...</div>';
  try{
    const d=await fetchJSON(API+'/maintenance/diagnostics?domain=core');
    if(!d)return;
    const sections=[
      {key:'stale_nodes',label:'Stale Nodes',icon:'\u23f3',desc:'Memories not accessed recently'},
      {key:'crowded_nodes',label:'Crowded Nodes',icon:'\U0001f4a5',desc:'Nodes with too many children'},
      {key:'orphaned_nodes',label:'Orphaned Nodes',icon:'\U0001f9ed',desc:'Disconnected from tree'},
    ];
    el.innerHTML='<div class="diag-grid">'+
      sections.map(s=>{
        const items=d[s.key]||[];
        return '<div class="diag-card">'+
          '<h3>'+s.icon+' '+s.label+' <span class="count">'+items.length+'</span></h3>'+
          '<p style="font-size:11px;color:#8b95a5;margin-bottom:8px">'+s.desc+'</p>'+
          (items.length?items.slice(0,10).map(i=>
            '<div class="diag-item">'+
              '<span style="color:#e6edf3">'+esc(i.uri||i.path||'?')+'</span>'+
              (i.priority!=null?' <span class="badge badge-p">p'+i.priority+'</span>':'')+
              (i.days_stale!=null?' <span style="color:#8b95a5;font-size:11px">'+i.days_stale+'d stale</span>':'')+
              (i.child_count!=null?' <span style="color:#8b95a5;font-size:11px">'+i.child_count+' children</span>':'')+
            '</div>').join('')
          :'<div style="color:#484f58;font-size:12px">No issues found</div>')+
        '</div>';
      }).join('')+'</div>';
  }catch(e){el.innerHTML='<div class="empty">Error: '+esc(e.message)+'</div>'}
}

/* ─── Orphans ─── */
async function loadOrphans(){
  const el=document.getElementById('orphanList');
  el.innerHTML='<div class="loading">Loading orphan memories...</div>';
  try{
    const data=await fetchJSON(API+'/maintenance/orphans');
    if(!data||!data.length){el.innerHTML='<div class="empty">No orphan memories found</div>';return}
    el.innerHTML='<div style="margin-bottom:12px;font-size:13px;color:#8b95a5">'+data.length+' orphan memory(ies) found</div>'+
      data.map(o=>
        '<div class="card" id="orphan-'+o.id+'">'+
          '<div class="card-header">'+
            '<span style="color:#e6edf3;font-size:13px;flex:1">'+esc(o.content_snippet||'(no content)')+'</span>'+
            '<div class="orphan-actions">'+
              '<span class="badge '+(o.category==='deprecated'?'badge-err':'badge-warn')+'">'+esc(o.category||'orphaned')+'</span>'+
              '<button class="btn btn-danger btn-sm" onclick="deleteOrphan('+o.id+')">Delete</button>'+
            '</div>'+
          '</div>'+
        '</div>').join('');
  }catch(e){el.innerHTML='<div class="empty">Error: '+esc(e.message)+'</div>'}
}

async function deleteOrphan(id){
  if(!confirm('Delete orphan memory #'+id+'? This cannot be undone.'))return;
  try{
    await fetchJSON(API+'/maintenance/orphans/'+id,{method:'DELETE'});
    const card=document.getElementById('orphan-'+id);
    if(card)card.remove();
    toast('Memory #'+id+' deleted',true);
  }catch(e){toast('Delete failed: '+e.message,false)}
}

/* ─── Create ─── */
async function doCreate(e){
  e.preventDefault();
  const body={
    parent_uri:document.getElementById('createParentUri').value.trim(),
    content:document.getElementById('createContent').value.trim(),
  };
  const title=document.getElementById('createTitle').value.trim();
  const priority=parseInt(document.getElementById('createPriority').value);
  const disclosure=document.getElementById('createDisclosure').value.trim();
  if(title)body.title=title;
  if(priority>=1&&priority<=10)body.priority=priority;
  if(disclosure)body.disclosure=disclosure;
  const el=document.getElementById('createResult');
  el.innerHTML='<div class="loading">Creating...</div>';
  try{
    const data=await fetchJSON(API+'/create',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify(body),
    });
    el.innerHTML='<div class="card" style="border-color:#c9875a">'+
      '<div style="color:#c9875a;font-weight:600;margin-bottom:4px">Memory created!</div>'+
      '<div style="font-size:12px;color:#8b95a5">URI: '+esc(data.uri||data.id||JSON.stringify(data))+'</div>'+
    '</div>';
    document.getElementById('createForm').reset();
    toast('Memory created successfully',true);
  }catch(e){el.innerHTML='<div style="color:#da3633;font-size:13px">Error: '+esc(e.message)+'</div>';toast('Create failed',false)}
  return false;
}

/* ─── Init ─── */
document.getElementById('searchInput').addEventListener('keydown',e=>{if(e.key==='Enter')doSearch()});
loadUser();
loadStats();
loadTree();
</script>
</body>
</html>"""
