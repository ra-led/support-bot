import axios from 'axios'

const normalizeUrl = (value: string) => {
  const trimmed = value.trim()
  const noWeirdColon = trimmed.replace('/:', ':')
  return noWeirdColon.replace(/\/$/, '')
}

const resolveApiBaseUrl = () => {
  const envUrl = import.meta.env.VITE_API_URL
  if (envUrl) {
    return normalizeUrl(envUrl)
  }
  if (typeof window !== 'undefined') {
    const { hostname, protocol, port, origin } = window.location
    if (port === '5173') {
      return `${protocol}//${hostname}:5051`
    }
    return `${origin}/api`
  }
  return 'http://localhost:5051'
}

const apiBaseUrl = resolveApiBaseUrl()

const createMessageId = () => {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID()
  }
  const fallback = `${Date.now()}-${Math.random().toString(16).slice(2)}`
  return `msg-${fallback}`
}

export const api = axios.create({
  baseURL: apiBaseUrl
})

export async function sendMessage(message: string, reporterEmail: string) {
  const response = await api.post('/v1/intake/text', {
    message_id: createMessageId(),
    thread_id: null,
    tenant_id: 'default',
    branch_id: 'main',
    reporter_email: reporterEmail,
    channel: 'chatbot',
    message_text: message,
    user_context: {
      name: 'Front Desk',
      role: 'requester'
    },
    received_at: new Date().toISOString()
  })
  return response.data
}

export async function clarifyRequest(requestId: string, text: string) {
  const response = await api.post(`/v1/requests/${requestId}/clarify`, {
    additional_text: text,
    answers: {}
  })
  return response.data
}

export async function submitRequest(requestId: string) {
  const response = await api.post(`/v1/requests/${requestId}/submit`)
  return response.data
}

export async function fetchStats() {
  const response = await api.get('/v1/admin/stats')
  return response.data
}

export async function fetchRequests() {
  const response = await api.get('/v1/requests')
  return response.data
}

export async function fetchRequestsForEmail(email: string) {
  const response = await api.get('/v1/requests', {
    params: { reporter_email: email }
  })
  return response.data
}

export async function fetchRequestMessages(requestId: string) {
  const response = await api.get(`/v1/requests/${requestId}/messages`)
  return response.data
}
