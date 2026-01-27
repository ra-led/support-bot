import { useEffect, useState } from 'react'
import { fetchRequestMessages, fetchRequests, fetchStats } from '../api'

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

  useEffect(() => {
    fetchStats().then(setStats)
    fetchRequests().then((data) => setRequests(data.requests || []))
  }, [])

  const handleOpenConversation = async (request: RequestItem) => {
    const data = await fetchRequestMessages(request.request_id)
    setActiveConversation({
      requestId: request.request_id,
      title: request.title,
      messages: data.messages || []
    })
  }

  return (
    <div className="nes-container">
      <h2>Admin Statistics</h2>
      <p className="muted">Separated admin view</p>
      <div className="stat-grid">
        <div className="stat-card nes-container">
          <h3>Total requests</h3>
          <p>{stats?.total_requests ?? 0}</p>
        </div>
        {stats &&
          Object.entries(stats.by_status).map(([status, count]) => (
            <div className="stat-card nes-container" key={status}>
              <h3>{status}</h3>
              <p>{count}</p>
            </div>
          ))}
      </div>

      <h3 style={{ marginTop: '24px' }}>Extracted requests</h3>
      <div className="request-list">
        {requests.length === 0 ? (
          <p className="muted">No requests yet.</p>
        ) : (
          requests.map((request) => (
            <div key={request.request_id} className="request-card nes-container">
              <div className="request-header">
                <strong>{request.title}</strong>
                <span className="nes-badge">{request.status}</span>
              </div>
              <p className="muted">{request.description}</p>
              <div className="request-meta">
                <span>Urgency: {request.urgency}</span>
                <span>
                  Location:{' '}
                  {request.location?.room ||
                    request.location?.floor ||
                    request.location?.building ||
                    request.location?.free_text ||
                    'Unknown'}
                </span>
              </div>
              <div className="request-meta">
                <span>Email: {request.reporter_email || 'Unknown'}</span>
              </div>
              <div className="request-meta">
                <span>Facilities: {request.taxonomy?.facilities_area || 'Unknown'}</span>
                <span>Service: {request.taxonomy?.impacted_service || 'Unknown'}</span>
                <span>Type: {request.taxonomy?.request_type || 'Unknown'}</span>
              </div>
              {request.missing_required_fields?.length ? (
                <div className="request-meta">
                  <span>Missing: {request.missing_required_fields.join(', ')}</span>
                </div>
              ) : null}
              {request.clarifying_questions?.length ? (
                <div className="request-meta">
                  <span>Next question: {request.clarifying_questions[0]}</span>
                </div>
              ) : null}
              <div className="request-meta">
                <button
                  type="button"
                  className="link-button nes-btn"
                  onClick={() => handleOpenConversation(request)}
                >
                  View conversation
                </button>
              </div>
            </div>
          ))
        )}
      </div>

      {activeConversation ? (
        <div className="modal-overlay" onClick={() => setActiveConversation(null)}>
          <div
            className="modal nes-container"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="modal-header">
              <h4>Conversation: {activeConversation.title}</h4>
              <button type="button" onClick={() => setActiveConversation(null)} className="nes-btn">
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
                    <strong>{message.sender === 'user' ? 'User' : 'Bot'}:</strong>{' '}
                    {message.content}
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
