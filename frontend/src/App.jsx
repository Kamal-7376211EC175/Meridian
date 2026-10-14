import { useState, useEffect, useCallback } from 'react'
const usd = n => '$' + Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })
const usd2 = n => '$' + Number(n || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const cls = s => (s || '').split(' ')[0]
let UID = 4
async function api(p, o = {}) {
  const r = await fetch('/api' + p, { ...o, headers: { 'Content-Type': 'application/json', 'X-User-Id': UID } })
  const j = await r.json().catch(() => ({})); if (!r.ok) throw new Error(j.detail || r.statusText); return j
}
const post = (p, b) => api(p, { method: 'POST', body: JSON.stringify(b || {}) })
const Pill = ({ v }) => <span className={'pill ' + cls(v)}>{v}</span>
const Bars = ({ rows, k, v = 'amount', fmt = usd }) => { const m = Math.max(...rows.map(r => r[v] || 0), 1); return rows.map(r => <div className="bar" key={r[k]}><span>{r[k]}</span><div><i style={{ width: (r[v] / m * 100) + '%' }} /></div><b>{fmt(r[v])}</b></div>) }
const days = d => Math.round((new Date(d) - new Date('2026-10-14')) / 864e5)
const Due = ({ d }) => { const n = days(d); return <span style={{ color: n < 0 ? '#b3262b' : n <= 3 ? '#9a5d00' : 'inherit', fontWeight: n <= 3 ? 600 : 400 }}>{d} ({n < 0 ? Math.abs(n) + 'd overdue' : n + 'd left'})</span> }

function Dashboard({ open }) {
  const [d, setD] = useState(null); useEffect(() => { api('/dashboard').then(setD) }, [])
  if (!d) return <p>Loading…</p>; const k = d.kpis, m = d.success_metrics, rc = k.reconciliation
  const K = [['Total receipts', usd(k.total_receipts), 'All agencies, synthetic', '#0f9d8a'], ['Unapplied cash', usd(k.unapplied_cash), 'Received, not matched to an invoice', '#f2a93b'], ['Overdue receivables', usd(k.overdue_receivables), 'Past due date', '#e5484d'], ['Carrier payables due', usd(k.carrier_payables_due), 'Due within 14 days', '#0b3c5d'], ['Commission exceptions', k.commission_exceptions.count, usd(k.commission_exceptions.amount) + ' in variance', '#7c5cff'], ['Reconciliations', `${rc.Matched || 0} / ${(rc.Matched || 0) + (rc.Unmatched || 0)}`, (rc.Unmatched || 0) + ' unmatched accounts', '#0f9d8a']]
  return <>
    <div className="head"><div><h1>Finance command center</h1><p>Where money is stuck, what is late, and what to fix first. As of {d.as_of}.</p></div></div>
    <div className="grid kpis">{K.map(([a, b, c, col]) => <div key={a} className="card kpi" style={{ '--c': col }}><small>{a}</small><b>{b}</b><span>{c}</span></div>)}</div>
    <div className="grid two">
      <div className="card"><h2>Fix these first</h2><table><thead><tr><th>ID</th><th>Category</th><th>Agency</th><th>Amount</th><th>Severity</th></tr></thead><tbody>
        {d.top.map(e => <tr className="row" key={e.id} onClick={() => open(e.id)}><td><b>{e.id}</b></td><td>{e.category}</td><td>{e.agency}</td><td>{usd(e.amount)}</td><td><Pill v={e.severity} /></td></tr>)}</tbody></table></div>
      <div className="card" style={{ display: 'flex', gap: 20, alignItems: 'center' }}><div className="ring" style={{ '--p': k.close_readiness }}><b>{k.close_readiness}%</b></div>
        <div><h2>Month-end close readiness</h2><p style={{ color: 'var(--mute)' }}>Tasks done plus half credit for in-progress. Target date Oct 30.</p></div></div></div>
    <div className="grid three">
      <div className="card"><h2>Exposure by category</h2><Bars rows={d.by_category} k="category" /></div>
      <div className="card"><h2>Exposure by agency</h2><Bars rows={d.by_agency} k="agency" /></div>
      <div className="card"><h2>Is the tool helping?</h2><Bars rows={[{ k: 'Alerts before grouping', n: m.alerts_before_grouping }, { k: 'Alerts after grouping', n: m.alerts_after_grouping }]} k="k" v="n" fmt={x => x} />
        <p style={{ color: 'var(--mute)' }}>{m.duplicate_alerts_removed} duplicate alerts merged into groups. {m.open_exceptions} open, {m.resolved} resolved.</p></div></div></>
}

function Workbench({ open }) {
  const [rows, setRows] = useState([]); const [f, setF] = useState({ q: '', category: '', severity: '', status: '' })
  useEffect(() => { const p = new URLSearchParams(Object.entries(f).filter(([, v]) => v)); api('/exceptions?' + p).then(setRows) }, [f])
  const S = (k, opts, label) => <select value={f[k]} onChange={e => setF({ ...f, [k]: e.target.value })}><option value="">{label}</option>{opts.map(o => <option key={o}>{o}</option>)}</select>
  return <><div className="head"><div><h1>Exception workbench</h1><p>{rows.length} exceptions, ranked by priority score.</p></div></div>
    <div className="filters"><input placeholder="Search ID, agency, owner, client…" value={f.q} onChange={e => setF({ ...f, q: e.target.value })} />
      {S('category', ['Unapplied Cash', 'Probable Duplicate', 'Overdue Receivable', 'Carrier Settlement', 'Commission Variance', 'Close Blocker'], 'All categories')}{S('severity', ['Critical', 'High', 'Medium', 'Low'], 'All severities')}{S('status', ['Open', 'Investigating', 'Pending Approval', 'Resolved'], 'All statuses')}</div>
    <div className="card" style={{ padding: 0, overflow: 'auto' }}><table><thead><tr><th>ID</th><th>Agency</th><th>Category</th><th>Amount</th><th>Age</th><th>Severity</th><th>Deadline</th><th>Owner</th><th>Status</th></tr></thead><tbody>
      {rows.map(e => <tr className="row" key={e.id} onClick={() => open(e.id)}><td><b>{e.id}</b></td><td>{e.agency}</td><td>{e.category}{e.dup_group && <small style={{ color: 'var(--mute)' }}> · {e.dup_group}</small>}</td><td>{usd2(e.amount)}</td><td>{e.age_days}d</td><td><Pill v={e.severity} /> <small>{e.score}</small></td><td><Due d={e.deadline} /></td><td>{e.owner}</td><td><Pill v={e.status} /></td></tr>)}</tbody></table></div></>
}

const Mini = ({ rows, cols }) => rows?.length ? <table className="mini"><thead><tr>{cols.map(c => <th key={c}>{c}</th>)}</tr></thead><tbody>{rows.map((r, i) => <tr key={i}>{cols.map(c => <td key={c}>{typeof r[c] === 'number' && r[c] > 99 ? usd2(r[c]) : String(r[c] ?? '–')}</td>)}</tr>)}</tbody></table> : null

function Drawer({ id, close, user, refresh }) {
  const [d, setD] = useState(null), [a, setA] = useState(null), [msg, setMsg] = useState(null), [note, setNote] = useState(''), [act, setAct] = useState('ledger_posting'), [draft, setDraft] = useState(null)
  const load = useCallback(() => { api('/exceptions/' + id).then(setD); api(`/exceptions/${id}/analysis`).then(setA) }, [id]); useEffect(load, [load])
  const run = async (fn, ok) => { try { await fn(); setMsg({ ok: ok }); load(); refresh() } catch (e) { setMsg({ err: e.message }) } }
  if (!d || !a) return <div className="over"><div className="drawer">Loading…</div></div>
  const e = d.exception, L = d.linked, ro = user.role === 'viewer'
  return <div className="over" onClick={close}><div className="drawer" onClick={x => x.stopPropagation()}>
    <div style={{ display: 'flex', justifyContent: 'space-between' }}><div><h1>{e.id} <Pill v={e.severity} /></h1><p style={{ color: 'var(--mute)', margin: '4px 0' }}>{e.category} · {e.agency} · {usd2(e.amount)} · {e.age_days}d old</p></div><button className="btn alt" onClick={close}>Close</button></div>
    {msg?.err && <div className="err">{msg.err}</div>}{msg?.ok && <div className="ok">{msg.ok}</div>}
    <div className="card sec"><h3>Verified facts <span className="tag v">From records</span></h3><div className="facts">{a.verified_facts.map(([k, v]) => <div key={k}><span>{k}</span><b>{String(v)}</b></div>)}<div><span>Materiality</span><b>{a.materiality.level} ({a.materiality.pct_of_agency_receipts}% of agency receipts)</b></div><div><span>Deadline</span><b><Due d={e.deadline} /></b></div></div></div>
    <div className="card sec"><h3>AI hypotheses <span className="tag h">Not verified</span></h3>
      {a.hypotheses.map((h, i) => <div className="hyp" key={i}><b>{h.text}</b><small>Basis: {h.basis} · Confidence {Math.round(h.confidence * 100)}%</small><div className="conf"><i style={{ width: h.confidence * 100 + '%' }} /></div></div>)}
      <b>Recommended next steps</b><ol>{a.recommended_steps.map(s => <li key={s}>{s}</li>)}</ol>
      {a.duplicate_group.length > 0 && <><b>Probable duplicate group</b><Mini rows={a.duplicate_group} cols={['id', 'payer', 'amount', 'received', 'method']} /></>}
      <small style={{ color: 'var(--mute)' }}>{a.guardrail}</small></div>
    <div className="card sec"><h3>Linked records</h3>
      {L.receipts && <><b>Receipts</b><Mini rows={L.receipts} cols={['id', 'payer', 'amount', 'received', 'reference', 'invoice_id']} /></>}
      {L.invoices && <><b>Invoices</b><Mini rows={L.invoices} cols={['id', 'client', 'amount', 'paid', 'due']} /></>}
      {L.statements && <><b>Carrier statements</b><Mini rows={L.statements} cols={['id', 'carrier', 'period', 'expected', 'paid', 'due_date']} /></>}
      {L.commissions && <><b>Commission records</b><Mini rows={L.commissions} cols={['id', 'producer', 'policy', 'expected', 'paid']} /></>}
      {L.close_tasks && <><b>Close task</b><Mini rows={L.close_tasks} cols={['id', 'name', 'owner', 'due', 'status']} /></>}
      <b>Reconciliation results</b><Mini rows={L.reconciliations} cols={['account', 'book_balance', 'bank_balance', 'status']} /></div>
    <div className="card sec"><h3>Resolution controls</h3>{ro && <div className="err">Viewers have read-only access.</div>}
      <div className="f"><select disabled={ro} value={e.owner} onChange={x => run(() => post(`/exceptions/${id}/assign`, { owner: x.target.value }), 'Owner updated')}>{['Priya Nair', 'Marcus Lee', 'Sofia Alvarez', 'Daniel Okoye'].map(o => <option key={o}>{o}</option>)}</select>
        <select disabled={ro} value={e.status} onChange={x => run(() => post(`/exceptions/${id}/status`, { status: x.target.value }), 'Status updated')}>{['Open', 'Investigating', 'Pending Approval', 'Resolved'].map(o => <option key={o}>{o}</option>)}</select>
        <button className="btn alt" onClick={() => post(`/exceptions/${id}/notify`).then(setDraft).catch(x => setMsg({ err: x.message }))}>Prepare notification</button></div>
      {draft && <div className="ok"><b>{draft.subject}</b><br />To: {draft.to}<br />{draft.body}<br /><i>{draft.note}</i></div>}
      <div className="f"><input placeholder="Add investigation note" value={note} onChange={x => setNote(x.target.value)} /><button className="btn" disabled={!note} onClick={() => run(async () => { await post(`/exceptions/${id}/notes`, { text: note }); setNote('') }, 'Note added')}>Add note</button></div>
      <div className="f"><select value={act} onChange={x => setAct(x.target.value)}><option value="ledger_posting">Ledger posting</option><option value="payment">Payment</option><option value="commission_change">Commission change</option></select>
        <button className="btn go" onClick={() => run(() => post(`/exceptions/${id}/approvals`, { action_type: act }), 'Approval requested')}>Request approval</button></div>
      <small style={{ color: 'var(--mute)' }}>Approving records a decision only. Nothing is paid, posted or changed automatically.</small></div>
    <div className="card sec"><h3>Notes, approvals and history</h3>
      {d.notes.map(n => <p key={n.id}><b>{n.author}</b>: {n.text}</p>)}{d.approvals.map(x => <p key={x.id}>Approval #{x.id} · {x.action_type} · <Pill v={x.status} /> {x.decided_by && 'by ' + x.decided_by}</p>)}
      <Mini rows={d.history.slice(0, 8)} cols={['ts', 'actor', 'action', 'detail']} /></div></div></div>
}

function Approvals({ refresh }) {
  const [r, setR] = useState([]), [m, setM] = useState(null); const load = () => api('/approvals').then(setR); useEffect(() => { load() }, [])
  const dec = async (id, approve) => { try { const x = await post(`/approvals/${id}/decide`, { approve }); setM({ ok: x.note }) } catch (e) { setM({ err: e.message }) } load(); refresh() }
  return <><div className="head"><div><h1>Approvals</h1><p>Payments, ledger postings and compensation changes need a controller.</p></div></div>{m?.err && <div className="err">{m.err}</div>}{m?.ok && <div className="ok">{m.ok}</div>}
    <div className="card" style={{ padding: 0 }}><table><thead><tr><th>#</th><th>Exception</th><th>Action</th><th>Amount</th><th>Requested by</th><th>Status</th><th></th></tr></thead><tbody>
      {r.map(a => <tr key={a.id}><td>{a.id}</td><td>{a.exception_id}</td><td>{a.action_type}</td><td>{usd2(a.amount)}</td><td>{a.requested_by}</td><td><Pill v={a.status} /></td><td>{a.status === 'Pending' && <><button className="btn go" onClick={() => dec(a.id, true)}>Approve</button> <button className="btn no" onClick={() => dec(a.id, false)}>Reject</button></>}</td></tr>)}
      {!r.length && <tr><td colSpan="7">No requests yet. Open an exception and choose Request approval.</td></tr>}</tbody></table></div></>
}

function Audit() {
  const [r, setR] = useState([]); useEffect(() => { api('/audit').then(setR) }, [])
  return <><div className="head"><div><h1>Audit trail</h1><p>Every view, change, denial and decision. Entries are hash-chained.</p></div></div>
    <div className="card" style={{ padding: 0, overflow: 'auto' }}><table className="mini"><thead><tr><th>Time (UTC)</th><th>Actor</th><th>Role</th><th>Action</th><th>Entity</th><th>Detail</th><th>Hash</th></tr></thead><tbody>
      {r.map(a => <tr key={a.id}><td>{a.ts}</td><td>{a.actor}</td><td>{a.role}</td><td><Pill v={['DENIED', 'BLOCKED'].includes(a.action) ? 'Critical' : 'Low'} /> {a.action}</td><td>{a.entity}</td><td>{a.detail}</td><td><code>{a.hash.slice(0, 10)}</code></td></tr>)}</tbody></table></div></>
}

function Copilot() {
  const [log, setLog] = useState([]), [q, setQ] = useState(''), [busy, setBusy] = useState(false)
  const ask = async t => { if (!t) return; setBusy(true); setQ(''); setLog(l => [...l, { q: t }]); try { const a = await post('/copilot', { question: t }); setLog(l => [...l, { a }]) } catch (e) { setLog(l => [...l, { a: { answer: e.message, evidence: [], assumptions: [], confidence: 0, source: 'error' } }]) } setBusy(false) }
  return <><div className="head"><div><h1>Finance copilot</h1><p>Answers come from the database. The model only words them.</p></div></div>
    <div className="sug">{['What cash remains unapplied?', 'Which carrier settlements are at risk?', 'Why might month-end close be delayed?', 'Which commission discrepancies need review first?'].map(s => <button key={s} onClick={() => ask(s)}>{s}</button>)}</div>
    <div className="chat">{log.map((m, i) => m.q ? <div key={i} className="q">{m.q}</div> : <div key={i} className="a"><pre>{m.a.answer}</pre>
      {m.a.evidence.length > 0 && <Mini rows={m.a.evidence.map(e => ({ Evidence: e.id, Category: e.category, Amount: e.amount, Severity: e.severity }))} cols={['Evidence', 'Category', 'Amount', 'Severity']} />}
      <p className="mini">Confidence <b>{Math.round(m.a.confidence * 100)}%</b> · Source {m.a.source}</p><ul className="mini">{m.a.assumptions.map(s => <li key={s}>{s}</li>)}</ul></div>)}{busy && <div className="a">Checking the numbers…</div>}</div>
    <div className="f" style={{ marginTop: 16 }}><input value={q} onChange={e => setQ(e.target.value)} onKeyDown={e => e.key === 'Enter' && ask(q)} placeholder="Ask about cash, carriers, commissions or close…" /><button className="btn" onClick={() => ask(q)}>Ask</button></div></>
}

export default function App() {
  const [page, setPage] = useState('dash'), [users, setUsers] = useState([]), [u, setU] = useState(4), [sel, setSel] = useState(null), [tick, setTick] = useState(0)
  useEffect(() => { api('/users').then(setUsers) }, []); UID = u; const cur = users.find(x => x.id === u) || { role: 'controller' }
  const pages = { dash: ['Dashboard', <Dashboard open={setSel} />], ex: ['Exception workbench', <Workbench open={setSel} />], ap: ['Approvals', <Approvals refresh={() => setTick(t => t + 1)} />], au: ['Audit trail', <Audit />], co: ['Finance copilot', <Copilot />] }
  return <div className="app"><aside className="side"><div className="logo"><i />Meridian</div>
    {Object.entries(pages).map(([k, [n]]) => <button key={k} className={'nav' + (page === k ? ' on' : '')} onClick={() => setPage(k)}>{n}</button>)}<div className="sp" />
    <label>Signed in as<select value={u} onChange={e => setU(+e.target.value)}>{users.map(x => <option key={x.id} value={x.id}>{x.name} ({x.role})</option>)}</select></label><span className="chip">Synthetic data only</span></aside>
    <main key={page + u + tick}>{pages[page][1]}</main>{sel && <Drawer id={sel} close={() => setSel(null)} user={cur} refresh={() => setTick(t => t + 1)} />}</div>
}
