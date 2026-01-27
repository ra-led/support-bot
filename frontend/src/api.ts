import axios from 'axios'

const apiBaseUrl = import.meta.env.VITE_API_URL || 'http://localhost:5051'

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

export async function sendMessage(message: string) {
  const response = await api.post('/v1/intake/text', {
    message_id: createMessageId(),
    thread_id: null,
    tenant_id: 'default',
    branch_id: 'main',
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

export async function fetchStats() {
  const response = await api.get('/v1/admin/stats')
  return response.data
}
