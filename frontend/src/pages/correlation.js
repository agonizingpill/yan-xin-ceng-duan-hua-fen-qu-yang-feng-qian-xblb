import{heading,badge,notice}from'../components/logbook.js';import{esc,values}from'../utils/format.js';import{api}from'../utils/api.js';

const KIND={match:'对层',left_only:'左孔尖灭',right_only:'右孔尖灭'};

function basisText(l){
  let b=l.basis||{},d=b.distance,m=b.margin,nd=b.nearest_distance;
  if(l.kind==='match')return `物性距离 ${d??'—'}${m!=null?' / 最近他层差 '+m:''}`;
  return `最近邻孔层距离 ${nd??'—'}`;
}
function sideLayers(list){return (list||[]).map((v,i)=>({...v,index:v.index??i+1}))}

function drawing(r){
  if(!r||!r.left||!r.right)return'';
  let L=r.left.statistics||[],R=r.right.statistics||[],all=[...L,...R];
  let max=Math.max(...all.map(x=>x.end_m),1),H=440,top=30,bottom=26,W=800;
  let y=d=>top+(d/max)*(H-top-bottom);
  let mid=v=>y((v.start_m+v.end_m)/2);
  let LX0=120,LX1=268,RX0=532,RX1=680;
  let box=(x0,x1,list,side)=>list.map(v=>{let t=y(v.start_m),h=Math.max(y(v.end_m)-t,2);
    return `<g><rect x="${x0}" y="${t}" width="${x1-x0}" height="${h}" class="pr-${side}${v.has_gap?' gap':''}"${v.has_gap?` style="fill:url(#pr-gap-${side})"`:''}><title>${esc(v.lithology)} ${v.start_m}—${v.end_m}m · ${v.n}点${v.has_gap?' · 含缺芯':''}</title></rect>`+
      `<text x="${side==='l'?x0-10:x1+10}" y="${t+h/2+4}" text-anchor="${side==='l'?'end':'start'}" class="pr-label">${esc(v.lithology)} <tspan class="pr-idx">${side==='l'?'L':'R'}${v.index}</tspan></text>`+
      `<text x="${side==='l'?x0-10:x1+10}" y="${t+h/2+16}" text-anchor="${side==='l'?'end':'start'}" class="pr-range">${v.start_m}—${v.end_m}m</text></g>`}).join('');
  let leftById=new Map(L.map(v=>[v.stratum_id,v])),rightById=new Map(R.map(v=>[v.stratum_id,v]));
  let links=r.links||[];
  // 连线端点：有本层者取层中点；尖灭一侧在相邻已对层之间做单调插值，保证线不交叉。
  let ys=side=>links.map(l=>{let v=l[side+'_stratum_id']?(side==='left'?leftById:rightById).get(l[side+'_stratum_id']):null;return v?mid(v):null});
  let leftY=ys('left'),rightY=ys('right');
  let fill=arr=>{let known=arr.map((v,i)=>v==null?null:i).filter(i=>i!=null);
    if(!known.length)return arr.map(()=>top);
    for(let i=0;i<arr.length;i++)if(arr[i]==null){
      let before=[...known].reverse().find(k=>k<i),after=known.find(k=>k>i);
      if(before!=null&&after!=null)arr[i]=arr[before]+(arr[after]-arr[before])*(i-before)/(after-before);
      else if(before!=null)arr[i]=arr[before];else arr[i]=arr[after];
    }return arr};
  fill(leftY);fill(rightY);
  let lines=links.map((l,i)=>{
    let cls=l.status==='pending'?'pr-link pending':'pr-link';
    if(l.origin==='anchor')cls+=' anchor';
    if(l.kind!=='match')cls+=' pinch';
    let tip=`${KIND[l.kind]} · ${l.origin==='anchor'?'现场锚点':'推算'} · ${l.status==='pending'?'待核实':'已核实'}${l.reason?'\n'+l.reason:''}`;
    let ay=leftY[i],by=rightY[i];
    let mark=l.kind==='left_only'?`<polygon points="${RX0},${by} ${RX0-10},${by-5} ${RX0-10},${by+5}" class="pr-pinch"><title>左孔该层在右孔尖灭</title></polygon>`
      :l.kind==='right_only'?`<polygon points="${LX1},${ay} ${LX1+10},${ay-5} ${LX1+10},${ay+5}" class="pr-pinch"><title>右孔该层在左孔尖灭</title></polygon>`:'';
    return `<line x1="${LX1}" y1="${ay.toFixed(1)}" x2="${RX0}" y2="${by.toFixed(1)}" class="${cls}"><title>${esc(tip)}</title></line>${mark}`}).join('');
  let step=Math.max(6,Math.round(max/6/6)*6),ticks=[];
  for(let d=0;d<=max;d+=step){ticks.push(`<line x1="46" y1="${y(d)}" x2="${RX1+18}" y2="${y(d)}" class="pr-grid"/><text x="4" y="${y(d)+4}" class="pr-tick">${d}m</text>`)}
  return `<svg class="pr-canvas" viewBox="0 0 ${W} ${H}" role="img" aria-label="相邻钻孔对比剖面：左孔与右孔岩性柱按深度排列，对层连线不交叉，楔形标记表示层位在邻孔尖灭">
  <defs><pattern id="pr-gap-l" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(35)"><rect width="6" height="6" fill="#e7d9c7"/><line x1="0" y1="0" x2="0" y2="6" stroke="#963e2b" stroke-width="2" opacity=".55"/></pattern>
  <pattern id="pr-gap-r" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(35)"><rect width="6" height="6" fill="#dce8dc"/><line x1="0" y1="0" x2="0" y2="6" stroke="#963e2b" stroke-width="2" opacity=".55"/></pattern></defs>
  ${ticks.join('')}${box(LX0,LX1,L,'l')}${box(RX0,RX1,R,'r')}
  <text x="${LX0}" y="16" class="pr-head">左孔 ${esc(r.left.code||'')}</text><text x="${RX0}" y="16" class="pr-head">右孔 ${esc(r.right.code||'')}</text>
  ${lines}</svg>`;
}

function layerTable(r){
  return `<table class="pr-table"><thead><tr><th>对层关系</th><th>来源</th><th>状态</th><th>对层依据</th></tr></thead><tbody>${(r.links||[]).map(l=>{let a=(r.left.statistics||[]).find(v=>v.stratum_id===l.left_stratum_id),b=(r.right.statistics||[]).find(v=>v.stratum_id===l.right_stratum_id);return `<tr class="${l.status==='pending'?'pending-row':''}"><td>${KIND[l.kind]}</td><td>${a?esc(a.lithology)+' L'+a.index:'—'} ↔ ${b?esc(b.lithology)+' R'+b.index:'—'}</td><td>${l.status==='pending'?'<span class="status observed">待核实</span>':'<span class="status confirmed">已核实</span>'} ${l.origin==='anchor'?'<span class="status">锚点</span>':''}</td><td>${basisText(l)}${l.reason?`<br><span class="error">${esc(l.reason)}</span>`:''}</td></tr>`}).join('')}</tbody></table>`;
}

function snapshotView(p){
  let s=p.snapshot||{},r=s.result||{},li=s.left_interpretation,ri=s.right_interpretation;
  let ls=s.left_strata||[],rs=s.right_strata||[];
  let label=(list,id)=>{let v=list.find(x=>x.id===id);return v?`${esc(v.lithology)} ${v.start_m}—${v.end_m}m`:`层段 #${id}`};
  return `<details class="pr-snap"><summary>回看 ${esc(s.version||p.version||'')} 发布时的源层与对层依据</summary>
  <p class="tiny">发布 ${esc(s.published_by||'')} · ${esc(s.published_at||'')}<br>左孔 ${esc(s.left_borehole?.code||'')} 源层解释 #${li?.id??'—'}（${esc(li?.state||'')}） / 右孔 ${esc(s.right_borehole?.code||'')} 源层解释 #${ri?.id??'—'}（${esc(ri?.state||'')}）</p>
  <div class="pr-snap-cols"><div><h3>左孔源层</h3>${ls.map(v=>`<p class="tiny">${esc(v.lithology)} ${v.start_m}—${v.end_m}m<br>${esc(v.contact_note)}</p>`).join('')}</div><div><h3>右孔源层</h3>${rs.map(v=>`<p class="tiny">${esc(v.lithology)} ${v.start_m}—${v.end_m}m<br>${esc(v.contact_note)}</p>`).join('')}</div></div>
  ${(r.anchors||[]).length?`<h3>当时固定的现场锚点</h3><ul class="tiny">${r.anchors.map(a=>`<li>${label(ls,a.left_stratum_id)} ↔ ${label(rs,a.right_stratum_id)}${a.note?'：'+esc(a.note):''}</li>`).join('')}</ul>`:'<p class="tiny">该版本未固定现场锚点。</p>'}
  ${layerTable(r)}<p class="tiny">源数据摘要 ${esc(r.source_digest||'')}</p></details>`;
}

export function render(s,u){
  let h=s.hole,others=s.data.boreholes.filter(x=>x.id!==s.holeId);
  let mine=s.data.correlations.filter(x=>x.left_borehole_id===s.holeId||x.right_borehole_id===s.holeId);
  let active=mine.filter(x=>x.state==='draft').at(-1);
  // 已发布后转待复核的版本留在留档里；从未发布却已待复核的草稿，给一次性“重新绑定”入口。
  let staleDraft=mine.filter(x=>x.state==='pending_review'&&!x.version).at(-1);
  let archived=mine.filter(x=>x.state==='published'||(x.state==='pending_review'&&x.version)).sort((a,b)=>b.id-a.id);
  let can=u.role!=='viewer',sup=u.role==='supervisor';
  let code=id=>s.data.boreholes.find(x=>x.id===id)?.code||('#'+id);
  let r=active?.result,anchored=!!r?.anchored,left=sideLayers(r?.left?.statistics),right=sideLayers(r?.right?.statistics);  let anchorText=(active?.anchors||[]).map(a=>{let l=left.find(v=>v.stratum_id===a.left_stratum_id),rr=right.find(v=>v.stratum_id===a.right_stratum_id);return l&&rr?`${l.index},${rr.index},${a.note||''}`:''}).filter(Boolean).join('\n');
  // 不预填任何“默认锚点”：现场认定必须由编录员亲自填写，避免把建议当成结论。
  let defaultAnchors=anchorText||'';
  let pending=(r?.pending)||[];
  let pendingAll=[];let seen=new Set();
  for(let p of [...mine].sort((a,b)=>b.id-a.id)){if(p.id===active?.id)continue;
    for(let v of (p.result?.pending||[])){
      // 同一孔对可能正反向各存一份，按“孔号 + 层位深度”归一后去重。
      let a=(p.result?.left?.statistics||[]).find(z=>z.stratum_id===v.left_stratum_id);
      let b=(p.result?.right?.statistics||[]).find(z=>z.stratum_id===v.right_stratum_id);
      let side=(borehole,lay)=>lay?[borehole,lay.start_m,lay.end_m].join('~'):String(borehole);
      let coords=[side(p.left_borehole_id,a),side(p.right_borehole_id,b)].sort().join('|');
      let key=[Math.min(p.left_borehole_id,p.right_borehole_id),Math.max(p.left_borehole_id,p.right_borehole_id),coords].join(':');
      if(seen.has(key))continue;seen.add(key);
      pendingAll.push({p,v});
    }}
  let confirmed=s.data.interpretations.filter(x=>x.state==='confirmed'&&x.borehole_id===s.holeId).length;
  let emptyNote=confirmed
    ? '本孔已有确认层段。下方留档可回看历史版本；如需按最新解释复核，可选定对比右孔另建草稿。'
    : '本孔尚无主管确认的层段解释。两孔都须先确认解释，才能对比剖面。';
  let emptyHtml=`<div class="field-note">${emptyNote}</div>`;
  return heading('07','相邻两孔，一层一层对过去。','先固定现场认定的对层锚点，再按三项物性分布推算其余层。连线保证不交叉，允许某层在邻孔尖灭；缺芯或分不清的层留待核实。')
  +`<div class="pr-tools"><label class="pr-pick">对比右孔<select id="pr-right">${others.map(x=>`<option value="${x.id}">${esc(x.code)} · ${esc(x.site)}</option>`).join('')||'<option value="">本区还没有第二孔</option>'}</select></label><button id="pr-create" ${can&&others.length&&h?.state!=='frozen'?'':'disabled'}>新建对比剖面草稿</button>${active?badge(active.state):''}</div>`
  +(active?'':(staleDraft?`<div class="field-note">${badge('pending_review')} ${esc(code(staleDraft.left_borehole_id))} ↔ ${esc(code(staleDraft.right_borehole_id))} 尚未发布的草稿因源层撤回转入待复核：${esc(staleDraft.error)}<div class="actions"><button id="pr-rebind" data-id="${staleDraft.id}" ${can?'':'disabled'}>按两孔当前已确认解释重新绑定</button></div></div>`:emptyHtml))
  +(active?`<div class="corr-layout"><section><div class="pr-caption"><h2>${esc(code(active.left_borehole_id))} ↔ ${esc(code(active.right_borehole_id))}</h2><p class="tiny">${esc(active.note||'')}<br>左孔源层解释 #${active.left_interpretation_id} / 右孔源层解释 #${active.right_interpretation_id}${anchored?` · 待核实 ${pending.length} 层`:' · 尚未固定锚点'}</p></div>${active.error?`<p class="error">${esc(active.error)}</p>`:''}${anchored?drawing(r):'<div class="empty">先固定现场认定的对层锚点，剖面才推算其余层；未固定前不给出任何对层结论。层序号见右侧 L1/R1 说明。</div>'}${anchored?layerTable(r):''}${active.state==='draft'&&anchored?`<div class="actions"><button class="ochre" id="pr-publish" data-id="${active.id}" ${sup?'':'disabled'}>主管发布剖面版本</button><span class="tiny">发布后冻结本版对层结果与源层依据；撤回解释不会改写已发布快照，只会让该版留待复核。</span></div>`:''}</section><aside><h2>固定现场认定对层</h2><form id="pr-anchors" data-id="${active.id}"><label>每行：左层序号,右层序号,现场依据<textarea name="anchors" class="layers-input" placeholder="1,1,现场见粉砂岩顶面一致">${esc(defaultAnchors)}</textarea></label><p class="note">层段自孔口向下编号 L1/R1，与剖面左右柱一致。只填现场已经共同认定的接触面；未填不推算。锚点互相矛盾时整份作废，剖面退回草案并留下原因。</p><button ${can&&active.state==='draft'?'':'disabled'}>保存锚点并重算</button></form><h2>待核实层</h2>${anchored?(pending.length?`<ul class="pr-pending">${pending.map(l=>{let a=left.find(v=>v.stratum_id===l.left_stratum_id),b=right.find(v=>v.stratum_id===l.right_stratum_id);return `<li><b>${a?esc(a.lithology)+' L'+a.index:'—'} ↔ ${b?esc(b.lithology)+' R'+b.index:'—'}</b><small>${esc(l.reason)}</small></li>`}).join('')}</ul>`:'<p class="tiny">当前草稿没有待核实层。</p>'):'<p class="tiny">尚未固定锚点，暂不推算。</p>'}</aside></div>`:'')
  +`<section class="pr-history"><h2>剖面版本留档 <small>已发布 ${archived.length} 版</small></h2>${archived.map(p=>`<article class="pr-version"><div><h3>${esc(p.snapshot?.version||p.version||'未发布')} ${badge(p.state)}</h3><p class="tiny">${esc(code(p.left_borehole_id))} ↔ ${esc(code(p.right_borehole_id))} · ${esc(p.snapshot?.published_by||p.published_by||'')} · ${esc(p.snapshot?.published_at||p.published_at||'')}${p.state==='pending_review'?'<br><span class="error">'+esc(p.error)+'</span>':''}</p></div>${p.snapshot?.result?snapshotView(p):'<p class="tiny">尚无发布快照。</p>'}</article>`).join('')||'<div class="empty">还没有已发布的对比剖面。发布后此处保留当时源层与对层依据，供复核回看。</div>'}
  ${pendingAll.length?`<h3>全部待核实对层</h3><ul class="pr-pending">${pendingAll.map(({p,v})=>{let a=(p.result?.left?.statistics||[]).find(z=>z.stratum_id===v.left_stratum_id),b=(p.result?.right?.statistics||[]).find(z=>z.stratum_id===v.right_stratum_id);let lo=p.left_borehole_id<=p.right_borehole_id?[code(p.left_borehole_id),a,code(p.right_borehole_id),b]:[code(p.right_borehole_id),b,code(p.left_borehole_id),a];let[ca,la,cb,lb]=lo;return `<li><b>${esc(ca)} ↔ ${esc(cb)}</b> · ${la?esc(la.lithology)+' L'+la.index:'—'} ↔ ${lb?esc(lb.lithology)+' R'+lb.index:'—'}<small>${esc(v.reason)}</small></li>`}).join('')}</ul>`:''}</section>`;
}

export function bind(run,render,s){
  let c=document.getElementById('pr-create');
  if(c)c.onclick=()=>{let right=+document.getElementById('pr-right').value;if(!right)return;run(()=>api('/correlations','POST',{left_borehole_id:s.holeId,right_borehole_id:right,note:'相邻孔三项物性对比剖面，先固定现场锚点再推算其余层'}),'对比剖面草稿已建立')};
  let f=document.getElementById('pr-anchors');
  if(f)f.onsubmit=e=>{e.preventDefault();let err=null;let anchors=values(f).anchors.split('\n').filter(x=>x.trim()).map(x=>{let[a,b,...d]=x.split(',');let li=+a,ri=+b;return{li,ri,note:d.join(',').trim()}});
    // 序号在本页渲染时已按层段深度排序；提交前换算为层段 id 交给后端校验。
    let pid=+f.dataset.id,prof=s.data.correlations.find(p=>p.id===pid);
    let st=s.data.strata.filter(x=>x.interpretation_id===prof?.left_interpretation_id).sort((p,q)=>p.start_m-q.start_m);
    let sr=s.data.strata.filter(x=>x.interpretation_id===prof?.right_interpretation_id).sort((p,q)=>p.start_m-q.start_m);
    let payload=[];for(let a of anchors){if(!st[a.li-1]||!sr[a.ri-1]){err='层序号超出范围，请对照 L/R 编号填写';break}payload.push({left_stratum_id:st[a.li-1].id,right_stratum_id:sr[a.ri-1].id,note:a.note})}
    if(err){notice(err);return}
    run(()=>api('/correlations/'+pid+'/anchors','PUT',{anchors:payload}),'锚点已保存，其余层已按物性分布重算')};
  let b=document.getElementById('pr-publish');
  if(b)b.onclick=()=>run(()=>api('/correlations/'+b.dataset.id+'/publish','POST',{}),'剖面版本已发布，对层结果与源层依据已留档');
  let rb=document.getElementById('pr-rebind');
  if(rb)rb.onclick=()=>run(()=>api('/correlations/'+rb.dataset.id+'/rebind','POST',{}),'草稿已按当前已确认解释重新绑定，请重新固定现场锚点');
}
