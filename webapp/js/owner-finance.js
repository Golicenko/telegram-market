(function(root){
  "use strict";
  let version=0;
  const node=(tag,text,cls)=>{const el=document.createElement(tag);if(text!=null)el.textContent=text;if(cls)el.className=cls;return el;};
  const button=(text,fn)=>{const el=node("button",text);el.type="button";el.addEventListener("click",fn);return el;};
  const today=()=>new Intl.DateTimeFormat("en-CA",{timeZone:"Europe/Bratislava",year:"numeric",month:"2-digit",day:"2-digit"}).format(new Date());
  const time=value=>new Intl.DateTimeFormat("ru",{timeZone:"Europe/Bratislava",dateStyle:"short",timeStyle:"short"}).format(new Date(value));
  function table(headers,rows){
    const wrap=node("div",null,"analytics-table-scroll"),el=node("table"),head=node("tr"),body=node("tbody");
    headers.forEach(text=>{const th=node("th",text);th.scope="col";head.append(th);});const thead=node("thead");thead.append(head);el.append(thead);
    rows.forEach(values=>{const tr=node("tr");values.forEach(value=>{const td=node("td");value instanceof Node?td.append(value):td.textContent=value==null?"Нет данных":String(value);tr.append(td);});body.append(tr);});
    el.append(body);wrap.append(el);if(headers.length===2)wrap.classList.add("finance-table-compact");if(!rows.length)wrap.append(node("p","За период нет операций"));return wrap;
  }
  function chart(data){
    const box=node("section",null,"finance-chart");box.append(node("h3","Доход платформы · по "+(data.grain==="month"?"месяцам":"дням")));
    for(const unit of ["AF","Stars"]){
      const values=data.items.filter(x=>x.unit===unit);box.append(node("h4",unit));
      if(!values.length||values.every(x=>Number(x.amount)===0)){box.append(node("p","Признанного дохода за период нет"));continue;}
      // Number is only for plot coordinates; displayed money stays exact server strings.
      const max=Math.max(...values.map(x=>Number(x.amount)),1),svg=document.createElementNS("http://www.w3.org/2000/svg","svg");
      svg.setAttribute("viewBox","0 0 300 90");svg.setAttribute("role","img");svg.setAttribute("aria-label","Доход "+unit+"; точные значения в таблице ниже");
      const poly=document.createElementNS(svg.namespaceURI,"polyline");
      poly.setAttribute("points",values.map((x,i)=>(5+i*290/Math.max(1,values.length-1))+","+(80-Number(x.amount)/max*70)).join(" "));
      poly.setAttribute("fill","none");poly.setAttribute("stroke",unit==="AF"?"#ffbd39":"#6aaaff");poly.setAttribute("stroke-width","2");svg.append(poly);box.append(svg);
      const details=node("details");details.append(node("summary","Точные значения и даты"),table(["Дата",unit],values.map(x=>[x.day,x.amount])));box.append(details);
    }
    return box;
  }
  function leaders(data){
    const box=node("section");box.append(node("h3","Топ-10 по приглашённым друзьям"),node("p",data.definition));
    const rows=data.items.map(user=>{
      const identity=node("div",null,"finance-person");
      if(user.avatar_url&&/^(https?:\/\/|\/uploads\/)/.test(user.avatar_url)){const img=node("img");img.src=user.avatar_url;img.alt="";img.loading="lazy";img.addEventListener("error",()=>img.remove(),{once:true});identity.append(img);}
      identity.append(node("span",user.name));const contact=node("div"),link=node("a","Написать");link.href=user.profile_url;link.target="_blank";link.rel="noopener noreferrer";contact.append(link);
      if(user.contact_note)contact.append(node("small",user.contact_note));
      return [user.rank,identity,user.username?"@"+user.username:"Нет username",user.invited,user.qualified,user.accrued_af+" AF",user.credited_bonus_af+" бонусных AF",contact];
    });
    box.append(table(["Место","Пользователь","Username","Друзья","Квалифицированы","Начислено","Зачислено","Связь"],rows));return box;
  }
  async function render(api){
    const host=document.getElementById("adminFinance");
    if(!host.dataset.ready){
      host.dataset.ready="true";host.classList.add("owner-finance");
      const form=node("form",null,"admin-report-filters"),start=node("input"),end=node("input");start.type=end.type="date";start.required=end.required=true;start.value=end.value=today();
      for(const [title,input] of [["С",start],["По",end]]){const label=node("label",title);label.append(input);form.append(label);}
      const submit=node("button","Показать период");submit.type="submit";form.append(submit);
      const content=node("div"),list=node("div");content.setAttribute("aria-live","polite");let all=false,offset=0;
      const query=()=>new URLSearchParams({start:start.value,end:end.value,all_time:all,timezone:"Europe/Bratislava",limit:25,offset});
      const load=async()=>{
        const key=++version;submit.disabled=true;content.textContent="Загрузка финансов…";list.replaceChildren();
        try{
          const [data,referrals]=await Promise.all([api.request("/admin/finance?"+query()),api.request("/admin/finance/referrals")]);if(key!==version)return;
          const s=data.summary;content.replaceChildren(node("p",time(data.from_utc)+" — "+time(data.until_utc_exclusive)+" · Europe/Bratislava · конец периода не включён"));
          const grid=node("div",null,"admin-metric-grid finance-summary");
          for(const [title,values,note] of [
            ["Оборот",[s.turnover_af+" AF"],"Оплаченные автомобили и обучение до возвратов"],
            ["Доход платформы",[s.platform_income_af+" AF",s.publication_income_stars+" Stars"],"Разные единицы, не суммируются"],
            ["Расходы и обязательства",[s.recorded_payout_stars+" Stars — выполненные выводы",data.liabilities_now.non_bonus_af+" AF — текущие остатки и резервы"],"Дополнительно "+data.liabilities_now.bonus_credits_af+" бонусных AF сейчас; за период выдано "+s.bonus_issued_af+" AF бонусов. Внешние затраты не учтены"],
            ["Чистый результат",[s.net_profit===null?"Не рассчитан":s.net_profit],s.net_label],
          ]){const card=node("div",null,"admin-metric");card.append(node("h3",title));values.forEach(x=>card.append(node("strong",x)));card.append(node("span",note));grid.append(card);}
          content.append(grid,node("p","Зачислено владельцу за его продажи и обучение: "+s.owner_income_af+" AF. Это не вывод в реальные деньги."),
            node("p","Подтверждённые поступления: "+s.stars_received+" Stars (не прибыль). Возвращено из этой когорты: "+s.stars_returned_from_receipts_cohort+" Stars. Возвраты AF по дате ledger: "+s.refund_af+" AF."),chart(data.chart));
          const categories={platform_income:"Доход платформы",owner_income:"Доход владельца",turnover:"Оборот",receipt:"Поступление",refund:"Возврат",bonus_issued:"Бонус",recorded_payout:"Выплата",returned_cohort:"Возврат когорты",adjustment:"Корректировка",detail:"Распределение"};
          content.append(node("h3","Источники и распределение"),table(["Источник","Операции","Сумма","Тип"],data.sources.map(x=>[x.label,x.count,x.amount+" "+x.unit,categories[x.category]])));
          const liabilities=data.liabilities_now;content.append(node("h3","Обязательства сейчас · все даты"));
          const names={purchased_balance:"Купленные AF, доступны",earned_balance:"Заработанные AF, доступны",bonus_balance:"Бонусные AF, доступны",purchased_frozen_balance:"Купленные AF в резервах",earned_frozen_balance:"Заработанные AF в резервах",bonus_frozen_balance:"Бонусные AF в резервах"};
          content.append(table(["Кошельки","AF"],Object.entries(liabilities.wallets_af).map(([k,v])=>[names[k],v])),
            node("p","Открытые выводы: "+liabilities.withdrawals.count+"; резерв "+liabilities.withdrawals.reserved_af+" AF, полный номинал "+liabilities.withdrawals.expected_stars+" Stars (остаток после частичной отправки — в заявке). Сохранённая комиссия к исполнению "+liabilities.withdrawals.expected_fee_af+" AF — ещё не доход. Не прибавляйте резерв повторно к кошелькам."),
            node("p","Неисполненные платные публикации: "+liabilities.unfulfilled_publications_stars+" Stars."));
          const q=data.data_quality;content.append(node("p","Неполные записи: "+q.paid_withdrawals_without_fee+" исполненных выводов без сохранённой комиссии; "+q.unverified_training_purchases+" неподтверждённых покупок обучения; "+q.unverified_car_orders+" заказов автомобиля без доказательства оплаты. Они не заменяются расчётными значениями."));
          const details=node("details");details.append(node("summary","Правила расчёта и ограничения"));data.definitions.forEach(x=>details.append(node("p",x)));content.append(details);
          list.append(node("h3","Операции · не суммировать разные типы"),table(["Время · Bratislava","Операция","Сумма","Ссылка для аудита"],data.operations.map(x=>[time(x.at),x.label,x.amount+" "+x.unit,x.reference])));
          const prev=button("Назад",()=>{offset=Math.max(0,offset-25);void load();}),next=button("Далее",()=>{offset+=25;void load();});prev.disabled=!offset;next.disabled=!data.has_more;
          const pager=node("div",null,"admin-report-filters");pager.append(prev,node("span","Страница "+(offset/25+1)),next);list.append(pager,leaders(referrals));
        }catch(error){if(key===version)root.AutoFlowAdmin.errorState(content,error,load);}
        finally{if(key===version)submit.disabled=false;}
      };
      const quick=node("div",null,"admin-report-filters");for(const [days,label] of [[1,"Сегодня"],[7,"7 дней"],[30,"30 дней"],[0,"Всё время"]])quick.append(button(label,()=>{all=!days;offset=0;if(days){end.value=today();const d=new Date(end.value+"T12:00:00Z");d.setUTCDate(d.getUTCDate()-days+1);start.value=d.toISOString().slice(0,10);}void load();}));
      form.addEventListener("submit",event=>{event.preventDefault();all=false;offset=0;void load();});
      host.append(node("h2","Финансы / Доходы AutoFlow Market"),node("p","Только владелец · чтение из БД · AF и Stars отдельно"),quick,form,content,list);host.reload=load;
    }
    await host.reload();
  }
  root.AutoFlowFinance={render};
})(window);
