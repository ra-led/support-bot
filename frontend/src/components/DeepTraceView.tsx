import { FormEvent, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { fetchDialogTrace } from '../api'

type TraceItem = {
  id: number
  request_id: string
  model: string
  schema_name: string
  prompt: string
  response_text: string
  created_at: string
}

type TracePayload = {
  dialog_id: string
  request: Record<string, unknown>
  traces: TraceItem[]
}

const extractErrorMessage = (error: unknown, fallback: string) => {
  if (
    typeof error === 'object' &&
    error !== null &&
    'response' in error &&
    typeof (error as { response?: { data?: { detail?: string } } }).response?.data?.detail === 'string'
  ) {
    return (error as { response: { data: { detail: string } } }).response.data.detail
  }
  return fallback
}

export default function DeepTraceView() {
  const [searchParams, setSearchParams] = useSearchParams()
  const initialId = searchParams.get('id') || ''
  const [dialogIdInput, setDialogIdInput] = useState(initialId)
  const [isLoading, setIsLoading] = useState(false)
  const [errorText, setErrorText] = useState<string | null>(null)
  const [payload, setPayload] = useState<TracePayload | null>(null)

  const traces = useMemo(() => payload?.traces || [], [payload])

  useEffect(() => {
    if (!initialId) return
    void loadById(initialId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const loadById = async (nextDialogId: string) => {
    const cleanId = nextDialogId.trim()
    if (!cleanId) return
    setIsLoading(true)
    setErrorText(null)
    try {
      const data = await fetchDialogTrace(cleanId)
      setPayload(data)
      setSearchParams({ id: cleanId })
    } catch (error) {
      setPayload(null)
      setErrorText(extractErrorMessage(error, 'Failed to load traces.'))
    } finally {
      setIsLoading(false)
    }
  }

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    void loadById(dialogIdInput)
  }

  return (
    <div className="deep-view">
      <section className="panel deep-panel">
        <h2>Deep Trace</h2>
        <p className="muted">Open by direct URL: `/deep?id=&lt;dialog_id&gt;`</p>
        <form className="deep-form" onSubmit={handleSubmit}>
          <input
            value={dialogIdInput}
            onChange={(event) => setDialogIdInput(event.target.value)}
            className="text-input"
            placeholder="Enter dialog_id"
          />
          <button type="submit" className="btn primary" disabled={isLoading || !dialogIdInput.trim()}>
            {isLoading ? 'Loading...' : 'Load trace'}
          </button>
        </form>
        {errorText ? <p className="error-text">{errorText}</p> : null}
      </section>

      {payload ? (
        <section className="panel deep-panel">
          <div className="request-meta">
            <span>
              <strong>Dialog ID:</strong> {payload.dialog_id}
            </span>
            <span>
              <strong>Trace records:</strong> {traces.length}
            </span>
          </div>

          {traces.length === 0 ? (
            <p className="muted">No traces recorded for this dialog yet.</p>
          ) : (
            <div className="deep-trace-list">
              {traces.map((trace) => (
                <article key={trace.id} className="deep-trace-card">
                  <div className="request-meta">
                    <span>
                      <strong>ID:</strong> {trace.id}
                    </span>
                    <span>
                      <strong>Schema:</strong> {trace.schema_name}
                    </span>
                    <span>
                      <strong>Model:</strong> {trace.model}
                    </span>
                    <span>
                      <strong>At:</strong> {trace.created_at}
                    </span>
                  </div>
                  <h4>Prompt</h4>
                  <pre className="deep-pre">{trace.prompt}</pre>
                  <h4>Response</h4>
                  <pre className="deep-pre">{trace.response_text}</pre>
                </article>
              ))}
            </div>
          )}
        </section>
      ) : null}
    </div>
  )
}
