// app/src/pages/GadsMaintenancePage.jsx
import { useState, useMemo, useEffect, useRef } from 'react'
import { useGadsMaintenance } from '../hooks/useGadsMaintenance.js'
import { supabase } from '../lib/supabase.js'

const TOUCH_BUCKETS = [
  { key: 0, label: 'Today',       color: '#22c55e' },
  { key: 1, label: '1 day ago',   color: '#4ade80' },
  { key: 2, label: '2 days ago',  color: '#a3e635' },
  { key: 3, label: '3 days ago',  color: '#facc15' },
  { key: 4, label: '4 days ago',  color: '#fb923c' },
  { key: 5, label: '5 days ago',  color: '#f97316' },
  { key: 6, label: '6 days ago',  color: '#ef4444' },
  { key: 7, label: '7d+ / Never', color: '#7f1d1d' },
]

function touchBucket(ts) {
  if (!ts) return 7
  return Math.min(Math.floor((Date.now() - new Date(ts).getTime()) / 86400000), 7)
}

function fmtRelative(ts) {
  if (!ts) return 'Never'
  const d = Math.floor((Date.now() - new Date(ts).getTime()) / 86400000)
  if (d === 0) return 'Today'
  if (d === 1) return 'Yesterday'
  return `${d}d ago`
}

function healthColor(lastGads, lastCR) {
  const worst = Math.max(touchBucket(lastGads), touchBucket(lastCR))
  return TOUCH_BUCKETS[worst].color
}

function bucketCounts(list, field) {
  const c = Array(8).fill(0)
  for (const a of list) c[touchBucket(a[field])]++
  return c
}

// ── Donut + pod toggles ────────────────────────────────────────────────────
const PIE_R    = 66
const PIE_CIRC = 2 * Math.PI * PIE_R
const PIE_GAP  = 2

function TouchDonut({ title, values, total, pods, activePod, onPodChange }) {
  const [ready,   setReady]   = useState(false)
  const [hovered, setHovered] = useState(null)

  useEffect(() => {
    const id = requestAnimationFrame(() => setReady(true))
    return () => cancelAnimationFrame(id)
  }, [])

  let accum = 0
  const slices = TOUCH_BUCKETS.map((b, i) => {
    const count = values[i] ?? 0
    const dash  = count > 0 && total > 0 ? Math.max((count / total) * PIE_CIRC - PIE_GAP, 0) : 0
    const slice = { ...b, count, pct: total > 0 ? count / total : 0, dash, offset: accum }
    accum += total > 0 ? (count / total) * PIE_CIRC : 0
    return slice
  }).filter(s => s.count > 0)

  const active = hovered !== null ? slices.find(s => s.key === hovered) : null

  const podBtnStyle = sel => ({
    padding: '3px 10px', borderRadius: 20, fontSize: 11, fontWeight: 600,
    fontFamily: 'inherit', cursor: 'pointer', transition: 'all 0.12s',
    background: sel ? 'rgba(77,142,247,0.15)' : 'transparent',
    border: `1px solid ${sel ? 'rgba(77,142,247,0.4)' : 'var(--border)'}`,
    color: sel ? 'var(--color-new)' : 'var(--text-muted)',
  })

  return (
    <div style={{ flex: 1, padding: '18px 20px', background: 'var(--surface-1)', border: '1px solid var(--border)', borderRadius: 'var(--radius-md)', display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '.07em', color: 'var(--text-dim)' }}>{title}</div>

      {/* Donut + legend row */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 20 }}>
        <div style={{ position: 'relative', width: 144, height: 144, flexShrink: 0 }}>
          <svg viewBox="0 0 200 200" style={{ width: '100%', height: '100%', transform: 'rotate(-90deg)' }}>
            <circle cx={100} cy={100} r={PIE_R} fill="none" stroke="var(--surface-3)" strokeWidth={22} />
            {slices.map(s => (
              <circle key={s.key} cx={100} cy={100} r={PIE_R}
                fill="none" stroke={s.color}
                strokeWidth={active?.key === s.key ? 28 : 22}
                strokeDasharray={ready ? `${s.dash} ${PIE_CIRC}` : `0 ${PIE_CIRC}`}
                strokeDashoffset={-s.offset}
                style={{ transition: 'stroke-dasharray 0.9s cubic-bezier(0.4,0,0.2,1), stroke-width 0.15s ease', cursor: 'pointer' }}
                onMouseEnter={() => setHovered(s.key)}
                onMouseLeave={() => setHovered(null)}
              />
            ))}
          </svg>
          <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', pointerEvents: 'none', gap: 2 }}>
            {active ? (
              <>
                <div style={{ fontSize: 22, fontWeight: 800, color: active.color, lineHeight: 1 }}>{active.count}</div>
                <div style={{ fontSize: 8, fontWeight: 700, color: active.color, textTransform: 'uppercase', letterSpacing: '.05em', textAlign: 'center', maxWidth: 64 }}>{active.label}</div>
                <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-dim)' }}>{(active.pct * 100).toFixed(0)}%</div>
              </>
            ) : (
              <>
                <div style={{ fontSize: 22, fontWeight: 800, color: 'var(--text-primary)', lineHeight: 1 }}>{total}</div>
                <div style={{ fontSize: 9, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '.05em' }}>Accounts</div>
              </>
            )}
          </div>
        </div>

        {/* Legend 2-col */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '5px 16px', flex: 1 }}>
          {slices.map(s => (
            <div key={s.key}
              onMouseEnter={() => setHovered(s.key)}
              onMouseLeave={() => setHovered(null)}
              style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'default', opacity: active && active.key !== s.key ? 0.25 : 1, transition: 'opacity 0.15s' }}
            >
              <div style={{ width: 7, height: 7, borderRadius: '50%', background: s.color, flexShrink: 0 }} />
              <div>
                <span style={{ fontSize: 14, fontWeight: 800, color: s.color }}>{s.count}</span>
                <span style={{ fontSize: 10, color: 'var(--text-muted)', marginLeft: 4 }}>{s.label}</span>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Pod toggle buttons */}
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', paddingTop: 10, borderTop: '1px solid var(--border-muted)' }}>
        <button onClick={() => onPodChange(null)} style={podBtnStyle(activePod === null)}>All</button>
        {pods.map(p => {
          const clr = podColor(p.id)
          const sel = activePod === p.id
          return (
            <button key={p.id} onClick={() => onPodChange(sel ? null : p.id)} style={{
              padding: '3px 10px', borderRadius: 20, fontSize: 11, fontWeight: 600,
              fontFamily: 'inherit', cursor: 'pointer', transition: 'all 0.12s',
              background: sel ? clr.bg : 'transparent',
              border: `1px solid ${sel ? clr.border : 'var(--border)'}`,
              color: sel ? clr.text : 'var(--text-muted)',
            }}>
              {p.name}
            </button>
          )
        })}
      </div>
    </div>
  )
}

// ── Pod color palette ──────────────────────────────────────────────────────
const POD_COLORS = [
  { bg: 'rgba(99,102,241,0.15)',  border: 'rgba(99,102,241,0.4)',  text: '#a5b4fc' },
  { bg: 'rgba(236,72,153,0.15)', border: 'rgba(236,72,153,0.4)', text: '#f9a8d4' },
  { bg: 'rgba(20,184,166,0.15)', border: 'rgba(20,184,166,0.4)', text: '#5eead4' },
  { bg: 'rgba(245,158,11,0.15)', border: 'rgba(245,158,11,0.4)', text: '#fcd34d' },
  { bg: 'rgba(239,68,68,0.15)',  border: 'rgba(239,68,68,0.4)',  text: '#fca5a5' },
  { bg: 'rgba(34,197,94,0.15)',  border: 'rgba(34,197,94,0.4)',  text: '#86efac' },
  { bg: 'rgba(249,115,22,0.15)', border: 'rgba(249,115,22,0.4)', text: '#fdba74' },
  { bg: 'rgba(6,182,212,0.15)',  border: 'rgba(6,182,212,0.4)',  text: '#67e8f9' },
]

const podColorCache = {}
let podColorIndex = 0

function podColor(podId) {
  if (!podId) return null
  if (!podColorCache[podId]) podColorCache[podId] = POD_COLORS[podColorIndex++ % POD_COLORS.length]
  return podColorCache[podId]
}

// ── Domain badge (primary + hover tooltip for rest) ───────────────────────
function DomainBadge({ websites }) {
  const [open, setOpen] = useState(false)
  if (!websites.length) return null
  const primary = websites[0].url || websites[0].location_name
  const rest    = websites.slice(1)

  return (
    <div style={{ position: 'relative', display: 'inline-flex', alignItems: 'center', gap: 4 }}
      onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}>
      <span style={{ fontSize: 10, fontWeight: 600, padding: '2px 8px', borderRadius: 10,
        background: 'rgba(77,142,247,0.08)', color: 'var(--color-new)',
        border: '1px solid rgba(77,142,247,0.2)', whiteSpace: 'nowrap',
        overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 180, display: 'block', cursor: 'default' }}>
        {primary}
      </span>
      {rest.length > 0 && (
        <span style={{ fontSize: 9, fontWeight: 700, padding: '2px 6px', borderRadius: 10,
          background: 'rgba(77,142,247,0.06)', color: 'var(--text-dim)',
          border: '1px solid var(--border-muted)', cursor: 'default', flexShrink: 0 }}>
          +{rest.length}
        </span>
      )}
      {open && rest.length > 0 && (
        <div style={{ position: 'absolute', bottom: 'calc(100% + 6px)', left: 0,
          background: 'var(--surface-3)', border: '1px solid var(--border)', borderRadius: 6,
          padding: '8px 12px', whiteSpace: 'nowrap', boxShadow: '0 4px 12px rgba(0,0,0,0.4)',
          zIndex: 100, pointerEvents: 'none' }}>
          {rest.map(w => (
            <div key={w.id} style={{ fontSize: 11, color: 'var(--color-new)', marginBottom: 3 }}>
              {w.url || w.location_name}
            </div>
          ))}
          <div style={{ position: 'absolute', top: '100%', left: 14,
            transform: 'translateX(-50%)', width: 0, height: 0,
            borderLeft: '5px solid transparent', borderRight: '5px solid transparent',
            borderTop: '5px solid var(--border)' }} />
          <div style={{ position: 'absolute', top: '100%', left: 14,
            transform: 'translateX(-50%) translateY(-1px)', width: 0, height: 0,
            borderLeft: '4px solid transparent', borderRight: '4px solid transparent',
            borderTop: '4px solid var(--surface-3)' }} />
        </div>
      )}
    </div>
  )
}

// ── Pod badge ──────────────────────────────────────────────────────────────
function PodBadge({ account }) {
  const [open, setOpen] = useState(false)
  if (!account.pod_name) return <span style={{ fontSize: 10, color: 'var(--text-dim)', fontStyle: 'italic' }}>No pod</span>

  const clr     = podColor(account.pod_id) ?? POD_COLORS[0]
  const members = [['CSS', account.pod_css], ['Ads', account.pod_ads], ['SEO', account.pod_seo], ['Social', account.pod_social]].filter(([, v]) => v)

  return (
    <div style={{ position: 'relative', display: 'inline-block' }}
      onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}>
      <span style={{ fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 10,
        background: clr.bg, color: clr.text, border: `1px solid ${clr.border}`,
        cursor: 'default', whiteSpace: 'nowrap' }}>
        {account.pod_name}
      </span>
      {open && (
        <div style={{ position: 'absolute', bottom: 'calc(100% + 6px)', left: 0, background: 'var(--surface-3)', border: '1px solid var(--border)', borderRadius: 6, padding: '8px 12px', whiteSpace: 'nowrap', boxShadow: '0 4px 12px rgba(0,0,0,0.4)', zIndex: 100, pointerEvents: 'none' }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: clr.text, marginBottom: 6 }}>{account.pod_name}</div>
          {members.map(([role, name]) => (
            <div key={role} style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 2 }}>
              <span style={{ color: 'var(--text-dim)', display: 'inline-block', minWidth: 38 }}>{role}</span>{name}
            </div>
          ))}
          <div style={{ position: 'absolute', top: '100%', left: 14, transform: 'translateX(-50%)', width: 0, height: 0, borderLeft: '5px solid transparent', borderRight: '5px solid transparent', borderTop: '5px solid var(--border)' }} />
          <div style={{ position: 'absolute', top: '100%', left: 14, transform: 'translateX(-50%) translateY(-1px)', width: 0, height: 0, borderLeft: '4px solid transparent', borderRight: '4px solid transparent', borderTop: '4px solid var(--surface-3)' }} />
        </div>
      )}
    </div>
  )
}

// ── Main page ──────────────────────────────────────────────────────────────
const TOUCH_OPTS = [
  { value: 'all', label: 'Any date'     },
  { value: '0',   label: 'Today'        },
  { value: '1-3', label: '1–3 days ago' },
  { value: '4-6', label: '4–6 days ago' },
  { value: '7+',  label: '7d+ / Never'  },
]

function inBucket(ts, filter) {
  if (filter === 'all') return true
  const b = touchBucket(ts)
  if (filter === '0')   return b === 0
  if (filter === '1-3') return b >= 1 && b <= 3
  if (filter === '4-6') return b >= 4 && b <= 6
  if (filter === '7+')  return b === 7
  return true
}

export default function GadsMaintenancePage() {
  const { accounts, podLocIds, loading, error } = useGadsMaintenance()

  // Pod run state — pod_id → { queuing, total, done, error }
  const [podRunState,        setPodRunState]        = useState({})
  const [podTranscribeState, setPodTranscribeState] = useState({})
  const didResume = useRef(false)

  // On mount: resume polling for any in-flight jobs surviving a page refresh
  useEffect(() => {
    if (didResume.current) return
    if (!podLocIds || Object.keys(podLocIds).length === 0) return
    didResume.current = true

    const allLocIds = Object.values(podLocIds).flatMap(p => p.locIds)
    if (allLocIds.length === 0) return

    supabase
      .from('locations')
      .select('id, pod_status, automation_status')
      .in('id', allLocIds)
      .then(({ data }) => {
        if (!data) return
        const byId = Object.fromEntries(data.map(r => [r.id, r]))
        Object.entries(podLocIds).forEach(([podId, { locIds }]) => {
          const rows = locIds.map(id => byId[id]).filter(Boolean)

          const podPending = rows.some(r => r.pod_status === 'pending')
          if (podPending) {
            const done = rows.filter(r => r.pod_status === 'done' || r.pod_status === 'failed').length
            setPodRunState(prev => ({ ...prev, [podId]: { queuing: false, total: locIds.length, done, error: null } }))
            startProgressPoll(podId, locIds, 'pod_status', setPodRunState)
          }

          const txPending = rows.some(r => r.automation_status === 'pending')
          if (txPending) {
            const done = rows.filter(r => r.automation_status === 'done' || r.automation_status === 'failed').length
            setPodTranscribeState(prev => ({ ...prev, [podId]: { queuing: false, total: locIds.length, done, error: null } }))
            startProgressPoll(podId, locIds, 'automation_status', setPodTranscribeState)
          }
        })
      })
  }, [podLocIds])

  function startProgressPoll(podId, locIds, statusCol, setState) {
    const interval = setInterval(async () => {
      const { data } = await supabase
        .from('locations')
        .select(statusCol)
        .in('id', locIds)
      if (!data) return
      const done = data.filter(r => r[statusCol] === 'done' || r[statusCol] === 'failed').length
      setState(prev => {
        const cur = prev[podId]
        if (!cur) { clearInterval(interval); return prev }
        const next = { ...cur, done }
        if (done >= locIds.length) clearInterval(interval)
        return { ...prev, [podId]: next }
      })
    }, 3000)
  }

  async function runPod(podId) {
    const podInfo = podLocIds[podId]
    if (!podInfo || podInfo.locIds.length === 0) return
    const { locIds } = podInfo
    setPodRunState(prev => ({ ...prev, [podId]: { queuing: true, total: locIds.length, done: 0, error: null } }))
    const { error } = await supabase
      .from('locations')
      .update({ pod_queued: 'gads_touch', pod_status: 'pending', pod_output: '' })
      .in('id', locIds)
    if (error) {
      setPodRunState(prev => ({ ...prev, [podId]: { queuing: false, total: locIds.length, done: 0, error: error.message } }))
    } else {
      setPodRunState(prev => ({ ...prev, [podId]: { queuing: false, total: locIds.length, done: 0, error: null } }))
      startProgressPoll(podId, locIds, 'pod_status', setPodRunState)
    }
  }

  async function runAll() {
    const allLocIds = Object.values(podLocIds).flatMap(p => p.locIds)
    if (allLocIds.length === 0) return

    const podInit = {}
    const txInit  = {}
    Object.entries(podLocIds).forEach(([podId, { locIds }]) => {
      podInit[podId] = { queuing: false, total: locIds.length, done: 0, error: null }
      txInit[podId]  = { queuing: false, total: locIds.length, done: 0, error: null }
    })

    const [podRes, txRes] = await Promise.all([
      supabase.from('locations')
        .update({ pod_queued: 'gads_touch', pod_status: 'pending', pod_output: '' })
        .in('id', allLocIds),
      supabase.from('locations')
        .update({ automation_queued: 'transcribe_calls', automation_status: 'pending', automation_output: '' })
        .in('id', allLocIds)
        .not('callrail_account_id', 'is', null),
    ])

    if (!podRes.error) {
      setPodRunState(podInit)
      Object.entries(podLocIds).forEach(([podId, { locIds }]) => {
        startProgressPoll(podId, locIds, 'pod_status', setPodRunState)
      })
    }
    if (!txRes.error) {
      setPodTranscribeState(txInit)
      Object.entries(podLocIds).forEach(([podId, { locIds }]) => {
        startProgressPoll(podId, locIds, 'automation_status', setPodTranscribeState)
      })
    }
  }

  async function runPodTranscribe(podId) {
    const podInfo = podLocIds[podId]
    if (!podInfo || podInfo.locIds.length === 0) return
    const { locIds } = podInfo
    setPodTranscribeState(prev => ({ ...prev, [podId]: { queuing: true, total: locIds.length, done: 0, error: null } }))
    const { error } = await supabase
      .from('locations')
      .update({ automation_queued: 'transcribe_calls', automation_status: 'pending', automation_output: '' })
      .in('id', locIds)
      .not('callrail_account_id', 'is', null)
    if (error) {
      setPodTranscribeState(prev => ({ ...prev, [podId]: { queuing: false, total: locIds.length, done: 0, error: error.message } }))
    } else {
      setPodTranscribeState(prev => ({ ...prev, [podId]: { queuing: false, total: locIds.length, done: 0, error: null } }))
      startProgressPoll(podId, locIds, 'automation_status', setPodTranscribeState)
    }
  }

  // Chart pod filters (independent per chart)
  const [gadsPod, setGadsPod] = useState(null)
  const [crPod,   setCrPod]   = useState(null)

  // Card filters
  const [search,     setSearch]     = useState('')
  const [filterPod,  setFilterPod]  = useState('all')
  const [filterGads, setFilterGads] = useState('all')
  const [filterCR,   setFilterCR]   = useState('all')

  const pods = useMemo(() => {
    const seen = new Map()
    for (const a of accounts) if (a.pod_id && !seen.has(a.pod_id)) seen.set(a.pod_id, a.pod_name)
    return [...seen.entries()].map(([id, name]) => ({ id, name })).sort((a, b) => a.name.localeCompare(b.name))
  }, [accounts])

  // Accounts for each chart (filtered by that chart's pod toggle)
  const gadsChartAccounts = useMemo(() => gadsPod ? accounts.filter(a => a.pod_id === gadsPod) : accounts, [accounts, gadsPod])
  const crChartAccounts   = useMemo(() => crPod   ? accounts.filter(a => a.pod_id === crPod)   : accounts, [accounts, crPod])

  const gadsBuckets = useMemo(() => bucketCounts(gadsChartAccounts, 'lastGadsTouched'),     [gadsChartAccounts])
  const crBuckets   = useMemo(() => bucketCounts(crChartAccounts,   'lastCallrailTouched'), [crChartAccounts])

  const filtered = useMemo(() => {
    let list = accounts
    if (search.trim()) {
      const q = search.toLowerCase()
      list = list.filter(a =>
        (a.gads_cid ?? '').includes(q) ||
        (a.gads_account_name ?? '').toLowerCase().includes(q) ||
        (a.account_name ?? '').toLowerCase().includes(q) ||
        a.websites.some(w => (w.url ?? '').toLowerCase().includes(q) || (w.location_name ?? '').toLowerCase().includes(q))
      )
    }
    if (filterPod === 'none') list = list.filter(a => !a.pod_id)
    else if (filterPod !== 'all') list = list.filter(a => a.pod_id === filterPod)
    list = list.filter(a => inBucket(a.lastGadsTouched,     filterGads))
    list = list.filter(a => inBucket(a.lastCallrailTouched, filterCR))
    return list
  }, [accounts, search, filterPod, filterGads, filterCR])

  if (loading) return <div style={{ padding: 24, color: 'var(--text-muted)' }}>Loading…</div>
  if (error)   return <div style={{ padding: 24, color: 'var(--color-overdue)' }}>Error: {error.message}</div>

  const selStyle  = { background: 'var(--surface-2)', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', padding: '5px 8px', color: 'var(--text-primary)', fontSize: 12, fontFamily: 'inherit', cursor: 'pointer' }
  const hasFilter = search || filterPod !== 'all' || filterGads !== 'all' || filterCR !== 'all'

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 16 }}>
        <h1 style={{ fontSize: 22, fontWeight: 800, color: 'var(--text-primary)', margin: 0 }}>GAds Maintenance</h1>
        <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-dim)' }}>{filtered.length} of {accounts.length} accounts</span>
      </div>

      {/* Side-by-side donuts with pod toggles */}
      <div style={{ display: 'flex', gap: 14, marginBottom: 20 }}>
        <TouchDonut
          title="GAds Touch"
          values={gadsBuckets}
          total={gadsChartAccounts.length}
          pods={pods}
          activePod={gadsPod}
          onPodChange={setGadsPod}
        />
        <TouchDonut
          title="CallRail Touch"
          values={crBuckets}
          total={crChartAccounts.length}
          pods={pods}
          activePod={crPod}
          onPodChange={setCrPod}
        />
      </div>

      {/* Pod bulk run buttons */}
      {pods.length > 0 && (
        <div style={{ background: 'var(--surface-1)', border: '1px solid var(--border)', borderRadius: 'var(--radius-md)', padding: '12px 18px', marginBottom: 16, display: 'flex', flexDirection: 'column', gap: 10 }}>
          {/* Run All row */}
          {(() => {
            const allBusy = Object.values(podRunState).some(s => s?.queuing) || Object.values(podTranscribeState).some(s => s?.queuing)
            const totalLocs = Object.values(podLocIds).reduce((n, p) => n + p.locIds.length, 0)
            return (
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, paddingBottom: 10, borderBottom: '1px solid var(--border-muted)' }}>
                <button
                  onClick={runAll}
                  disabled={allBusy || totalLocs === 0}
                  style={{
                    padding: '6px 18px', borderRadius: 20, fontSize: 12, fontWeight: 800,
                    fontFamily: 'inherit', cursor: allBusy || totalLocs === 0 ? 'not-allowed' : 'pointer',
                    background: 'rgba(77,142,247,0.15)', border: '1px solid rgba(77,142,247,0.4)',
                    color: 'var(--color-new)', opacity: allBusy ? 0.6 : 1, transition: 'all 0.15s',
                  }}
                >
                  ⚡ Run All Pods + Transcribe
                </button>
                <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>{pods.length} pods · {totalLocs} locations</span>
              </div>
            )
          })()}
          {/* GAds touch row */}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center' }}>
            <span style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '.07em', color: 'var(--text-dim)', marginRight: 4, minWidth: 80 }}>Run Pod</span>
            {pods.map(p => {
              const clr      = podColor(p.id) ?? POD_COLORS[0]
              const prs      = podRunState[p.id]
              const locs     = podLocIds[p.id]?.locIds ?? []
              const busy     = prs?.queuing
              const complete = prs && !busy && prs.done >= prs.total
              const pct      = prs ? Math.round((prs.done / prs.total) * 100) : 0
              return (
                <div key={p.id} style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <button
                      onClick={() => runPod(p.id)}
                      disabled={busy || locs.length === 0}
                      style={{
                        padding: '5px 14px', borderRadius: 20, fontSize: 12, fontWeight: 700,
                        fontFamily: 'inherit', cursor: busy || locs.length === 0 ? 'not-allowed' : 'pointer',
                        background: complete ? 'rgba(34,197,94,0.15)' : clr.bg,
                        border: `1px solid ${complete ? 'rgba(34,197,94,0.4)' : clr.border}`,
                        color: complete ? '#86efac' : clr.text,
                        opacity: busy || locs.length === 0 ? 0.6 : 1,
                        transition: 'all 0.15s',
                      }}
                    >
                      {busy ? `Queuing…` : `${p.name} (${locs.length})`}
                    </button>
                    {prs?.error && <span style={{ fontSize: 10, color: 'var(--color-overdue)' }}>{prs.error}</span>}
                  </div>
                  {prs && !busy && !prs.error && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                      <div style={{ height: 4, borderRadius: 2, background: 'var(--surface-3)', overflow: 'hidden', width: '100%' }}>
                        <div style={{ height: '100%', width: `${pct}%`, borderRadius: 2, transition: 'width 0.3s ease', background: complete ? '#22c55e' : clr.text }} />
                      </div>
                      <span style={{ fontSize: 9, color: complete ? '#86efac' : 'var(--text-dim)', textAlign: 'right' }}>
                        {complete ? `✓ ${prs.total} done` : `${prs.done} / ${prs.total}`}
                      </span>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
          {/* Transcribe row */}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center' }}>
            <span style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '.07em', color: 'var(--text-dim)', marginRight: 4, minWidth: 80 }}>Transcribe</span>
            {pods.map(p => {
              const prs      = podTranscribeState[p.id]
              const locs     = podLocIds[p.id]?.locIds ?? []
              const busy     = prs?.queuing
              const complete = prs && !busy && prs.done >= prs.total
              const pct      = prs ? Math.round((prs.done / prs.total) * 100) : 0
              return (
                <div key={p.id} style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <button
                      onClick={() => runPodTranscribe(p.id)}
                      disabled={busy || locs.length === 0}
                      style={{
                        padding: '5px 14px', borderRadius: 20, fontSize: 12, fontWeight: 700,
                        fontFamily: 'inherit', cursor: busy || locs.length === 0 ? 'not-allowed' : 'pointer',
                        background: complete ? 'rgba(34,197,94,0.15)' : 'rgba(167,139,250,0.12)',
                        border: `1px solid ${complete ? 'rgba(34,197,94,0.4)' : 'rgba(167,139,250,0.4)'}`,
                        color: complete ? '#86efac' : '#a78bfa',
                        opacity: busy || locs.length === 0 ? 0.6 : 1,
                        transition: 'all 0.15s',
                      }}
                    >
                      {busy ? `Queuing…` : `🎙 ${p.name}`}
                    </button>
                    {prs?.error && <span style={{ fontSize: 10, color: 'var(--color-overdue)' }}>{prs.error}</span>}
                  </div>
                  {prs && !busy && !prs.error && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                      <div style={{ height: 4, borderRadius: 2, background: 'var(--surface-3)', overflow: 'hidden', width: '100%' }}>
                        <div style={{ height: '100%', width: `${pct}%`, borderRadius: 2, transition: 'width 0.3s ease', background: complete ? '#22c55e' : '#a78bfa' }} />
                      </div>
                      <span style={{ fontSize: 9, color: complete ? '#86efac' : 'var(--text-dim)', textAlign: 'right' }}>
                        {complete ? `✓ ${prs.total} done` : `${prs.done} / ${prs.total}`}
                      </span>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Card filters */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 16, alignItems: 'center', flexWrap: 'wrap' }}>
        <input value={search} onChange={e => setSearch(e.target.value)}
          placeholder="Search domain, account, CID…"
          style={{ flex: 1, maxWidth: 240, background: 'var(--surface-2)', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', padding: '5px 10px', color: 'var(--text-primary)', fontSize: 13, fontFamily: 'inherit' }}
        />
        <select value={filterPod} onChange={e => setFilterPod(e.target.value)} style={selStyle}>
          <option value="all">All Pods</option>
          {pods.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
          <option value="none">No Pod</option>
        </select>
        <select value={filterGads} onChange={e => setFilterGads(e.target.value)} style={selStyle}>
          <option value="all">GAds: Any date</option>
          {TOUCH_OPTS.filter(o => o.value !== 'all').map(o => <option key={o.value} value={o.value}>GAds: {o.label}</option>)}
        </select>
        <select value={filterCR} onChange={e => setFilterCR(e.target.value)} style={selStyle}>
          <option value="all">CallRail: Any date</option>
          {TOUCH_OPTS.filter(o => o.value !== 'all').map(o => <option key={o.value} value={o.value}>CR: {o.label}</option>)}
        </select>
        {hasFilter && (
          <button onClick={() => { setSearch(''); setFilterPod('all'); setFilterGads('all'); setFilterCR('all') }}
            style={{ background: 'none', border: 'none', color: 'var(--text-dim)', fontSize: 12, fontFamily: 'inherit', cursor: 'pointer', padding: '5px 4px' }}>
            Clear
          </button>
        )}
      </div>

      {/* Card grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(290px, 1fr))', gap: 12 }}>
        {filtered.map(a => {
          const hColor    = healthColor(a.lastGadsTouched, a.lastCallrailTouched)
          const gadsColor = TOUCH_BUCKETS[touchBucket(a.lastGadsTouched)].color
          const crColor   = TOUCH_BUCKETS[touchBucket(a.lastCallrailTouched)].color

          return (
            <div key={a.gads_cid}
              style={{
                background: `color-mix(in oklch, ${hColor} 5%, var(--surface-1))`,
                border: `1px solid color-mix(in oklch, ${hColor} 35%, var(--border))`,
                borderRadius: 'var(--radius-md)', padding: '14px 16px',
                display: 'flex', flexDirection: 'column', gap: 6,
                transition: 'background 0.1s, border-color 0.1s',
              }}
              onMouseEnter={e => { e.currentTarget.style.background = `color-mix(in oklch, ${hColor} 10%, var(--surface-2))` }}
              onMouseLeave={e => { e.currentTarget.style.background = `color-mix(in oklch, ${hColor} 5%, var(--surface-1))` }}
            >
              {/* Google Ads account name + CID */}
              <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 8 }}>
                <div
                  title={a.gads_account_raw || a.gads_account_name || a.gads_cid}
                  style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', cursor: 'default' }}>
                  {a.gads_account_name || a.gads_cid}
                </div>
                <div style={{ fontSize: 10, fontFamily: 'monospace', color: 'var(--text-dim)', flexShrink: 0 }}>CID {a.gads_cid}</div>
              </div>

              {/* CRM Account */}
              {a.account_name && (
                <div style={{ fontSize: 11, color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {a.account_name}
                </div>
              )}

              {/* Primary domain badge + hover tooltip */}
              <DomainBadge websites={a.websites} />

              {/* Pod + touch indicators */}
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 6, paddingTop: 6, borderTop: `1px solid color-mix(in oklch, ${hColor} 20%, var(--border-muted))` }}>
                <PodBadge account={a} />
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 3 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                    <span style={{ fontSize: 9, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '.04em' }}>GAds</span>
                    <div style={{ width: 6, height: 6, borderRadius: '50%', background: gadsColor }} />
                    <span style={{ fontSize: 11, fontWeight: 700, color: gadsColor }}>{fmtRelative(a.lastGadsTouched)}</span>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                    <span style={{ fontSize: 9, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '.04em' }}>CR</span>
                    <div style={{ width: 6, height: 6, borderRadius: '50%', background: crColor }} />
                    <span style={{ fontSize: 11, fontWeight: 700, color: crColor }}>{fmtRelative(a.lastCallrailTouched)}</span>
                  </div>
                </div>
              </div>
            </div>
          )
        })}
        {filtered.length === 0 && (
          <div style={{ gridColumn: '1/-1', padding: 40, textAlign: 'center', color: 'var(--text-dim)', fontSize: 13 }}>No accounts match.</div>
        )}
      </div>
    </div>
  )
}
