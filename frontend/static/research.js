import {markdown} from './js/markdown.js';
const $ = id => document.getElementById(id);
const el = (tag, cls, text) => { const n=document.createElement(tag); if(cls)n.className=cls; if(text!==undefined)n.textContent=text; return n; };
let state=null, tab='paper', selectedRun=new URLSearchParams(location.search).get('run')||'', busy=false, ticket=0, workKey='';
const time = t => `Day ${Math.floor(t/86400)+1} · ${String(Math.floor(t%86400/3600)).padStart(2,'0')}:${String(Math.floor(t%3600/60)).padStart(2,'0')}`;
const stateText={idle:'自由活动',work:'工作中',sleep:'休息中',movement:'在路上',bedridden:'卧床休养'};
const occupations={'team-leader':'组长',programmer:'程序员',chef:'厨师',doctor:'医生',shopkeeper:'店主',mayor:'市长',teacher:'教师',student:'学生'};
const phases={running:'实验进行中',completed:'实验已结束',interrupted:'实验已暂停',failed:'实验异常停止'};
async function api(path,params={}){const r=await fetch(path+'?'+new URLSearchParams(params),{cache:'no-store'});const d=await r.json();if(!r.ok)throw new Error(d.error||`HTTP ${r.status}`);return d;}
function empty(title,description){const box=el('div','empty');box.append(el('span','paper-icon','⌑'),el('h3','',title),el('p','',description));return box;}
function townLink(name,view='town'){return `index.html#/run/${encodeURIComponent(state.run)}/${view}${name?'?agent='+encodeURIComponent(name):''}`;}
function render(){
 $('clock').textContent=time(state.now);$('phase').textContent=`${phases[state.manifest.status]||state.manifest.status} · 共 ${state.days} 天`;
 $('live').textContent=state.manifest.status==='running'?'实时记录':'历史记录';$('live').classList.remove('stale');
 $('town-link').href=townLink();
 $('run-details').textContent=`${state.environment==='academy'?'学院课题组':'社会小镇'} · ${state.people.length} 位居民 · ${state.actor_model}`;
 if([...$('run').options].map(o=>o.value).join('|')!==state.runs.join('|')){$('run').replaceChildren(...state.runs.map(n=>new Option(n,n)));}$('run').value=state.run;
 const shared=state.files.filter(f=>f.path.startsWith('files/'));
 $('files-count').textContent=shared.length;$('commands-count').textContent=state.counts.shell||0;$('sources-count').textContent=`${(state.counts.search_literature||0)+(state.counts.search_web||0)} / ${(state.counts.read_source||0)+(state.counts.curl||0)}`;
 $('paper-state').textContent=shared.some(f=>f.path==='files/paper.md')?'已有草稿':'尚无草稿';$('revision').textContent=`版本 ${state.revision.slice(0,8)}`;
 $('people').replaceChildren(...state.people.map(p=>{const a=el('a','person');a.href=`index.html#/run/${encodeURIComponent(state.run)}/people/${encodeURIComponent(p.name)}?tab=trace`;a.append(el('div','avatar',p.name[0]),el('strong','',p.name),el('p','',occupations[p.occupation]||p.occupation),el('p','',p.place),el('span','state',stateText[p.state]||p.state),el('p','',`${state.currency}${p.money}`));return a;}));
 if($('actor').options.length!==state.people.length+1){const chosen=$('actor').value;$('actor').replaceChildren(new Option('全部居民',''),...state.people.map(p=>new Option(p.name,p.name)));$('actor').value=chosen;}
 renderMilestones();renderFeed();renderWorkspace();$('updated').textContent='更新于 '+new Date(state.updated_at*1000).toLocaleTimeString('zh-CN',{hour12:false});
}
function renderMilestones(){
 const reviews=new Map((state.milestones||[]).map(m=>[m.stage,m]));
 const cards=(state.scheduled_milestones||[]).map(stage=>{
  const m=reviews.get(stage.id),card=el('article','milestone');
  card.append(el('small','',`Day ${stage.day} · ${stage.artifact}`),el('h3','',stage.id==='proposal'?'选题提案':stage.id==='draft'?'初步稿件':stage.id));
  if(m){card.append(el('strong','score',`${m.score} / 100`),el('p','',`资金 ${state.currency}${m.reward_total} · 每人 ${state.currency}${m.reward_per_resident}`),el('p','',m.summary));const b=el('button','view-original','评审与证据 ↗');b.onclick=()=>showFile(m.record);card.append(b);}
  else card.append(el('p','',`尚未评审 · 每人最高 ${state.currency}${stage.max_reward_per_resident}`));
  return card;
 });
 $('milestones').replaceChildren(...cards);
 const table=el('table'),head=el('tr');for(const label of ['实验','环境 / 人数','选题','初稿','累计资金'])head.append(el('th','',label));table.append(head);
 for(const r of state.comparison||[]){const tr=el('tr'),name=el('td'),a=el('a','',r.run);a.href='?run='+encodeURIComponent(r.run);name.append(a);tr.append(name,el('td','',`${r.environment==='academy'?'学院':'小镇'} / ${r.people}`),el('td','',r.scores.proposal??'—'),el('td','',r.scores.draft??'—'),el('td','',`${r.currency}${r.reward_total}`));table.append(tr);}
 $('comparison').replaceChildren(table,el('p','fine','分数来自相同阶段的外部评审；资金总额按居民人数发放，不作为科研质量排名。'));
}
function renderFeed(){if(!state)return;const actor=$('actor').value,kind=$('kind').value;const events=state.activity.filter(e=>(!actor||e.actor===actor)&&(!kind||(kind==='conversation'?['speech','message','announcement'].includes(e.kind):e.kind===kind)));$('feed').replaceChildren(...events.map(e=>{const box=el('article','event'),head=el('div','event-top'),id=el('button','event-id',`E${e.seq} ↗`);id.onclick=()=>showEvent(e);head.append(el('span','',time(e.sim_time)),el('strong','',e.actor||'全镇'),id);box.append(head,el('p','',e.text));return box;}));if(!events.length)$('feed').append(empty('暂时没有记录','符合筛选条件的活动会显示在这里。'));}
function showEvent(e){$('detail-title').textContent=`E${e.seq} · ${e.actor||'全镇'}`;const pre=el('pre','',e.text);$('detail-body').replaceChildren(el('p','meta',`${time(e.sim_time)} · ${e.kind}`),pre);$('detail').showModal();}
async function showFile(path){const t=++ticket;$('detail-title').textContent=path;$('detail-body').replaceChildren(el('p','loading','正在读取…'));if(!$('detail').open)$('detail').showModal();try{const f=await api('/api/research/file',{run:state.run,path,revision:state.revision});if(t!==ticket)return;const meta=el('p','meta',`${(f.bytes/1024).toFixed(1)} KB · 版本 ${f.revision.slice(0,8)}${f.truncated?' · 正文预览已截断':''}`);let content;if(f.image){content=el('img');content.src=f.image;content.alt=path;}else{content=el('pre','',f.text);}$('detail-body').replaceChildren(meta,content);}catch(e){if(t===ticket)$('detail-body').replaceChildren(el('p','',e.message));}}
async function renderWorkspace(){if(!state)return;const key=state.run+state.revision+tab;if(key===workKey)return;workKey=key;const target=$('workspace-body');if(tab==='paper'){
 const paper=state.files.find(f=>f.path==='files/paper.md');if(!paper){target.replaceChildren(empty('论文还在酝酿中','居民们可以先讨论问题、查阅文献或开展实验。创建 paper.md 后，论文草稿会出现在这里。'));return;}
 target.replaceChildren(el('div','loading','正在读取论文…'));try{const f=await api('/api/research/file',{run:state.run,path:paper.path,revision:state.revision});if(workKey!==key)return;const body=el('article','paper');body.append(...markdown(f.text));const button=el('button','view-original','查看原始文件 ↗');button.onclick=()=>showFile(paper.path);target.replaceChildren(button,body);}catch(e){if(workKey===key){workKey='';target.replaceChildren(empty('暂时无法读取',e.message));}}return;}
 if(tab==='files'){const list=el('div','file-list');for(const f of state.files.filter(f=>f.path.startsWith('files/'))){const b=el('button','file-row');b.append(el('span','tag',f.path.split('.').pop().toUpperCase().slice(0,6)),el('span','file-name',f.path.slice(6)),el('small','',`${(f.bytes/1024).toFixed(1)} KB ↗`));b.onclick=()=>showFile(f.path);list.append(b);}target.replaceChildren(list);return;}
 const list=el('div','record-list');for(const r of state.records){const b=el('button','record-row'),info=el('div');info.append(el('small','',`${time(r.t)} · ${r.actor} · E${r.seq}`),el('p','',r.summary));b.append(el('span','tag'+(r.failed?' failed':''),r.failed?'未完成':({shell:'执行',search_literature:'检索',read_source:'读取'}[r.tool]||'写入')),info);b.onclick=()=>showFile(r.path);list.append(b);}target.replaceChildren(state.records.length?list:empty('第一条研究记录尚未产生','共享文件修改、命令执行和文献读取都会留下原始记录。'));
}
async function refresh(){if(busy)return;busy=true;try{const data=await api('/api/research',{run:selectedRun});if(data.waiting){$('phase').textContent='实验准备中';$('clock').textContent='即将开始';return;}state=data;selectedRun=data.run;$('error').hidden=true;render();}catch(e){$('error').hidden=false;$('error').textContent='暂时无法更新：'+e.message;$('live').textContent='连接中断';$('live').classList.add('stale');}finally{busy=false;}}
$('run').onchange=()=>{selectedRun=$('run').value;history.replaceState(null,'','?run='+encodeURIComponent(selectedRun));workKey='';refresh();};$('actor').onchange=renderFeed;$('kind').onchange=renderFeed;
for(const b of document.querySelectorAll('[data-tab]'))b.onclick=()=>{tab=b.dataset.tab;for(const x of document.querySelectorAll('[data-tab]')){x.classList.toggle('active',x===b);x.setAttribute('aria-selected',String(x===b));}renderWorkspace();};
$('close-detail').onclick=()=>{ticket++;$('detail').close();};$('detail').addEventListener('click',e=>{if(e.target===$('detail'))$('detail').close();});
refresh();setInterval(refresh,5000);
