'use strict';
(() => {
  const graph = JSON.parse(document.getElementById('graph-data').textContent);
  const nodes = new Map(graph.nodes.map(n => [n.id, n]));
  const svg = document.getElementById('universe');
  const inspector = document.getElementById('inspector');
  const search = document.getElementById('search');
  const list = document.getElementById('node-list');
  const allToggle = document.getElementById('show-all');
  const ruledToggle = document.getElementById('show-ruled-out');
  let selected = null;
  let view = [0, 0, 1100, 800];
  let dragging = null;
  const satellite = n => n && (n.kind === 'skill' || n.kind === 'concept');
  const label = n => n.kind === 'concept' ? graph.labels.facets[n.category] : n.kind === 'skill' ? graph.labels.categories[n.category] : graph.labels.kinds[n.kind];
  const links = () => graph.links.filter(l => ruledToggle.checked || l.role !== 'not_used');
  const el = (tag, text, cls) => { const e = document.createElement(tag); if (text !== undefined) e.textContent = text; if (cls) e.className = cls; return e; };
  const shape = (tag, attrs, text) => { const e = document.createElementNS('http://www.w3.org/2000/svg', tag); for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, String(v)); if (text !== undefined) e.textContent = text; return e; };
  const add = (parent, tag, text, cls) => { const e = el(tag, text, cls); parent.append(e); return e; };
  const select = id => { selected = id; draw(); details(); browse(); };
  const setView = () => svg.setAttribute('viewBox', view.join(' '));
  const zoom = scale => { const width = Math.max(440, Math.min(2200, view[2] * scale)); const height = width * 800 / 1100; view = [view[0] + (view[2] - width) / 2, view[1] + (view[3] - height) / 2, width, height]; setView(); };

  function draw() {
    svg.replaceChildren(shape('title', {}, 'Your experiences, skills and interests'));
    [130, 230, 340].forEach(r => svg.append(shape('ellipse', {cx:550, cy:390, rx:r * 1.2, ry:r * .86, class:'orbit'})));
    const usable = links();
    const chosen = nodes.get(selected);
    const experiences = graph.nodes.filter(n => !satellite(n));
    const degree = new Map();
    usable.forEach(l => degree.set(l.to, (degree.get(l.to) || 0) + 1));
    let visibleSkills = graph.nodes.filter(n => satellite(n) && (allToggle.checked || (degree.get(n.id) || 0) > 1));
    if (satellite(chosen)) visibleSkills = [chosen];
    else if (chosen) visibleSkills = graph.nodes.filter(n => satellite(n) && usable.some(l => l.from === chosen.id && l.to === n.id));
    const positions = new Map();
    experiences.forEach((n, i) => { const angle = -Math.PI / 2 + i * 2 * Math.PI / Math.max(1, experiences.length); positions.set(n.id, [550 + Math.cos(angle) * 425, 390 + Math.sin(angle) * 280]); });
    visibleSkills.forEach((n, i) => { const angle = -Math.PI / 2 + i * 2 * Math.PI / Math.max(1, visibleSkills.length); const radius = visibleSkills.length > 16 ? (i % 2 ? 205 : 120) : 180; positions.set(n.id, satellite(chosen) ? [550, 390] : [550 + Math.cos(angle) * radius, 390 + Math.sin(angle) * radius * .9]); });
    const relevant = new Set(chosen ? [chosen.id] : []);
    usable.forEach(l => { if (positions.has(l.from) && positions.has(l.to)) { relevant.add(l.from); relevant.add(l.to); const [x1,y1] = positions.get(l.from), [x2,y2] = positions.get(l.to); svg.append(shape('path', {d:`M${x1},${y1} Q550,390 ${x2},${y2}`, class:`connection ${l.role}`, 'data-link':l.id})); } });
    if (!satellite(chosen)) { svg.append(shape('circle', {cx:550,cy:390,r:28,class:'sun'})); svg.append(shape('text',{x:550,y:439,class:'sun-label'},'Me')); }
    for (const n of [...experiences, ...visibleSkills]) {
      const [x,y] = positions.get(n.id);
      const cls = `node ${satellite(n) ? 'skill' : 'planet'}${selected === n.id ? ' selected' : ''}${chosen && !relevant.has(n.id) ? ' dimmed' : ''}`;
      const g = shape('g', {class:cls, transform:`translate(${x},${y})`, tabindex:0, role:'button', 'aria-label':`${n.label}, ${label(n)}`, 'data-node':n.id});
      g.append(shape('circle',{r:24,class:'hit'}));
      g.append(shape('circle',{r:satellite(n) ? 10 : 24,class:'body'}));
      const words = n.label.split(' '); const lines = [''];
      for (const word of words) { if ((lines.at(-1) + ' ' + word).trim().length > 24 && lines.length < 2) lines.push(word); else lines[lines.length - 1] = (lines.at(-1) + ' ' + word).trim(); }
      lines.forEach((line,i) => g.append(shape('text', {x:0,y:(satellite(n) ? 28 : 44) + i * 18}, line.length > 29 ? line.slice(0,28) + '…' : line)));
      g.addEventListener('click', () => select(n.id));
      g.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') {event.preventDefault(); select(n.id); svg.querySelector(`[data-node="${n.id}"]`)?.focus();} });
      svg.append(g);
    }
    document.getElementById('map-caption').textContent = chosen ? `${chosen.label} · ${satellite(chosen) ? 'connections across experiences' : 'skills and interests in context'}` : 'Experiences are planets. Skills and interests connect their stories.';
    setView();
  }

  function evidence(parent, claimIds) {
    const container = add(parent, 'details');
    add(container, 'summary', `Inspect ${claimIds.length} supporting statement${claimIds.length === 1 ? '' : 's'}`);
    claimIds.forEach(cid => { const item = graph.evidence[cid]; if (!item) return; add(container,'p',item.text); item.passages.forEach(p => {add(container,'div',`${p.locator} · v${p.version}`,'citation');add(container,'blockquote',p.quote);}); });
  }

  function details() {
    inspector.replaceChildren();
    const n = nodes.get(selected);
    if (!n) {
      add(inspector,'span','YOUR CONNECTED EXPERIENCE','eyebrow');
      add(inspector,'h2','Find the threads');
      add(inspector,'p','Select a skill to see where it appears across your projects and experiences. Select a planet to explore the knowledge behind that work.','muted');
      add(inspector,'h3','Depth needs context');
      add(inspector,'p','Explaining graphics, designing a renderer and knowing Rust are separate capabilities. AI assistance and your own contribution belong in that context.','muted');
      const q = graph.questions[0];
      if (q) {add(inspector,'h3','A useful next question');add(inspector,'p',q.prompt,'question');}
      if (!graph.nodes.length) add(inspector,'p','Add or review an experience in Foundry to start your map.');
      return;
    }
    add(inspector,'span',label(n).toUpperCase(),'eyebrow');
    add(inspector,'h2',n.label);
    if (n.dates.length) add(inspector,'p',`Dates from your records: ${n.dates.join('; ')}. Current activity is unconfirmed.`,'muted');
    const attached = links().filter(l => l.from === n.id || l.to === n.id);
    add(inspector,'span',`${attached.length} connection${attached.length === 1 ? '' : 's'}`,'badge');
    add(inspector,'p',n.kind === 'skill' ? 'Capability is described separately in each experience. Repeated mentions do not establish mastery.' : 'Your reviewed evidence is preserved. Add your contribution, enjoyment and difficulties through a short project reflection.','muted');
    for (const link of attached) {
      const other = nodes.get(link.from === n.id ? link.to : link.from);
      const item = add(inspector,'div',undefined,'connection-item');
      const button = add(item,'button',other.label); button.addEventListener('click',()=>select(other.id));
      if (!link.relation) add(item,'p',graph.labels.roles[link.role],'muted');
      add(item,'p',link.basis,'muted');
      if (link.assessment) {
        const a = link.assessment; const dl = add(item,'dl');
        for (const [dimension,value] of Object.entries(a.depth)) {add(dl,'dt',graph.labels.dimensions[dimension]);add(dl,'dd',graph.labels.depth[value]);}
        add(item,'p',graph.labels.assistance[a.assistance],'muted');
        add(item,'blockquote',graph.evidence[a.claim_id]?.text || '');
      } else if (!link.relation) add(item,'p','Depth and assistance have not been assessed.','muted');
      evidence(item,link.claim_ids);
    }
    const answers = graph.answers.filter(a => a.experience === n.id);
    if (answers.length) {add(inspector,'h3','Your experience');answers.forEach(a=>{add(inspector,'span',graph.labels.topics[a.topic],'badge');add(inspector,'blockquote',graph.evidence[a.claim_id]?.text || '');});}
    const q = graph.questions.find(q=>q.experience === n.id);
    if (q) {add(inspector,'h3','Next reflection');add(inspector,'p',q.prompt,'question');}
    evidence(inspector,n.claim_ids);
  }

  function browse() {
    const term = search.value.trim().toLocaleLowerCase();
    const matches = graph.nodes.filter(n=>(n.label + ' ' + label(n)).toLocaleLowerCase().includes(term)).sort((a,b)=>a.label.localeCompare(b.label));
    list.replaceChildren();
    document.getElementById('search-count').textContent = `${matches.length} matching entries`;
    for (const n of matches) {const b=add(list,'button',undefined,'list-item');b.setAttribute('aria-pressed',String(selected===n.id));add(b,'span',n.label);add(b,'small',label(n));b.addEventListener('click',()=>select(n.id));}
  }
  svg.addEventListener('pointerdown',event=>{if (event.target.closest('.node')) return;dragging={x:event.clientX,y:event.clientY,view:[...view]};svg.setPointerCapture(event.pointerId);});
  svg.addEventListener('pointermove',event=>{if (!dragging) return;const rect=svg.getBoundingClientRect();view=[dragging.view[0]-(event.clientX-dragging.x)*view[2]/rect.width,dragging.view[1]-(event.clientY-dragging.y)*view[3]/rect.height,view[2],view[3]];setView();});
  svg.addEventListener('pointerup',()=>{dragging=null;});svg.addEventListener('pointercancel',()=>{dragging=null;});
  document.getElementById('zoom-in').addEventListener('click',()=>zoom(.8));document.getElementById('zoom-out').addEventListener('click',()=>zoom(1.25));
  document.getElementById('reset-view').addEventListener('click',()=>{view=[0,0,1100,800];setView();});
  document.getElementById('overview').addEventListener('click',()=>select(null));
  document.addEventListener('keydown',event=>{if(event.key==='Escape')select(null);});
  search.addEventListener('input',browse);allToggle.addEventListener('change',draw);ruledToggle.addEventListener('change',()=>{draw();details();});
  document.getElementById('dataset').textContent = `${graph.dataset === 'synthetic' ? 'FICTIONAL DEMONSTRATION' : 'PERSONAL'} · LOCAL SNAPSHOT`;
  document.getElementById('counts').textContent = `${graph.nodes.filter(n=>!satellite(n)).length} experiences · ${graph.nodes.filter(n=>n.kind==='skill').length} skills · ${graph.nodes.filter(n=>n.kind==='concept').length} interests and preferences`;
  draw();details();browse();
})();
