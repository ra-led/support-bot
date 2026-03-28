import { useEffect, useState } from 'react'
import { downloadIssuesExport, fetchRequestMessages, fetchRequests, fetchStats } from '../api'

interface StatsResponse {
  total_requests: number
  by_status: Record<string, number>
}

interface RequestItem {
  request_id: string
  title: string
  description: string
  urgency: string
  status: string
  reporter_email?: string | null
  location?: {
    site?: string | null
    building?: string | null
    floor?: string | null
    room?: string | null
    free_text?: string | null
  }
  taxonomy?: {
    facilities_area?: string | null
    impacted_service?: string | null
    request_type?: string | null
  }
  missing_required_fields?: string[]
  clarifying_questions?: string[]
}

export default function AdminView() {
  const [stats, setStats] = useState<StatsResponse | null>(null)
  const [requests, setRequests] = useState<RequestItem[]>([])
  const [activeConversation, setActiveConversation] = useState<{
    requestId: string
    title: string
    messages: { sender: string; content: string }[]
  } | null>(null)
  const [isExporting, setIsExporting] = useState(false)

  useEffect(() => {
    fetchStats().then(setStats).catch(() => setStats({ total_requests: 0, by_status: {} }))
    fetchRequests().then((data) => setRequests(data.requests || [])).catch(() => setRequests([]))
  }, [])

  const handleOpenConversation = async (request: RequestItem) => {
    const data = await fetchRequestMessages(request.request_id)
    setActiveConversation({
      requestId: request.request_id,
      title: request.title,
      messages: data.messages || []
    })
  }

  const handleExport = async () => {
    setIsExporting(true)
    try {
      const blob = await downloadIssuesExport()
      const url = window.URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = `issues-history-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.xlsx`
      document.body.appendChild(anchor)
      anchor.click()
      anchor.remove()
      window.URL.revokeObjectURL(url)
    } finally {
      setIsExporting(false)
    }
  }

  return (
    <div className="admin-view">
      <section className="panel admin-overview">
        <div className="admin-overview-header">
          <h2>Admin Overview</h2>
          <button
            type="button"
            className="btn subtle"
            onClick={() => void handleExport()}
            disabled={isExporting}
          >
            {isExporting ? 'Exporting...' : 'Export issues to Excel'}
          </button>
        </div>
        <p className="muted">Real-time intake status and operational queue</p>
        <div className="stat-grid">
          <article className="stat-card">
            <h3>Total requests</h3>
            <p>{stats?.total_requests ?? 0}</p>
          </article>
          {stats &&
            Object.entries(stats.by_status).map(([status, count]) => (
              <article className="stat-card" key={status}>
                <h3>{status}</h3>
                <p>{count}</p>
              </article>
            ))}
        </div>
      </section>

      <section className="panel admin-requests">
        <h2>Extracted Requests</h2>
        <div className="request-list">
          {requests.length === 0 ? (
            <p className="muted">No requests yet.</p>
          ) : (
            requests.map((request) => (
              <article key={request.request_id} className="request-card">
                <div className="request-header">
                  <strong>{request.title}</strong>
                  <span className={`status-pill status-${request.status}`}>{request.status}</span>
                </div>
                <p className="muted">{request.description}</p>
                <div className="request-meta">
                  <span>
                    <strong>Urgency:</strong> {request.urgency}
                  </span>
                  <span>
                    <strong>Location:</strong>{' '}
                    {request.location?.room ||
                      request.location?.floor ||
                      request.location?.building ||
                      request.location?.free_text ||
                      'Unknown'}
                  </span>
                </div>
                <div className="request-meta">
                  <span>
                    <strong>Email:</strong> {request.reporter_email || 'Unknown'}
                  </span>
                </div>
                <div className="request-meta">
                  <span>
                    <strong>Facilities:</strong> {request.taxonomy?.facilities_area || 'Unknown'}
                  </span>
                  <span>
                    <strong>Service:</strong> {request.taxonomy?.impacted_service || 'Unknown'}
                  </span>
                </div>
                <div className="request-meta">
                  <span>
                    <strong>Type:</strong> {request.taxonomy?.request_type || 'Unknown'}
                  </span>
                </div>
                {request.missing_required_fields?.length ? (
                  <div className="request-meta">
                    <span>
                      <strong>Missing:</strong> {request.missing_required_fields.join(', ')}
                    </span>
                  </div>
                ) : null}
                {request.clarifying_questions?.length ? (
                  <div className="request-meta">
                    <span>
                      <strong>Next question:</strong> {request.clarifying_questions[0]}
                    </span>
                  </div>
                ) : null}
                <div className="request-meta">
                  <button
                    type="button"
                    className="btn primary"
                    onClick={() => void handleOpenConversation(request)}
                  >
                    View conversation
                  </button>
                </div>
              </article>
            ))
          )}
        </div>
      </section>

      {activeConversation ? (
        <div className="modal-overlay" onClick={() => setActiveConversation(null)}>
          <div className="modal" onClick={(event) => event.stopPropagation()}>
            <div className="modal-header">
              <h4>Conversation: {activeConversation.title}</h4>
              <button type="button" onClick={() => setActiveConversation(null)} className="btn subtle">
                Close
              </button>
            </div>
            <div className="modal-body">
              {activeConversation.messages.length === 0 ? (
                <p className="muted">No messages recorded.</p>
              ) : (
                activeConversation.messages.map((message, index) => (
                  <div
                    key={`${message.sender}-${index}`}
                    className={`conversation-line ${
                      message.sender === 'user' ? 'from-user' : 'from-bot'
                    }`}
                  >
                    <strong>{message.sender === 'user' ? 'User' : 'Bot'}:</strong> {message.content}
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}
