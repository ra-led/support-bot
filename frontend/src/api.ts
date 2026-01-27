import axios from 'axios'

const apiBaseUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000'

export const api = axios.create({
  baseURL: apiBaseUrl
})

export async function sendMessage(message: string) {
  const response = await api.post('/v1/intake/text', {
    message_id: crypto.randomUUID(),
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
