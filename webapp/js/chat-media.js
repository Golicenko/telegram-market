(function(root){
  "use strict";
  let api,notify,scope="",selected=[],previewHost,input,attach,viewer=null,observer=null;
  const cache=new Map(),node=(tag,text,cls)=>{const el=document.createElement(tag);if(text!=null)el.textContent=text;if(cls)el.className=cls;return el;};
  const button=(text,fn,label)=>{const el=node("button",text);el.type="button";if(label)el.setAttribute("aria-label",label);el.onclick=fn;return el;};
  function clearSelection(){selected.forEach(x=>URL.revokeObjectURL(x.url));selected=[];if(input)input.value="";previewHost?.replaceChildren();const field=document.getElementById("chatInput");if(field)field.required=true;}
  function dismiss(){if(!viewer)return false;viewer.close();return true;}
  function leave(){clearSelection();dismiss();observer?.disconnect();observer=null;for(const x of cache.values()){x.controller?.abort();if(x.url)URL.revokeObjectURL(x.url);}cache.clear();scope="";}
  function mount(options){
    api=options.api;notify=options.notify;
    if(scope!==options.scope){leave();scope=options.scope;}
    if(!input){
      const form=document.getElementById("chatForm");
      input=node("input");input.type="file";input.accept="image/jpeg,image/png,image/webp,image/heic,image/heif,.heic,.heif";input.multiple=true;input.hidden=true;input.id="chatPhotoInput";
      attach=button("＋",()=>input.click(),"Прикрепить фотографии");attach.className="chat-attach";attach.id="chatAttach";
      previewHost=node("div",null,"chat-photo-selection");previewHost.id="chatPhotoSelection";
      form.prepend(attach);form.append(input);form.before(previewHost);
      input.onchange=()=>{
        const files=Array.from(input.files||[]);
        choose(files);
      };
    }
    attach.disabled=!options.enabled;attach.title=options.enabled?"До 4 фото, каждое до 12 МБ":"Фото доступны в начатой переписке";
    if(!options.enabled)clearSelection();
    if(!observer&&root.IntersectionObserver)observer=new IntersectionObserver(entries=>entries.forEach(entry=>{
      const el=entry.target;if(entry.isIntersecting)loadThumbnail(el);else if(el.dataset.loaded){el.removeAttribute("src");delete el.dataset.loaded;}
    }),{root:document.getElementById("dealMessages"),rootMargin:"160px"});
  }
  function choose(files){
    clearSelection();
    if(files.length>4)notify("Можно выбрать до 4 фотографий за один раз");
    for(const file of files.slice(0,4)){
      if(!file.size||file.size>12*1024*1024){notify("Каждое фото должно быть не больше 12 МБ");continue;}
      const item={file,url:URL.createObjectURL(file),previewable:false};selected.push(item);
      const tile=node("div"),image=node("img");image.alt="Предпросмотр";const label=node("small",file.name);
      image.onerror=()=>{image.hidden=true;label.textContent="Предпросмотр недоступен; файл проверит сервер";};
      tile.append(image,label,button("×",()=>{URL.revokeObjectURL(item.url);selected=selected.filter(x=>x!==item);tile.remove();document.getElementById("chatInput").required=!selected.length;},"Убрать фотографию"));previewHost.append(tile);
      // Do not decode an unbounded phone raster just to show a small preview.
      api.previewDimensions(file).then(size=>{if(!selected.includes(item))return;if(size){item.previewable=true;image.src=item.url;}else{image.hidden=true;label.textContent="Фото проверит сервер; предпросмотр после отправки";}}).catch(()=>{image.hidden=true;});
    }
    document.getElementById("chatInput").required=!selected.length;
  }
  function take(){const value=selected;selected=[];input.value="";previewHost.replaceChildren();document.getElementById("chatInput").required=true;return value;}
  async function loadThumbnail(el){
    if(!el.isConnected||el.dataset.loading||el.dataset.loaded)return;
    const captured=scope,key=el.dataset.photoPath;el.dataset.loading="true";
    let record=cache.get(key);
    if(!record){
      const controller=root.AbortController?new AbortController():null;
      record={controller,url:null};cache.set(key,record);
      record.promise=api.request(key,{responseType:"blob",signal:controller?.signal,retries:0}).then(blob=>{
        if(scope!==captured||cache.get(key)!==record)return null;
        record.url=URL.createObjectURL(blob);
        for(const [oldKey,old]of cache){if(cache.size<=32)break;if(oldKey!==key&&old.url){URL.revokeObjectURL(old.url);cache.delete(oldKey);}}
        return record.url;
      }).catch(error=>{if(cache.get(key)===record)cache.delete(key);throw error;});
    }
    try{const url=record.url||await record.promise;if(scope===captured&&el.isConnected&&url){el.src=url;el.dataset.loaded="true";el.parentElement.classList.remove("has-error");}}
    catch(error){if(scope===captured&&el.isConnected){el.parentElement.classList.add("has-error");el.alt="Фото не загрузилось. Нажмите, чтобы повторить";}}
    finally{delete el.dataset.loading;}
  }
  function image(message){
    const box=button("",()=>{},"Открыть фотографию");box.className="chat-photo";
    const img=node("img");img.alt="Фотография в переписке";img.decoding="async";img.loading="lazy";
    img.style.aspectRatio=(message.media_width||4)+"/"+(message.media_height||3);
    if(message.local_photo_url){if(message.local_photo_previewable!==false)img.src=message.local_photo_url;else{img.hidden=true;box.textContent="Фото проверяется сервером…";}box.onclick=()=>{};}
    else{
      const path="/conversations/"+message.conversation_id+"/photos/"+message.media_id;
      img.dataset.photoPath=path+"?preview=true";
      img.onerror=()=>{if(!img.isConnected)return;box.classList.add("has-error");img.alt="Фото не загрузилось. Нажмите, чтобы повторить";delete img.dataset.loaded;const record=cache.get(img.dataset.photoPath);if(record?.url)URL.revokeObjectURL(record.url);cache.delete(img.dataset.photoPath);};
      box.onclick=()=>{if(box.classList.contains("has-error")){loadThumbnail(img);return;}openViewer(path);};
      if(observer)observer.observe(img);else requestAnimationFrame(()=>loadThumbnail(img));
    }
    box.append(img);return box;
  }
  async function openViewer(path){
    dismiss();document.activeElement?.blur();
    const dialog=node("dialog",null,"chat-photo-viewer");viewer=dialog;dialog.setAttribute("aria-label","Просмотр фотографии");
    const controls=node("div",null,"chat-photo-viewer__controls"),canvas=node("div",null,"chat-photo-canvas"),img=node("img"),status=node("p","Загрузка фотографии…");
    img.alt="Фотография";img.draggable=false;canvas.append(img,status);dialog.append(controls,canvas);document.body.append(dialog);
    img.onload=()=>status.remove();img.onerror=()=>{status.textContent="Не удалось открыть фото. Закройте просмотр и попробуйте ещё раз.";canvas.append(status);};
    let scale=1,dx=0,dy=0,previous=null,url=null;const points=new Map(),controller=root.AbortController?new AbortController():null,captured=scope;
    const draw=()=>{const x=Math.max(0,(img.clientWidth*scale-canvas.clientWidth)/2),y=Math.max(0,(img.clientHeight*scale-canvas.clientHeight)/2);dx=Math.max(-x,Math.min(x,dx));dy=Math.max(-y,Math.min(y,dy));img.style.transform="translate("+dx+"px,"+dy+"px) scale("+scale+")";};
    const zoom=value=>{scale=Math.max(1,Math.min(5,value));draw();};
    controls.append(button("−",()=>zoom(scale/1.3),"Уменьшить фото"),button("＋",()=>zoom(scale*1.3),"Увеличить фото"),button("Сбросить",()=>{scale=1;dx=dy=0;draw();}),button("×",()=>dialog.close(),"Закрыть фотографию"));
    const geometry=()=>{const values=[...points.values()];return values.length>=2?{x:(values[0].x+values[1].x)/2,y:(values[0].y+values[1].y)/2,d:Math.hypot(values[0].x-values[1].x,values[0].y-values[1].y)}:values[0];};
    canvas.onpointerdown=event=>{points.set(event.pointerId,{x:event.clientX,y:event.clientY});previous=geometry();canvas.setPointerCapture(event.pointerId);};
    canvas.onpointermove=event=>{if(!points.has(event.pointerId))return;points.set(event.pointerId,{x:event.clientX,y:event.clientY});const next=geometry();if(previous&&next){if(next.d&&previous.d)scale=Math.max(1,Math.min(5,scale*next.d/previous.d));if(scale>1){dx+=next.x-previous.x;dy+=next.y-previous.y;}draw();}previous=next;};
    canvas.onpointerup=canvas.onpointercancel=event=>{points.delete(event.pointerId);previous=geometry();};
    canvas.addEventListener("wheel",event=>{event.preventDefault();zoom(scale*(event.deltaY<0?1.15:1/1.15));},{passive:false});
    dialog.addEventListener("close",()=>{controller?.abort();if(url)URL.revokeObjectURL(url);if(viewer===dialog)viewer=null;dialog.remove();},{once:true});
    dialog.showModal();
    try{const blob=await api.request(path+"?preview=false",{responseType:"blob",signal:controller?.signal,retries:0});if(!dialog.open||scope!==captured)return;url=URL.createObjectURL(blob);img.src=url;}
    catch(error){if(dialog.open){status.textContent="Не удалось загрузить фото. Закройте просмотр и попробуйте ещё раз.";}}
  }
  root.AutoFlowChatMedia={mount,leave,dismiss,image,take,hasSelection:()=>selected.length>0};
})(window);
