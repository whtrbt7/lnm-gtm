import { useEffect, useRef } from 'react'

function lineClass(text) {
  if (/error|fail|exception|traceback/i.test(text)) return 'log-line-err'
  if (/warn|warning|already/i.test(text)) return 'log-line-warn'
  if (/done|success|injected|updated|created|active/i.test(text)) return 'log-line-ok'
  return 'log-line-plain'
}

export default function LogPanel({ title, lines, running, onClose, colSpan = 7 }) {
  const bottomRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [lines])

  return (
    <tr className="log-row">
      <td colSpan={colSpan}>
        <div className="log-panel">
          <div className="log-header">
            <span className="log-title">
              {running && <span className="spinner" style={{ marginRight: 6 }} />}
              {title}
            </span>
            {!running && (
              <button className="btn btn-sm" onClick={onClose}>Close</button>
            )}
          </div>
          <div className="log-output">
            {lines.map((l, i) => (
              <div key={i} className={lineClass(l)}>{l}</div>
            ))}
            <div ref={bottomRef} />
          </div>
        </div>
      </td>
    </tr>
  )
}
