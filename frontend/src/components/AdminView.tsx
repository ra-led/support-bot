import { useEffect, useState } from 'react'
import { fetchRequests, fetchStats } from '../api'

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

  useEffect(() => {
    fetchStats().then(setStats)
    fetchRequests().then((data) => setRequests(data.requests || []))
  }, [])

  return (
    <div>
      <h2>Admin Statistics</h2>
      <p className="tag">Separated admin view</p>
      <div className="stat-grid">
        <div className="stat-card">
          <h3>Total requests</h3>
          <p>{stats?.total_requests ?? 0}</p>
        </div>
        {stats &&
          Object.entries(stats.by_status).map(([status, count]) => (
            <div className="stat-card" key={status}>
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
            <div key={request.request_id} className="request-card">
              <div className="request-header">
                <strong>{request.title}</strong>
                <span className="tag">{request.status}</span>
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
            </div>
          ))
        )}
      </div>
    </div>
  )
}
