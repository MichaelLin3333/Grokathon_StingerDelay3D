/** Campus renderer. All transit animation is historical replay, not a live feed. */
const GOLD = '#edc66d';
const pairs = a => Array.from({length: Math.floor(a.length / 2)}, (_, i) => [a[i * 2], a[i * 2 + 1]]);
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
const ROAD_WIDTH = {motorway: 18, trunk: 16, primary: 13, secondary: 11, tertiary: 9, residential: 7, service: 4, footway: 2, path: 2, pedestrian: 4};

export class CampusMap {
  constructor(container, {onSelect, onReady} = {}) {
    this.container = container; this.onSelect = onSelect; this.onReady = onReady;
    this.time = 9.5 * 3600; this.playing = false; this.layers = {buses: true, labels: true};
    this.width = 1; this.height = 1; this.view = '3d'; this.buses = []; this.labels = [];
    this.canvas = document.createElement('canvas');
    this.canvas.setAttribute('aria-label', 'Interactive Georgia Tech campus map. Drag to orbit, scroll to zoom.');
    this.canvas.style.cssText = 'display:block;width:100%;height:100%;outline:none;touch-action:none';
    this.canvas.tabIndex = 0; if (getComputedStyle(this.container).position === 'static') this.container.style.position = 'relative'; this.container.append(this.canvas);
    this.labelLayer = document.createElement('div');
    this.labelLayer.style.cssText = 'position:absolute;inset:0;pointer-events:none;overflow:hidden';
    this.container.append(this.labelLayer);
    this.tooltip = document.createElement('div');
    this.tooltip.style.cssText = 'position:absolute;display:none;pointer-events:none;z-index:5;padding:10px 13px;color:#eef0ee;background:rgba(11,21,30,.96);border:1px solid #34434b;border-radius:9px;font:12px/1.5 system-ui;max-width:240px;box-shadow:0 8px 30px #0005';
    this.container.append(this.tooltip);
    this.last = 0; this.disposed = false;
    this._pointerMove = e => this.pointerMove(e); this._click = e => this.click(e);
    this.canvas.addEventListener('pointermove', this._pointerMove);
    this.canvas.addEventListener('pointerleave', () => this.tooltip.style.display = 'none');
    this.canvas.addEventListener('click', this._click);
  }

  async init() {
    const response = await fetch('/assets/campus.json');
    if (!response.ok) throw new Error('Campus data could not be loaded.');
    this.data = await response.json();
    this.routes = this.data.routes.map(r => {
      const pts = pairs(r.p), cum = [0];
      for(let i = 1; i < pts.length; i++) cum.push(cum[i - 1] + Math.hypot(pts[i][0] - pts[i-1][0], pts[i][1] - pts[i-1][1]));
      return {...r, pts, cum, total: cum.at(-1)};
    });
    for (const route of this.routes) {
      if (route.replay) route.replay.veh.forEach(record => this.buses.push({route, record}));
      else for(let k = 0; k < Math.round(route.n_bus || 2); k++) this.buses.push({route, k});
    }
    try {
      const [THREE, {OrbitControls}, {mergeGeometries}] = await Promise.all([
        import('/assets/vendor/three.module.js'), import('/assets/vendor/OrbitControls.js'), import('/assets/vendor/BufferGeometryUtils.js')
      ]);
      this.THREE = THREE; this.OrbitControls = OrbitControls; this.mergeGeometries = mergeGeometries;
      this.init3D(); this.mode = '3d';
    } catch (error) {
      console.info('Using lightweight campus map:', error.message);
      // A failed WebGL context request can lock a canvas to WebGL; replace it for the fallback.
      const replacement = this.canvas.cloneNode(); this.canvas.replaceWith(replacement); this.canvas = replacement;
      this.canvas.addEventListener('pointermove', this._pointerMove); this.canvas.addEventListener('click', this._click);
      this.ctx = this.canvas.getContext('2d'); this.mode = '2d';
      this.install2DNavigation();
    }
    this.resizeObserver = new ResizeObserver(() => this.resize()); this.resizeObserver.observe(this.container);
    this.resize();
    if (this.pendingTrace || this.trace) this.setPlan(this.pendingTrace || this.trace);
    this.frame = requestAnimationFrame(t => this.loop(t));
    this.onReady?.({mode: this.mode, ...(this.mode === '2d' ? {warning: 'Lightweight map · WebGL unavailable'} : {})});
    return this;
  }

  toXY(latlon) {
    const [lat0, lon0] = this.data.meta.origin;
    return [(latlon[1] - lon0) * Math.cos(lat0 * Math.PI / 180) * 111320, (latlon[0] - lat0) * 111320];
  }
  fromXY(x, y) {
    const [lat, lon] = this.data.meta.origin;
    return {lat: lat + y / 111320, lon: lon + x / (111320 * Math.cos(lat * Math.PI / 180))};
  }
  vec(x, y, h = 0) { return new this.THREE.Vector3(x, h, -y); }
  ribbon(lines, elevation = 1) {
    const T = this.THREE, pos = [], colors = [];
    for (const {pts, width, color} of lines) {
      const col = new T.Color(color);
      for(let i=0; i<pts.length-1; i++) {
        const [ax,ay]=pts[i],[bx,by]=pts[i+1],dx=bx-ax,dy=by-ay,len=Math.hypot(dx,dy)||1;
        const nx=-dy/len*width/2,ny=dx/len*width/2;
        const q=[[ax+nx,ay+ny],[ax-nx,ay-ny],[bx+nx,by+ny],[bx-nx,by-ny]];
        for(const k of [0,1,2,2,1,3]) {pos.push(q[k][0],elevation,-q[k][1]); colors.push(col.r,col.g,col.b);}
      }
    }
    const geometry = new T.BufferGeometry();
    geometry.setAttribute('position',new T.Float32BufferAttribute(pos,3));
    geometry.setAttribute('color',new T.Float32BufferAttribute(colors,3)); geometry.computeVertexNormals();
    return geometry;
  }

  init3D() {
    const T = this.THREE;
    this.renderer = new T.WebGLRenderer({canvas: this.canvas, antialias: true, alpha: false, powerPreference: 'high-performance'});
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.6));
    this.renderer.setClearColor(0x10242c); this.renderer.toneMapping = T.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.32; this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = T.PCFSoftShadowMap;
    this.scene = new T.Scene(); this.scene.fog = new T.FogExp2(0x10242c, .00013);
    this.camera = new T.PerspectiveCamera(39, 1, 5, 18000);
    this.controls = new this.OrbitControls(this.camera, this.canvas);
    this.controls.enableDamping = true; this.controls.dampingFactor=.07;
    this.controls.maxPolarAngle = Math.PI * .485; this.controls.minDistance=140; this.controls.maxDistance=5600;
    this.resetCamera();
    this.scene.add(new T.HemisphereLight(0xe3edf4,0x1f3435,2.1));
    this.sun = new T.DirectionalLight(0xffedca,2.9); this.sun.position.set(-800,1600,400);
    this.sun.castShadow=true; this.sun.shadow.mapSize.set(2048,2048);
    Object.assign(this.sun.shadow.camera,{left:-1800,right:1800,top:1800,bottom:-1800,near:5,far:6000});
    this.sun.shadow.normalBias=.7;this.sun.shadow.bias=-.0005;this.scene.add(this.sun);
    const ground=new T.Mesh(new T.PlaneGeometry(15000,15000).rotateX(-Math.PI/2),new T.MeshStandardMaterial({color:0x183039,roughness:1}));
    ground.receiveShadow=true;this.scene.add(ground);
    const green=[];
    for(const g of this.data.green) {
      const p=pairs(g.p); if(p.length<3)continue;
      green.push(new T.ShapeGeometry(new T.Shape(p.map(([x,y])=>new T.Vector2(x,y)))).rotateX(-Math.PI/2).translate(0,.15,0));
    }
    if(green.length) {
      const mesh=new T.Mesh(this.mergeGeometries(green),new T.MeshStandardMaterial({color:0x29463d,roughness:1}));mesh.receiveShadow=true;this.scene.add(mesh);green.forEach(g=>g.dispose());
    }
    const roads=new T.Mesh(this.ribbon(this.data.roads.map(r=>({pts:pairs(r.p),width:ROAD_WIDTH[r.k]||5,color:['footway','path','pedestrian'].includes(r.k)?'#3b5350':'#3a505a'})),.35),new T.MeshStandardMaterial({vertexColors:true,roughness:1,side:T.DoubleSide}));
    roads.receiveShadow=true;this.scene.add(roads);
    const geometries=[];
    this.data.buildings.forEach((b,i)=>{
      let p=pairs(b.p);if(p.length>2 && p[0][0]===p.at(-1)[0] && p[0][1]===p.at(-1)[1])p=p.slice(0,-1);if(p.length<3)return;
      const g=new T.ExtrudeGeometry(new T.Shape(p.map(([x,y])=>new T.Vector2(x,y))),{depth:Math.max(3,b.h),bevelEnabled:false});g.rotateX(-Math.PI/2);g.deleteAttribute('uv');
      g.setAttribute('bid',new T.Float32BufferAttribute(new Float32Array(g.attributes.position.count).fill(i),1));
      const colors=[],roof=new T.Color(b.c?0x879a9d:0x415965),wall=new T.Color(b.c?0x4a6674:0x2c4551),n=g.attributes.normal;
      for(let v=0;v<n.count;v++){const c=n.getY(v)>.5?roof:wall;colors.push(c.r,c.g,c.b);}g.setAttribute('color',new T.Float32BufferAttribute(colors,3));geometries.push(g);
    });
    this.buildings = new T.Mesh(this.mergeGeometries(geometries),new T.MeshStandardMaterial({vertexColors:true,roughness:.89,metalness:.03}));
    this.buildings.castShadow=true;this.buildings.receiveShadow=true;this.scene.add(this.buildings);geometries.forEach(g=>g.dispose());
    this.routeMesh=new T.Mesh(this.ribbon(this.routes.map(r=>({pts:r.pts,width:4,color:r.color})),1.3),new T.MeshBasicMaterial({vertexColors:true,transparent:true,opacity:.52,side:T.DoubleSide}));this.scene.add(this.routeMesh);
    this.stopMeshes=[];
    const stopGeometry=new T.CylinderGeometry(3,3,7,8);
    for(const route of this.routes)for(const stop of route.stops){
      const m=new T.Mesh(stopGeometry,new T.MeshStandardMaterial({color:route.color,emissive:route.color,emissiveIntensity:.25}));m.position.copy(this.vec(stop.x,stop.y,3.5));m.userData={type:'stop',route,stop};this.stopMeshes.push(m);this.scene.add(m);
    }
    const busGeometry=new T.BoxGeometry(22,8,9),haloGeometry=new T.RingGeometry(14,18,24).rotateX(-Math.PI/2);
    for(const bus of this.buses){
      bus.mesh=new T.Mesh(busGeometry,new T.MeshStandardMaterial({color:bus.route.color,emissive:bus.route.color,emissiveIntensity:.55,transparent:bus.route.synthetic,opacity:bus.route.synthetic ? .55 : 1}));
      bus.mesh.castShadow=true;bus.mesh.userData={type:'bus',bus};
      bus.halo=new T.Mesh(haloGeometry,new T.MeshBasicMaterial({color:bus.route.color,transparent:true,opacity:.4,side:T.DoubleSide}));this.scene.add(bus.mesh,bus.halo);
    }
    this.planGroup=new T.Group();this.scene.add(this.planGroup);
    this.userMarker=new T.Group();
    const person=new T.Mesh(new T.SphereGeometry(9,16,12),new T.MeshBasicMaterial({color:0xffffff}));person.position.y=14;
    const ring=new T.Mesh(new T.RingGeometry(13,20,32).rotateX(-Math.PI/2),new T.MeshBasicMaterial({color:0x75e4ce,transparent:true,opacity:.7,side:T.DoubleSide}));ring.position.y=2;
    this.userMarker.add(person,ring);this.userMarker.visible=false;this.scene.add(this.userMarker);
    this.raycaster=new T.Raycaster();this.mouse=new T.Vector2();
    this.createLandmarkLabels();
  }

  async createLandmarkLabels() {
    let landmarks=[];try{const response=await fetch('/places');landmarks=(await response.json()).places.filter(p=>p.kind==='landmark')}catch{return}
    if(this.disposed)return;
    for(const place of landmarks){
      const el=document.createElement('div');el.textContent=place.name;
      el.style.cssText='position:absolute;white-space:nowrap;transform:translate(-50%,-100%);padding:4px 7px;border-radius:5px;background:#11212bd9;border:1px solid #73878c55;color:#d9e4df;font:500 10px/1.1 system-ui;letter-spacing:.02em;box-shadow:0 2px 8px #0003';
      this.labelLayer.append(el);const [x,y]=this.toXY([place.lat,place.lon]);this.labels.push({el,x,y});
    }
  }
  focus(point){if(point.place_id){fetch('/places').then(r=>r.json()).then(d=>{const p=d.places.find(p=>p.id===point.place_id);if(p)this.focus(p)});return}if(!Number.isFinite(point.lat)||!Number.isFinite(point.lon))return;const [x,y]=this.toXY([point.lat,point.lon]);if(this.mode==='3d')this.cameraGoal={target:this.vec(x,y),position:this.vec(x-250,y-500,700)};}
  dashPath(points,on=16,off=9){let phase=0,result=[];for(let i=1;i<points.length;i++){const a=points[i-1],b=points[i],length=Math.hypot(b[0]-a[0],b[1]-a[1]);let position=0;while(position<length){const drawing=phase<on,step=Math.min(length-position,(drawing?on:on+off)-phase);if(step<=.00001){phase=0;continue}if(drawing){const at=t=>[a[0]+(b[0]-a[0])*t/length,a[1]+(b[1]-a[1])*t/length];result.push([at(position),at(position+step)])}position+=step;phase=(phase+step)%(on+off)}}return result;}

  routePosition(route,distance) {
    const s=((distance%route.total)+route.total)%route.total;let lo=0,hi=route.cum.length-1;
    while(hi-lo>1){const mid=(lo+hi)>>1;if(route.cum[mid]<=s)lo=mid;else hi=mid;}
    const a=route.pts[lo],b=route.pts[hi],f=(s-route.cum[lo])/(route.cum[hi]-route.cum[lo]||1);
    return{x:a[0]+f*(b[0]-a[0]),y:a[1]+f*(b[1]-a[1]),angle:Math.atan2(b[1]-a[1],b[0]-a[0])};
  }
  updateBuses() {
    for(const bus of this.buses){
      let distance=null;const route=bus.route;
      if(bus.record){const f=this.time/(route.replay.dt||10)-bus.record.i0,j=Math.floor(f),a=bus.record.D;
        if(j>=0&&j+1<a.length&&a[j]!=null&&a[j+1]!=null)distance=a[j]+(f-j)*(a[j+1]-a[j]);
      }else if(this.time>7*3600&&this.time<23*3600)distance=(this.time-7*3600)/(route.loop_s||1200)*route.total+bus.k*route.total/Math.round(route.n_bus||2);
      bus.visible=distance!=null&&this.layers.buses;bus.position=distance==null?null:this.routePosition(route,distance);
      if(bus.mesh){bus.mesh.visible=bus.halo.visible=bus.visible;if(bus.visible){bus.mesh.position.copy(this.vec(bus.position.x,bus.position.y,7));bus.mesh.rotation.y=bus.position.angle;bus.halo.position.copy(this.vec(bus.position.x,bus.position.y,1.8));}}
    }
  }

  setPlan(trace) {
    if (!this.data) { this.pendingTrace = trace; return; }
    this.pendingTrace = null;
    this.trace=trace;this.plan=trace?.chosen || trace || null;
    this.planPoints=(this.plan?.geometry||[]).map(p=>this.toXY(p));this.progress=null;
    if(this.mode==='3d'){
      const T=this.THREE;
      while(this.planGroup.children.length){const child=this.planGroup.children[0];this.planGroup.remove(child);child.traverse(obj=>{obj.geometry?.dispose();if(obj.material)Array.isArray(obj.material)?obj.material.forEach(m=>m.dispose()):obj.material.dispose();});}
      this.userMarker.visible=false;
      if(this.planPoints.length<2)return;
      const legPaths=(this.plan.legs||[]).filter(l=>l.geometry?.length>1).flatMap(leg=>{const points=leg.geometry.map(p=>this.toXY(p));return leg.kind==='ride'?[{pts:points,width:10,color:leg.color||GOLD}]:this.dashPath(points).map(pts=>({pts,width:6,color:'#98e8d2'}))});
      const mesh=new T.Mesh(this.ribbon(legPaths.length?legPaths:[{pts:this.planPoints,width:9,color:GOLD}],3),new T.MeshBasicMaterial({vertexColors:true,side:T.DoubleSide,depthTest:false}));mesh.renderOrder=10;this.planGroup.add(mesh);
      for(const [index,point] of [this.planPoints[0],this.planPoints.at(-1)].entries()){
        const pin=new T.Group();pin.position.copy(this.vec(point[0],point[1]));
        const color=index===0?0x86e4cf:0xedc66d;
        const ring=new T.Mesh(new T.RingGeometry(13,20,48).rotateX(-Math.PI/2),new T.MeshBasicMaterial({color,side:T.DoubleSide,depthTest:false}));ring.position.y=5;ring.renderOrder=11;pin.add(ring);
        const stem=new T.Mesh(new T.CylinderGeometry(2,2,78,8),new T.MeshBasicMaterial({color,depthTest:false}));stem.position.y=42;stem.renderOrder=11;pin.add(stem);
        const tip=new T.Mesh(new T.SphereGeometry(9,16,12),new T.MeshBasicMaterial({color,depthTest:false}));tip.position.y=83;tip.renderOrder=11;pin.add(tip);this.planGroup.add(pin);
      }
      this.routeMesh.material.opacity=.24;
      const xs=this.planPoints.map(p=>p[0]),ys=this.planPoints.map(p=>p[1]);
      const centerX=(Math.min(...xs)+Math.max(...xs))/2,centerY=(Math.min(...ys)+Math.max(...ys))/2;
      const radius=Math.max(900,Math.max(Math.max(...xs)-Math.min(...xs),Math.max(...ys)-Math.min(...ys))*1.4);
      this.cameraGoal={target:this.vec(centerX,centerY),position:this.vec(centerX-250,centerY-radius*.7,radius*.8)};
      if(this.view==='2d')this.cameraGoal.position=this.vec(centerX,centerY+.1,radius*1.1);
    }
  }
  setTime(seconds){if(Number.isFinite(seconds))this.time=((seconds%86400)+86400)%86400;}
  setPlaying(playing){this.playing=Boolean(playing);}
  setLayers(layers){Object.assign(this.layers,layers);}
  setView(view){this.view=view;if(this.mode==='3d'){
    const t=this.controls.target.clone(),d=this.camera.position.distanceTo(t);
    this.cameraGoal={target:t,position:view==='2d'?new this.THREE.Vector3(t.x,Math.max(1200,d),t.z+.1):new this.THREE.Vector3(t.x-450,1100,t.z+1300)};
  }}
  resetCamera(){if(this.controls){this.camera.position.set(-550,1350,1550);this.controls.target.set(170,0,-40);this.cameraGoal=null;this.controls.update();}this.zoom2D=1;this.pan2D={x:0,y:0};}
  simulate(progress){if(progress==null){this.progress=null;this.userPosition=null;if(this.userMarker)this.userMarker.visible=false;return;}this.progress=clamp(Number(progress)||0,0,1);if(!this.planPoints?.length)return;
    let lengths=[0];for(let i=1;i<this.planPoints.length;i++)lengths.push(lengths.at(-1)+Math.hypot(this.planPoints[i][0]-this.planPoints[i-1][0],this.planPoints[i][1]-this.planPoints[i-1][1]));
    const distance=this.progress*lengths.at(-1);let i=1;while(i<lengths.length-1&&lengths[i]<distance)i++;
    const a=this.planPoints[Math.max(0,i-1)],b=this.planPoints[Math.min(i,this.planPoints.length-1)],f=(distance-(lengths[i-1]||0))/(lengths[i]-lengths[i-1]||1);
    this.userPosition={x:a[0]+(b[0]-a[0])*f,y:a[1]+(b[1]-a[1])*f};
    if(this.userMarker){this.userMarker.visible=true;this.userMarker.position.copy(this.vec(this.userPosition.x,this.userPosition.y));}
  }

  resize(){this.width=Math.max(1,this.container.clientWidth);this.height=Math.max(1,this.container.clientHeight);
    if(this.renderer){this.renderer.setSize(this.width,this.height,false);this.camera.aspect=this.width/this.height;this.camera.updateProjectionMatrix();}
    else {const ratio=Math.min(devicePixelRatio||1,2);this.canvas.width=this.width*ratio;this.canvas.height=this.height*ratio;this.ctx?.setTransform(ratio,0,0,ratio,0,0);}}
  pointerMove(e){
    if(this.drag2D){this.pan2D.x=e.clientX-this.drag2D.x;this.pan2D.y=e.clientY-this.drag2D.y;return;}
    if(this.mode!=='3d')return;
    if(performance.now()-(this.lastHover||0)<80)return;this.lastHover=performance.now();
    const rect=this.canvas.getBoundingClientRect();this.mouse.set((e.clientX-rect.left)/rect.width*2-1,-(e.clientY-rect.top)/rect.height*2+1);
    this.raycaster.setFromCamera(this.mouse,this.camera);
    let hit=this.raycaster.intersectObjects(this.buses.filter(b=>b.mesh.visible).map(b=>b.mesh))[0],text='';
    this.hoverData=null;
    if(hit){const b=hit.object.userData.bus;text=b.route.name+' · '+(b.route.synthetic?'Simulated bus':'Recorded GPS replay');this.hoverData={type:'bus',route:b.route.id};}
    else {hit=this.raycaster.intersectObjects(this.stopMeshes)[0];if(hit){const {stop,route}=hit.object.userData;text=stop.n+' · '+route.name;this.hoverData={type:'stop',name:stop.n,...this.fromXY(stop.x,stop.y)};}
      else {hit=this.raycaster.intersectObject(this.buildings)[0];if(hit){const index=this.buildings.geometry.attributes.bid.getX(hit.face.a),b=this.data.buildings[index];text=b.n||(b.c?'Georgia Tech building':'Campus neighborhood');const p=pairs(b.p);const x=p.reduce((s,v)=>s+v[0],0)/p.length,y=p.reduce((s,v)=>s+v[1],0)/p.length;this.hoverData={type:'building',name:text,...this.fromXY(x,y)};}}}
    this.tooltip.textContent=text;this.tooltip.style.display=text?'block':'none';this.tooltip.style.left=clamp(e.clientX-rect.left+14,8,this.width-245)+'px';this.tooltip.style.top=clamp(e.clientY-rect.top+14,8,this.height-70)+'px';this.canvas.style.cursor=text?'pointer':'grab';
  }
  click(event){if(this.hoverData)this.onSelect?.({...this.hoverData,...(event?.altKey?{select_as:'origin'}:{})});}

  install2DNavigation(){this.zoom2D=1;this.pan2D={x:0,y:0};
    this.canvas.addEventListener('wheel',e=>{e.preventDefault();this.zoom2D=clamp(this.zoom2D*Math.exp(-e.deltaY*.001),.4,5);},{passive:false});
    this.canvas.addEventListener('pointerdown',e=>{this.drag2D={x:e.clientX-this.pan2D.x,y:e.clientY-this.pan2D.y};this.canvas.setPointerCapture(e.pointerId);});
    this.canvas.addEventListener('pointerup',()=>this.drag2D=null);
  }
  draw2D(){
    const ctx=this.ctx,w=this.width,h=this.height;if(!ctx)return;ctx.fillStyle='#132a33';ctx.fillRect(0,0,w,h);
    const scale=Math.min(w/2600,h/2400)*this.zoom2D;
    const project=([x,y])=>[w*.5+(x-140)*scale+this.pan2D.x,h*.51-y*scale+this.pan2D.y];
    const polygon=(points,color,stroke=null)=>{if(!points.length)return;ctx.beginPath();points.forEach((p,i)=>{const[x,y]=project(p);i?ctx.lineTo(x,y):ctx.moveTo(x,y);});ctx.closePath();ctx.fillStyle=color;ctx.fill();if(stroke){ctx.strokeStyle=stroke;ctx.stroke();}};
    for(const g of this.data.green)polygon(pairs(g.p),'#243f37');
    ctx.lineCap='round';
    for(const road of this.data.roads){const ps=pairs(road.p);ctx.beginPath();ps.forEach((p,i)=>{const[x,y]=project(p);i?ctx.lineTo(x,y):ctx.moveTo(x,y);});ctx.strokeStyle=['footway','path'].includes(road.k)?'#40544b':'#3a505b';ctx.lineWidth=Math.max(.5,(ROAD_WIDTH[road.k]||5)*scale);ctx.stroke();}
    for(const b of this.data.buildings)polygon(pairs(b.p),b.c?'#516976':'#2b4653','#122d37');
    for(const route of this.routes){ctx.beginPath();route.pts.forEach((p,i)=>{const[x,y]=project(p);i?ctx.lineTo(x,y):ctx.moveTo(x,y);});ctx.globalAlpha=this.plan ? .4 : .7;ctx.strokeStyle=route.color;ctx.lineWidth=2;ctx.stroke();ctx.globalAlpha=1;}
    if(this.planPoints?.length){for(const leg of this.plan.legs||[]){ctx.beginPath();(leg.geometry||[]).forEach((p,i)=>{const[x,y]=project(this.toXY(p));i?ctx.lineTo(x,y):ctx.moveTo(x,y)});ctx.setLineDash(leg.kind==='ride'?[]:[6,5]);ctx.strokeStyle=leg.kind==='ride'?(leg.color||GOLD):'#98e8d2';ctx.lineWidth=4;ctx.stroke();ctx.setLineDash([]);}
      [this.planPoints[0],this.planPoints.at(-1)].forEach((p,i)=>{const[x,y]=project(p);ctx.beginPath();ctx.arc(x,y,7,0,Math.PI*2);ctx.fillStyle=i?GOLD:'#8be5d1';ctx.fill();ctx.strokeStyle='#fff';ctx.lineWidth=2;ctx.stroke();});}
    for(const bus of this.buses)if(bus.visible&&bus.position){const[x,y]=project([bus.position.x,bus.position.y]);ctx.save();ctx.translate(x,y);ctx.rotate(-bus.position.angle);ctx.fillStyle=bus.route.color;ctx.globalAlpha=bus.route.synthetic ? .5 : 1;ctx.shadowColor=bus.route.color;ctx.shadowBlur=8;ctx.fillRect(-8,-4,16,8);ctx.restore();}
    if(this.userPosition){const[x,y]=project([this.userPosition.x,this.userPosition.y]);ctx.beginPath();ctx.arc(x,y,8,0,Math.PI*2);ctx.fillStyle='#fff';ctx.fill();ctx.strokeStyle='#80e7d2';ctx.lineWidth=4;ctx.stroke();}
    if(this.layers.labels){ctx.font='500 11px system-ui';ctx.fillStyle='#d9e4df';for(const route of this.routes)for(const s of route.stops.slice(0,3)){const[x,y]=project([s.x,s.y]);if(x>10&&x<w-80&&y>20&&y<h-20){ctx.fillStyle='#132a33dc';ctx.fillRect(x+5,y-14,ctx.measureText(s.n).width+8,19);ctx.fillStyle='#dce5e1';ctx.fillText(s.n,x+9,y);}}}
  }
  loop(now){if(this.disposed)return;const dt=Math.min(.1,(now-(this.last||now))/1000);this.last=now;
    if(this.playing)this.time=(this.time+dt*60)%86400;this.updateBuses();
    if(this.mode==='3d'){
      if(now-(this.lastSunUpdate||0)>1000){
        this.lastSunUpdate=now;
        const sunData=this.data.sun, hour=(69-1)*24+this.time/3600+4, i=Math.floor(hour);
        if(sunData?.az?.[i]!=null&&sunData?.el?.[i]!=null){
          const az=sunData.az[i]*Math.PI/180,el=sunData.el[i]*Math.PI/180;
          this.sun.position.set(Math.sin(az)*Math.cos(el)*2000,Math.max(70,Math.sin(el)*2000),-Math.cos(az)*Math.cos(el)*2000);
          this.sun.intensity=.5+Math.max(0,Math.sin(el))*2.7;
        }
      }
      if(this.cameraGoal){this.camera.position.lerp(this.cameraGoal.position,.055);this.controls.target.lerp(this.cameraGoal.target,.055);if(this.camera.position.distanceTo(this.cameraGoal.position)<1)this.cameraGoal=null;}
      this.controls.update();this.renderer.render(this.scene,this.camera);
      for(const label of this.labels){const p=this.vec(label.x,label.y,65).project(this.camera),visible=this.layers.labels&&p.z<1&&Math.abs(p.x)<1&&Math.abs(p.y)<1;label.el.style.display=visible?'block':'none';if(visible){label.el.style.left=(p.x+1)*.5*this.width+'px';label.el.style.top=(1-p.y)*.5*this.height+'px';}}
    }else this.draw2D();
    this.frame=requestAnimationFrame(t=>this.loop(t));
  }
  dispose(){this.disposed=true;cancelAnimationFrame(this.frame);this.resizeObserver?.disconnect();this.controls?.dispose();this.scene?.traverse(o=>{o.geometry?.dispose();if(o.material)Array.isArray(o.material)?o.material.forEach(m=>m.dispose()):o.material.dispose();});this.renderer?.dispose();this.canvas.remove();this.labelLayer.remove();this.tooltip.remove();}
}
