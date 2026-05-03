import { useEffect, useMemo, useState } from 'react'
import {
  clearAdminPassword,
  downloadIssuesExport,
  fetchAdminTaxonomy,
  fetchRequestMessages,
  fetchRequests,
  fetchStats,
  getAdminPassword,
  setAdminPassword,
  updateAdminTaxonomy
} from '../api'

interface StatsResponse {
  total_requests: number
  by_status: Record<string, number>
}

interface RequestItem {
  request_id: string
  dialog_id?: string
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

interface TaxonomyRequestType {
  id?: string
  label?: string
}

interface TaxonomyImpactedService {
  id?: string
  label?: string
  request_types?: TaxonomyRequestType[]
}

interface TaxonomyFacilityArea {
  id?: string
  label?: string
  impacted_services?: TaxonomyImpactedService[]
}

const getRequestTypeLabel = (taxonomy: TaxonomyFacilityArea[], requestTypeId?: string | null) => {
  if (!requestTypeId) return null
  for (const area of taxonomy) {
    for (const service of area.impacted_services || []) {
      for (const requestType of service.request_types || []) {
        if (requestType.id === requestTypeId) {
          return requestType.label || requestType.id || null
        }
      }
    }
  }
  return null
}

const prettyJson = (value: unknown) => `${JSON.stringify(value, null, 2)}\n`

const parseTaxonomyJson = (text: string): { value: TaxonomyFacilityArea[] | null; error: string | null } => {
  try {
    const parsed = JSON.parse(text)
    if (!Array.isArray(parsed)) {
      return { value: null, error: 'Taxonomy JSON must be an array at the top level.' }
    }
    return { value: parsed as TaxonomyFacilityArea[], error: null }
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Invalid JSON.'
    return { value: null, error: message }
  }
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

export default function AdminView() {
  const [adminPassword, setAdminPasswordInput] = useState('')
  const [isAuthorized, setIsAuthorized] = useState(false)
  const [authError, setAuthError] = useState<string | null>(null)
  const [isAuthenticating, setIsAuthenticating] = useState(false)
  const [stats, setStats] = useState<StatsResponse | null>(null)
  const [requests, setRequests] = useState<RequestItem[]>([])
  const [activeConversation, setActiveConversation] = useState<{
    requestId: string
    title: string
    messages: { sender: string; content: string }[]
  } | null>(null)
  const [isExporting, setIsExporting] = useState(false)

  const [taxonomyEditorValue, setTaxonomyEditorValue] = useState('[]\n')
  const [taxonomyPreview, setTaxonomyPreview] = useState<TaxonomyFacilityArea[]>([])
  const [taxonomyError, setTaxonomyError] = useState<string | null>(null)
  const [taxonomySavedCanonical, setTaxonomySavedCanonical] = useState('[]')
  const [taxonomySaveError, setTaxonomySaveError] = useState<string | null>(null)
  const [taxonomySaveSuccess, setTaxonomySaveSuccess] = useState<string | null>(null)
  const [isSavingTaxonomy, setIsSavingTaxonomy] = useState(false)

  const loadAdminData = async () => {
    const [statsResponse, requestsResponse, taxonomyResponse] = await Promise.all([
      fetchStats(),
      fetchRequests(),
      fetchAdminTaxonomy()
    ])
    const facilitiesAreas = Array.isArray(taxonomyResponse.facilities_areas)
      ? (taxonomyResponse.facilities_areas as TaxonomyFacilityArea[])
      : []
    const editorValue = prettyJson(facilitiesAreas)

    setStats(statsResponse)
    setRequests(requestsResponse.requests || [])
    setTaxonomyEditorValue(editorValue)
    setTaxonomyPreview(facilitiesAreas)
    setTaxonomyError(null)
    setTaxonomySavedCanonical(JSON.stringify(facilitiesAreas))
    setTaxonomySaveError(null)
    setTaxonomySaveSuccess(null)
  }

  useEffect(() => {
    const storedPassword = getAdminPassword()
    if (!storedPassword) return
    setAdminPasswordInput(storedPassword)
    setIsAuthenticating(true)
    loadAdminData()
      .then(() => {
        setIsAuthorized(true)
      })
      .catch(() => {
        clearAdminPassword()
        setAuthError('Saved password is invalid. Please sign in again.')
      })
      .finally(() => {
        setIsAuthenticating(false)
      })
  }, [])

  const handleLogin = async () => {
    const password = adminPassword.trim()
    if (!password || isAuthenticating) return
    setAuthError(null)
    setIsAuthenticating(true)
    setAdminPassword(password)
    try {
      await loadAdminData()
      setIsAuthorized(true)
    } catch {
      clearAdminPassword()
      setIsAuthorized(false)
      setAuthError('Wrong password.')
    } finally {
      setIsAuthenticating(false)
    }
  }

  const handleLogout = () => {
    clearAdminPassword()
    setIsAuthorized(false)
    setAdminPasswordInput('')
    setStats(null)
    setRequests([])
    setActiveConversation(null)
    setAuthError(null)
    setTaxonomyEditorValue('[]\n')
    setTaxonomyPreview([])
    setTaxonomyError(null)
    setTaxonomySavedCanonical('[]')
    setTaxonomySaveError(null)
    setTaxonomySaveSuccess(null)
  }

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

  const handleTaxonomyEditorChange = (nextValue: string) => {
    setTaxonomyEditorValue(nextValue)
    setTaxonomySaveError(null)
    setTaxonomySaveSuccess(null)

    const parsed = parseTaxonomyJson(nextValue)
    setTaxonomyError(parsed.error)
    if (parsed.value) {
      setTaxonomyPreview(parsed.value)
    }
  }

  const isTaxonomyChanged = useMemo(() => {
    if (taxonomyError) return false
    return JSON.stringify(taxonomyPreview) !== taxonomySavedCanonical
  }, [taxonomyError, taxonomyPreview, taxonomySavedCanonical])

  const handleSaveTaxonomy = async () => {
    const parsed = parseTaxonomyJson(taxonomyEditorValue)
    if (!parsed.value) {
      setTaxonomyError(parsed.error)
      return
    }

    setIsSavingTaxonomy(true)
    setTaxonomySaveError(null)
    setTaxonomySaveSuccess(null)
    try {
      const response = await updateAdminTaxonomy(parsed.value)
      const facilitiesAreas = Array.isArray(response.facilities_areas)
        ? (response.facilities_areas as TaxonomyFacilityArea[])
        : []
      setTaxonomyPreview(facilitiesAreas)
      setTaxonomyEditorValue(prettyJson(facilitiesAreas))
      setTaxonomySavedCanonical(JSON.stringify(facilitiesAreas))
      setTaxonomyError(null)
      setTaxonomySaveSuccess('Taxonomy saved.')
    } catch (error) {
      setTaxonomySaveError(extractErrorMessage(error, 'Failed to save taxonomy.'))
    } finally {
      setIsSavingTaxonomy(false)
    }
  }

  if (!isAuthorized) {
    return (
      <div className="email-gate">
        <div className="panel email-panel admin-auth-panel">
          <h2>Admin Login</h2>
          <p className="muted">Enter admin password to open dashboard.</p>
          <label className="form-label" htmlFor="admin-password">
            Password
          </label>
          <input
            id="admin-password"
            type="password"
            value={adminPassword}
            onChange={(event) => setAdminPasswordInput(event.target.value)}
            className="text-input"
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                void handleLogin()
              }
            }}
          />
          {authError ? <p className="error-text">{authError}</p> : null}
          <button
            type="button"
            onClick={() => void handleLogin()}
            className="btn primary"
            disabled={isAuthenticating}
          >
            {isAuthenticating ? 'Checking...' : 'Sign in'}
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="admin-view">
      <section className="panel admin-overview">
        <div className="admin-overview-header">
          <h2>Admin Overview</h2>
          <div className="admin-actions">
            <button
              type="button"
              className="btn subtle"
              onClick={() => void handleExport()}
              disabled={isExporting}
            >
              {isExporting ? 'Exporting...' : 'Export issues to Excel'}
            </button>
            <button type="button" className="btn subtle" onClick={handleLogout}>
              Log out
            </button>
          </div>
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

      <section className="panel admin-taxonomy">
        <div className="admin-overview-header">
          <h2>Facility Taxonomy</h2>
          <button
            type="button"
            className="btn primary"
            onClick={() => void handleSaveTaxonomy()}
            disabled={isSavingTaxonomy || !!taxonomyError || !isTaxonomyChanged}
          >
            {isSavingTaxonomy ? 'Saving...' : 'Save taxonomy'}
          </button>
        </div>
        <p className="muted">Edit JSON, keep it valid, and save. Server writes this taxonomy into file.</p>

        <div className="taxonomy-layout">
          <div className="taxonomy-editor-panel">
            <h3>JSON editor</h3>
            <textarea
              className="taxonomy-editor"
              value={taxonomyEditorValue}
              onChange={(event) => handleTaxonomyEditorChange(event.target.value)}
              spellCheck={false}
            />
            {taxonomyError ? <p className="error-text">Invalid JSON: {taxonomyError}</p> : null}
            {taxonomySaveError ? <p className="error-text">{taxonomySaveError}</p> : null}
            {taxonomySaveSuccess ? <p className="muted">{taxonomySaveSuccess}</p> : null}
          </div>

          <div className="taxonomy-tree-panel">
            <h3>Tree preview</h3>
            {taxonomyPreview.length === 0 ? (
              <p className="muted">No facility areas in taxonomy.</p>
            ) : (
              <ul className="taxonomy-tree">
                {taxonomyPreview.map((area, areaIndex) => (
                  <li key={`${area.id || 'area'}-${areaIndex}`}>
                    <strong>{area.label || area.id || `Area ${areaIndex + 1}`}</strong>
                    <span className="taxonomy-id">{area.id || 'no-id'}</span>
                    <ul>
                      {(area.impacted_services || []).map((service, serviceIndex) => (
                        <li key={`${service.id || 'service'}-${serviceIndex}`}>
                          <span>{service.label || service.id || `Service ${serviceIndex + 1}`}</span>
                          <span className="taxonomy-id">{service.id || 'no-id'}</span>
                          <ul>
                            {(service.request_types || []).map((requestType, typeIndex) => (
                              <li key={`${requestType.id || 'type'}-${typeIndex}`}>
                                <span>{requestType.label || requestType.id || `Type ${typeIndex + 1}`}</span>
                                <span className="taxonomy-id">{requestType.id || 'no-id'}</span>
                              </li>
                            ))}
                          </ul>
                        </li>
                      ))}
                    </ul>
                  </li>
                ))}
              </ul>
            )}
          </div>
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
                  <strong>
                    {(request.reporter_email || 'Unknown') + ' | ' + (request.title || 'Untitled request')}
                  </strong>
                </div>
                <p className="muted">{request.description}</p>
                <div className="request-meta">
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
                    <strong>Type:</strong>{' '}
                    {(() => {
                      const typeId = request.taxonomy?.request_type || null
                      const typeLabel = getRequestTypeLabel(taxonomyPreview, typeId)
                      if (!typeId) return 'Unknown'
                      return `${typeLabel || 'Unknown'} (${typeId})`
                    })()}
                  </span>
                </div>
                <div className="request-meta">
                  <span>
                    <strong>Urgency:</strong> {request.urgency || 'unknown'}
                  </span>
                </div>
                <div className="request-meta">
                  <span>
                    <strong>Dialog ID:</strong> {request.dialog_id || request.request_id}
                  </span>
                </div>
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
