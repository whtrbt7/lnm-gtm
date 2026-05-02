/**
 * Stream a job's output via SSE.
 * onLine(text, type) — called for each output line
 * Returns a cleanup function.
 */
export function runJob(action, gadsCid, onLine, onDone) {
  const url = `/api/run/${action}?gads_cid=${encodeURIComponent(gadsCid)}`
  const es = new EventSource(url)

  es.addEventListener('line', e => {
    const { text, type } = JSON.parse(e.data)
    onLine(text, type)
  })

  es.addEventListener('done', e => {
    const { exit_code } = JSON.parse(e.data)
    es.close()
    onDone(exit_code)
  })

  es.addEventListener('error', () => {
    es.close()
    onDone(1)
  })

  return () => es.close()
}
