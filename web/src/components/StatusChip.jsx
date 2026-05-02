export const GTM_STATUS_LABELS = {
  needs_container:  { label: 'Needs Container', cls: 'chip-dim' },
  has_container:    { label: 'Has Container',   cls: 'chip-blue' },
  external_container: { label: 'External',      cls: 'chip-dim' },
  script_injected:  { label: 'Script Injected', cls: 'chip-yellow' },
  injection_failed: { label: 'Inject Failed',   cls: 'chip-red' },
  verified:         { label: 'Verified Live',   cls: 'chip-green' },
}

export default function StatusChip({ status }) {
  if (!status) return <span className="chip chip-dim">Not Started</span>
  const { label, cls } = GTM_STATUS_LABELS[status] ?? { label: status, cls: 'chip-dim' }
  return <span className={`chip ${cls}`}>● {label}</span>
}
