const DB = 'buzz-route-v0';
let memory = new Map();
async function open() {
  return new Promise((resolve, reject) => {
    if (!globalThis.indexedDB) return reject(new Error('Storage unavailable'));
    const request = indexedDB.open(DB, 1);
    request.onupgradeneeded = () => { const db = request.result; db.createObjectStore('plans', {keyPath:'id'}); db.createObjectStore('settings', {keyPath:'id'}); };
    request.onerror = () => reject(request.error);
    request.onsuccess = () => resolve(request.result);
  });
}
async function operate(store, mode, action) {
  const db = await open();
  return new Promise((resolve,reject) => {
    const tx = db.transaction(store, mode); let result;
    const req = action(tx.objectStore(store));
    req.onsuccess = () => {result = req.result};
    tx.oncomplete = () => {db.close();resolve(result)};
    tx.onerror = () => {db.close();reject(tx.error)};
  });
}
export async function savePlan(trace,label) {
  const item={id:trace.id, day:trace.chosen.departure_time.slice(0,10),label,tripTrace:trace,createdAt:new Date().toISOString()};
  await operate('plans','readwrite',s=>s.put(item)); return item;
}
export async function allPlans(){return (await operate('plans','readonly',s=>s.getAll())).sort((a,b)=>b.createdAt.localeCompare(a.createdAt))}
export async function deletePlan(id){return operate('plans','readwrite',s=>s.delete(id))}
export async function getSetting(id,fallback=null){try{return (await operate('settings','readonly',s=>s.get(id)))?.value ?? fallback}catch{return memory.get(id)??fallback}}
export async function setSetting(id,value){try{await operate('settings','readwrite',s=>s.put({id,value}));}catch{memory.set(id,value)}}
