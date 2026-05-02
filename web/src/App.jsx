import { useState, useEffect, useCallback, useRef } from 'react'
import { fetchLocations } from './api/supabase.js'
import ClientRow from './components/ClientRow.jsx'
import logo from '/whitelnmlogo.svg'
import { COLUMNS, DEFAULT_HIDDEN } from './columns.js'

const STATUS_ORDER = {
  needs_container: 0, has_container: 1, script_injected: 2,
  injection_failed: 1, external_container: 3, verified: 4,
}

async function checkChromeUp() {
  try {
    const r = await fetch('/api/chrome-status', { signal: AbortSignal.timeout(3000) })
    return (await r.json()).up === true
  } catch { return false }
}

const EMPTY_FILTERS = Object.fromEntries(
  COLUMNS.filter(c => c.filterType).map(c => [c.key, ''])
)

export default function App() {
  const [locs, setLocs]           = useState([])
  const [loading, setLoading]     = useState(true)
  const [error, setError]         = useState(null)
  const [search, setSearch]       = useState('')
  const [colFilters, setColFilters] = useState(EMPTY_FILTERS)
  const [chromeUp, setChromeUp]   = useState(false)
  const [theme, setTheme]         = useState('dark')
  const [sortBy, setSortBy]       = useState(null)
  const [sortDir, setSortDir]     = useState('asc')
  const [hiddenCols, setHiddenCols] = useState(DEFAULT_HIDDEN)
  const [colPickerOpen, setColPickerOpen] = useState(false)
  const pickerRef = useRef(null)

  const load = useCallback(async () => {
    try {
      const data = await fetchLocations()
      setLocs(data)
      setError(null)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { document.documentElement.setAttribute('data-theme', theme) }, [theme])

  function toggleTheme() {
    document.documentElement.classList.add('theme-transitioning')
    setTheme(t => t === 'dark' ? 'light' : 'dark')
    setTimeout(() => document.documentElement.classList.remove('theme-transitioning'), 900)
  }

  function toggleSort(col) {
    if (sortBy === col) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortBy(col); setSortDir('asc') }
  }

  function setColFilter(key, val) {
    setColFilters(prev => ({ ...prev, [key]: val }))
  }

  function clearFilters() {
    setSearch('')
    setColFilters(EMPTY_FILTERS)
  }

  function toggleCol(key) {
    setHiddenCols(prev => {
      const next = new Set(prev)
      next.has(key) ? next.delete(key) : next.add(key)
      return next
    })
  }

  // Close col picker on outside click
  useEffect(() => {
    function handler(e) {
      if (pickerRef.current && !pickerRef.current.contains(e.target)) {
        setColPickerOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  useEffect(() => {
    load()
    const pollChrome = async () => setChromeUp(await checkChromeUp())
    pollChrome()
    const iv = setInterval(pollChrome, 10000)
    return () => clearInterval(iv)
  }, [load])

  const visibleCols = COLUMNS.filter(c => !hiddenCols.has(c.key))
  const colSpan = visibleCols.length

  const hasActiveFilters = search || Object.values(colFilters).some(Boolean)

  const filtered = locs.filter(l => {
    const q = search.toLowerCase()
    if (q && !(
      l.name?.toLowerCase().includes(q) ||
      l.brands?.domain?.toLowerCase().includes(q) ||
      l.gads_cid?.includes(q) ||
      l.gtm_id?.toLowerCase().includes(q) ||
      l.phone_number?.includes(q)
    )) return false

    const f = colFilters
    if (f.status) {
      const val = f.status === '__none__' ? null : f.status
      if (l.gtm_container_status !== val) return false
    }
    if (f.ga4 === 'has'     && !l.ga4_measurement_id) return false
    if (f.ga4 === 'missing' && l.ga4_measurement_id)  return false
    if (f.gads_conv === 'has'     && !l.gads_conversion_id) return false
    if (f.gads_conv === 'missing' && l.gads_conversion_id)  return false
    if (f.scheduler) {
      const val = f.scheduler === '__none__' ? null : f.scheduler
      if (l.scheduler_type !== val) return false
    }

    return true
  })

  const sorted = [...filtered].sort((a, b) => {
    let cmp = 0
    if (sortBy === 'name') {
      cmp = (a.name ?? '').localeCompare(b.name ?? '')
    } else if (sortBy === 'status') {
      cmp = (STATUS_ORDER[a.gtm_container_status] ?? -1) - (STATUS_ORDER[b.gtm_container_status] ?? -1)
    } else if (sortBy === 'gads_conv') {
      cmp = (!!a.gads_conversion_id === !!b.gads_conversion_id) ? 0 : !!a.gads_conversion_id ? -1 : 1
    } else {
      const sa = STATUS_ORDER[a.gtm_container_status] ?? -1
      const sb = STATUS_ORDER[b.gtm_container_status] ?? -1
      cmp = sa !== sb ? sa - sb : (a.name ?? '').localeCompare(b.name ?? '')
    }
    return sortDir === 'asc' ? cmp : -cmp
  })

  return (
    <>
      <header className="header">
        <img src={logo} alt="LeadsNearMe" style={{ height: '24px', width: 'auto', filter: 'var(--header-logo-filter)' }} />
        <div style={{ borderLeft: '1px solid var(--border)', paddingLeft: '14px', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span className="header-title">GTM Setup</span>
          <span className="header-sub">LNM Google Tag Manager Workflow</span>
        </div>
        <div className="chrome-badge">
          <span className="chrome-dot" style={{ background: chromeUp ? 'var(--color-green)' : 'var(--color-red)' }} />
          Chrome CDP {chromeUp ? 'running' : 'offline'}
          <button onClick={toggleTheme} className="btn btn-sm" style={{ marginLeft: '8px' }} title="Toggle light/dark mode">
            {theme === 'dark' ? '☀' : '☾'}
          </button>
        </div>
      </header>

      <div className="toolbar">
        <input
          className="search-input"
          placeholder="Search client, domain, GTM ID, phone…"
          value={search}
          onChange={e => setSearch(e.target.value)}
        />

        {/* Column picker */}
        <div ref={pickerRef} style={{ position: 'relative' }}>
          <button className="btn" onClick={() => setColPickerOpen(o => !o)}>
            ⊞ Columns {hiddenCols.size > 0 ? `(${hiddenCols.size} hidden)` : ''}
          </button>
          {colPickerOpen && (
            <div className="col-picker">
              {COLUMNS.filter(c => !c.fixed).map(c => (
                <label key={c.key} className="col-picker-row">
                  <input
                    type="checkbox"
                    checked={!hiddenCols.has(c.key)}
                    onChange={() => toggleCol(c.key)}
                  />
                  {c.label}
                </label>
              ))}
            </div>
          )}
        </div>

        {hasActiveFilters && (
          <button className="btn" onClick={clearFilters} style={{ color: 'var(--color-yellow)' }}>
            ✕ Clear filters
          </button>
        )}

        <button className="btn" onClick={load} title="Refresh">↻ Refresh</button>
        <span className="count-label">{sorted.length} client{sorted.length !== 1 ? 's' : ''}</span>
      </div>

      <div className="table-wrap">
        {loading && <p style={{ color: 'var(--text-dim)', padding: '24px 0' }}>Loading…</p>}
        {error   && <p style={{ color: 'var(--color-red)', padding: '24px 0' }}>Error: {error}</p>}
        {!loading && !error && (
          <table>
            <thead>
              {/* Column headers */}
              <tr>
                {visibleCols.map(col => {
                  if (col.sortable) {
                    const active = sortBy === col.key
                    return (
                      <th key={col.key} className="th-sort" onClick={() => toggleSort(col.key)}>
                        {col.label}
                        <span className="sort-indicator">
                          {active ? (sortDir === 'asc' ? ' ▲' : ' ▼') : ' ↕'}
                        </span>
                      </th>
                    )
                  }
                  return <th key={col.key}>{col.label}</th>
                })}
              </tr>

              {/* Per-column filter row */}
              <tr className="filter-row">
                {visibleCols.map(col => (
                  <td key={col.key} className="filter-cell">
                    {col.filterType === 'select' ? (
                      <select
                        className="filter-inline"
                        value={colFilters[col.key] ?? ''}
                        onChange={e => setColFilter(col.key, e.target.value)}
                      >
                        {col.filterOptions.map(o => (
                          <option key={o.value} value={o.value}>{o.label}</option>
                        ))}
                      </select>
                    ) : null}
                  </td>
                ))}
              </tr>
            </thead>

            <tbody>
              {sorted.map(loc => (
                <ClientRow
                  key={loc.id}
                  loc={loc}
                  chromeUp={chromeUp}
                  onRefresh={load}
                  visibleCols={visibleCols}
                  colSpan={colSpan}
                />
              ))}
              {sorted.length === 0 && (
                <tr>
                  <td colSpan={colSpan} style={{ textAlign: 'center', color: 'var(--text-dim)', padding: '32px 0' }}>
                    No clients match current filters.
                    {hasActiveFilters && (
                      <button className="btn btn-sm" style={{ marginLeft: 12 }} onClick={clearFilters}>Clear</button>
                    )}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        )}
      </div>
    </>
  )
}
