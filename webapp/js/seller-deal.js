(function(root){
  "use strict";
  let timer=null;
  const node=(tag,text,cls)=>{const el=document.createElement(tag);if(text!=null)el.textContent=text;if(cls)el.className=cls;return el;};
  function stop(){if(timer!==null)root.clearInterval(timer);timer=null;}
  function render({panel,deal,formatNumber,nextAllowed={},isBusy=()=>false,hasMessages=false}){
    stop();panel.replaceChildren();panel.hidden=false;
    const accepted=Boolean(deal.seller_accepted_at||deal.status==="seller_contacted");
    const intro=deal.status==="paid"&&!accepted;
    panel.classList.add("seller-deal");panel.classList.toggle("seller-deal--intro",intro&&!hasMessages);
    const card=node("section",null,"seller-deal__card");const actions=[];
    panel.append(card);
    const button=(text,action,reminder=false)=>{const el=node("button",text,reminder?"seller-deal__remind":"seller-deal__primary");el.type="button";
      if(reminder)el.dataset.dealReminder=action;else el.dataset.dealAction=action;actions.push([el,action,reminder]);return el;};
    let clock=null,deadline=NaN;
    if(["completed","cancelled","disputed"].includes(deal.status)){
      const text={completed:["✅ Сделка завершена","Расчёт выполнен. Актуальные средства и история доступны в кошельке."],cancelled:["Сделка отменена","Кнопки передачи больше недоступны. Подробности — в истории операций."],disputed:["Сделка на проверке","Средства удерживаются до решения поддержки. Автоматической выплаты по таймеру нет."]}[deal.status];
      card.append(node("h2",text[0]),node("p",text[1]));
    }else if(intro){
      card.append(node("span","◷","seller-deal__intro-clock"),node("h2","24 часа на передачу машины"));
      const steps=node("ol");["Примите сделку и дождитесь ID покупателя.","Передайте автомобиль в игре по указанному ID.","Отметьте передачу и дождитесь подтверждения покупателя."].forEach(text=>steps.append(node("li",text)));card.append(steps,button("Принять сделку","seller-contacted"));
    }else if(deal.status==="transfer_in_progress"){
      const progress=node("div",null,"seller-deal__progress");progress.append(node("span","Шаг 3 из 3"));for(let i=0;i<3;i++)progress.append(node("i",null,i<2?"is-done":""));
      card.append(progress,node("h2","⏳ Ожидаем подтверждения покупателя"),node("p","Вы отметили машину как переданную. Деньги поступят на баланс после подтверждения покупателя."));
      panel.append(button("Напомнить о подтверждении","receipt",true));
    }else if(["paid","seller_contacted"].includes(deal.status)&&accepted){
      const heading=node("div",null,"seller-deal__heading");heading.append(node("h2",deal.buyer_game_id?"Передача машины":"◷ Время на передачу"));clock=node("span",null,"seller-deal__clock");clock.setAttribute("role","timer");heading.append(clock);card.append(heading);
      if(deal.buyer_game_id){
        const id=node("div",null,"seller-deal__id");id.append(node("span","ID покупателя:"),node("strong",deal.buyer_game_id));const copy=node("button","⧉","seller-deal__copy");copy.type="button";copy.dataset.copyGameId=deal.buyer_game_id;copy.setAttribute("aria-label","Скопировать ID покупателя");id.append(copy);
        card.append(id,node("p","Передайте авто по ID и нажмите «Машина передана»."),button("Машина передана","transfer"),node("small","Затем дождитесь подтверждения покупателя."));
      }else card.append(node("p","ID появится здесь, когда покупатель его укажет. Передайте машину в игре по этому ID."),button("Напомнить об ID","id",true));
    }else card.append(node("h2","Ожидаем оплаты"),node("p","Передача станет доступна после подтверждённой оплаты."));
    if(["paid","seller_contacted","transfer_in_progress","disputed"].includes(deal.status)&&!intro)panel.append(node("p",`🔒 ${formatNumber(deal.price_af_coins)} AF под защитой${deal.status==="transfer_in_progress"?"":" до подтверждения получения"}`,"seller-deal__escrow"));
    const deadlines=[deal.seller_delivery_deadline,!deal.seller_responded_at?deal.seller_response_deadline:null].filter(Boolean).map(value=>Date.parse(value)).filter(Number.isFinite);
    deadline=deadlines.length?Math.min(...deadlines):NaN;
    const expiryNote=intro?node("p","Срок передачи истёк. Ожидаем обновления статуса сервером; при задержке откройте помощь."):null;
    if(expiryNote){expiryNote.setAttribute("role","status");card.append(expiryNote);}
    const tick=()=>{
      const expired=Number.isFinite(deadline)&&deadline<=Date.now();
      if(expiryNote)expiryNote.hidden=!expired;
      if(clock){const minutes=Math.max(0,Math.ceil((deadline-Date.now())/60000));clock.textContent=!Number.isFinite(deadline)?"Срок уточняется сервером":expired?"Срок истёк":`${Math.floor(minutes/60)} ч ${String(minutes%60).padStart(2,"0")} мин`;}
      actions.forEach(([el,action,reminder])=>{const cooldown=Date.parse(nextAllowed[action]||"")>Date.now();el.disabled=isBusy()||cooldown||(["id","transfer","seller-contacted"].includes(action)&&expired);el.title=reminder&&cooldown?"Напоминание уже отправлено; повтор будет доступен позже":"";});
    };
    tick();if(actions.length||clock)timer=root.setInterval(tick,1000);
  }
  root.AutoFlowSellerDeal={render,stop};
})(window);
