const $ = s => document.querySelector(s);
const number = new Intl.NumberFormat('en-US', {maximumFractionDigits: 0});
let current = null, loading = false, dirty = false;
function node(tag, text, cls) { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; }
function fmt(value, kind) {
  if (value === null || value === undefined) return '—';
  if (kind === 'pct') return `${(value * 100).toFixed(1)}%`;
  if (kind === 'hours') return `${value.toFixed(2)} h`;
  return `${kind === 'money' ? '$' : ''}${number.format(value)}`;
}
function badge(gap, kind) {
  if (gap === null || gap === undefined) return node('span', 'No goal set', 'badge unset');
  const text = kind === 'pct' ? `${Math.abs(gap * 100).toFixed(1)} pp` : fmt(Math.abs(gap), kind);
  return node('span', gap === 0 ? 'On goal' : `${text} ${gap > 0 ? 'above' : 'below'}`, `badge ${gap < 0 ? 'behind' : ''}`);
}
function showNotice(message, cls = '') { const n = $('#notice'); n.textContent = message; n.className = `notice ${cls}`; n.hidden = !message; }
function rows(target, items, total, showSales = false) {
  const tbody = $(target); tbody.replaceChildren();
  for (const row of [...items, ...(total ? [total] : [])]) {
    const tr = node('tr'); if (row === total) tr.className = 'total';
    tr.append(node('td', row.label));
    if (showSales) tr.append(node('td', fmt(row.sales, 'money')));
    tr.append(node('td', fmt(row.actual, row.kind)),
              node('td', fmt(row.pace, row.kind)), node('td', fmt(row.goal, row.kind)));
    const cell = node('td'); cell.append(badge(row.gap, row.kind)); tr.append(cell); tbody.append(tr);
  }
}
function timeLabel(value) { if (!value) return 'Not available'; const d = new Date(value); return Number.isNaN(d.getTime()) ? 'Not available' : d.toLocaleString('en-US', {timeZone:'America/New_York',month:'short',day:'numeric',hour:'numeric',minute:'2-digit',timeZoneName:'short'}); }
function render(data) {
  current = data; const s = data.source, c = s.calendar;
  $('#report').hidden = false;
  $('#fetched').textContent = `Read ${timeLabel(s.generated_at)}`;
  $('#working-days').textContent = `Week: day ${c.week_elapsed} / ${c.week_total}  ·  Month: day ${c.month_elapsed} / ${c.month_total}`;
  $('#gp-cards').replaceChildren();
  data.gp_rows.forEach((row, i) => {
    const card = node('article', undefined, 'gp-card');
    card.append(node('h3', row.label), node('div', fmt(i < 2 ? row.pace : row.actual, 'money'), 'big-number'), node('p', i < 2 ? 'on pace' : 'per elapsed working day', 'muted small'));
    const detail = node('div', undefined, 'card-detail'); detail.append(node('span', `Actual ${fmt(row.actual,'money')}`), node('span', `Goal ${fmt(row.goal,'money')}`)); card.append(detail);
    const bar = node('progress', undefined, 'progress'); bar.max = 100;
    bar.value = row.goal > 0 ? Math.max(0, Math.min(100, 100 * (row.pace ?? row.actual ?? 0) / row.goal)) : 0;
    bar.setAttribute('aria-label', `${row.label}: ${Math.round(bar.value)}% of goal`);
    card.append(bar, badge(row.gap,'money')); $('#gp-cards').append(card);
  });
  rows('#kpis', data.kpis); rows('#techs', data.techs, data.totals.techs); rows('#advisors', data.advisors, data.totals.advisors, true);
  const fields = $('#goal-fields'), summary = node('div', undefined, 'personal-list');
  if (!dirty) fields.replaceChildren();
  for (const key of ['techs','advisors']) for (const person of data[key]) {
    if (!dirty) {
      const label = node('label', `${person.label} · ${key === 'techs' ? 'hours / week' : 'GP $ / week'}`);
      const input = node('input'); input.type = 'number'; input.min = '0'; input.max = '1000000'; input.step = '0.01'; input.dataset.key = person.goal_key; input.value = person.personal ?? ''; input.placeholder = 'Optional manager target'; label.append(input); fields.append(label);
    }
    if (person.personal !== null && person.personal !== undefined) {
      const item = node('div', undefined, 'personal-item'); item.append(node('strong', person.label), node('span', `Target ${fmt(person.personal,person.kind)} · `), badge(person.personal_gap,person.kind)); summary.append(item);
    }
  }
  if (!summary.children.length) summary.append(node('span','No manager targets yet. P&L goals are shown above.','muted small'));
  $('#personal-summary').replaceChildren(summary);
  $('#source-note').textContent = s.basis ? `Shop and advisor GP come from Paul’s saved daily actuals, through ${s.basis.actual_through || 'no actual days yet'}. Working days follow his shop schedule, including closed days. Shop GP pace uses the MTD daily average for the month, week and day. Technician and advisor pace uses WTD actuals. ARO, quotes and posted sales use the current Tekmetric warehouse.` : 'Working days and official goals come from P&L.';
  $('#freshness').textContent = `Tekmetric last synced: ${timeLabel(s.freshness.tekmetric)}. Report through ${s.as_of}. Refreshes every 60 seconds while this page is open.`;
  $('#reconciliation').hidden = !data.reconciliation;
  if (data.reconciliation) {
    const body=$('#reference-rows'); body.replaceChildren();
    for (const r of data.reconciliation.rows) {
      const tr=node('tr');
      tr.append(node('td',r.label),node('td',`${fmt(r.reference,r.kind)} / ${fmt(r.reference_goal,r.kind)}`),
                node('td',`${fmt(r.calculated,r.kind)} / ${fmt(r.goal,r.kind)}`),
                node('td',r.difference===null ? '—' : `${r.difference>0?'+':''}${fmt(r.difference,r.kind)}`));
      body.append(tr);
    }
    const notes=$('#reference-notes'); notes.replaceChildren();
    data.reconciliation.notes.forEach(text=>notes.append(node('p',text)));
  }
}
async function load(force = false) {
  if (loading) return; loading = true; $('#refresh').disabled = true;
  try {
    const query = new URLSearchParams({as_of: $('#as-of').value}); if(force) query.set('refresh','1');
    const response = await fetch(`/api/report?${query}`, {cache:'no-store'});
    if(response.status === 401) { location.href='/login'; return; }
    const data = await response.json(); if(!response.ok) throw Error(data.error || 'Unable to refresh the report.');
    render(data);
    const missing = data.source.basis?.missing_actual_dates || [];
    showNotice(missing.length ? `Paul’s daily actuals are not yet available for ${missing.join(', ')}. Forecast rows are excluded from GP.` : '', missing.length ? 'warning' : '');
  } catch(error) {
    showNotice(`${error.message}${current ? ' The numbers below are from the last successful refresh.' : ''}`, current ? 'warning' : 'error');
  } finally {loading=false; $('#refresh').disabled=false;}
}
$('#refresh').addEventListener('click',()=>load(true));
$('#print').addEventListener('click',()=>{ if(current && !loading) window.print(); });
$('#as-of').addEventListener('change',()=>{ current=null; $('#report').hidden=true; const u=new URL(location.href); u.searchParams.set('as_of',$('#as-of').value); history.replaceState(null,'',u); showNotice('Loading P&L numbers…'); load(); });
$('#toggle-goals').addEventListener('click',()=>{const form=$('#goals-form'); form.hidden=!form.hidden; $('#toggle-goals').setAttribute('aria-expanded',String(!form.hidden));});
$('#goals-form').addEventListener('input',()=>{dirty=true;});
$('#goals-form').addEventListener('submit',async event=>{
  event.preventDefault(); const button=event.target.querySelector('button'); button.disabled=true;
  try {
    const values={}; $('#goal-fields').querySelectorAll('input').forEach(input=>{values[input.dataset.key]=input.value;});
    const response=await fetch(`/api/goals?as_of=${encodeURIComponent($('#as-of').value)}`,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':$('meta[name="csrf-token"]').content},body:JSON.stringify(values)});
    if(response.status===401){location.href='/login';return;}
    const data=await response.json(); if(!response.ok) throw Error(data.error || 'Could not save manager goals.');
    dirty=false; await load(); showNotice('Manager goals saved.');
  }catch(error){showNotice(error.message,'error');}finally{button.disabled=false;}
});
load(); setInterval(()=>{if(!document.hidden) load();},60000);
