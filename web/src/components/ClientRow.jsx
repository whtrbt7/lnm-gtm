import { useState, useCallback } from 'react'
import StatusChip from './StatusChip.jsx'
import LogPanel from './LogPanel.jsx'
import { runJob } from '../api/jobs.js'

const STEPS = [
  { action: 'create-container', label: 'Create Container', needsChrome: true },
  { action: 'setup-tags',       label: 'Setup Tags',       needsChrome: false },
  { action: 'inject-wordpress', label: 'Inject WP',        needsChrome: false },
]

const SCHEDULER_LABELS = {
  autoops:    { label: 'AutoOps',    cls: 'chip-blue' },
  shopgenie:  { label: 'ShopGenie',  cls: 'chip-blue' },
  oktomocket: { label: 'OktoRocket', cls: 'chip-blue' },
}

function fmtPhone(raw) {
  if (!raw) return null
  const d = raw.replace(/\D/g, '')
  if (d.length === 10) return `(${d.slice(0,3)}) ${d.slice(3,6)}-${d.slice(6)}`
  if (d.length === 11 && d[0] === '1') return `(${d.slice(1,4)}) ${d.slice(4,7)}-${d.slice(7)}`
  return raw
}

export default function ClientRow({ loc, chromeUp, onRefresh, visibleCols, colSpan }) {
  const [activeJob, setActiveJob] = useState(null)
  const [lines, setLines]         = useState([])
  const [running, setRunning]     = useState(false)

  const domain = loc.brands?.domain ?? loc.url?.replace(/^https?:\/\//, '').replace(/\/$/, '') ?? '—'

  const canRun = useCallback((step) => {
    if (running) return false
    if (step.needsChrome && !chromeUp) return false
    return true
  }, [running, chromeUp])

  function start(action) {
    setActiveJob(action)
    setLines([])
    setRunning(true)
    runJob(
      action,
      loc.gads_cid,
      (text) => setLines(prev => [...prev, text]),
      (exitCode) => {
        setRunning(false)
        setLines(prev => [...prev, exitCode === 0 ? '✓ Done.' : `✗ Exited with code ${exitCode}`])
        if (exitCode === 0) onRefresh()
      },
    )
  }

  function close() { setActiveJob(null); setLines([]) }

  const isVisible = key => visibleCols.some(c => c.key === key)

  return (
    <>
      <tr>
        {isVisible('name') && (
          <td style={{ minWidth: 200 }}>
            <div style={{ fontWeight: 500 }}>{loc.name}</div>
            <div className="text-dim mono" style={{ fontSize: 11 }}>{domain}</div>
          </td>
        )}
        {isVisible('gads_cid') && (
          <td>
            {loc.gads_cid
              ? <span className="mono text-muted">{loc.gads_cid}</span>
              : <span className="text-dim">—</span>}
          </td>
        )}
        {isVisible('gtm_id') && (
          <td>
            {loc.gtm_id
              ? <span className="mono" style={{ fontSize: 11 }}>{loc.gtm_id}</span>
              : <span className="text-dim">—</span>}
          </td>
        )}
        {isVisible('status') && (
          <td><StatusChip status={loc.gtm_container_status} /></td>
        )}
        {isVisible('ga4') && (
          <td>
            {loc.ga4_measurement_id
              ? <span className={`chip ${loc.ga4_connected ? 'chip-green' : 'chip-yellow'}`}>● {loc.ga4_measurement_id}</span>
              : <span className="text-dim">—</span>}
          </td>
        )}
        {isVisible('gads_conv') && (
          <td>
            {loc.gads_conversion_id
              ? <span className="chip chip-green">● {loc.gads_conversion_id}</span>
              : <span className="text-dim">—</span>}
          </td>
        )}
        {isVisible('scheduler') && (
          <td>
            {loc.scheduler_type
              ? (() => {
                  const s = SCHEDULER_LABELS[loc.scheduler_type]
                  return s
                    ? <span className={`chip ${s.cls}`}>{s.label}</span>
                    : <span className="mono text-muted" style={{ fontSize: 11 }}>{loc.scheduler_type}</span>
                })()
              : <span className="text-dim">—</span>}
          </td>
        )}
        {isVisible('phone') && (
          <td>
            {(() => {
              const p = fmtPhone(loc.phone_number)
              return p
                ? <span className="mono text-muted" style={{ fontSize: 12 }}>{p}</span>
                : <span className="text-dim">—</span>
            })()}
          </td>
        )}
        {isVisible('actions') && (
          <td>
            <div className="actions-cell">
              {STEPS.map(step => {
                const isActive = activeJob === step.action
                const disabled = !canRun(step) || !loc.gads_cid
                const tooltip = step.needsChrome && !chromeUp
                  ? 'Chrome CDP not running (port 9222)'
                  : !loc.gads_cid ? 'No GAds CID — cannot run' : undefined
                return (
                  <button
                    key={step.action}
                    className={`btn ${isActive ? 'btn-primary' : ''}`}
                    disabled={disabled}
                    title={tooltip}
                    onClick={() => isActive ? close() : start(step.action)}
                  >
                    {isActive && running ? <span className="spinner" /> : null}
                    {step.label}
                  </button>
                )
              })}
            </div>
          </td>
        )}
      </tr>

      {activeJob && (
        <LogPanel
          title={STEPS.find(s => s.action === activeJob)?.label ?? activeJob}
          lines={lines}
          running={running}
          onClose={close}
          colSpan={colSpan}
        />
      )}
    </>
  )
}
