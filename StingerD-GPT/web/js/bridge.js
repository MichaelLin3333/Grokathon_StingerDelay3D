/** Versioned map transport shared by browser embeds and native web views. */
export function normalizeTrace(value){
 const trace=value?.trace||value;if(trace?.chosen)return trace;if(!trace?.plan?.legs)throw new Error('A TripTrace is required.');
 const p=trace.plan,geometry=p.legs.flatMap(l=>l.path||[]);if(!geometry.length)throw new Error('A plan needs geometry.');
 for(const pair of geometry)if(!Array.isArray(pair)||pair.length<2||!pair.every(Number.isFinite))throw new Error('Invalid plan coordinates.');
 for(const leg of p.legs)if(!Number.isFinite(leg.duration_s_p50)||leg.duration_s_p50<0)throw new Error('Invalid leg duration.');
 const origin={id:'bridge-origin',name:trace.origin_name||'Origin',lat:geometry[0][0],lon:geometry[0][1]},destination={id:'bridge-destination',name:trace.destination_name||'Destination',lat:geometry.at(-1)[0],lon:geometry.at(-1)[1]};
 const chosen={id:null,label:p.mode==='bus'?'Walk + Stinger':'Walking',legs:p.legs.map((l,i)=>({id:'bridge-'+i,kind:l.kind==='transfer_walk'?'walk':l.kind,duration_minutes:l.duration_s_p50/60,distance_m:l.distance_m||0,from_name:i===0?origin.name:l.label,to_name:l.label,instruction:l.label,route_id:l.route_id,route_name:l.route_id,color:'#c6a650',geometry:l.path||[]})),departure_time:p.leave_at,arrival_time:p.arrive_at,leave_by:p.leave_at,duration_minutes:p.total_s.p50/60,quantiles:Object.fromEntries(Object.entries(p.total_s).map(([k,v])=>[k,v/60])),p_on_time:p.p_on_time,p_catch:p.p_catch,geometry,synthetic:p.legs.some(l=>l.synthetic),social_applied:!!trace.social_factor,confidence_label:'Shared planner trace'};
 return {id:null,version:'v0',origin,destination,chosen,alternatives:[],constraints:{depart_at:p.leave_at},allowed_numbers:trace.allowed_numbers||[],warnings:['Received from the shared map bridge. Helper requests are revalidated by this server.'],verified:false};
}
export function installBridge(handlers){
 const params=new URLSearchParams(location.search);if(params.get('embed')==='1')document.documentElement.classList.add('embed');
 let parentOrigin=location.origin;try{if(params.get('parent_origin'))parentOrigin=new URL(params.get('parent_origin')).origin}catch{}
 const post=message=>{if(window.parent!==window)window.parent.postMessage(message,parentOrigin);try{window.webkit?.messageHandlers?.simBridge?.postMessage(message)}catch{}};
 const receive=message=>{try{switch(message?.type){case 'plan.show':handlers.show(normalizeTrace(message.trace));break;case 'plan.clear':handlers.clear();break;case 'walk.start':handlers.start();break;case 'walk.stop':handlers.stop();break;case 'clock.set':{const parts=new Intl.DateTimeFormat('en-US',{timeZone:'America/New_York',hour:'numeric',minute:'numeric',second:'numeric',hourCycle:'h23'}).formatToParts(new Date(message.iso));const get=t=>Number(parts.find(x=>x.type===t).value);handlers.clock({seconds:get('hour')*3600+get('minute')*60+get('second'),speed:message.speed,playing:message.playing});break}case 'camera.focus':handlers.focus(message);break}}catch(e){post({type:'sim.error',message:e.message})}};
 window.addEventListener('message',event=>{if(event.source===window.parent&&event.origin===parentOrigin)receive(event.data)});
 window.simBridge={receive};let last=0;
 return {ready:()=>post({type:'sim.ready'}),pick:p=>post({type:'sim.pick',...p}),progress:p=>{const now=performance.now();if(now-last>250){last=now;post({type:'walk.progress',...p})}},done:()=>post({type:'walk.done'})};
}
