(() => {
  "use strict";
  const STORAGE_KEY = "panelbook-workspace-v4";
  const SORT_KEY = "panelbook-sort-preference-v1";
  const SORT_FIELDS = {circuits:["assignment","name","voltage","amps","gauge","labelMode"],points:["circuitId","name","location","id"]};
  const GAUGES = {"14":15,"12":20,"10":30,"8":40,"6":55,"4":70,"2":95,"1/0":125};
  const el = id => document.getElementById(id);
  const escapeHTML = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"})[c]);
  const makePanel = (id,name,kind="main",parentPanelId=null) => ({id,name,kind,parentPanelId,parentCircuitId:null,spaces:24,types:{},circuits:[],nextCircuitId:1,points:[],nextPointId:1});
  const initial = () => ({version:4,homes:[{id:1,name:"Home",panels:[makePanel(1,"Main panel")]}],nextHomeId:2,nextPanelId:2,selectedHomeId:1,selectedPanelId:1});
  let workbook = initial();
  let state = workbook.homes[0].panels[0];
  let selected = 1;
  let messageTimer;
  let sorts = {circuits:{key:"assignment",dir:1},points:{key:"circuitId",dir:1}};
  let scopeMode = "print";
  let pendingPanelImport = null;
  let availableUpdate = null;
  let csrfToken = null;
  let currentUser = null;
  let currentVersion = null;
  let requireSetupCode = false;
  let localTabId = null;
  let localPresenceTimer = null;
  let savedHomes = new Map();
  let saveQueue = Promise.resolve();
  let saveBlocked = false;
  let appEventsWired = false;
  let resetUserId = null;

  async function api(path,method="GET",data) {
    const options={method,credentials:"same-origin",headers:{}};
    if(data!==undefined){options.headers["Content-Type"]="application/json";options.body=JSON.stringify(data);}
    if(method!=="GET" && csrfToken)options.headers["X-Panelbook-CSRF"]=csrfToken;
    const response=await fetch(path,options);
    const result=await response.json();
    if(!response.ok){const error=Error(result.error||`Request failed (${response.status}).`);error.status=response.status;throw error;}
    return result;
  }

  function homeSnapshot(h) { return JSON.stringify({name:h.name,panels:h.panels}); }
  function allocatePanelId() {
    let id;
    do {const bytes=crypto.getRandomValues(new Uint8Array(6));id=bytes.reduce((value,byte)=>value*256+byte,0)+1;}
    while(workbook.homes.some(h=>h.panels.some(p=>p.id===id)));
    workbook.nextPanelId=Math.max(workbook.nextPanelId,id+1);
    return id;
  }

  async function loadWorkspace() {
    const response=await api("/api/workspace");
    const homes=response.homes;
    if(!homes.length)throw Error("No homes are available for this account.");
    const selectedHome=homes.find(h=>h.id===workbook.selectedHomeId)||homes[0];
    const selectedPanel=selectedHome.panels.find(p=>p.id===workbook.selectedPanelId)||selectedHome.panels[0];
    workbook={version:4,homes,nextHomeId:Math.max(...homes.map(h=>h.id))+1,nextPanelId:Math.max(...homes.flatMap(h=>h.panels.map(p=>p.id)))+1,selectedHomeId:selectedHome.id,selectedPanelId:selectedPanel.id};
    state=selectedPanel;
    savedHomes=new Map(homes.map(h=>[h.id,homeSnapshot(h)]));
    saveBlocked=false;
  }

  async function checkPortableUpdate() {
    el("updateMessage").textContent="Checking for updates…";
    el("updateInstallBtn").hidden=true;
    el("updateDialog").showModal();
    try {
      const result=await api("/api/update/check");
      availableUpdate=result.release;
      el("updateMessage").textContent=result.release ? `Version ${result.release.version.replace(/^v/,"")} is ready to install.` : "Panelbook is up to date.";
      el("updateInstallBtn").hidden=!result.release;
    } catch(error) { el("updateMessage").textContent=error.message; }
  }
  async function installPortableUpdate() {
    if(!availableUpdate)return;
    el("updateInstallBtn").disabled=true;
    el("updateMessage").textContent="Finishing any pending saves…";
    try {
      await saveQueue;
      if(saveBlocked || workbook.homes.some(h=>h.role!=="viewer" && homeSnapshot(h)!==savedHomes.get(h.id)))
        throw Error("Some changes are not saved yet. Export a backup or reload before updating.");
      el("updateMessage").textContent="Installing the update. This page will reload when Panelbook restarts…";
      await api("/api/update/install","POST",{version:availableUpdate.version});
      const expectedVersion=availableUpdate.version.replace(/^v/,"");
      const deadline=Date.now()+300000;
      let wasOffline=false;
      while(Date.now()<deadline) {
        await new Promise(resolve=>setTimeout(resolve,1000));
        try {
          const response=await fetch("/api/status",{cache:"no-store"});
          if(!response.ok)continue;
          const status=await response.json();
          if(status.version===expectedVersion){location.reload();return;}
          if(wasOffline && status.version===currentVersion)
            throw Error("The update failed and the previous version restarted. See data/updater.log in your Panelbook folder.");
        } catch(error) {
          if(error.message.startsWith("The update failed"))throw error;
          wasOffline=true;
        }
      }
      throw Error("Panelbook did not return in five minutes. Check data/updater.log in your Panelbook folder, then run Panelbook.exe if needed.");
    }
    catch(error) { el("updateMessage").textContent=error.message; el("updateInstallBtn").disabled=false; }
  }

  function isPosition(n, spaces = state.spaces) { return Number.isInteger(n) && n >= 1 && n <= spaces; }
  function nextInColumn(n) { return n + 2; }
  function kind(n) { return state.types[n] || "single"; }
  function spansTwo(type) { return type === "double" || type === "quad"; }
  function owner(n) { return n > 2 && spansTwo(kind(n - 2)) ? n - 2 : n; }
  function leg(n) { return Math.floor((n - 1) / 2) % 2 === 0 ? "A" : "B"; }
  function designation(n, type = kind(n)) { return spansTwo(type) ? `${n}/${nextInColumn(n)}` : String(n); }
  function keysAt(n, type = kind(n)) { return type === "tandem" ? [`${n}a`,`${n}b`] : type === "quad" ? [`${n}a`,`${n}b/${n+2}a`,`${n+2}b`] : [designation(n,type)]; }
  function home() { return workbook.homes.find(h => h.id === workbook.selectedHomeId); }
  function panelById(id) { return home().panels.find(p => p.id === id); }
  function choosePanel(id) { const p=panelById(id); if (!p) return; workbook.selectedPanelId=id; state=p; selected=1; renderAll(); }
  function descendants(id) { const result=new Set([id]); let size; do { size=result.size; for(const p of home().panels) if(result.has(p.parentPanelId)) result.add(p.id); } while(result.size!==size); return result; }
  function feederChildren(panelId,circuitId) { return home().panels.filter(p=>p.parentPanelId===panelId && p.parentCircuitId===circuitId); }
  function validateFeeder(parentId,circuitId,childId=null,childCircuits=[]) {
    const parent=panelById(Number(parentId));
    const feeder=parent?.circuits.find(c=>c.id===Number(circuitId));
    if(!feeder || !feeder.assignment || feeder.voltage!==240 || !feeder.amps) throw Error("Choose an assigned 240 V feeder circuit with an amp rating.");
    if(feederChildren(parent.id,feeder.id).some(p=>p.id!==childId))throw Error("That feeder circuit already supplies another subpanel.");
    const oversized=childCircuits.find(c=>c.amps && c.amps>feeder.amps);
    if(oversized)throw Error(`A ${oversized.amps} A circuit in the subpanel exceeds its ${feeder.amps} A feeder.`);
    return feeder;
  }
  function feederOptions(parentId,selectedId=null,childId=null,childCircuits=[]) {
    const parent=panelById(Number(parentId));
    const choices=parent?.circuits.filter(c=>{
      try{validateFeeder(parent.id,c.id,childId,childCircuits);return true;}catch{return false;}
    }).sort((a,b)=>breakerOrder(a.assignment,b.assignment))||[];
    return `<option value="">Select 240 V feeder</option>`+choices.map(c=>`<option value="${c.id}"${c.id===selectedId?" selected":""}>${escapeHTML(c.assignment)} · ${escapeHTML(c.name||"Unnamed circuit")} · ${c.amps} A</option>`).join("");
  }
  function assignments() {
    const out = [];
    for (let n = 1; n <= state.spaces; n++) if (owner(n) === n) for (const key of keysAt(n)) out.push(key);
    return out;
  }
  function circuitAt(key) { return state.circuits.find(c => c.assignment === key); }
  function pointsFor(id) { return state.points.filter(p => p.circuitId === id); }
  function circuitFor(id) { return state.circuits.find(c => c.id === id); }
  function isCompatible(voltage,assignment) { return !assignment || (voltage === 240) === assignment.includes("/"); }
  function danger(c) { return Boolean(c.gauge && Number.isFinite(c.amps) && c.amps > GAUGES[c.gauge]); }
  function save() {
    queueHomeSave(home()?.id);
  }
  function queueHomeSave(homeId) {
    const h=workbook.homes.find(item=>item.id===homeId);
    if(!h || h.role==="viewer" || saveBlocked || homeSnapshot(h)===savedHomes.get(h.id))return;
    el("saveStatus").textContent="Saving to data folder…";
    saveQueue=saveQueue.then(async()=>{
      const latest=workbook.homes.find(item=>item.id===h.id);
      if(!latest || latest.role==="viewer")return;
      const snapshot=homeSnapshot(latest);
      if(snapshot===savedHomes.get(h.id))return;
      const response=await api(`/api/homes/${h.id}`,"PUT",{name:latest.name,panels:latest.panels,revision:latest.revision});
      latest.revision=response.revision;
      savedHomes.set(h.id,snapshot);
      el("saveStatus").textContent="Saved in data folder";
      if(homeSnapshot(latest)!==snapshot)queueHomeSave(latest.id);
    }).catch(error=>{
      el("saveStatus").textContent="Not saved · export a backup";
      if(error.status===409)saveBlocked=true;
      notify(error.message);
    });
  }
  function notify(message, ok = false) {
    const node = el("message"); node.textContent = message; node.classList.toggle("ok", ok);
    clearTimeout(messageTimer); messageTimer = setTimeout(() => { node.textContent = ""; }, 7000);
  }
  function assertPanel(data) {
    if (!data || !Number.isInteger(data.spaces) || data.spaces < 12 || data.spaces > 42 || data.spaces % 2 || typeof data.name !== "string" || !data.types || Array.isArray(data.types) || typeof data.types !== "object" || !Array.isArray(data.circuits) || !Number.isSafeInteger(data.nextCircuitId) || data.nextCircuitId < 1) throw Error("Invalid panel format.");
    if (data.name.length > 80 || data.circuits.length > 84) throw Error("Panel data exceeds the supported size.");
    const occupied = new Set();
    const types = {};
    for (const [raw, type] of Object.entries(data.types)) {
      const n = Number(raw);
      if (!/^[1-9]\d*$/.test(raw) || !isPosition(n,data.spaces) || !["single","double","tandem","quad"].includes(type)) throw Error("Invalid breaker type or position.");
      if (spansTwo(type)) {
        if (n + 2 > data.spaces || occupied.has(n) || occupied.has(n + 2)) throw Error("Overlapping or out-of-range two-space breaker.");
        occupied.add(n); occupied.add(n + 2);
      }
      types[n] = type;
    }
    for (const n of occupied) if (types[n] && n > 2 && spansTwo(types[n - 2])) throw Error("A covered position has its own breaker type.");
    const allowed = new Set();
    for (let n = 1; n <= data.spaces; n++) {
      if (occupied.has(n) && n > 2 && spansTwo(types[n - 2])) continue;
      const type = types[n] || "single";
      for (const key of (type === "tandem" ? [`${n}a`,`${n}b`] : type === "quad" ? [`${n}a`,`${n}b/${n+2}a`,`${n+2}b`] : [type === "double" ? `${n}/${n + 2}` : String(n)])) allowed.add(key);
    }
    const usedIds = new Set(), usedAssignments = new Set();
    const circuits = data.circuits.map(c => {
      if (!c || !Number.isSafeInteger(c.id) || c.id < 1 || c.id >= data.nextCircuitId || usedIds.has(c.id) || typeof c.name !== "string" || c.name.length > 100 || ![120,240].includes(c.voltage) || !["circuits","points"].includes(c.labelMode) || typeof c.assignment !== "string" || (c.assignment && (!allowed.has(c.assignment) || usedAssignments.has(c.assignment))) || !isCompatible(c.voltage,c.assignment) || !(c.amps === null || (Number.isInteger(c.amps) && c.amps > 0 && c.amps <= 400)) || typeof c.gauge !== "string" || (c.gauge && !(c.gauge in GAUGES))) throw Error("Invalid, conflicting, or incompatible circuit record.");
      usedIds.add(c.id); if (c.assignment) usedAssignments.add(c.assignment);
      return {id:c.id,name:c.name,assignment:c.assignment,voltage:c.voltage,amps:c.amps,gauge:c.gauge,labelMode:c.labelMode};
    });
    if (!Array.isArray(data.points) || data.points.length > 1000 || !Number.isSafeInteger(data.nextPointId) || data.nextPointId < 1) throw Error("Invalid point data.");
    const ids=new Set();
    const points=data.points.map(p=>{
      if (!p || !Number.isSafeInteger(p.id) || p.id < 1 || p.id >= data.nextPointId || ids.has(p.id) || typeof p.name !== "string" || p.name.length > 160 || typeof p.location !== "string" || p.location.length > 500 || !(p.circuitId === null || Number.isSafeInteger(p.circuitId) && usedIds.has(p.circuitId))) throw Error("Invalid or duplicate point of consumption.");
      ids.add(p.id);
      return {id:p.id,circuitId:p.circuitId,name:p.name,location:p.location};
    });
    return {name:data.name,spaces:data.spaces,types,circuits,nextCircuitId:data.nextCircuitId,points,nextPointId:data.nextPointId};
  }
  function assertImport(data) {
    if (!data || data.version!==4 || !Array.isArray(data.homes) || !data.homes.length || data.homes.length>100 || !Number.isSafeInteger(data.nextHomeId) || !Number.isSafeInteger(data.nextPanelId)) throw Error("Invalid file or unsupported version (requires version 4).");
    const homeIds=new Set(),panelIds=new Set();
    const homes=data.homes.map(h=>{
      if(!h || !Number.isSafeInteger(h.id) || h.id<1 || h.id>=data.nextHomeId || homeIds.has(h.id) || typeof h.name!=="string" || h.name.length>80 || !Array.isArray(h.panels) || !h.panels.length || h.panels.length>100) throw Error("Invalid home data.");
      homeIds.add(h.id);
      const panels=h.panels.map(p=>{
        if(!p || !Number.isSafeInteger(p.id) || p.id<1 || p.id>=data.nextPanelId || panelIds.has(p.id) || !["main","sub"].includes(p.kind) || !(p.parentPanelId===null || Number.isSafeInteger(p.parentPanelId)) || !(p.parentCircuitId===null || Number.isSafeInteger(p.parentCircuitId))) throw Error("Invalid panel link.");
        panelIds.add(p.id);
        return {id:p.id,kind:p.kind,parentPanelId:p.parentPanelId,parentCircuitId:p.parentCircuitId,...assertPanel(p)};
      });
      const byId=new Map(panels.map(p=>[p.id,p]));
      if(!panels.some(p=>p.kind==="main")) throw Error("Each home requires a main panel.");
      for(const p of panels){
        if(p.kind==="main" && (p.parentPanelId!==null || p.parentCircuitId!==null)) throw Error("A main panel cannot have a feeder.");
        if(p.kind==="sub"){
          const parent=byId.get(p.parentPanelId);
          if(!parent || parent.id===p.id || (p.parentCircuitId!==null && !parent.circuits.some(c=>c.id===p.parentCircuitId && c.assignment))) throw Error("Invalid subpanel feeder.");
          const seen=new Set([p.id]); let cursor=parent;
          while(cursor){if(seen.has(cursor.id)) throw Error("Circular panel link.");seen.add(cursor.id);cursor=byId.get(cursor.parentPanelId);}
        }
      }
      return {id:h.id,name:h.name,panels};
    });
    if(!homeIds.has(data.selectedHomeId) || !homes.find(h=>h.id===data.selectedHomeId).panels.some(p=>p.id===data.selectedPanelId)) throw Error("Invalid selected panel.");
    return {version:4,homes,nextHomeId:data.nextHomeId,nextPanelId:data.nextPanelId,selectedHomeId:data.selectedHomeId,selectedPanelId:data.selectedPanelId};
  }
  function load() {
    try {
      const raw=localStorage.getItem(SORT_KEY);
      if (raw) {
        const stored=JSON.parse(raw);
        if (["circuits","points"].every(table=>stored?.[table] && SORT_FIELDS[table].includes(stored[table].key) && [1,-1].includes(stored[table].dir))) sorts=stored;
      }
    } catch { /* Keep the default order if a stored preference is damaged. */ }
  }
  function totals() {
    const result = {A:0,B:0};
    for (const c of state.circuits) {
      if (!c.assignment || !c.amps) continue;
      const n = Number.parseInt(c.assignment,10);
      if (c.assignment.includes("/")) { result.A += c.amps; result.B += c.amps; }
      else result[leg(n)] += c.amps;
    }
    return result;
  }
  function renderTotals() {
    const t = totals(), diff = Math.abs(t.A-t.B), max = Math.max(t.A,t.B), balanced = diff <= max * .1;
    el("phaseA").textContent = `${t.A} A`; el("phaseB").textContent = `${t.B} A`; el("phaseDifference").textContent = `${diff} A`;
    const badge = el("balanceBadge"); badge.textContent = balanced ? "Balanced" : "Unbalanced"; badge.className = `badge ${balanced ? "balanced" : "unbalanced"}`;
    el("balanceDetail").textContent = max ? `Within 10% of the larger total: ${balanced ? "yes" : "no"}` : "No assigned ratings yet";
  }
  function breakerNumber(key) { return key ? Number.parseInt(key,10) : Infinity; }
  function breakerOrder(a,b) {
    const n=breakerNumber(a)-breakerNumber(b);
    if (Number.isFinite(n) && n) return n;
    if (!a || !b) return a ? -1 : b ? 1 : 0;
    return a.localeCompare(b,undefined,{numeric:true});
  }
  function compareValues(a,b) {
    if (a === null || a === "" || a === undefined) return b === null || b === "" || b === undefined ? 0 : 1;
    if (b === null || b === "" || b === undefined) return -1;
    return typeof a === "number" && typeof b === "number" ? a-b : String(a).localeCompare(String(b),undefined,{numeric:true,sensitivity:"base"});
  }
  function sortedRows(table) {
    const {key,dir}=sorts[table];
    const items=(table === "circuits" ? state.circuits : state.points).slice();
    const breakerKey=item => table === "circuits" ? item.assignment : circuitFor(item.circuitId)?.assignment || "";
    return items.sort((a,b)=>{
      const primary=key === "assignment" || key === "circuitId" ? breakerOrder(breakerKey(a),breakerKey(b)) : compareValues(a[key],b[key]);
      return primary*dir || a.id-b.id;
    });
  }
  function searchFields(table,item) {
    if(table==="circuits")return {
      assignment:item.assignment||"Unassigned",name:item.name||"",voltage:`${item.voltage} V`,
      amps:item.amps==null?"":`${item.amps} A`,gauge:item.gauge?`${item.gauge} AWG`:"",
      labelMode:item.labelMode==="points"?"Outlet / switch names":"Circuit name"
    };
    const circuit=circuitFor(item.circuitId);
    return {circuitId:circuit?`${circuit.assignment||"Unassigned"} · ${circuit.name||"Unnamed circuit"}`:"Unassigned",
      name:item.name||"",location:item.location||"",id:String(item.id)};
  }
  function applyTableSearch(table) {
    const prefix=table==="circuits"?"circuit":"point";
    const query=el(`${prefix}Search`).value.trim().toLocaleLowerCase();
    const column=el(`${prefix}SearchColumn`).value;
    const items=table==="circuits"?state.circuits:state.points;
    const byId=new Map(items.map(item=>[item.id,item]));
    let visible=0;
    for(const row of el(table==="circuits"?"circuitRows":"pointRows").rows){
      const item=byId.get(Number(table==="circuits"?row.dataset.circuitId:row.dataset.pointId));
      const fields=searchFields(table,item);
      const value=column==="all"?Object.values(fields).join(" "):fields[column]??"";
      row.hidden=!!query&&!String(value).toLocaleLowerCase().includes(query);
      if(!row.hidden)visible++;
    }
    const status=el(`${prefix}SearchStatus`);
    status.hidden=!query||!items.length;
    if(!status.hidden)status.textContent=visible?`Showing ${visible} of ${items.length} ${table==="circuits"?"circuits":"outlets / switches"}.`:`No ${table==="circuits"?"circuits":"outlets / switches"} match your search.`;
  }
  function renderSortHeaders() {
    for (const [name,id] of [["circuits","circuitTable"],["points","pointTable"]]) {
      for (const button of el(id).querySelectorAll("[data-sort-key]")) {
        const active=sorts[name].key === button.dataset.sortKey;
        button.dataset.direction=active ? (sorts[name].dir === 1 ? "asc" : "desc") : "";
        button.closest("th").setAttribute("aria-sort",active ? (sorts[name].dir === 1 ? "ascending" : "descending") : "none");
      }
    }
  }
  function changeSort(table,key) {
    if (!SORT_FIELDS[table]?.includes(key)) return;
    sorts[table].dir=sorts[table].key === key ? -sorts[table].dir : 1;
    sorts[table].key=key;
    if (table === "circuits") renderRows(); else renderPointRows();
    renderSortHeaders();applyRole();
    try { localStorage.setItem(SORT_KEY,JSON.stringify(sorts)); }
    catch { el("saveStatus").textContent="Storage unavailable · export a backup"; }
  }
  function formatName(c) {
    if (!c) return `<span class="slot-placeholder">Unassigned</span>`;
    if (c.labelMode === "points") {
      const points=pointsFor(c.id);
      return `<span class="circuit-name point-label">${points.length ? points.map(p=>`<span>${escapeHTML(p.name || "Unnamed point")}</span>`).join("") : `<span class="slot-placeholder">No points linked</span>`}</span>`;
    }
    return `<span class="circuit-name">${escapeHTML(c.name || "Unnamed circuit")}</span>`;
  }
  function slotHTML(n) {
    const type = kind(n), key = designation(n), c = circuitAt(key);
    if (type === "tandem") return `<div class="leg-tag">${leg(n)}</div>${["a","b"].map(s => { const item = circuitAt(`${n}${s}`); return `<div class="half"><span class="num">${n}${s}</span><span class="slot-body">${formatName(item)}</span></div>`; }).join("")}`;
    if (type === "quad") return keysAt(n).map((part,i)=>`<div class="quad-part${i===1?" quad-middle":""}"><span class="num">${escapeHTML(part)}</span><span class="slot-body">${formatName(circuitAt(part))}</span></div>`).join("");
    return `<div class="leg-tag">${type === "double" ? "A+B" : leg(n)}</div><span class="num">${escapeHTML(key)}</span><span class="slot-body">${formatName(c)}${c && c.amps ? `<span class="slot-meta">${c.amps} A${c.gauge ? ` · ${escapeHTML(c.gauge)} AWG` : ""}</span>` : ""}</span>`;
  }
  function renderPanel() {
    const grid = el("panelGrid"); grid.innerHTML = "";
    for (let row = 0; row < state.spaces / 2; row++) for (let col = 0; col < 2; col++) {
      const n = 2*row + col + 1;
      if (owner(n) !== n) continue;
      const type = kind(n), occupiedKeys = keysAt(n), warning = occupiedKeys.some(key => { const c = circuitAt(key); return c && danger(c); });
      const button = document.createElement("button"); button.type = "button"; button.className = `slot ${type}${selected === n ? " selected" : ""}${warning ? " warning" : ""}`;
      button.style.gridColumn = String(col + 1); button.style.gridRow = `${row + 1} / span ${spansTwo(type) ? 2 : 1}`;
      button.dataset.position = String(n); button.setAttribute("aria-label", `Position ${designation(n)}; ${type} breaker; ${occupiedKeys.map(key => { const c=circuitAt(key); return c ? (c.labelMode === "points" ? pointsFor(c.id).map(p=>p.name).join(", ") || "no points linked" : c.name || "unnamed circuit") : "unassigned"; }).join(", ")}`);
      button.innerHTML = slotHTML(n); grid.append(button);
    }
    el("panelCaption").textContent = state.name.trim().toUpperCase() || "UNTITLED PANEL";
    el("panelCapacity").textContent = `${state.spaces} SPACES`;
    renderInspector();
  }
  function renderInspector() {
    selected = owner(Math.min(selected,state.spaces));
    const type = kind(selected), keys = keysAt(selected);
    el("selectionTitle").textContent = `Position ${designation(selected)}`;
    el("selectionHint").textContent = `${selected % 2 ? "Left" : "Right"} column · ${spansTwo(type) ? "both legs" : `leg ${leg(selected)}`}`;
    el("breakerType").value = type;
    el("selectionInfo").textContent = keys.map(key => `${key}: ${circuitAt(key)?.name || "unassigned"}`).join(" · ");
    const linked=home().panels.filter(p=>p.parentPanelId===state.id && keys.some(key=>circuitAt(key)?.id===p.parentCircuitId));
    el("linkedPanels").innerHTML=linked.length ? `<strong>Subpanels fed here</strong>${linked.map(p=>`<button type="button" data-open-panel="${p.id}">${escapeHTML(p.name||"Untitled subpanel")} →</button>`).join("")}` : "";
  }
  function renderNavigation() {
    const current=home(),select=el("homeSelect");
    select.innerHTML=workbook.homes.map(h=>`<option value="${h.id}"${h.id===current.id?" selected":""}>${escapeHTML(h.name||"Untitled home")}</option>`).join("");
    el("removeHomeBtn").textContent=current.role==="owner"?"Delete home":"Leave home";
    const nav=el("panelNav");nav.innerHTML="";
    function leafCount(panel){const children=current.panels.filter(p=>p.parentPanelId===panel.id);return children.length?children.reduce((total,child)=>total+leafCount(child),0):1;}
    function treeWidth(panel){const leaves=leafCount(panel);return leaves*200+(leaves-1)*12;}
    function appendPanel(p,container){
      const tree=document.createElement("div");tree.className="panel-tree";
      tree.style.width=`${treeWidth(p)}px`;
      const button=document.createElement("button");button.type="button";button.className=`panel-nav-item${p.id===state.id?" active":""}`;
      button.dataset.openPanel=String(p.id);
      const source=p.kind==="sub"?current.panels.find(x=>x.id===p.parentPanelId):null;
      const feeder=source?.circuits.find(c=>c.id===p.parentCircuitId);
      let feedValid=false;
      if(p.kind==="sub")try{validateFeeder(p.parentPanelId,p.parentCircuitId,p.id,p.circuits);feedValid=true;}catch{}
      button.innerHTML=`<span>${p.kind==="sub"?"↳ ":"▣ "}${escapeHTML(p.name||"Untitled panel")}</span><small>${p.kind==="main"?"Main panel":`Subpanel · ${feedValid?`fed by ${escapeHTML(feeder.assignment)}`:"feeder required"}`}</small>`;
      tree.append(button);
      const children=current.panels.filter(x=>x.parentPanelId===p.id);
      if(children.length){const branches=document.createElement("div");branches.className="panel-branches";branches.style.setProperty("--first-width",`${treeWidth(children[0])}px`);branches.style.setProperty("--last-width",`${treeWidth(children.at(-1))}px`);for(const child of children)appendPanel(child,branches);tree.append(branches);}
      container.append(tree);
    }
    for(const p of current.panels.filter(p=>p.kind==="main")) appendPanel(p,nav);
    const row=el("feedRow");row.hidden=state.kind!=="sub";
    if(state.kind==="sub"){
      const blocked=descendants(state.id);
      el("parentPanelSelect").innerHTML=current.panels.filter(p=>!blocked.has(p.id)).map(p=>`<option value="${p.id}"${p.id===state.parentPanelId?" selected":""}>${escapeHTML(p.name||"Untitled panel")}</option>`).join("");
      const parent=panelById(state.parentPanelId);
      el("feederCircuitSelect").innerHTML=feederOptions(parent?.id,state.parentCircuitId,state.id,state.circuits);
      try{validateFeeder(state.parentPanelId,state.parentCircuitId,state.id,state.circuits);el("feederStatus").textContent="";}
      catch(error){el("feederStatus").textContent=error.message;}
    }
  }
  function renderRows() {
    const body = el("circuitRows"); body.innerHTML = "";
    const keys = assignments(); const used = new Set(state.circuits.map(c => c.assignment).filter(Boolean));
    for (const c of sortedRows("circuits")) {
      const tr = document.createElement("tr"); tr.dataset.circuitId = c.id; tr.className = danger(c) ? "row-warning" : "";
      const options = [`<option value="">Unassigned</option>`,...keys.filter(k => isCompatible(c.voltage,k) && (k === c.assignment || !used.has(k))).map(k => `<option value="${escapeHTML(k)}"${k === c.assignment ? " selected" : ""}>${escapeHTML(k)}</option>`)].join("");
      const gaugeOptions = [`<option value="">—</option>`,...Object.keys(GAUGES).map(g => `<option value="${g}"${g === c.gauge ? " selected" : ""}>${g} AWG</option>`)].join("");
      tr.innerHTML = `<td class="assignment-cell"><select data-field="assignment" aria-label="Breaker for ${escapeHTML(c.name || "circuit")}" title="${c.voltage} V positions only">${options}</select></td><td class="name-cell"><input data-field="name" aria-label="Friendly name for breaker ${escapeHTML(c.assignment || "unassigned")}" maxlength="100" placeholder="Kitchen lights" value="${escapeHTML(c.name)}"></td><td class="voltage-cell"><select data-field="voltage" aria-label="Voltage for ${escapeHTML(c.name || "circuit")}"><option value="120"${c.voltage === 120 ? " selected" : ""}>120 V</option><option value="240"${c.voltage === 240 ? " selected" : ""}>240 V</option></select></td><td class="amps-cell"><input data-field="amps" aria-label="Amps for ${escapeHTML(c.name || "circuit")}" type="number" min="1" max="400" step="1" placeholder="A" value="${c.amps ?? ""}"></td><td class="gauge-cell"><select data-field="gauge" aria-label="Wire gauge for ${escapeHTML(c.name || "circuit")}">${gaugeOptions}</select><div class="wire-warning">${danger(c) ? "Undersized wire" : ""}</div></td><td class="label-cell"><select data-field="labelMode" aria-label="Breaker label for ${escapeHTML(c.name || "circuit")}"><option value="circuits"${c.labelMode === "circuits" ? " selected" : ""}>Circuit name</option><option value="points"${c.labelMode === "points" ? " selected" : ""}>Outlet / switch names</option></select></td><td><button class="delete-btn" type="button" data-delete="${c.id}" aria-label="Delete circuit at ${escapeHTML(c.assignment || "unassigned")}" title="Delete circuit">×</button></td>`;
      body.append(tr);
    }
    el("emptyCircuits").hidden = state.circuits.length > 0;
    el("circuitCount").textContent = String(state.circuits.length);
    applyTableSearch("circuits");
  }
  function renderPointRows() {
    const body=el("pointRows"); body.innerHTML="";
    for (const p of sortedRows("points")) {
      const tr=document.createElement("tr"); tr.dataset.pointId=String(p.id);
      const options=[`<option value="">Unassigned</option>`,...state.circuits.slice().sort((a,b)=>breakerOrder(a.assignment,b.assignment)).map(c=>`<option value="${c.id}"${p.circuitId === c.id ? " selected" : ""}>${escapeHTML(c.assignment || "Unassigned")} · ${escapeHTML(c.name || "Unnamed circuit")}</option>`)].join("");
      tr.innerHTML=`<td class="point-circuit-cell"><select data-point-field="circuitId" aria-label="Circuit for point ${p.id}">${options}</select></td><td class="name-cell"><input data-point-field="name" aria-label="Point name ${p.id}" maxlength="160" placeholder="Guest room outlet" value="${escapeHTML(p.name)}"></td><td class="point-location-cell"><textarea data-point-field="location" aria-label="Location for point ${p.id}" maxlength="500" placeholder="Wall or room details">${escapeHTML(p.location)}</textarea></td><td class="serial-cell"><span>${p.id}</span></td><td><button class="delete-btn" type="button" data-delete-point="${p.id}" aria-label="Delete point ${p.id}" title="Delete point">×</button></td>`;
      body.append(tr);
    }
    el("emptyPoints").hidden=state.points.length>0;
    el("pointCount").textContent=String(state.points.length);
    applyTableSearch("points");
  }
  function renderAll() {
    el("panelName").value = state.name; el("spaceCount").value = String(state.spaces);
    el("convertPanelBtn").textContent=state.kind==="main"?"Make subpanel":"Make main panel";
    renderNavigation();renderPanel(); renderTotals(); renderRows(); renderPointRows(); renderSortHeaders(); applyRole(); save();
  }
  function applyRole() {
    const role=home().role,readonly=role==="viewer";
    document.body.dataset.role=role;
    el("shareHomeBtn").hidden=role!=="owner" || currentUser?.isLocal;
    el("importBtn").disabled=readonly;
    for(const id of ["renameHomeBtn","addMainBtn","addSubBtn","convertPanelBtn","deletePanelBtn","addCircuitBtn","addPointBtn","panelName","spaceCount","breakerType","parentPanelSelect","feederCircuitSelect"])
      el(id).disabled=readonly;
    for(const field of document.querySelectorAll("#circuitRows input,#circuitRows select,#circuitRows button,#pointRows input,#pointRows select,#pointRows textarea,#pointRows button"))field.disabled=readonly;
  }
  function convert(n,type) {
    const current = kind(n); if (current === type) return;
    if (spansTwo(type) && !spansTwo(current)) {
      const below = nextInColumn(n);
      if (below > state.spaces) { notify("A two-space breaker needs a free position below in the same column."); el("breakerType").value=current; return; }
      if (owner(below) !== below || kind(below) !== "single" || circuitAt(String(below))) { notify(`Position ${below} must be an unused single space before placing a two-space breaker.`); el("breakerType").value=current; return; }
    }
    const oldKeys=keysAt(n,current);
    const oldKey=current==="quad" ? (type==="double" ? oldKeys[1] : oldKeys[0]) : oldKeys[0];
    for(const key of oldKeys) if(key!==oldKey && circuitAt(key)) { notify(`Move the circuit at ${key} before changing this breaker type.`);el("breakerType").value=current;return; }
    const existing = circuitAt(oldKey);
    const newKey=type==="quad" ? (current==="double" ? `${n}b/${n+2}a` : `${n}a`) : type==="tandem" ? `${n}a` : designation(n,type);
    if (existing && !isCompatible(existing.voltage,newKey)) {
      notify(`Move the ${existing.voltage} V circuit off position ${oldKey} before changing its breaker type.`);el("breakerType").value=current;return;
    }
    if (existing) existing.assignment=newKey;
    if (type === "single") delete state.types[n]; else state.types[n] = type;
    renderAll(); notify(`Position ${n} is now ${type.replace("double","double-pole")}.`,true);
  }
  function setSpaces(spaces) {
    if (spaces < state.spaces) {
      const beyond = state.circuits.some(c => c.assignment && (Number.parseInt(c.assignment,10) > spaces || (c.assignment.includes("/") && Number(c.assignment.split("/")[1]) > spaces)));
      if (beyond) { el("spaceCount").value = String(state.spaces); notify("Move circuits outside the new panel size before removing those spaces."); return; }
      for (let n=1;n<=spaces;n++) if (spansTwo(kind(n)) && n+2>spaces) { el("spaceCount").value=String(state.spaces); notify(`Convert the two-space breaker at ${n} before shrinking the panel.`); return; }
      for (const key of Object.keys(state.types)) if (Number(key)>spaces) delete state.types[key];
    }
    state.spaces=spaces; selected=Math.min(selected,spaces); renderAll();
  }
  function addCircuit() {
    el("circuitSearch").value="";
    const id=state.nextCircuitId++;
    state.circuits.push({id,name:"",assignment:"",voltage:120,amps:null,gauge:"",labelMode:"circuits"});
    renderAll(); el("circuitRows").querySelector(`[data-circuit-id="${id}"] [data-field="name"]`)?.focus();
  }
  function addPoint() {
    el("pointSearch").value="";
    const id=state.nextPointId++;
    state.points.push({id,circuitId:null,name:"",location:""});
    renderAll(); el("pointRows").querySelector(`[data-point-id="${id}"] [data-point-field="name"]`)?.focus();
  }
  function updateWarning(row,c) {
    row.classList.toggle("row-warning",danger(c)); row.querySelector(".wire-warning").textContent = danger(c) ? "Undersized wire" : "";
  }
  function updateCircuit(target,commit) {
    const row=target.closest("tr"); if (!row) return;
    const c=circuitFor(Number(row.dataset.circuitId)),field=target.dataset.field;
    if (!c || !field) return;
    const children=feederChildren(state.id,c.id);
    if (field==="amps") {
      const value=target.value.trim();
      if (value && (!/^\d+$/.test(value) || Number(value)<1 || Number(value)>400)) { target.setCustomValidity("Enter a whole number from 1 to 400."); target.reportValidity(); return; }
      const next=value?Number(value):null;
      const tooLarge=state.kind==="sub" && state.parentCircuitId && (()=>{const feeder=panelById(state.parentPanelId)?.circuits.find(item=>item.id===state.parentCircuitId);return feeder?.voltage===240 && feeder?.amps && next>feeder.amps ? feeder.amps : null;})();
      const childLimit=children.length && (!next || children.some(child=>child.circuits.some(item=>item.amps && item.amps>next)));
      if(tooLarge||childLimit){const message=tooLarge?`This subpanel’s feeder is rated ${tooLarge} A.`:"A linked subpanel has a circuit above that feeder rating. Change its circuits first.";target.setCustomValidity(message);if(commit){target.reportValidity();notify(message);renderRows();}return;}
      target.setCustomValidity(""); c.amps=value ? Number(value) : null;
    } else if (field==="voltage") {
      if(children.length && Number(target.value)!==240){notify("A circuit feeding a subpanel must stay 240 V. Reassign the subpanel first.");renderRows();return;}
      c.voltage=Number(target.value);
      if (!isCompatible(c.voltage,c.assignment)) { c.assignment=""; notify(`Circuit unassigned: ${c.voltage} V requires a ${c.voltage === 240 ? "double-pole or quad center" : "single-pole, tandem, or quad outer"} position.`); }
    } else if (field==="assignment") {
      if(children.length && !target.value){notify("Choose another 240 V breaker for this feeder before unassigning it.");renderRows();return;}
      if (!isCompatible(c.voltage,target.value)) { notify("Breaker and voltage do not match."); renderRows(); return; }
      c.assignment=target.value;
    } else c[field]=target.value;
    if(!c.assignment) for(const child of feederChildren(state.id,c.id)) child.parentCircuitId=null;
    save(); updateWarning(row,c); renderPanel(); renderTotals();
    if(field==="name" || field==="assignment" || field==="voltage" || field==="amps") renderNavigation();
    if (field==="name" || field==="assignment" || field==="voltage") renderPointRows();
    if (commit && (field==="assignment" || field==="voltage" || sorts.circuits.key===field)) renderRows();
    if(commit)applyTableSearch("circuits");
  }
  function updatePoint(target,commit) {
    const row=target.closest("tr"); if (!row) return;
    const p=state.points.find(item=>item.id===Number(row.dataset.pointId)),field=target.dataset.pointField;
    if (!p || !field) return;
    if (field==="circuitId") p.circuitId=target.value ? Number(target.value) : null;
    else p[field]=target.value;
    save(); renderPanel();
    if (commit && (field==="circuitId" || sorts.points.key===field)) renderPointRows();
    if(commit)applyTableSearch("points");
  }
  function printSlot(n) {
    const type=kind(n);
    if (type==="tandem") return `<td class="paper-num${n%2===0?" paper-right":""}"><div>${n}a</div><div>${n}b</div></td><td class="paper-description"><div>${printCircuit(circuitAt(`${n}a`))}</div><div>${printCircuit(circuitAt(`${n}b`))}</div></td>`;
    if (type==="quad") return `<td class="paper-num paper-quad-cell${n%2===0?" paper-right":""}" rowspan="2"><div class="paper-quad">${keysAt(n).map(key=>`<div>${escapeHTML(key)}</div>`).join("")}</div></td><td class="paper-description paper-quad-cell" rowspan="2"><div class="paper-quad">${keysAt(n).map(key=>`<div>${printCircuit(circuitAt(key))}</div>`).join("")}</div></td>`;
    const label=designation(n),c=circuitAt(label);
    const span=type==="double" ? ' rowspan="2"' : "";
    return `<td class="paper-num${n%2===0?" paper-right":""}"${span}>${label}</td><td class="paper-description"${span}>${printCircuit(c)}</td>`;
  }
  function printCircuit(c) {
    if (!c) return "—";
    const points=pointsFor(c.id);
    return c.labelMode === "points" ? (points.length ? points.map(p=>escapeHTML(p.name || "Unnamed point")).join(" · ") : "No points linked") : escapeHTML(c.name || "Unnamed circuit");
  }
  function printPanels(scope) {
    if(scope==="panel") return [state];
    const list=[];
    function visit(panel){list.push(panel);for(const child of home().panels.filter(p=>p.parentPanelId===panel.id))visit(child);}
    if(scope==="branch") visit(state);
    else for(const panel of home().panels.filter(p=>p.kind==="main"))visit(panel);
    return list;
  }
  function printHead(table,key,label) {
    const active=sorts[table].key===key;
    return `<th${active?` aria-sort="${sorts[table].dir===1?"ascending":"descending"}"`:""}>${label}${active?` <span class="print-sort-arrow">${sorts[table].dir===1?"▲":"▼"}</span>`:""}</th>`;
  }
  function printSortNote(table) {
    const labels=table==="circuits"?{assignment:"Breaker",name:"Friendly name",voltage:"Voltage",amps:"Amps",gauge:"Wire",labelMode:"Breaker label"}:{circuitId:"Circuit",name:"Friendly name",location:"Location / description",id:"No."};
    return `<span class="print-sort-note">Sorted by ${labels[sorts[table].key]} ${sorts[table].dir===1?"▲":"▼"}</span>`;
  }
  function printPanel(panel) {
    const previous=state;state=panel;
    try {
      let grid="";
      for(let r=0;r<state.spaces/2;r++) { grid+="<tr>"; for(let col=0;col<2;col++){const n=r*2+col+1;if(owner(n)===n) grid+=printSlot(n);} grid+="</tr>"; }
      const records=sortedRows("circuits").map(c=>`<tr><td>${escapeHTML(c.assignment||"—")}</td><td>${escapeHTML(c.name||"—")}</td><td>${c.voltage} V</td><td>${c.amps??"—"} A</td><td class="${danger(c)?"print-warning":""}">${escapeHTML(c.gauge||"—")} AWG</td></tr>`).join("");
      const pointRecords=sortedRows("points").map(p=>`<tr><td>${escapeHTML(circuitFor(p.circuitId)?.assignment||"—")}</td><td>${escapeHTML(p.name||"—")}</td><td>${escapeHTML(p.location||"—")}</td><td>${p.id}</td></tr>`).join("");
      const circuitHeads=[["assignment","Breaker"],["name","Friendly name"],["voltage","Voltage"],["amps","Amps"],["gauge","Wire"]].map(([key,label])=>printHead("circuits",key,label)).join("");
      const pointHeads=[["circuitId","Circuit"],["name","Friendly name"],["location","Location / description"],["id","No."]].map(([key,label])=>printHead("points",key,label)).join("");
      const feeder=panel.kind==="sub"?home().panels.find(p=>p.id===panel.parentPanelId):null;
      const feederCircuit=feeder?.circuits.find(c=>c.id===panel.parentCircuitId);
      let feedValid=false;
      if(feeder)try{validateFeeder(feeder.id,panel.parentCircuitId,panel.id,panel.circuits);feedValid=true;}catch{}
      const source=feeder?`<div class="paper-source${feedValid?"":" print-warning"}">${feedValid?"Fed from":"Feeder needs correction · source"} ${escapeHTML(feeder.name||"Untitled panel")}${feedValid?` · breaker ${escapeHTML(feederCircuit.assignment)}`:""}</div>`:"";
      return `<article class="print-panel${state.spaces>32?" compact":""}"><div class="paper-sheet"><div class="paper-title"><div><span class="paper-kicker">ELECTRICAL PANEL · ${escapeHTML(home().name)}</span><h1>${escapeHTML(state.name||"Untitled panel")}</h1>${source}</div><div class="paper-title-meta">DIRECTORY<br>${state.spaces} SPACES<br>${new Date().toLocaleDateString()}</div></div><table class="paper-panel"><colgroup><col class="paper-no-col"><col><col class="paper-no-col"><col></colgroup><thead><tr><th>No.</th><th>Circuit / destination</th><th>No.</th><th>Circuit / destination</th></tr></thead><tbody>${grid}</tbody></table></div>${state.circuits.length||state.points.length?`<div class="paper-detail"><div class="paper-detail-header"><span>PANELBOOK · ${escapeHTML(home().name)}</span><h2>${escapeHTML(state.name||"Untitled panel")} · Breaker &amp; point details</h2></div>${state.circuits.length?`<h3>Circuits ${printSortNote("circuits")}</h3><table class="paper-index"><thead><tr>${circuitHeads}</tr></thead><tbody>${records}</tbody></table>`:""}${state.points.length?`<h3>Points of consumption ${printSortNote("points")}</h3><table class="paper-index points-index"><thead><tr>${pointHeads}</tr></thead><tbody>${pointRecords}</tbody></table>`:""}</div>`:""}</article>`;
    } finally {state=previous;}
  }
  function buildPrint(scope="panel") {el("printDirectory").innerHTML=printPanels(scope).map(printPanel).join("");}
  function print(scope) {buildPrint(scope);document.body.dataset.print="directory";window.print();}
  function openScopeDialog(mode) {
    scopeMode=mode;
    const printing=mode==="print";
    el("scopeTitle").textContent=printing?"What would you like to print?":"What would you like to export?";
    el("scopeDescription").textContent=printing?"Choose which panel directories to include.":"Choose how much of your data to save as JSON.";
    const choices=printing?[["panel","Current panel"],["branch","Current panel + subpanels"],["home","All panels in this home"]]:[["panel","Current panel"],["home","Current home"],["everything","Everything"]];
    el("scopeChoices").innerHTML=choices.map(([value,label],index)=>`<label><input type="radio" name="scopeOption" value="${value}"${index===0?" checked":""}>${label}</label>`).join("");
    el("scopeConfirmBtn").textContent=printing?"Print / PDF":"Export JSON";
    const dialog=el("scopeDialog");dialog.returnValue="";dialog.showModal();
  }
  function exportJSON(scope) {
    const payload=scope==="panel"?{version:4,scope,panel:state,homeName:home().name}:scope==="home"?{version:4,scope,home:home()}:{version:4,scope:"everything",workbook};
    const slug=value=>(value||"untitled").trim().replace(/[^a-z0-9_-]+/gi,"-").slice(0,45)||"untitled";
    const fileName=scope==="panel"?`panelbook-panel-${slug(state.name)}.json`:scope==="home"?`panelbook-home-${slug(home().name)}.json`:"panelbook-everything.json";
    const blob=new Blob([JSON.stringify(payload,null,2)],{type:"application/json"});const url=URL.createObjectURL(blob);
    const a=document.createElement("a");a.href=url;a.download=fileName;a.click();setTimeout(()=>URL.revokeObjectURL(url),30000);
  }
  function chosenFeeder(parentId,feederId,childId=null,childCircuits=[]) {
    const value=el(feederId).value;
    validateFeeder(el(parentId).value,value,childId,childCircuits);
    return Number(value);
  }
  function showConvertDialog() {
    const blocked=descendants(state.id);
    const options=home().panels.filter(p=>!blocked.has(p.id));
    if(!options.length){notify("Add another main panel before converting this one to a subpanel.");return;}
    el("convertParent").innerHTML=options.map(p=>`<option value="${p.id}">${escapeHTML(p.name||"Untitled panel")}</option>`).join("");
    el("convertParent").value=String(options.find(p=>p.kind==="main")?.id??options[0].id);
    el("convertFeeder").innerHTML=feederOptions(el("convertParent").value,null,state.id,state.circuits);
    const dialog=el("convertDialog");dialog.returnValue="";dialog.showModal();
  }
  function convertPanel() {
    if(state.kind==="sub") {state.kind="main";state.parentPanelId=null;state.parentCircuitId=null;renderAll();notify("This panel is now a main panel.",true);return;}
    showConvertDialog();
  }
  function finishConversion() {
    const parent=panelById(Number(el("convertParent").value));
    if(!parent || descendants(state.id).has(parent.id))throw Error("Choose a source panel outside this panel’s branch.");
    const feederId=chosenFeeder("convertParent","convertFeeder",state.id,state.circuits);
    state.kind="sub";state.parentPanelId=parent.id;state.parentCircuitId=feederId;
    renderAll();notify("This panel is now a subpanel.",true);
  }
  function deletePanel() {
    const doomed=descendants(state.id);
    if(state.kind==="main" && !home().panels.some(p=>p.kind==="main" && !doomed.has(p.id))){notify("Each home needs a main panel. Add another main panel before deleting this one.");return;}
    const name=state.name||"Untitled panel";
    const extra=doomed.size-1;
    if(!confirm(`Are you sure you want to delete ${name}? Its circuits and points will be deleted.${extra?` This also deletes ${extra} subpanel${extra===1?"":"s"} beneath it, with all their circuits and points.`:""} This cannot be undone; export a backup first if needed.`))return;
    const parentId=state.parentPanelId;
    home().panels=home().panels.filter(p=>!doomed.has(p.id));
    const next=home().panels.find(p=>p.id===parentId)??home().panels.find(p=>p.kind==="main");
    choosePanel(next.id);notify("Panel deleted.",true);
  }
  function updateImportFields() {
    const mode=el("panelImportChoices").querySelector('input[name="panelImportMode"]:checked')?.value;
    el("importOverwriteFields").hidden=mode!=="overwrite";
    el("importSubFields").hidden=mode!=="sub";
    el("importFeeder").required=mode==="sub";
    if(mode==="sub" && pendingPanelImport)el("importFeeder").innerHTML=feederOptions(el("importParent").value,null,null,pendingPanelImport.circuits);
    if(mode==="overwrite"){
      const target=panelById(Number(el("importTargetPanel").value));
      const children=home().panels.filter(p=>p.parentPanelId===target?.id).length;
      el("importImpact").textContent=children?`The ${children} directly linked subpanel feeder${children===1?"":"s"} will be cleared.`:"The selected panel’s circuits and points will be replaced.";
    }
  }
  function showPanelImportDialog(imported) {
    pendingPanelImport=imported;
    el("panelImportTitle").textContent=`Import ${imported.name||"Untitled panel"}`;
    el("importTargetPanel").innerHTML=home().panels.map(p=>`<option value="${p.id}">${escapeHTML(p.name||"Untitled panel")} · ${p.kind==="main"?"main":"subpanel"}</option>`).join("");
    el("importTargetPanel").value=String(state.id);
    el("importParent").innerHTML=home().panels.map(p=>`<option value="${p.id}">${escapeHTML(p.name||"Untitled panel")}</option>`).join("");
    el("importParent").value=String(state.id);
    el("importFeeder").innerHTML=feederOptions(state.id,null,null,imported.circuits);
    el("panelImportChoices").querySelector('input[value="main"]').checked=true;
    updateImportFields();
    const dialog=el("panelImportDialog");dialog.returnValue="";dialog.showModal();
  }
  function finishPanelImport() {
    const imported=pendingPanelImport;
    if(!imported)return;
    const mode=el("panelImportChoices").querySelector('input[name="panelImportMode"]:checked')?.value;
    if(mode==="overwrite"){
      const target=panelById(Number(el("importTargetPanel").value));if(!target)throw Error("Choose a panel to replace.");
      if(!confirm(`Replace ${target.name||"Untitled panel"} and all its circuits and points with ${imported.name||"Untitled panel"}? Directly linked subpanel feeders will be cleared. This cannot be undone.`))return;
      Object.assign(target,imported);
      for(const child of home().panels.filter(p=>p.parentPanelId===target.id))child.parentCircuitId=null;
      choosePanel(target.id);notify("Panel replaced. Child feeder links were cleared.",true);
    } else if(mode==="main"){
      const panel={...makePanel(allocatePanelId(),imported.name),...imported};
      home().panels.push(panel);choosePanel(panel.id);notify("Panel added as a main panel.",true);
    } else if(mode==="sub"){
      const parent=panelById(Number(el("importParent").value));if(!parent)throw Error("Choose a source panel.");
      const feeder=chosenFeeder("importParent","importFeeder",null,imported.circuits);
      const panel={...makePanel(allocatePanelId(),imported.name,"sub",parent.id),...imported,parentCircuitId:feeder};
      home().panels.push(panel);choosePanel(panel.id);notify("Panel added as a subpanel.",true);
    } else throw Error("Choose an import option.");
  }
  async function importJSON(data) {
    if(data?.scope==="panel" && data.version===4){
      showPanelImportDialog(assertPanel(data.panel));return;
    }
    if(data?.version!==4 || !["home","everything"].includes(data.scope))throw Error("Import requires a Panelbook version 4 JSON export.");
    const count=data.scope==="home"?1:data.workbook?.homes?.length;
    if(!Number.isInteger(count) || count<1 || count>100)throw Error("Invalid home export.");
    if(!confirm(`Add ${count} imported home${count===1?"":"s"} to your account? Existing homes will stay available.`))return;
    const result=await api("/api/import","POST",data);
    workbook.selectedHomeId=result.homes[0].id;workbook.selectedPanelId=result.homes[0].panels[0].id;
    await loadWorkspace();selected=1;renderAll();notify(`${count} home${count===1?"":"s"} imported.`,true);
  }
  function showAccountControls(status) {
    csrfToken=status.csrf;currentUser=status.user;currentVersion=status.version;requireSetupCode=!!status.requireSetupCode;
    el("brandSubtitle").textContent=`Residential panel directory · v${status.version}`;
    el("signedInAs").textContent=currentUser.isLocal?"Local only":currentUser.username;
    el("autoCloseControl").hidden=!currentUser.isLocal;
    el("autoCloseCheckbox").checked=!!status.autoClose;
    if(!currentUser.isLocal && localPresenceTimer){clearInterval(localPresenceTimer);localPresenceTimer=null;localTabId=null;}
    el("convertLoginBtn").hidden=!currentUser.isLocal;
    el("manageUsersBtn").hidden=!currentUser.isAdmin || currentUser.isLocal;
    el("changePasswordBtn").hidden=currentUser.isLocal;
    el("logoutBtn").hidden=currentUser.isLocal;
    el("updateActions").hidden=!status.canUpdate;
  }
  async function enterApp(status) {
    showAccountControls(status);
    load();await loadWorkspace();
    if(!appEventsWired){wireEvents();appEventsWired=true;}
    document.body.classList.remove("locked");
    renderAll();
    if(currentUser.isLocal)startLocalPresence();
  }
  async function reportLocalPresence() {
    if(!localTabId || !currentUser?.isLocal)return;
    try {
      const result=await api("/api/local/presence","POST",{tabId:localTabId,active:true});
      if(currentUser?.isLocal)el("autoCloseCheckbox").checked=result.autoClose;
    } catch { /* A later heartbeat can reconnect. */ }
  }
  function startLocalPresence() {
    if(localTabId)return;
    localTabId=crypto.randomUUID();
    reportLocalPresence();
    localPresenceTimer=setInterval(reportLocalPresence,15000);
  }
  function offerLegacyExport(message) {
    el("authTitle").textContent="Start Panelbook";
    el("authDescription").textContent=message;
    el("authUsername").parentElement.hidden=true;
    el("authPassword").parentElement.hidden=true;
    el("authSubmit").hidden=true;
    el("localOnlyBtn").hidden=true;
    el("loginChoiceLabel").hidden=true;
    try{el("legacyExportBtn").hidden=!localStorage.getItem(STORAGE_KEY);}catch{el("legacyExportBtn").hidden=true;}
  }
  async function refreshShareDialog() {
    const id=home().id;
    const [users,members]=await Promise.all([api("/api/users"),api(`/api/homes/${id}/members`)]);
    const owner=members.members.find(item=>item.role==="owner");
    el("shareTitle").textContent=`Share ${home().name}`;
    el("shareUser").innerHTML=users.users.filter(user=>user.id!==owner?.id).map(user=>`<option value="${user.id}">${escapeHTML(user.username)}</option>`).join("");
    el("shareMembers").innerHTML=members.members.map(member=>`<div><span>${escapeHTML(member.username)} · ${member.role}</span>${member.role==="owner"?"":`<button class="button" type="button" data-remove-user="${member.id}">Remove</button>`}</div>`).join("");
  }
  async function refreshUsersDialog() {
    const {users}=await api("/api/users");
    el("userList").innerHTML=users.map(user=>{
      const canManage=user.id!==currentUser.id&&!user.isSuperAdmin&&(!user.isAdmin||currentUser.isSuperAdmin);
      const role=user.isSuperAdmin?"super admin":user.isAdmin?"admin":"";
      return `<div><span>${escapeHTML(user.username)}${role?` · ${role}`:""}${user.id===currentUser.id?" · you":""}</span>${canManage?`<span>${currentUser.isSuperAdmin?`<button class="button" type="button" data-toggle-admin="${user.id}" data-admin="${user.isAdmin}">${user.isAdmin?"Remove admin":"Make admin"}</button> `:""}<button class="button" type="button" data-reset-user="${user.id}" data-name="${escapeHTML(user.username)}">Reset password</button> <button class="button danger-button" type="button" data-delete-user="${user.id}" data-name="${escapeHTML(user.username)}">Delete</button></span>`:""}</div>`;
    }).join("");
    return users;
  }
  async function refreshSetupCodes() {
    const {codes}=await api("/api/setup-codes");
    el("setupCodeList").innerHTML=codes.length?codes.map(code=>`<div><span>Code #${code.id} · ${code.unlimited?"Unlimited use":"One-time"}</span><button class="button danger-button" type="button" data-revoke-code="${code.id}">Revoke</button></div>`).join(""):"<p>No active setup codes.</p>";
  }
  function setAuthMode(mode) {
    el("authForm").dataset.setup=mode;
    el("authTitle").textContent=mode==="register"?"Create account":"Sign in";
    el("authDescription").textContent=mode==="register"?(requireSetupCode?"Enter a setup code given to you by an administrator.":"Choose a username and password to get started."):"Open your homes and panels.";
    el("authSubmit").textContent=mode==="register"?"Create account":"Sign in";
    el("authModeBtn").textContent=mode==="register"?"Back to sign in":"Create account";
    el("setupTokenField").hidden=mode!=="register"||!requireSetupCode;
    el("setupToken").required=mode==="register"&&requireSetupCode;
    el("authPassword").autocomplete=mode==="register"?"new-password":"current-password";
    el("authPassword").minLength=mode==="register"?12:0;
    el("authError").textContent="";
  }
  async function removeHome() {
    const current=home(),owner=current.role==="owner";
    const message=owner
      ? `Delete ${current.name||"this home"} and all of its panels? Everyone it is shared with loses access. This cannot be undone; export a backup first if needed.`
      : `Leave ${current.name||"this home"}? The owner can share it with you again.`;
    if(!confirm(message))return;
    try{
      await saveQueue.catch(()=>{});
      await api(owner?`/api/homes/${current.id}`:`/api/homes/${current.id}/members/${currentUser.id}`,"DELETE",{});
      await loadWorkspace();selected=1;renderAll();
      notify(owner?"Home deleted.":"You left the home.",true);
    }catch(error){notify(error.message);}
  }
  function wireAccountEvents() {
    window.addEventListener("pagehide",()=>{
      if(!localTabId || !currentUser?.isLocal)return;
      fetch("/api/local/presence",{method:"POST",credentials:"same-origin",keepalive:true,
        headers:{"Content-Type":"application/json","X-Panelbook-CSRF":csrfToken},
        body:JSON.stringify({tabId:localTabId,active:false})}).catch(()=>{});
    });
    window.addEventListener("pageshow",()=>{if(localTabId)reportLocalPresence();});
    el("autoCloseCheckbox").addEventListener("change",async()=>{
      const checkbox=el("autoCloseCheckbox"),enabled=checkbox.checked;
      checkbox.disabled=true;
      try{
        const result=await api("/api/local/auto-close","POST",{enabled});
        checkbox.checked=result.autoClose;
        notify(enabled?"Panelbook will close after all its tabs close.":"Automatic server close turned off.",true);
      }catch(error){checkbox.checked=!enabled;notify(error.message);}
      finally{checkbox.disabled=false;}
    });
    el("localOnlyBtn").addEventListener("click",async()=>{
      el("authError").textContent="";el("localOnlyBtn").disabled=true;
      try{
        await api("/api/setup/local","POST",{});
        await enterApp(await api("/api/status"));
        history.replaceState(null,"",location.pathname);
      }catch(error){el("authError").textContent=error.message;}
      finally{el("localOnlyBtn").disabled=false;}
    });
    el("authForm").addEventListener("submit",async event=>{
      event.preventDefault();el("authError").textContent="";el("authSubmit").disabled=true;
      try{
        const mode=el("authForm").dataset.setup;
        const data={username:el("authUsername").value.trim(),password:el("authPassword").value};
        if(mode==="true")data.setupToken=el("setupToken").value.trim();
        if(mode==="register"&&requireSetupCode)data.setupCode=el("setupToken").value.trim();
        await api(mode==="true"?"/api/setup":mode==="register"?"/api/register":"/api/login","POST",data);
        await enterApp(await api("/api/status"));
        history.replaceState(null,"",location.pathname);
      }catch(error){el("authError").textContent=error.message;}
      finally{el("authSubmit").disabled=false;}
    });
    el("authModeBtn").addEventListener("click",()=>setAuthMode(el("authForm").dataset.setup==="register"?"login":"register"));
    el("legacyExportBtn").addEventListener("click",()=>{
      try{
        const workbook=JSON.parse(localStorage.getItem(STORAGE_KEY));
        if(!workbook || workbook.version!==4)throw Error("No version 4 data was found in this browser.");
        const blob=new Blob([JSON.stringify({version:4,scope:"everything",workbook},null,2)],{type:"application/json"});
        const url=URL.createObjectURL(blob),link=document.createElement("a");link.href=url;link.download="panelbook-legacy-export.json";link.click();setTimeout(()=>URL.revokeObjectURL(url),30000);
      }catch(error){el("authError").textContent=error.message;}
    });
    el("logoutBtn").addEventListener("click",async()=>{try{await api("/api/logout","POST",{});location.reload();}catch(error){notify(error.message);}});
    el("changePasswordBtn").addEventListener("click",()=>{el("currentPassword").value="";el("newPassword").value="";el("passwordDialog").showModal();});
    el("convertLoginBtn").addEventListener("click",()=>{el("convertUsername").value="";el("convertPassword").value="";el("convertLoginDialog").showModal();el("convertUsername").focus();});
    el("convertLoginCancelBtn").addEventListener("click",()=>el("convertLoginDialog").close());
    el("convertLoginSaveBtn").addEventListener("click",async()=>{
      const button=el("convertLoginSaveBtn");button.disabled=true;
      try{
        await api("/api/account/convert","POST",{username:el("convertUsername").value.trim(),password:el("convertPassword").value});
        showAccountControls(await api("/api/status"));
        el("convertLoginDialog").close();renderAll();notify("Login created. Your homes and panels are unchanged.",true);
      }catch(error){alert(error.message);}
      finally{button.disabled=false;}
    });
    el("passwordCloseBtn").addEventListener("click",()=>el("passwordDialog").close());
    el("passwordSaveBtn").addEventListener("click",async()=>{try{await api("/api/account/password","POST",{currentPassword:el("currentPassword").value,newPassword:el("newPassword").value});el("passwordDialog").close();notify("Password changed.",true);}catch(error){alert(error.message);}});
    el("manageUsersBtn").addEventListener("click",async()=>{try{el("newUsername").value="";el("newUserPassword").value="";el("newSetupCode").hidden=true;el("newSetupCodeMessage").hidden=true;const [status]=await Promise.all([api("/api/status"),refreshUsersDialog(),refreshSetupCodes()]);requireSetupCode=!!status.requireSetupCode;el("registrationSettings").hidden=!currentUser.isSuperAdmin;el("requireSetupCode").checked=requireSetupCode;el("usersDialog").showModal();}catch(error){notify(error.message);}});
    el("requireSetupCode").addEventListener("change",async()=>{const checkbox=el("requireSetupCode");checkbox.disabled=true;try{const result=await api("/api/admin/registration","POST",{requireSetupCode:checkbox.checked});requireSetupCode=result.requireSetupCode;notify(requireSetupCode?"New accounts now require a setup code.":"New accounts can now register without a code.",true);}catch(error){checkbox.checked=requireSetupCode;alert(error.message);}finally{checkbox.disabled=false;}});
    el("usersCloseBtn").addEventListener("click",()=>el("usersDialog").close());
    el("usersSaveBtn").addEventListener("click",async()=>{try{const result=await api("/api/users","POST",{username:el("newUsername").value.trim(),password:el("newUserPassword").value});el("newUsername").value="";el("newUserPassword").value="";await refreshUsersDialog();notify(`User ${result.user.username} created. Share a home to grant access.`,true);}catch(error){alert(error.message);}});
    el("createSetupCodeBtn").addEventListener("click",async()=>{try{const result=await api("/api/setup-codes","POST",{unlimited:el("setupCodeType").value==="unlimited"});el("newSetupCode").value=result.code;el("newSetupCode").hidden=false;el("newSetupCodeMessage").hidden=false;el("newSetupCode").select();await refreshSetupCodes();}catch(error){alert(error.message);}});
    el("setupCodeList").addEventListener("click",async event=>{const button=event.target.closest("[data-revoke-code]");if(!button)return;if(!confirm("Revoke this setup code? It will stop working immediately."))return;try{await api(`/api/setup-codes/${button.dataset.revokeCode}`,"DELETE",{});await refreshSetupCodes();el("newSetupCode").hidden=true;el("newSetupCodeMessage").hidden=true;notify("Setup code revoked.",true);}catch(error){alert(error.message);}});
    el("userList").addEventListener("click",async event=>{
      const toggle=event.target.closest("[data-toggle-admin]"),reset=event.target.closest("[data-reset-user]"),remove=event.target.closest("[data-delete-user]");
      if(toggle){try{await api(`/api/users/${toggle.dataset.toggleAdmin}/admin`,"POST",{isAdmin:toggle.dataset.admin!=="true"});await refreshUsersDialog();notify("Administrator access updated.",true);}catch(error){alert(error.message);}return;}
      const name=(reset||remove)?.dataset.name;
      if(reset){resetUserId=Number(reset.dataset.resetUser);el("resetPasswordTitle").textContent=`Reset password for ${name}`;el("resetPassword").value="";el("resetPasswordDialog").showModal();return;}
      if(!remove || !confirm(`Delete ${name}? Homes they own will move to you, and their login will stop working.`))return;
      try{
        await api(`/api/users/${remove.dataset.deleteUser}`,"DELETE",{});
        await refreshUsersDialog();
        await saveQueue.catch(()=>{});await loadWorkspace();renderAll();
        notify(`${name} deleted.`,true);
      }catch(error){alert(error.message);}
    });
    el("resetPasswordCloseBtn").addEventListener("click",()=>el("resetPasswordDialog").close());
    el("resetPasswordSaveBtn").addEventListener("click",async()=>{try{await api(`/api/users/${resetUserId}/password`,"POST",{password:el("resetPassword").value});el("resetPasswordDialog").close();notify("Password reset.",true);}catch(error){alert(error.message);}});
    el("shareHomeBtn").addEventListener("click",async()=>{try{await refreshShareDialog();el("shareDialog").showModal();}catch(error){notify(error.message);}});
    el("shareCloseBtn").addEventListener("click",()=>el("shareDialog").close());
    el("removeHomeBtn").addEventListener("click",removeHome);
    el("shareSaveBtn").addEventListener("click",async()=>{try{const userId=Number(el("shareUser").value);if(!userId)throw Error("Choose a user.");await api(`/api/homes/${home().id}/members/${userId}`,"PUT",{role:el("shareRole").value});await refreshShareDialog();notify("Home access updated.",true);}catch(error){alert(error.message);}});
    el("shareMembers").addEventListener("click",async event=>{const button=event.target.closest("[data-remove-user]");if(!button)return;try{await api(`/api/homes/${home().id}/members/${button.dataset.removeUser}`,"DELETE",{});await refreshShareDialog();notify("Home access removed.",true);}catch(error){alert(error.message);}});
  }
  function wireEvents() {
    el("checkUpdatesBtn").addEventListener("click",checkPortableUpdate);
    el("updateCancelBtn").addEventListener("click",()=>el("updateDialog").close());
    el("updateInstallBtn").addEventListener("click",installPortableUpdate);
    el("homeSelect").addEventListener("change",e=>{const chosen=workbook.homes.find(h=>h.id===Number(e.target.value));if(!chosen)return;workbook.selectedHomeId=chosen.id;workbook.selectedPanelId=chosen.panels[0].id;state=chosen.panels[0];selected=1;renderAll();});
    el("renameHomeBtn").addEventListener("click",()=>{const name=prompt("Rename this home or location:",home().name);if(name===null)return;const clean=name.trim().slice(0,80);if(!clean){notify("Enter a home name.");return;}home().name=clean;renderAll();});
    el("panelNav").addEventListener("click",e=>{const button=e.target.closest("[data-open-panel]");if(button)choosePanel(Number(button.dataset.openPanel));});
    el("linkedPanels").addEventListener("click",e=>{const button=e.target.closest("[data-open-panel]");if(button)choosePanel(Number(button.dataset.openPanel));});
    el("addHomeBtn").addEventListener("click",async()=>{const name=prompt("Name this home or location:",`Home ${workbook.nextHomeId}`);if(name===null)return;const clean=name.trim().slice(0,80);if(!clean){notify("Enter a home name.");return;}try{const {home:h}=await api("/api/homes","POST",{name:clean});workbook.homes.push(h);savedHomes.set(h.id,homeSnapshot(h));workbook.nextHomeId=Math.max(workbook.nextHomeId,h.id+1);workbook.selectedHomeId=h.id;workbook.selectedPanelId=h.panels[0].id;state=h.panels[0];selected=1;renderAll();}catch(error){notify(error.message);}});
    el("addMainBtn").addEventListener("click",()=>{const name=prompt("Name this main panel:",`Main panel ${home().panels.filter(p=>p.kind==="main").length+1}`);if(name===null)return;const clean=name.trim().slice(0,80);if(!clean){notify("Enter a panel name.");return;}const p=makePanel(allocatePanelId(),clean);home().panels.push(p);choosePanel(p.id);});
    el("addSubBtn").addEventListener("click",()=>{
      el("newSubName").value="";el("newSubFeeder").innerHTML=feederOptions(state.id);
      if(el("newSubFeeder").options.length===1){notify("Add an unused 240 V circuit with a breaker and amp rating to this panel first.");return;}
      el("addSubDialog").returnValue="";el("addSubDialog").showModal();el("newSubName").focus();
    });
    el("addSubDialog").addEventListener("close",()=>{if(el("addSubDialog").returnValue!=="confirm")return;try{
      const name=el("newSubName").value.trim();if(!name)throw Error("Enter a subpanel name.");
      const feeder=validateFeeder(state.id,el("newSubFeeder").value);
      const panel=makePanel(allocatePanelId(),name,"sub",state.id);panel.parentCircuitId=feeder.id;
      home().panels.push(panel);choosePanel(panel.id);notify("Subpanel added with the selected 240 V feeder.",true);
    }catch(error){notify(error.message);}});
    el("parentPanelSelect").addEventListener("change",e=>{const parent=panelById(Number(e.target.value));if(!parent || descendants(state.id).has(parent.id))return;state.parentPanelId=parent.id;state.parentCircuitId=null;renderAll();notify("Choose an unused 240 V feeder from the new source panel.");});
    el("feederCircuitSelect").addEventListener("change",e=>{try{const feeder=validateFeeder(state.parentPanelId,e.target.value,state.id,state.circuits);state.parentCircuitId=feeder.id;renderAll();}catch(error){notify(error.message);renderNavigation();}});
    el("goParentBtn").addEventListener("click",()=>choosePanel(state.parentPanelId));
    el("convertPanelBtn").addEventListener("click",convertPanel);
    el("deletePanelBtn").addEventListener("click",deletePanel);
    el("convertParent").addEventListener("change",e=>{el("convertFeeder").innerHTML=feederOptions(e.target.value,null,state.id,state.circuits);});
    el("convertDialog").addEventListener("close",()=>{if(el("convertDialog").returnValue==="confirm")try{finishConversion();}catch(error){notify(error.message);}});
    el("panelImportChoices").addEventListener("change",updateImportFields);
    el("importTargetPanel").addEventListener("change",updateImportFields);
    el("importParent").addEventListener("change",e=>{el("importFeeder").innerHTML=feederOptions(e.target.value,null,null,pendingPanelImport?.circuits||[]);});
    el("panelImportDialog").addEventListener("close",()=>{try{if(el("panelImportDialog").returnValue==="confirm")finishPanelImport();}catch(error){notify(error.message);}finally{pendingPanelImport=null;}});
    el("panelGrid").addEventListener("click",e=>{const btn=e.target.closest("[data-position]");if(!btn)return;selected=Number(btn.dataset.position);renderPanel();});
    el("breakerType").addEventListener("change",e=>convert(selected,e.target.value));
    el("spaceCount").addEventListener("change",e=>setSpaces(Number(e.target.value)));
    el("panelName").addEventListener("input",e=>{state.name=e.target.value;save();el("panelCaption").textContent=state.name.trim().toUpperCase()||"UNTITLED PANEL";renderNavigation();});
    el("addCircuitBtn").addEventListener("click",addCircuit);
    el("circuitRows").addEventListener("input",e=>{if(e.target.matches('[data-field="name"],[data-field="amps"]'))updateCircuit(e.target,false);});
    el("circuitRows").addEventListener("change",e=>{if(e.target.matches('[data-field="assignment"],[data-field="voltage"],[data-field="gauge"],[data-field="labelMode"],[data-field="name"],[data-field="amps"]'))updateCircuit(e.target,true);});
    el("circuitRows").addEventListener("click",e=>{const btn=e.target.closest("[data-delete]");if(!btn)return;const id=Number(btn.dataset.delete),c=circuitFor(id);if(!c)return;const linked=pointsFor(id).length,subpanels=feederChildren(state.id,id).length;if(!confirm(`Delete ${c.name||"this circuit"}${c.assignment?` at breaker ${c.assignment}`:""}?${linked?` ${linked} linked point${linked===1?"":"s"} will become unassigned.`:""}${subpanels?` ${subpanels} subpanel feeder link${subpanels===1?"":"s"} will be cleared.`:""}`))return;for(const p of state.points)if(p.circuitId===id)p.circuitId=null;for(const p of feederChildren(state.id,id))p.parentCircuitId=null;state.circuits=state.circuits.filter(x=>x!==c);renderAll();});
    el("addPointBtn").addEventListener("click",addPoint);
    for(const [table,prefix] of [["circuits","circuit"],["points","point"]]){
      el(`${prefix}Search`).addEventListener("input",()=>applyTableSearch(table));
      el(`${prefix}SearchColumn`).addEventListener("change",()=>applyTableSearch(table));
    }
    el("pointRows").addEventListener("input",e=>{if(e.target.matches('[data-point-field="name"],[data-point-field="location"]'))updatePoint(e.target,false);});
    el("pointRows").addEventListener("change",e=>{if(e.target.matches('[data-point-field="name"],[data-point-field="location"],[data-point-field="circuitId"]'))updatePoint(e.target,true);});
    el("pointRows").addEventListener("click",e=>{const btn=e.target.closest("[data-delete-point]");if(!btn)return;const id=Number(btn.dataset.deletePoint);const p=state.points.find(x=>x.id===id);if(!p)return;if(!confirm(`Delete point ${id}${p.name?` (${p.name})`:""}? Its number will not be reused.`))return;state.points=state.points.filter(x=>x!==p);renderAll();});
    for (const [table,id] of [["circuits","circuitTable"],["points","pointTable"]]) el(id).addEventListener("click",e=>{const button=e.target.closest("[data-sort-key]");if(button)changeSort(table,button.dataset.sortKey);});
    el("printDirectoryBtn").addEventListener("click",()=>openScopeDialog("print"));window.addEventListener("afterprint",()=>{delete document.body.dataset.print;});
    el("exportBtn").addEventListener("click",()=>openScopeDialog("export"));
    el("scopeDialog").addEventListener("close",()=>{if(el("scopeDialog").returnValue!=="confirm")return;const scope=el("scopeChoices").querySelector('input[name="scopeOption"]:checked')?.value;if(!scope)return;if(scopeMode==="print")print(scope);else exportJSON(scope);});
    el("importBtn").addEventListener("click",()=>el("importFile").click());
    el("importFile").addEventListener("change",async e=>{const file=e.target.files?.[0];e.target.value="";if(!file)return;if(file.size>20*1024*1024){notify("The JSON file exceeds 20 MB.");return;}try{await importJSON(JSON.parse(await file.text()));}catch(error){notify(`Import failed: ${error.message}`);}});
  }
  async function init() {
    for(let n=12;n<=42;n+=2){const option=document.createElement("option");option.value=n;option.textContent=`${n} spaces`;el("spaceCount").append(option);}
    wireAccountEvents();
    if(location.protocol==="file:"){
      offerLegacyExport("Run Panelbook.exe, then import your old JSON export. This file page can export data saved by this browser.");
      return;
    }
    try{
      const status=await api("/api/status");
      requireSetupCode=!!status.requireSetupCode;
      el("brandSubtitle").textContent=`Residential panel directory · v${status.version}`;
      if(status.needsSetup){
        el("authForm").dataset.setup="true";
        el("authTitle").textContent=status.canUseLocal?"Choose how to start":"Create first account";
        el("authDescription").textContent=status.canUseLocal?"Use Panelbook on this machine without a login, or create a login for accounts and sharing.":"This account can create users and share homes.";
        el("authSubmit").textContent=status.canUseLocal?"Create login":"Create account";
        el("localOnlyBtn").hidden=!status.canUseLocal;
        el("loginChoiceLabel").hidden=!status.canUseLocal;
        el("setupTokenField").hidden=false;
        const token=/^#setup=(.+)$/.exec(location.hash)?.[1];
        if(token)el("setupToken").value=decodeURIComponent(token);
      }else if(status.user)await enterApp(status);
      else{setAuthMode("login");el("authModeBtn").hidden=false;}
    }catch(error){offerLegacyExport(`Could not reach the Panelbook server: ${error.message}. Run Panelbook.exe.`);}
  }
  init();
})();
