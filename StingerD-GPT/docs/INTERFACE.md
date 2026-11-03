# Frozen integration contract v0

Backend runs same-origin with static web/ at /. Python stdlib implementation, no Node/dependency installation required. Prefix /api optional alias.

GET /health -> {ok,mode,integrations:{grok,calendar,x},upstream}
GET /places -> {places:[{id,name,lat,lon}]}
GET /routes -> {routes:[{id,name,color,synthetic,stops:[{id,name,lat,lon}]}]}
POST /trips/plan body {origin:"student-center",destination:"klaus",depart_at:ISO|null,arrive_by:ISO|null,evaluate_at:ISO|null,walk_speed:1.35,avoid_stairs:false,social_factor:false,delay_minutes:0,mode:"replay",preferred_mode:"best"|"bus"|"walk"}
Response TripTrace {id,version,generated_at,mode,origin:{id,name,lat,lon},destination:{...},constraints,chosen:TripPlan,alternatives:[TripPlan],explanation_facts:[string],allowed_numbers:[string],warnings:[string],verified:bool}
TripPlan {id,label,legs:[Leg],departure_time:ISO,arrival_time:ISO,leave_by:ISO,duration_minutes,quantiles:{p10,p50,p90} in minutes,p_on_time:0..1|null,p_catch:0..1|null,geometry:[[lat,lon]],synthetic:bool,social_applied:bool,confidence_label:string}
Leg {id,kind:"walk"|"wait"|"ride",from_name,to_name,duration_minutes,distance_m,route_id:null|number,route_name:null|string,color:null|string,geometry:[[lat,lon]],instruction:string}
GET /calendar/events -> {mode:"demo"|"google",events:[{id,title,location,place_id,start,end}]}
GET /calendar/next -> {mode,event}
POST /schedule {origin,events:[...]?} -> {mode,items:[{event,trace}],unresolved:[...]}
POST /grok/chat {message,trace?} -> {reply,provider:"template"|"grok",verified,trace?}
GET /signals/x -> {mode:"demo",signals:[{id,title,description,kind,active,source}]}
GET /upstream -> {status,checked_at,remote_sha,local_sha,changed,commits:[],error?,interval_seconds:300}
GET /integrations/status -> {grok,calendar,x,voice,location}
GET /auth/google -> OAuth redirect if configured, JSON 503 otherwise
GET /auth/google/callback -> redirect
POST /calendar/import {events:[...]} -> validated events (session local only; frontend uses IndexedDB)

Frontend index.html loads /js/app.js. Map API web/js/map.js exports class CampusMap constructor(container,{onSelect,onReady}={}); async init(); setPlan(trace); setTime(seconds); setPlaying(bool); setLayers({buses,labels}); simulate(progress); resetCamera(); setView("3d"|"2d"); dispose(). Map must render own controls? no, outer app owns toolbar. Map .init loads /assets/campus.json, uses bundled local Three module if available, graceful canvas2D fallback. map onReady({mode,warning?}).

`evaluate_at` is allowed only with `arrive_by` and without `depart_at`. It evaluates the fixed replay departure against the deadline. Without it, arrive-by searches latest safe departure. The returned constraints preserve evaluate_at for assessment traces.
