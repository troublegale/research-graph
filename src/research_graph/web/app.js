"use strict";
const $ = (selector) => document.querySelector(selector);
const money = (value) => new Intl.NumberFormat("ru-RU", {style:"currency",currency:"RUB",maximumFractionDigits:0}).format(value);
const escapeHtml = (value) => String(value ?? "—").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
let selected = null, page = 1, catalogTotal = 0, csvResults = null;
let requestPages = 1;
const estimates = new Map();
const activeOperations = new Map();
let messageTimer;
function notify(message, success=false) {
  clearTimeout(messageTimer);
  const box=$("#message");
  box.replaceChildren();
  box.className=success?"success":"";
  box.setAttribute("role",success?"status":"alert");
  const text=document.createElement("span");text.textContent=message;
  const close=document.createElement("button");close.type="button";
  close.className="dismiss-message";close.setAttribute("aria-label","Закрыть сообщение");
  close.textContent="×";close.onclick=()=>{box.hidden=true;};
  box.append(text,close);box.hidden=false;
  if(success)messageTimer=setTimeout(()=>{box.hidden=true;},8000);
}
function operationFor(event, button) {
  const source=event?.currentTarget;
  if(source===document && !["request","moreRequests","add","remove","estimate"].some(key=>button?.dataset[key]))return null;
  const id=source?.getAttribute?.("id");
  if(!event)return {scope:"requests",pending:"Загружаем справочники и заявки…",success:"Приложение готово к работе"};
  if(id==="request-form")return {scope:"requests",pending:"Сохраняем заявку…",success:"Заявка сохранена"};
  if(id==="match")return {scope:"requests",pending:"Подбираем автомобили…",success:()=>`Подбор завершён. Найдено автомобилей: ${$("#matches").querySelectorAll(".car-card").length}`};
  if(id==="status-request")return {scope:"requests",pending:"Меняем статус заявки…",success:()=>selected.status==="closed"?"Заявка закрыта":"Заявка открыта повторно"};
  if(id==="delete-request")return {scope:"requests",pending:"Удаляем заявку…",success:"Заявка удалена",confirm:"Удалить заявку и её подборку?"};
  if(id==="catalog-form" || id==="previous-page" || id==="next-page")return {scope:"catalog",pending:"Загружаем объявления…",success:()=>`Каталог обновлён. Найдено: ${catalogTotal}`};
  if(id==="manual-form")return {scope:"model",pending:"Рассчитываем стоимость автомобиля…",success:"Оценка готова"};
  if(id==="upload-form")return {scope:"model",pending:"Загружаем и проверяем модель…",success:"Модель загружена и готова к работе"};
  if(id==="csv-form")return {scope:"model",pending:"Обрабатываем CSV. Пожалуйста, подождите…",success:()=>`Обработка CSV завершена. Строк: ${csvResults.rows.length}`};
  if(button?.dataset.moreRequests)return {scope:"requests",pending:"Загружаем заявки…",success:"Список заявок обновлён"};
  if(button?.dataset.request)return {scope:"requests",pending:"Открываем заявку…"};
  if(button?.dataset.add)return {scope:"requests",pending:"Сохраняем автомобиль…",success:"Автомобиль добавлен в подборку"};
  if(button?.dataset.remove)return {scope:"requests",pending:"Удаляем кандидата…",success:"Автомобиль убран из подборки"};
  if(button?.dataset.estimate)return {scope:button.closest(".tab").id,pending:"Оцениваем автомобиль…",success:"Оценка готова. Прогноз и отклонение обновлены"};
  if(button?.dataset.tab){const tab=button.dataset.tab;return {scope:tab,pending:{requests:"Открываем заявки…",catalog:"Загружаем каталог…",analytics:"Формируем аналитические отчёты…",model:"Загружаем сведения о модели…"}[tab],success:{catalog:"Каталог загружен",analytics:"Аналитические отчёты готовы",model:"Сведения о модели загружены"}[tab]};}
  return null;
}
function showActivity() {
  const activity=$("#activity");
  activity.hidden=activeOperations.size===0;
  $("#activity-text").textContent=[...activeOperations.values()].join(" · ");
}
function syncControls() {
  $("#previous-page").disabled=page===1;
  $("#next-page").disabled=page*12>=catalogTotal;
  if(selected){
    $("#edit-request").disabled=selected.status!=="open";
    $("#delete-request").disabled=selected.status!=="open";
    document.querySelectorAll("#candidates [data-remove]").forEach(button=>{button.disabled=selected.status!=="open";});
  }
}
async function api(path, options={}) {
  const response=await fetch(path,{...options,headers:{...(options.body instanceof FormData?{}:{"Content-Type":"application/json"}),...options.headers}});
  if(response.status===204)return null;
  const data=await response.json();
  if(!response.ok){const detail=data.error?.details?.map(x=>`${x.field}: ${x.message}`).join("; ");throw new Error((data.error?.message || "Ошибка запроса")+(detail?`: ${detail}`:""));}
  return data;
}
const action = (callback) => async (event) => {
  if(event?.type==="submit")event.preventDefault();
  const button=event?.type==="submit"?(event.submitter||event.currentTarget.querySelector("button")):event?.target.closest("button");
  const operation=operationFor(event,button);
  if(!operation || activeOperations.has(operation.scope))return;
  if(operation.confirm && !confirm(operation.confirm))return;
  const scope=$(`#${operation.scope}`);
  const label=button?.textContent,wasDisabled=button?.disabled;
  const changeLabel=button && !button.matches(".request-card,[data-tab]");
  clearTimeout(messageTimer);$("#message").hidden=true;
  activeOperations.set(operation.scope,operation.pending);showActivity();
  scope.inert=true;scope.setAttribute("aria-busy","true");
  if(button){button.disabled=true;button.classList.add("is-loading");if(changeLabel)button.textContent=operation.pending;}
  try {
    await callback(event);
    if(operation.success)notify(typeof operation.success==="function"?operation.success():operation.success,true);
  } catch(error) {
    notify(error instanceof TypeError?"Не удалось связаться с сервисом. Проверьте подключение и повторите попытку.":error.message);
  } finally {
    scope.inert=false;scope.setAttribute("aria-busy","false");
    if(button){button.disabled=wasDisabled;button.classList.remove("is-loading");if(changeLabel && button.textContent===operation.pending)button.textContent=label;}
    activeOperations.delete(operation.scope);showActivity();syncControls();
  }
};
function table(headers,rows){return rows.length?`<table><thead><tr>${headers.map(x=>`<th>${escapeHtml(x)}</th>`).join("")}</tr></thead><tbody>${rows.map(row=>`<tr>${row.map(x=>`<td>${x}</td>`).join("")}</tr>`).join("")}</tbody></table>`:'<p class="muted">Пока нет данных.</p>';}
function featureText(car){return `${car.year ?? "Год не указан"} · ${car.mileage == null ? "Пробег не указан" : new Intl.NumberFormat("ru-RU").format(car.mileage)+" км"} · ${car.transmission}`;}
function estimateText(car){const estimate=estimates.get(car.id);return estimate?`<div class="estimate">Прогноз: <strong>${money(estimate.predicted_price)}</strong><br>Отклонение: ${estimate.deviation_percent>0?"+":""}${estimate.deviation_percent}%</div>`:"";}
function carCard(car, allowAdd=false){return `<article class="car-card" data-car="${car.id}"><h3>${escapeHtml(car.brand)} ${escapeHtml(car.name)}</h3><p class="muted">${escapeHtml(featureText(car))}</p><p>${escapeHtml(car.location)}</p><div class="price">${money(car.price)}</div><p class="muted">${car.is_demo ? "Синтетический пример · " : ""}Наблюдение: ${escapeHtml(car.observed_at.slice(0,10))}</p>${estimateText(car)}<div class="actions"><button data-estimate="${car.id}" class="secondary">Оценить</button>${allowAdd?`<button data-add="${car.id}">Сохранить</button>`:""}</div></article>`;}
async function loadRequests(targetPages=requestPages){
  const pages=await Promise.all(Array.from({length:targetPages},(_,index)=>api(`/api/requests?page=${index+1}`)));
  const rows=pages.flat();
  requestPages=targetPages;
  $("#request-list").innerHTML=rows.length?rows.map(item=>`<button class="request-card ${selected?.id===item.id?"selected":""}" data-request="${item.id}"><strong>${escapeHtml(item.title)}</strong>${money(item.budget)}<p class="muted">${item.status==="open"?"Открыта":"Закрыта"} · №${item.id}</p></button>`).join(""):'<p class="muted">Создайте первую заявку.</p>';
  if(pages.at(-1).length===100)$("#request-list").insertAdjacentHTML("beforeend",'<button data-more-requests="true" class="secondary">Показать ещё заявки</button>');
}
async function selectRequest(id){selected=await api(`/api/requests/${id}`);$("#request-detail").hidden=false;$("#detail-title").textContent=selected.title;$("#detail-status").textContent=selected.status==="open"?"Открыта":"Закрыта";$("#detail-budget").textContent=`Бюджет до ${money(selected.budget)} · версия требований ${selected.revision}`;$("#status-request").textContent=selected.status==="open"?"Закрыть":"Открыть повторно";$("#edit-request").disabled=selected.status!=="open";$("#delete-request").disabled=selected.status!=="open";$("#matches").innerHTML="";await Promise.all([loadRequests(),loadCandidates()]);}
async function loadCandidates(){if(!selected)return;const rows=await api(`/api/requests/${selected.id}/candidates`);$("#candidates").innerHTML=table(["Автомобиль","Цена","Прогноз","Отклонение","Состояние","Действия"],rows.map(item=>{const car=item.listing,e=estimates.get(car.id);return [`${escapeHtml(car.brand)} ${escapeHtml(car.name)}<br><span class="muted">${escapeHtml(featureText(car))}</span>`,money(car.price),e?money(e.predicted_price):"—",e?`${e.deviation_percent}%`:"—",item.stale?'<span class="badge stale">Требования изменились</span>':"Сохранён",`<button data-estimate="${car.id}" class="secondary">Оценить</button> <button data-remove="${item.id}" class="secondary" ${selected.status!=="open"?"disabled":""}>Убрать</button>`];}));}
function resetForm(){$("#request-form").reset();$("#request-form [name=id]").value="";$("#form-title").textContent="Новая заявка";}
$("#new-request").onclick=()=>{resetForm();$("#request-form [name=title]").focus();};
$("#cancel-edit").onclick=resetForm;
$("#request-form").onsubmit=action(async()=>{const form=$("#request-form"),data=Object.fromEntries(new FormData(form)),id=data.id;delete data.id;for(const key of Object.keys(data)){if(data[key]==="")data[key]=null;else if(["budget","min_year","max_mileage","brand_id","location_id"].includes(key))data[key]=Number(data[key]);}const item=await api(id?`/api/requests/${id}`:"/api/requests",{method:id?"PUT":"POST",body:JSON.stringify(data)});resetForm();await selectRequest(item.id);});
$("#edit-request").onclick=()=>{if(!selected)return;const form=$("#request-form");for(const[key,value]of Object.entries(selected)){if(form.elements.namedItem(key))form.elements.namedItem(key).value=value??"";}$("#form-title").textContent="Редактирование заявки";form.scrollIntoView({behavior:"smooth"});};
$("#match").onclick=action(async()=>{const rows=await api(`/api/requests/${selected.id}/match`,{method:"POST"});$("#matches").innerHTML=rows.length?rows.map(car=>carCard(car,selected.status==="open")).join(""):'<p class="muted">Нет совпадений. Попробуйте увеличить бюджет или смягчить требования.</p>';});
$("#status-request").onclick=action(async()=>{await api(`/api/requests/${selected.id}/${selected.status==="open"?"close":"reopen"}`,{method:"POST"});await selectRequest(selected.id);});
$("#delete-request").onclick=action(async()=>{await api(`/api/requests/${selected.id}`,{method:"DELETE"});selected=null;$("#request-detail").hidden=true;resetForm();await loadRequests();});
document.addEventListener("click",action(async event=>{const button=event.target.closest("button");if(!button)return;if(button.dataset.moreRequests)await loadRequests(requestPages+1);if(button.dataset.request)await selectRequest(Number(button.dataset.request));if(button.dataset.add){await api(`/api/requests/${selected.id}/candidates`,{method:"POST",body:JSON.stringify({listing_id:Number(button.dataset.add)})});await loadCandidates();}if(button.dataset.remove){await api(`/api/requests/${selected.id}/candidates/${button.dataset.remove}`,{method:"DELETE"});await loadCandidates();}if(button.dataset.estimate){const id=Number(button.dataset.estimate);estimates.set(id,await api(`/api/listings/${id}/estimate`,{method:"POST"}));document.querySelectorAll(`[data-car="${id}"]`).forEach(card=>{card.querySelector(".estimate")?.remove();const e=estimates.get(id);const box=document.createElement("div");box.className="estimate";box.textContent=`Прогноз: ${money(e.predicted_price)} · отклонение ${e.deviation_percent}%`;card.append(box);});await loadCandidates();}}));
async function loadCatalog(targetPage=page){const params=new URLSearchParams(new FormData($("#catalog-form")));for(const [key,value]of [...params])if(!value)params.delete(key);params.set("page",targetPage);params.set("page_size",12);const data=await api(`/api/listings?${params}`);page=data.page;catalogTotal=data.total;$("#catalog-items").innerHTML=data.items.map(car=>carCard(car)).join("")||'<p class="muted">Объявлений нет.</p>';$("#catalog-count").textContent=`Найдено: ${data.total}`;$("#page-label").textContent=`Страница ${page}`;$("#previous-page").disabled=page===1;$("#next-page").disabled=page*12>=catalogTotal;}
$("#catalog-form").onsubmit=action(async()=>{await loadCatalog(1);});$("#previous-page").onclick=action(async()=>{await loadCatalog(page-1);});$("#next-page").onclick=action(async()=>{await loadCatalog(page+1);});
async function loadAnalytics(){const[prices,deviations]=await Promise.all([api("/api/analytics/prices"),api("/api/analytics/deviations")]);$("#price-report").innerHTML=table(["Марка","Год","Объявлений","Средняя цена","Минимум","Максимум"],prices.map(x=>[escapeHtml(x.brand),escapeHtml(x.year),x.count,money(x.average_price),money(x.min_price),money(x.max_price)]));$("#deviation-report").innerHTML=table(["Город","Оценено машин","Среднее отклонение"],deviations.map(x=>[escapeHtml(x.location),x.count,`${x.average_deviation_percent.toFixed(1)}%`]));}
async function loadModel(){try{const model=await api("/api/model");$("#model-info").textContent=`${model.algorithm} · MAE на тесте: ${money(model.test?.mae||0)} · период данных: ${model.period?.min?.slice(0,10)||"—"} — ${model.period?.max?.slice(0,10)||"—"}`;}catch(error){$("#model-info").textContent=error.message;throw error;}}
$("#upload-form").onsubmit=action(async()=>{await api("/upload-model",{method:"POST",body:new FormData($("#upload-form"))});estimates.clear();await loadModel();});
$("#csv-form").onsubmit=action(async()=>{csvResults=null;$("#download-predictions").hidden=true;$("#csv-result").textContent="";csvResults=await api("/predict-from-csv",{method:"POST",body:new FormData($("#csv-form"))});$("#csv-result").textContent=`Обработано: ${csvResults.rows.length}`+(csvResults.metrics?` · MAE: ${money(csvResults.metrics.mae)} · RMSE: ${money(csvResults.metrics.rmse)}`:"");$("#download-predictions").hidden=false;});
$("#download-predictions").onclick=()=>{const quote=x=>'"'+String(x??"").replaceAll('"','""')+'"';const columns=["brand","name","location","price","predicted_price","model_version"];const lines=[columns,...csvResults.rows.map(x=>columns.map(key=>x[key]??x.features[key]))];const url=URL.createObjectURL(new Blob(["\ufeff"+lines.map(row=>row.map(quote).join(",")).join("\n")],{type:"text/csv;charset=utf-8"}));const link=document.createElement("a");link.href=url;link.download="predictions.csv";link.click();URL.revokeObjectURL(url);};
document.querySelectorAll("[data-tab]").forEach(button=>button.onclick=action(async()=>{document.querySelectorAll(".tab").forEach(x=>x.hidden=x.id!==button.dataset.tab);document.querySelectorAll("[data-tab]").forEach(x=>x.classList.toggle("active",x===button));if(button.dataset.tab==="catalog")await loadCatalog();if(button.dataset.tab==="analytics")await loadAnalytics();if(button.dataset.tab==="model")await loadModel();}));
action(async()=>{const refs=await api("/api/reference");document.querySelectorAll("[data-reference]").forEach(select=>{for(const item of refs[select.dataset.reference]){const option=document.createElement("option");option.value=typeof item==="string"?item:item.id;option.textContent=typeof item==="string"?item:item.name;select.append(option);}});await loadRequests();})();

$("#manual-form").onsubmit=action(async()=>{$("#manual-result").textContent="";const values=Object.fromEntries(new FormData($("#manual-form")));for(const key of ["year","mileage","power","engine_displacement"]){values[key]=values[key]===""?null:Number(values[key]);}const result=await api("/predict",{method:"POST",body:JSON.stringify([values])});$("#manual-result").textContent=money(result[0].predicted_price);});
