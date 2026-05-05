import { useEffect, useMemo, useRef, useState } from 'react'
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
  created_at?: string
  updated_at?: string
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

const VIEWED_ADMIN_DIALOG_IDS_STORAGE_KEY = 'supportBotAdminViewedDialogIds'
const CREATE_NEW_VALUE = '__create_new__'

interface TaxonomyFormState {
  facilityId: string
  newFacilityId: string
  newFacilityLabel: string
  serviceId: string
  newServiceId: string
  newServiceLabel: string
  requestTypeId: string
  requestTypeLabel: string
}

interface DeleteTaxonomyTarget {
  kind: 'facility' | 'service' | 'request_type'
  areaId: string
  serviceId?: string
  requestTypeId?: string
  label: string
}

const emptyTaxonomyForm: TaxonomyFormState = {
  facilityId: '',
  newFacilityId: '',
  newFacilityLabel: '',
  serviceId: '',
  newServiceId: '',
  newServiceLabel: '',
  requestTypeId: '',
  requestTypeLabel: ''
}

const getDefaultTaxonomyForm = (taxonomy: TaxonomyFacilityArea[]): TaxonomyFormState => {
  const firstFacility = taxonomy.find((area) => area.id)
  const firstService = firstFacility?.impacted_services?.find((service) => service.id)
  return {
    ...emptyTaxonomyForm,
    facilityId: firstFacility?.id || CREATE_NEW_VALUE,
    serviceId: firstFacility ? firstService?.id || CREATE_NEW_VALUE : CREATE_NEW_VALUE
  }
}

const normalizeTaxonomyForm = (
  taxonomy: TaxonomyFacilityArea[],
  form: TaxonomyFormState
): TaxonomyFormState => {
  if (form.facilityId === CREATE_NEW_VALUE) {
    return { ...form, serviceId: CREATE_NEW_VALUE }
  }

  const selectedArea = taxonomy.find((area) => area.id === form.facilityId)
  if (!selectedArea) {
    return getDefaultTaxonomyForm(taxonomy)
  }

  const hasSelectedService = (selectedArea.impacted_services || []).some(
    (service) => service.id === form.serviceId
  )
  return {
    ...form,
    serviceId:
      form.serviceId === CREATE_NEW_VALUE || hasSelectedService
        ? form.serviceId
        : selectedArea.impacted_services?.find((service) => service.id)?.id || CREATE_NEW_VALUE
  }
}

const getExamples = (values: Array<string | null | undefined>, maxCount = 3) =>
  Array.from(new Set(values.map((value) => value?.trim()).filter((value): value is string => !!value))).slice(
    0,
    maxCount
  )

const buildInputTip = (description: string, examples: string[]) =>
  examples.length > 0 ? `${description}, e.g. ${examples.join(', ')}` : description

interface DialogViewSnapshot {
  ids: Set<string>
  hasBaseline: boolean
}

const getDialogId = (request: RequestItem) => request.dialog_id || request.request_id

const readViewedDialogSnapshot = (): DialogViewSnapshot => {
  if (typeof window === 'undefined') {
    return { ids: new Set(), hasBaseline: false }
  }

  const storedValue = localStorage.getItem(VIEWED_ADMIN_DIALOG_IDS_STORAGE_KEY)
  if (!storedValue) {
    return { ids: new Set(), hasBaseline: false }
  }

  try {
    const parsed = JSON.parse(storedValue)
    if (!Array.isArray(parsed)) {
      return { ids: new Set(), hasBaseline: false }
    }
    return {
      ids: new Set(parsed.filter((value): value is string => typeof value === 'string')),
      hasBaseline: true
    }
  } catch {
    return { ids: new Set(), hasBaseline: false }
  }
}

const writeViewedDialogSnapshot = (dialogIds: string[]) => {
  if (typeof window === 'undefined') return
  localStorage.setItem(VIEWED_ADMIN_DIALOG_IDS_STORAGE_KEY, JSON.stringify(dialogIds))
}

const cloneTaxonomy = (taxonomy: TaxonomyFacilityArea[]) =>
  taxonomy.map((area) => ({
    ...area,
    impacted_services: (area.impacted_services || []).map((service) => ({
      ...service,
      request_types: [...(service.request_types || [])]
    }))
  }))

const getUsedTaxonomyIds = (taxonomy: TaxonomyFacilityArea[]) => {
  const ids = new Set<string>()
  for (const area of taxonomy) {
    if (area.id) ids.add(area.id)
    for (const service of area.impacted_services || []) {
      if (service.id) ids.add(service.id)
      for (const requestType of service.request_types || []) {
        if (requestType.id) ids.add(requestType.id)
      }
    }
  }
  return ids
}

const buildTaxonomyWithRequestType = (
  taxonomy: TaxonomyFacilityArea[],
  form: TaxonomyFormState
): { value: TaxonomyFacilityArea[] | null; error: string | null } => {
  const facilityId = form.facilityId.trim()
  const serviceId = form.serviceId.trim()
  const newFacilityId = form.newFacilityId.trim()
  const newFacilityLabel = form.newFacilityLabel.trim()
  const newServiceId = form.newServiceId.trim()
  const newServiceLabel = form.newServiceLabel.trim()
  const requestTypeId = form.requestTypeId.trim()
  const requestTypeLabel = form.requestTypeLabel.trim()

  if (!facilityId) return { value: null, error: 'Choose a facility area.' }
  if (!requestTypeId || !requestTypeLabel) {
    return { value: null, error: 'Fill request type id and label.' }
  }

  const usedIds = getUsedTaxonomyIds(taxonomy)
  if (usedIds.has(requestTypeId)) {
    return { value: null, error: 'Request type id already exists.' }
  }

  const requestType = { id: requestTypeId, label: requestTypeLabel }

  if (facilityId === CREATE_NEW_VALUE) {
    if (!newFacilityId || !newFacilityLabel || !newServiceId || !newServiceLabel) {
      return { value: null, error: 'Fill new facility and impact service fields.' }
    }
    if (newFacilityId === newServiceId || requestTypeId === newFacilityId || requestTypeId === newServiceId) {
      return { value: null, error: 'New taxonomy ids must be unique.' }
    }
    if (usedIds.has(newFacilityId)) return { value: null, error: 'Facility id already exists.' }
    if (usedIds.has(newServiceId)) return { value: null, error: 'Impact service id already exists.' }
    return {
      value: [
        ...cloneTaxonomy(taxonomy),
        {
          id: newFacilityId,
          label: newFacilityLabel,
          impacted_services: [{ id: newServiceId, label: newServiceLabel, request_types: [requestType] }]
        }
      ],
      error: null
    }
  }

  const areaIndex = taxonomy.findIndex((area) => area.id === facilityId)
  if (areaIndex < 0) return { value: null, error: 'Selected facility area was not found.' }
  if (!serviceId) return { value: null, error: 'Choose an impact service.' }

  const nextTaxonomy = cloneTaxonomy(taxonomy)
  const selectedArea = nextTaxonomy[areaIndex]
  selectedArea.impacted_services = selectedArea.impacted_services || []

  if (serviceId === CREATE_NEW_VALUE) {
    if (!newServiceId || !newServiceLabel) {
      return { value: null, error: 'Fill new impact service id and label.' }
    }
    if (requestTypeId === newServiceId) {
      return { value: null, error: 'New taxonomy ids must be unique.' }
    }
    if (usedIds.has(newServiceId)) return { value: null, error: 'Impact service id already exists.' }
    selectedArea.impacted_services.push({
      id: newServiceId,
      label: newServiceLabel,
      request_types: [requestType]
    })
    return { value: nextTaxonomy, error: null }
  }

  const selectedService = selectedArea.impacted_services.find((service) => service.id === serviceId)
  if (!selectedService) return { value: null, error: 'Selected impact service was not found.' }
  selectedService.request_types = [...(selectedService.request_types || []), requestType]
  return { value: nextTaxonomy, error: null }
}

const deleteTaxonomyNode = (taxonomy: TaxonomyFacilityArea[], target: DeleteTaxonomyTarget) => {
  if (target.kind === 'facility') {
    return cloneTaxonomy(taxonomy).filter((area) => area.id !== target.areaId)
  }

  return cloneTaxonomy(taxonomy).map((area) => {
    if (area.id !== target.areaId) return area
    if (target.kind === 'service') {
      return {
        ...area,
        impacted_services: (area.impacted_services || []).filter((service) => service.id !== target.serviceId)
      }
    }
    return {
      ...area,
      impacted_services: (area.impacted_services || []).map((service) => {
        if (service.id !== target.serviceId) return service
        return {
          ...service,
          request_types: (service.request_types || []).filter(
            (requestType) => requestType.id !== target.requestTypeId
          )
        }
      })
    }
  })
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
  const [newDialogIds, setNewDialogIds] = useState<Set<string>>(new Set())
  const [activeConversation, setActiveConversation] = useState<{
    requestId: string
    title: string
    messages: { sender: string; content: string }[]
  } | null>(null)
  const [isExporting, setIsExporting] = useState(false)

  const [taxonomyPreview, setTaxonomyPreview] = useState<TaxonomyFacilityArea[]>([])
  const [taxonomyVersion, setTaxonomyVersion] = useState<number | null>(null)
  const [taxonomyForm, setTaxonomyForm] = useState<TaxonomyFormState>(emptyTaxonomyForm)
  const [taxonomySaveError, setTaxonomySaveError] = useState<string | null>(null)
  const [taxonomySaveSuccess, setTaxonomySaveSuccess] = useState<string | null>(null)
  const [isSavingTaxonomy, setIsSavingTaxonomy] = useState(false)
  const initialDialogSnapshotRef = useRef<DialogViewSnapshot | null>(null)

  const loadAdminData = async () => {
    if (!initialDialogSnapshotRef.current) {
      initialDialogSnapshotRef.current = readViewedDialogSnapshot()
    }

    const [statsResponse, requestsResponse, taxonomyResponse] = await Promise.all([
      fetchStats(),
      fetchRequests(),
      fetchAdminTaxonomy()
    ])
    const loadedRequests = (requestsResponse.requests || []) as RequestItem[]
    const currentDialogIds = Array.from(new Set(loadedRequests.map(getDialogId).filter(Boolean)))
    const initialSnapshot = initialDialogSnapshotRef.current
    const nextNewDialogIds = initialSnapshot.hasBaseline
      ? new Set(currentDialogIds.filter((dialogId) => !initialSnapshot.ids.has(dialogId)))
      : new Set<string>()
    const facilitiesAreas = Array.isArray(taxonomyResponse.facilities_areas)
      ? (taxonomyResponse.facilities_areas as TaxonomyFacilityArea[])
      : []

    setStats(statsResponse)
    setRequests(loadedRequests)
    setNewDialogIds(nextNewDialogIds)
    writeViewedDialogSnapshot(currentDialogIds)
    setTaxonomyPreview(facilitiesAreas)
    setTaxonomyVersion(taxonomyResponse.taxonomy_version ?? null)
    setTaxonomyForm(getDefaultTaxonomyForm(facilitiesAreas))
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
    initialDialogSnapshotRef.current = null
    setIsAuthorized(false)
    setAdminPasswordInput('')
    setStats(null)
    setRequests([])
    setNewDialogIds(new Set())
    setActiveConversation(null)
    setAuthError(null)
    setTaxonomyPreview([])
    setTaxonomyVersion(null)
    setTaxonomyForm(emptyTaxonomyForm)
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

  const selectedFacility = useMemo(
    () => taxonomyPreview.find((area) => area.id === taxonomyForm.facilityId) || null,
    [taxonomyForm.facilityId, taxonomyPreview]
  )

  const selectedService = useMemo(
    () => selectedFacility?.impacted_services?.find((service) => service.id === taxonomyForm.serviceId) || null,
    [selectedFacility, taxonomyForm.serviceId]
  )

  const taxonomyInputTips = useMemo(() => {
    const allServices = taxonomyPreview.flatMap((area) => area.impacted_services || [])
    const scopedServices = selectedFacility?.impacted_services?.length
      ? selectedFacility.impacted_services
      : allServices
    const allRequestTypes = allServices.flatMap((service) => service.request_types || [])
    const scopedRequestTypes = selectedService?.request_types?.length
      ? selectedService.request_types
      : allRequestTypes

    return {
      facilityId: buildInputTip('Stable snake_case area id', getExamples(taxonomyPreview.map((area) => area.id))),
      facilityLabel: buildInputTip(
        'Human-readable facility area name',
        getExamples(taxonomyPreview.map((area) => area.label))
      ),
      serviceId: buildInputTip('Stable dot-separated impact service id', getExamples(scopedServices.map((service) => service.id))),
      serviceLabel: buildInputTip(
        'Human-readable impact service name',
        getExamples(scopedServices.map((service) => service.label))
      ),
      requestTypeId: buildInputTip(
        'Stable dot-separated request type id',
        getExamples(scopedRequestTypes.map((requestType) => requestType.id))
      ),
      requestTypeLabel: buildInputTip(
        'Human-readable request type name',
        getExamples(scopedRequestTypes.map((requestType) => requestType.label))
      )
    }
  }, [selectedFacility, selectedService, taxonomyPreview])

  const persistTaxonomy = async (nextTaxonomy: TaxonomyFacilityArea[], successMessage: string) => {
    setIsSavingTaxonomy(true)
    setTaxonomySaveError(null)
    setTaxonomySaveSuccess(null)
    try {
      const response = await updateAdminTaxonomy(nextTaxonomy)
      const facilitiesAreas = Array.isArray(response.facilities_areas)
        ? (response.facilities_areas as TaxonomyFacilityArea[])
        : []
      setTaxonomyPreview(facilitiesAreas)
      setTaxonomyForm((current) => normalizeTaxonomyForm(facilitiesAreas, current))
      setTaxonomyVersion(response.taxonomy_version ?? null)
      setTaxonomySaveSuccess(
        response.taxonomy_version
          ? `${successMessage} Version ${response.taxonomy_version}.`
          : successMessage
      )
      return true
    } catch (error) {
      setTaxonomySaveError(extractErrorMessage(error, 'Failed to save taxonomy.'))
      return false
    } finally {
      setIsSavingTaxonomy(false)
    }
  }

  const handleAddRequestType = async () => {
    if (isSavingTaxonomy) return
    const result = buildTaxonomyWithRequestType(taxonomyPreview, taxonomyForm)
    if (!result.value) {
      setTaxonomySaveError(result.error)
      setTaxonomySaveSuccess(null)
      return
    }

    const saved = await persistTaxonomy(result.value, 'Request type added.')
    if (saved) {
      setTaxonomyForm(getDefaultTaxonomyForm(result.value))
    }
  }

  const handleDeleteTaxonomyNode = async (target: DeleteTaxonomyTarget) => {
    if (isSavingTaxonomy) return
    const nestedWarning = target.kind === 'request_type' ? '' : ' and all nested taxonomy nodes'
    const confirmed = window.confirm(`Delete "${target.label}"${nestedWarning}?`)
    if (!confirmed) return
    await persistTaxonomy(deleteTaxonomyNode(taxonomyPreview, target), 'Taxonomy node deleted.')
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
          <article className="stat-card new-stat-card">
            <h3>New</h3>
            <p>{newDialogIds.size}</p>
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
          {taxonomyVersion ? <span className="taxonomy-version">Version {taxonomyVersion}</span> : null}
        </div>

        <div className="taxonomy-layout">
          <div className="taxonomy-form-panel">
            <h3>Add request type</h3>
            <div className="taxonomy-form-grid">
              <label className="form-label" htmlFor="taxonomy-facility">
                Facility
              </label>
              <select
                id="taxonomy-facility"
                className="text-input"
                value={taxonomyForm.facilityId}
                onChange={(event) => {
                  const nextFacilityId = event.target.value
                  const nextFacility = taxonomyPreview.find((area) => area.id === nextFacilityId)
                  setTaxonomyForm((current) => ({
                    ...current,
                    facilityId: nextFacilityId,
                    serviceId:
                      nextFacilityId === CREATE_NEW_VALUE
                        ? CREATE_NEW_VALUE
                        : nextFacility?.impacted_services?.find((service) => service.id)?.id || CREATE_NEW_VALUE
                  }))
                }}
              >
                {taxonomyPreview.map((area) => (
                  <option value={area.id || ''} key={area.id || area.label}>
                    {area.label || area.id}
                  </option>
                ))}
                <option value={CREATE_NEW_VALUE}>Create new</option>
              </select>

              {taxonomyForm.facilityId === CREATE_NEW_VALUE ? (
                <>
                  <label className="form-label" htmlFor="new-facility-id">
                    New facility ID
                  </label>
                  <input
                    id="new-facility-id"
                    className="text-input"
                    value={taxonomyForm.newFacilityId}
                    placeholder={taxonomyInputTips.facilityId}
                    title={taxonomyInputTips.facilityId}
                    onChange={(event) =>
                      setTaxonomyForm((current) => ({ ...current, newFacilityId: event.target.value }))
                    }
                  />

                  <label className="form-label" htmlFor="new-facility-label">
                    New facility label
                  </label>
                  <input
                    id="new-facility-label"
                    className="text-input"
                    value={taxonomyForm.newFacilityLabel}
                    placeholder={taxonomyInputTips.facilityLabel}
                    title={taxonomyInputTips.facilityLabel}
                    onChange={(event) =>
                      setTaxonomyForm((current) => ({ ...current, newFacilityLabel: event.target.value }))
                    }
                  />
                </>
              ) : null}

              {taxonomyForm.facilityId && taxonomyForm.facilityId !== CREATE_NEW_VALUE ? (
                <>
                  <label className="form-label" htmlFor="taxonomy-service">
                    Impact service
                  </label>
                  <select
                    id="taxonomy-service"
                    className="text-input"
                    value={taxonomyForm.serviceId}
                    onChange={(event) =>
                      setTaxonomyForm((current) => ({ ...current, serviceId: event.target.value }))
                    }
                  >
                    {(selectedFacility?.impacted_services || []).map((service) => (
                      <option value={service.id || ''} key={service.id || service.label}>
                        {service.label || service.id}
                      </option>
                    ))}
                    <option value={CREATE_NEW_VALUE}>Create new</option>
                  </select>
                </>
              ) : null}

              {taxonomyForm.serviceId === CREATE_NEW_VALUE ? (
                <>
                  <label className="form-label" htmlFor="new-service-id">
                    New impact service ID
                  </label>
                  <input
                    id="new-service-id"
                    className="text-input"
                    value={taxonomyForm.newServiceId}
                    placeholder={taxonomyInputTips.serviceId}
                    title={taxonomyInputTips.serviceId}
                    onChange={(event) =>
                      setTaxonomyForm((current) => ({ ...current, newServiceId: event.target.value }))
                    }
                  />

                  <label className="form-label" htmlFor="new-service-label">
                    New impact service label
                  </label>
                  <input
                    id="new-service-label"
                    className="text-input"
                    value={taxonomyForm.newServiceLabel}
                    placeholder={taxonomyInputTips.serviceLabel}
                    title={taxonomyInputTips.serviceLabel}
                    onChange={(event) =>
                      setTaxonomyForm((current) => ({ ...current, newServiceLabel: event.target.value }))
                    }
                  />
                </>
              ) : null}

              <label className="form-label" htmlFor="new-request-type-id">
                Request type ID
              </label>
              <input
                id="new-request-type-id"
                className="text-input"
                value={taxonomyForm.requestTypeId}
                placeholder={taxonomyInputTips.requestTypeId}
                title={taxonomyInputTips.requestTypeId}
                onChange={(event) =>
                  setTaxonomyForm((current) => ({ ...current, requestTypeId: event.target.value }))
                }
              />

              <label className="form-label" htmlFor="new-request-type-label">
                Request type label
              </label>
              <input
                id="new-request-type-label"
                className="text-input"
                value={taxonomyForm.requestTypeLabel}
                placeholder={taxonomyInputTips.requestTypeLabel}
                title={taxonomyInputTips.requestTypeLabel}
                onChange={(event) =>
                  setTaxonomyForm((current) => ({ ...current, requestTypeLabel: event.target.value }))
                }
              />
            </div>

            <button
              type="button"
              className="btn primary"
              onClick={() => void handleAddRequestType()}
              disabled={isSavingTaxonomy}
            >
              {isSavingTaxonomy ? 'Saving...' : 'Add request type'}
            </button>
            {taxonomySaveError ? <p className="error-text">{taxonomySaveError}</p> : null}
            {taxonomySaveSuccess ? <p className="muted">{taxonomySaveSuccess}</p> : null}
          </div>

          <div className="taxonomy-tree-panel">
            <h3>Taxonomy tree</h3>
            {taxonomyPreview.length === 0 ? (
              <p className="muted">No facility areas in taxonomy.</p>
            ) : (
              <ul className="taxonomy-tree">
                {taxonomyPreview.map((area, areaIndex) => (
                  <li key={`${area.id || 'area'}-${areaIndex}`}>
                    <div className="taxonomy-node-row">
                      <span>
                        <strong>{area.label || area.id || `Area ${areaIndex + 1}`}</strong>
                        <span className="taxonomy-id">{area.id || 'no-id'}</span>
                      </span>
                      <button
                        type="button"
                        className="btn danger taxonomy-delete-btn"
                        onClick={() =>
                          void handleDeleteTaxonomyNode({
                            kind: 'facility',
                            areaId: area.id || '',
                            label: area.label || area.id || `Area ${areaIndex + 1}`
                          })
                        }
                        disabled={isSavingTaxonomy || !area.id}
                      >
                        Delete
                      </button>
                    </div>
                    <ul>
                      {(area.impacted_services || []).map((service, serviceIndex) => (
                        <li key={`${service.id || 'service'}-${serviceIndex}`}>
                          <div className="taxonomy-node-row">
                            <span>
                              <span>{service.label || service.id || `Service ${serviceIndex + 1}`}</span>
                              <span className="taxonomy-id">{service.id || 'no-id'}</span>
                            </span>
                            <button
                              type="button"
                              className="btn danger taxonomy-delete-btn"
                              onClick={() =>
                                void handleDeleteTaxonomyNode({
                                  kind: 'service',
                                  areaId: area.id || '',
                                  serviceId: service.id || '',
                                  label: service.label || service.id || `Service ${serviceIndex + 1}`
                                })
                              }
                              disabled={isSavingTaxonomy || !area.id || !service.id}
                            >
                              Delete
                            </button>
                          </div>
                          <ul>
                            {(service.request_types || []).map((requestType, typeIndex) => (
                              <li key={`${requestType.id || 'type'}-${typeIndex}`}>
                                <div className="taxonomy-node-row">
                                  <span>
                                    <span>{requestType.label || requestType.id || `Type ${typeIndex + 1}`}</span>
                                    <span className="taxonomy-id">{requestType.id || 'no-id'}</span>
                                  </span>
                                  <button
                                    type="button"
                                    className="btn danger taxonomy-delete-btn"
                                    onClick={() =>
                                      void handleDeleteTaxonomyNode({
                                        kind: 'request_type',
                                        areaId: area.id || '',
                                        serviceId: service.id || '',
                                        requestTypeId: requestType.id || '',
                                        label: requestType.label || requestType.id || `Type ${typeIndex + 1}`
                                      })
                                    }
                                    disabled={isSavingTaxonomy || !area.id || !service.id || !requestType.id}
                                  >
                                    Delete
                                  </button>
                                </div>
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
        <div className="admin-requests-header">
          <h2>Extracted Requests</h2>
          {newDialogIds.size > 0 ? <span className="new-dialog-summary">{newDialogIds.size} new</span> : null}
        </div>
        <div className="request-list">
          {requests.length === 0 ? (
            <p className="muted">No requests yet.</p>
          ) : (
            requests.map((request) => {
              const isNewDialog = newDialogIds.has(getDialogId(request))
              return (
                <article
                  key={request.request_id}
                  className={`request-card ${isNewDialog ? 'new-dialog-card' : ''}`}
                >
                  <div className="request-header">
                    <strong>
                      {(request.reporter_email || 'Unknown') + ' | ' + (request.title || 'Untitled request')}
                    </strong>
                    {isNewDialog ? <span className="new-dialog-badge">New</span> : null}
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
              )
            })
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
