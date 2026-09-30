"use strict";
const $ = id => document.getElementById(id);
const present = value => value !== null && value !== undefined && value !== "";
// Concept2 uses zero for some unrecorded physiological and stroke metrics.
const positive = value => present(value) && Number.isFinite(Number(value)) && Number(value) > 0;
const number = (value, digits = 0) => Number(value).toLocaleString(undefined, { maximumFractionDigits: digits });
const fixedNumber = (value, digits) => Number(value).toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
const setText = (id, value) => { $(id).textContent = value; };
const duration = tenths => {
  if (!present(tenths) || !Number.isFinite(Number(tenths))) return "—";
  const total = Math.round(Number(tenths));
  const hours = Math.floor(total / 36000), minutes = Math.floor(total / 600) % 60;
  const seconds = Math.floor(total / 10) % 60, fraction = total % 10;
  return (hours ? `${hours}:${String(minutes).padStart(2, "0")}` : `${minutes}`) + `:${String(seconds).padStart(2, "0")}` + (fraction ? `.${fraction}` : "");
};
const pace = (time, distance) => present(time) && Number(distance) > 0 ? duration(Number(time) * 500 / Number(distance)) : "—";
const dateLabel = value => {
  if (!value) return "Unknown date";
  // Preserve Concept2's recorded local date; browser timezone must not move it.
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (!match) return value;
  return new Date(Date.UTC(+match[1], +match[2] - 1, +match[3])).toLocaleDateString(undefined, { year:"numeric", month:"short", day:"numeric", timeZone:"UTC" });
};
const words = value => value ? String(value).replace(/([a-z])([A-Z])/g, "$1 $2").replace(/_/g, " ") : "—";
const targetValue = (key, value) => {
  if (!present(value)) return "—";
  if (key === "pace") return duration(value) + " / 500 m";
  return String(value) + ({stroke_rate:" spm",watts:" W",calories:" cal",heart_rate_zone:" (zone)"}[key] || "");
};
function validateIndex(value) {
  const validNumber = number => typeof number === "number" && Number.isFinite(number);
  const validActivity = row => row && Number.isInteger(row.id) && row.id > 0 &&
    typeof row.date === "string" && validNumber(row.distance) && row.distance >= 0 &&
    validNumber(row.time) && row.time >= 0;
  if (!value || value.schema_version !== 1 || !Array.isArray(value.activities) ||
      !validNumber(value.goal_meters) || value.goal_meters <= 0 ||
      !validNumber(value.total_meters) || value.total_meters < 0 ||
      value.activity_count !== value.activities.length || !value.activities.every(validActivity)) {
    throw new Error("This logbook uses an unsupported or damaged data format.");
  }
  return value;
}
document.querySelector(".skip-link").addEventListener("click", event => {
  event.preventDefault(); $("main").focus(); $("main").scrollIntoView();
});
const metric = (list, name, value) => {
  const wrapper = document.createElement("div"), dt = document.createElement("dt"), dd = document.createElement("dd");
  dt.textContent = name; dd.textContent = present(value) ? value : "—";
  wrapper.append(dt, dd); list.append(wrapper);
};
async function getJSON(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`Could not load this part of the logbook (${response.status}).`);
  return response.json();
}
let indexData, currentPage = 0, currentStrokes = [], routeVersion = 0, currentTooltipMark = null;
const PAGE_SIZE = 50;
function displayList() {
  const year = $("year-filter").value;
  const rows = indexData.activities.filter(row => year === "all" || row.date.slice(0,4) === year);
  const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  currentPage = Math.min(currentPage, pages - 1);
  $("activities").replaceChildren();
  for (const row of rows.slice(currentPage * PAGE_SIZE, (currentPage + 1) * PAGE_SIZE)) {
    const tr = document.createElement("tr"), date = document.createElement("td"), link = document.createElement("a");
    link.href = `#activity/${row.id}`; link.textContent = dateLabel(row.date); date.append(link); tr.append(date);
    for (const value of [number(row.distance) + " m", duration(row.time), pace(row.time, row.distance), positive(row.stroke_rate) ? number(row.stroke_rate) + " spm" : "—"]) {
      const cell = document.createElement("td"); cell.textContent = value; tr.append(cell);
    }
    $("activities").append(tr);
  }
  if (!rows.length) {
    const tr = document.createElement("tr"), td = document.createElement("td"); td.colSpan = 5;
    td.textContent = "No rowing activities in this view."; tr.append(td); $("activities").append(tr);
  }
  setText("page-status", `Page ${currentPage + 1} of ${pages} · ${number(rows.length)} activities`);
  $("previous-page").disabled = currentPage === 0; $("next-page").disabled = currentPage + 1 >= pages;
}
function renderParts(activity) {
  const workout = activity.workout || {};
  const isIntervals = (workout.intervals || []).length > 0;
  const parts = isIntervals ? workout.intervals : (workout.splits || []);
  $("parts-section").hidden = !parts.length;
  if (!parts.length) return;
  const inconsistent = !isIntervals && ["distance", "time"].some(key =>
    Number.isFinite(activity[key]) && parts.every(p => Number.isFinite(p[key])) &&
    Math.abs(parts.reduce((total, part) => total + part[key], 0) - activity[key]) > Math.max(2, parts.length));
  $("parts-note").hidden = !inconsistent;
  setText("parts-title", isIntervals ? "Intervals" : "Splits");
  const columns = [
    ["#", (_, i) => i + 1], ["Distance", p => present(p.distance) ? number(p.distance) + " m" : "—"],
    ["Duration", p => duration(p.time)], ["Pace / 500 m", p => pace(p.time, p.distance)],
    ["Stroke rate", p => positive(p.stroke_rate) ? number(p.stroke_rate) + " spm" : "—"]
  ];
  for (const key of ["average","min","max","ending","recovery","rest"]) {
    if (parts.some(p => positive(p.heart_rate?.[key]))) columns.push([`HR · ${words(key)}`, p => positive(p.heart_rate?.[key]) ? number(p.heart_rate[key])+" bpm" : "—"]);
  }
  if (isIntervals) columns.push(["Rest", p => duration(p.rest_time)], ["Rest distance", p => present(p.rest_distance) ? number(p.rest_distance) + " m" : "—"]);
  for (const key of ["type","machine"]) {
    if (parts.some(p => present(p[key]))) columns.push([words(key),p => words(p[key])]);
  }
  for (const [label, key] of [["Calories", "calories_total"], ["Watt-minutes", "wattminutes_total"]]) {
    const recorded = key === "wattminutes_total" ? positive : present;
    if (parts.some(p => recorded(p[key]))) columns.push([label, p => recorded(p[key]) ? number(p[key]) : "—"]);
  }
  for (const key of ["stroke_rate","heart_rate_zone","pace","watts","calories"]) {
    if (parts.some(p => present(p.targets?.[key]))) columns.push([`Target · ${words(key)}`,p => targetValue(key,p.targets?.[key])]);
  }
  $("parts-head").replaceChildren(); $("parts-body").replaceChildren();
  const header = document.createElement("tr");
  for (const [label] of columns) { const th = document.createElement("th"); th.scope = "col"; th.textContent = label; header.append(th); }
  $("parts-head").append(header);
  parts.forEach((part, i) => { const tr = document.createElement("tr"); for (const [, render] of columns) {const td = document.createElement("td"); td.textContent = render(part, i); tr.append(td);} $("parts-body").append(tr); });
}
function svgElement(tag, attrs, text) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  if (text !== undefined) node.textContent = text;
  return node;
}
function renderProgressGlobe(totalMeters, goalMeters) {
  const svg = $("progress-globe");
  const progress = Math.max(0, Math.min(1, totalMeters / goalMeters));
  const cx = 210, cy = 207, radius = 143, compression = .34;
  const tilt = 23.44 * Math.PI / 180;
  const depthScale = Math.sqrt(1 - compression * compression);
  const cosTilt = Math.cos(tilt), sinTilt = Math.sin(tilt);
  const u = {x:cosTilt,y:sinTilt,z:0};
  const v = {x:-compression*sinTilt,y:compression*cosTilt,z:depthScale};
  const axis = {x:depthScale*sinTilt,y:-depthScale*cosTilt,z:compression};
  const project = (latitude, longitude) => {
    const sinLat=Math.sin(latitude), cosLat=Math.cos(latitude), cosLon=Math.cos(longitude), sinLon=Math.sin(longitude);
    return {
      x:cx+radius*(axis.x*sinLat+(u.x*cosLon+v.x*sinLon)*cosLat),
      y:cy+radius*(axis.y*sinLat+(u.y*cosLon+v.y*sinLon)*cosLat),
      depth:axis.z*sinLat+(u.z*cosLon+v.z*sinLon)*cosLat
    };
  };
  const title=svgElement("title",{id:"globe-title"},"Lifetime rowing progress around Earth's equator");
  const percentText=fixedNumber(progress*100,2)+"%";
  const description=svgElement("desc",{id:"globe-description"},`${percentText} of the equatorial journey is complete. The dark arc is completed distance and the light arc is remaining distance.`);
  const defs=svgElement("defs",{}), gradient=svgElement("radialGradient",{id:"progress-sphere",cx:"31%",cy:"24%",r:"79%"});
  for(const [offset,color] of [["0%","#fbfcfa"],["48%","#e5eae5"],["80%","#d0d8d2"],["100%","#aebbb3"]]) gradient.append(svgElement("stop",{offset,"stop-color":color}));
  const clip=svgElement("clipPath",{id:"progress-sphere-clip"}); clip.append(svgElement("circle",{cx,cy,r:radius-.5})); defs.append(gradient,clip);
  svg.replaceChildren(title,description,defs);
  svg.append(svgElement("ellipse",{class:"orb-shadow",cx:228,cy:365,rx:105,ry:10}));
  const axisLength=radius*1.23;
  svg.append(svgElement("line",{class:"orb-axis",x1:cx-axis.x*axisLength,y1:cy-axis.y*axisLength,x2:cx+axis.x*axisLength,y2:cy+axis.y*axisLength}));
  svg.append(svgElement("circle",{class:"orb-haze",cx,cy,r:radius+2}));
  svg.append(svgElement("circle",{class:"orb-sphere",cx,cy,r:radius,fill:"url(#progress-sphere)"}));
  const grid=svgElement("g",{"clip-path":"url(#progress-sphere-clip)","aria-hidden":"true"}), curves=[], steps=120;
  for(const degrees of [-60,-30,30,60]) {
    const latitude=degrees*Math.PI/180, points=[];
    for(let i=0;i<=steps;i++) points.push(project(latitude,i/steps*Math.PI*2));
    curves.push(points);
  }
  for(let degrees=0;degrees<180;degrees+=30) {
    const longitude=degrees*Math.PI/180;
    const direction={x:u.x*Math.cos(longitude)+v.x*Math.sin(longitude),y:u.y*Math.cos(longitude)+v.y*Math.sin(longitude),z:u.z*Math.cos(longitude)+v.z*Math.sin(longitude)};
    const points=[];
    for(let i=0;i<=steps;i++) {
      const angle=i/steps*Math.PI*2;
      points.push({x:cx+radius*(axis.x*Math.sin(angle)+direction.x*Math.cos(angle)),y:cy+radius*(axis.y*Math.sin(angle)+direction.y*Math.cos(angle)),depth:axis.z*Math.sin(angle)+direction.z*Math.cos(angle)});
    }
    curves.push(points);
  }
  const pathByDepth=(points,front)=>{
    let d="",drawing=false;
    for(const point of points) {
      if((point.depth>=0)===front) {d+=`${drawing?"L":"M"}${point.x.toFixed(2)} ${point.y.toFixed(2)}`;drawing=true;}
      else drawing=false;
    }
    return d;
  };
  for(const front of [false,true]) for(const curve of curves) grid.append(svgElement("path",{class:`orb-grid ${front?"front":"back"}`,d:pathByDepth(curve,front)}));
  svg.append(grid);
  const leftGroup=svgElement("g",{"aria-hidden":"true"}), doneGroup=svgElement("g",{"aria-hidden":"true"});
  const pointAt=fraction=>project(0,Math.PI/2-fraction*Math.PI*2), segments=720;
  const addArc=(group,startFraction,endFraction,state,depthFraction)=>{
    if(endFraction<=startFraction) return;
    const start=pointAt(startFraction),end=pointAt(endFraction),middle=pointAt(depthFraction);
    const depthPosition=Math.max(0,Math.min(1,(middle.depth/depthScale+1)/2));
    const smoothDepth=depthPosition*depthPosition*(3-2*depthPosition);
    group.append(svgElement("line",{class:`orb-segment ${state}`,x1:start.x.toFixed(2),y1:start.y.toFixed(2),x2:end.x.toFixed(2),y2:end.y.toFixed(2),"stroke-width":(3.5+2.25*smoothDepth).toFixed(3),opacity:(.43+.54*smoothDepth).toFixed(3)}));
  };
  for(let i=0;i<segments;i++) {
    const start=i/segments,end=(i+1)/segments,extendedEnd=Math.min(1,(i+1.35)/segments),middle=(i+.5)/segments;
    if(progress<=start) addArc(leftGroup,start,extendedEnd,"left",middle);
    else if(progress>=end) addArc(doneGroup,start,extendedEnd,"done",middle);
    else {
      addArc(leftGroup,progress,extendedEnd,"left",middle);
      addArc(doneGroup,start,progress,"done",middle);
    }
  }
  svg.append(leftGroup,doneGroup);
  const origin=pointAt(0),head=pointAt(progress);
  svg.append(svgElement("circle",{class:"orb-origin",cx:origin.x,cy:origin.y,r:5.5}));
  if(progress>0&&progress<1) svg.append(svgElement("circle",{class:"orb-head",cx:head.x,cy:head.y,r:4.5}));
}
function renderYearLines() {
  const grouped=new Map();
  for(const activity of indexData.activities) {
    const year=activity.date.slice(0,4);
    if(!grouped.has(year)) grouped.set(year,[]);
    grouped.get(year).push(activity);
  }
  $("year-lines").replaceChildren();
  for(const year of [...grouped.keys()].sort().reverse()) {
    const rows=grouped.get(year).slice().sort((a,b)=>a.date.localeCompare(b.date)||a.id-b.id);
    const total=rows.reduce((sum,row)=>sum+row.distance,0);
    const section=document.createElement("section"),meta=document.createElement("div"),heading=document.createElement("h3"),stats=document.createElement("div"),rowCount=document.createElement("span"),distance=document.createElement("span"),marks=document.createElement("div");
    section.className="year-row"; section.setAttribute("aria-labelledby",`year-${year}`);
    meta.className="year-meta"; heading.className="year-label"; heading.id=`year-${year}`; heading.textContent=year;
    stats.className="year-stats"; rowCount.textContent=`${number(rows.length)} rows`; distance.textContent=`${fixedNumber(total/1000,3)} km`; stats.append(rowCount,distance); meta.append(heading,stats);
    marks.className="year-marks";
    for(const row of rows) {
      const units=Math.max(1,Math.round(row.distance/1000)),link=document.createElement("a");
      link.className="workout-mark"; link.href=`#activity/${row.id}`; link.style.width=`${Math.max(4,units*2.1).toFixed(2)}px`;
      link.dataset.date=dateLabel(row.date); link.dataset.distance=`${number(row.distance)} m`; link.dataset.duration=duration(row.time); link.dataset.pace=pace(row.time,row.distance); link.dataset.stroke=positive(row.stroke_rate)?`${number(row.stroke_rate)} spm`:"stroke rate not recorded";
      link.setAttribute("aria-label",`${link.dataset.date}, ${link.dataset.distance}, ${link.dataset.duration}, ${link.dataset.pace} per 500 meters, ${link.dataset.stroke}`);
      marks.append(link);
    }
    section.append(meta,marks); $("year-lines").append(section);
  }
}
function hideArchiveTooltip() {
  currentTooltipMark=null; $("archive-tooltip").hidden=true;
}
function showArchiveTooltip(mark) {
  currentTooltipMark=mark;
  setText("tooltip-date",mark.dataset.date); setText("tooltip-distance",mark.dataset.distance);
  setText("tooltip-metrics",`${mark.dataset.duration} · ${mark.dataset.pace} / 500 m · ${mark.dataset.stroke}`);
  const tooltip=$("archive-tooltip"),archive=$("archive"); tooltip.hidden=false; tooltip.classList.remove("below");
  const archiveRect=archive.getBoundingClientRect(),markRect=mark.getBoundingClientRect(),tooltipWidth=tooltip.offsetWidth;
  const idealLeft=markRect.left-archiveRect.left+markRect.width/2;
  const left=Math.max(tooltipWidth/2+8,Math.min(archiveRect.width-tooltipWidth/2-8,idealLeft));
  const top=markRect.top-archiveRect.top;
  const below=top<tooltip.offsetHeight+12;
  tooltip.classList.toggle("below",below); tooltip.style.left=`${left}px`; tooltip.style.top=`${below?markRect.bottom-archiveRect.top:top}px`;
}
function setupArchiveTooltip() {
  const lines=$("year-lines"),markFrom=target=>target instanceof Element?target.closest(".workout-mark"):null;
  lines.addEventListener("pointerover",event=>{const mark=markFrom(event.target);if(mark&&!mark.contains(event.relatedTarget))showArchiveTooltip(mark);});
  lines.addEventListener("pointerout",event=>{const mark=markFrom(event.target);if(mark&&!mark.contains(event.relatedTarget))hideArchiveTooltip();});
  lines.addEventListener("focusin",event=>{const mark=markFrom(event.target);if(mark)showArchiveTooltip(mark);});
  lines.addEventListener("focusout",event=>{const mark=markFrom(event.target);if(mark&&!mark.contains(event.relatedTarget))hideArchiveTooltip();});
  lines.addEventListener("click",hideArchiveTooltip);
  window.addEventListener("resize",()=>{if(currentTooltipMark)showArchiveTooltip(currentTooltipMark);});
}
function renderChart() {
  $("chart").replaceChildren();
  const key = $("chart-metric").value;
  const segments = []; let segment = [], previousT = null, previousD = null;
  for (const row of currentStrokes) {
    if (!Number.isFinite(row.t)) continue;
    if ((previousT !== null && row.t < previousT) || (previousD !== null && Number.isFinite(row.d) && row.d < previousD)) {
      if (segment.length) segments.push(segment); segment = [];
    }
    previousT = row.t; previousD = row.d;
    if (!Number.isFinite(row[key]) || row[key] <= 0) continue;
    segment.push([row.t / 10, key === "p" ? row[key] / 10 : row[key]]);
  }
  if (segment.length) segments.push(segment);
  const points = segments.flat();
  if (points.length < 2) {setText("stroke-message", "This metric was not recorded with enough samples to chart."); $("chart-note").hidden = true; return;}
  setText("stroke-message", `${number(points.length)} recorded samples · ${key === "p" ? "pace in minutes:seconds per 500 m" : key === "spm" ? "strokes per minute" : "beats per minute"}`);
  $("chart-note").hidden = false;
  let maxX = 1, minY = Infinity, maxY = -Infinity;
  for (const [x,y] of points) { maxX = Math.max(maxX,x); minY = Math.min(minY,y); maxY = Math.max(maxY,y); }
  const pad = Math.max(1,(maxY-minY)*.12); minY -= pad; maxY += pad;
  const width = 900, height = 290, left = 72, right = 24, top = 24, bottom = 45;
  const xPixel = x => left+x/maxX*(width-left-right), yPixel = y => top+(maxY-y)/(maxY-minY)*(height-top-bottom);
  const svg = svgElement("svg", {viewBox:`0 0 ${width} ${height}`,role:"img","aria-label":`${words(key === "p" ? "pace" : key === "spm" ? "stroke rate" : "heart rate")} over workout time`});
  for (let i=0; i<=4; i++) {
    const y = minY+(maxY-minY)*i/4, py = yPixel(y);
    svg.append(svgElement("line",{x1:left,x2:width-right,y1:py,y2:py,stroke:"var(--rule)"}));
    svg.append(svgElement("text",{x:left-12,y:py+5,"text-anchor":"end"}, key === "p" ? duration(y*10) : number(y)));
    const x = maxX*i/4;
    svg.append(svgElement("text",{x:xPixel(x),y:height-14,"text-anchor":"middle"},duration(x*10)));
  }
  for (let i=0;i<segments.length;i++) {
    // Only display points are decimated; the downloaded archive remains complete.
    const source = segments[i], step = Math.max(1,Math.ceil(source.length/1500));
    const sampled = source.filter((_,n) => n%step === 0 || n===source.length-1);
    svg.append(svgElement("polyline",{points:sampled.map(([x,y])=>`${xPixel(x)},${yPixel(y)}`).join(" "),fill:"none",stroke:["var(--accent)","var(--ink)","var(--warning)"][i%3],"stroke-width":2,"vector-effect":"non-scaling-stroke"}));
  }
  $("chart").append(svg);
}
async function displayActivity(id, version) {
  const activity = await getJSON(`./data/activities/${id}.json`);
  if (version !== routeVersion) return;
  if (!activity || String(activity.id) !== id || !Number.isFinite(activity.distance) || !Number.isFinite(activity.time)) {
    throw new Error("This activity uses an unsupported or damaged data format.");
  }
  $("message").hidden = true; $("activity-detail").hidden = false;
  setText("detail-title", number(activity.distance) + " m row");
  setText("detail-date", dateLabel(activity.date));
  setText("detail-kind", `${words(activity.workout_type)} · ${words(activity.type)}`);
  const sourceURL = activity.concept2_url;
  const safeSource = typeof sourceURL === "string" && /^https:\/\/log\.concept2\.com\/profile\/\d+\/log\/\d+$/.test(sourceURL);
  $("verify-link").hidden = !safeSource;
  if (safeSource) $("verify-link").href = sourceURL;
  $("metrics").replaceChildren();
  const values = [
    ["Work distance",number(activity.distance)+" m"], ["Work duration",duration(activity.time)],
    ["Average pace / 500 m",pace(activity.time,activity.distance)], ["Stroke rate",positive(activity.stroke_rate)?number(activity.stroke_rate)+" spm":null],
    ["Average heart rate",positive(activity.heart_rate?.average)?number(activity.heart_rate.average)+" bpm":null],
    ["Drag factor",positive(activity.drag_factor)?activity.drag_factor:null], ["Stroke count",positive(activity.stroke_count)?number(activity.stroke_count):null],
    ["Toward lifetime goal",number(activity.contribution_meters)+" m"]
  ];
  if (present(activity.rest_time)) values.push(["Rest time",duration(activity.rest_time)]);
  if (present(activity.rest_distance)) values.push(["Rest distance",number(activity.rest_distance)+" m"]);
  if (present(activity.calories_total)) values.push(["Calories",number(activity.calories_total)]);
  if (positive(activity.wattminutes_total)) values.push(["Watt-minutes",number(activity.wattminutes_total)]);
  for (const [label,value] of values) metric($("metrics"),label,value);
  renderParts(activity);
  const targets = Object.entries(activity.workout?.targets || {});
  $("targets-section").hidden = !targets.length; $("targets").replaceChildren();
  for (const [key,value] of targets) metric($("targets"),words(key),targetValue(key,value));
  $("comments-section").hidden = !activity.comments; setText("comments",activity.comments || "");
  $("extra-details").replaceChildren();
  const extras = [["Recorded local date/time",activity.date],["Recorded timezone",activity.timezone], ["UTC date/time",activity.date_utc],["Source",activity.source], ["Concept2 activity ID",activity.id], ["Weight class",activity.weight_class], ["Concept2 verified",present(activity.verified)?(activity.verified?"Yes":"No"):null], ["Ranked",present(activity.ranked)?(activity.ranked?"Yes":"No"):null]];
  for (const [key,value] of Object.entries(activity.heart_rate || {})) if (key!=="average") extras.push([`Heart rate · ${words(key)}`,positive(value)?`${value} bpm`:null]);
  for (const [label,value] of extras) {const dt=document.createElement("dt"),dd=document.createElement("dd");dt.textContent=label;dd.textContent=present(value)?value:"—";$("extra-details").append(dt,dd);}
  $("chart").replaceChildren(); $("chart-control").hidden = true; $("chart-note").hidden = true; currentStrokes = [];
  $("detail-title").focus({preventScroll:true}); window.scrollTo(0,0);
  if (activity.stroke_status !== "available") {setText("stroke-message","No stroke samples are available for this activity."); return;}
  setText("stroke-message","Loading stroke samples…");
  try {
    const data=await getJSON(`./data/strokes/${id}.json`);
    if (version!==routeVersion) return;
    if (!data || !Array.isArray(data.data) || data.data.some(row => !row || typeof row !== "object" || Array.isArray(row))) {
      throw new Error("These stroke samples use an unsupported or damaged data format.");
    }
    currentStrokes=data.data; $("chart-control").hidden=false; renderChart();
  } catch(error) {if(version===routeVersion) setText("stroke-message",error.message+" Reload this page to retry.");}
}
async function route() {
  const version=++routeVersion;
  $("activity-detail").hidden=true; hideArchiveTooltip();
  const homeTarget=!location.hash||location.hash==="#"||location.hash==="#journey"||location.hash==="#archive";
  if (homeTarget) {
    $("message").hidden=true;$("overview").hidden=false;displayList();
    if(location.hash==="#journey"||location.hash==="#archive") requestAnimationFrame(()=>$(location.hash.slice(1)).scrollIntoView());
    return;
  }
  $("overview").hidden=true;$("message").hidden=false;setText("message","Loading activity…");
  const match=/^#activity\/(\d+)$/.exec(location.hash);
  if(!match || !indexData.activities.some(row=>String(row.id)===match[1])) {setText("message","Activity not found. Use the site title to return to all activities.");return;}
  try {await displayActivity(match[1],version);} catch(error) {if(version===routeVersion) setText("message",error.message+" Reload this page to retry.");}
}
async function start() {
  try {
    indexData=validateIndex(await getJSON("./data/index.json"));
    document.title=indexData.title; document.querySelector(".brand-name").textContent=indexData.title;
    setText("sync-time",`Data updated ${new Date(indexData.last_successful_sync).toLocaleString()}`);
    setText("total-distance",fixedNumber(indexData.total_meters/1000,3));setText("goal-distance",number(indexData.goal_meters/1000));
    setText("percentage",fixedNumber(indexData.total_meters/indexData.goal_meters*100,2)+"%");
    setText("remaining",fixedNumber(indexData.remaining_meters/1000,3)+" km remaining");setText("activity-count",number(indexData.activity_count)+" recorded rows");
    setText("counting-policy",`Goal progress includes ${indexData.rowing_types.map(words).join(", ")}${indexData.include_rest_distance?" and recorded rest distance":"; work distance only"}. Line lengths and yearly distances show work distance.`);
    renderProgressGlobe(indexData.total_meters,indexData.goal_meters); renderYearLines(); setupArchiveTooltip();
    const years=[...new Set(indexData.activities.map(row=>row.date.slice(0,4)))].sort().reverse();
    for(const year of years) {const option=document.createElement("option");option.value=year;option.textContent=year;$("year-filter").append(option);}
    $("year-filter").addEventListener("change",()=>{currentPage=0;displayList();});
    $("previous-page").addEventListener("click",()=>{currentPage--;displayList();});
    $("next-page").addEventListener("click",()=>{currentPage++;displayList();});
    $("chart-metric").addEventListener("change",renderChart);
    window.addEventListener("hashchange",route);await route();
  } catch(error) {setText("message",error.message+" If opening a downloaded copy, serve the generated public directory over HTTP.");setText("sync-time","Logbook unavailable");}
}
start();
