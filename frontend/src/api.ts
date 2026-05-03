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
const ADMIN_PASSWORD_STORAGE_KEY = 'supportBotAdminPassword'

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

const getStoredAdminPassword = () => {
  if (typeof window === 'undefined') return ''
  return localStorage.getItem(ADMIN_PASSWORD_STORAGE_KEY) || ''
}

const getAdminHeaders = () => {
  const password = getStoredAdminPassword()
  return password ? { 'X-Admin-Password': password } : {}
}

export const setAdminPassword = (password: string) => {
  if (typeof window === 'undefined') return
  localStorage.setItem(ADMIN_PASSWORD_STORAGE_KEY, password)
}

export const clearAdminPassword = () => {
  if (typeof window === 'undefined') return
  localStorage.removeItem(ADMIN_PASSWORD_STORAGE_KEY)
}

export const getAdminPassword = () => getStoredAdminPassword()

const AUDIO_DEBUG = true

const AUDIO_CONTEXT =
  typeof window !== 'undefined'
    ? (window.AudioContext || (window as typeof window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext)
    : undefined

const pickUploadName = (blob: Blob) => {
  const type = blob.type.toLowerCase()
  if (type.includes('webm')) return 'recording.webm'
  if (type.includes('wav')) return 'recording.wav'
  if (type.includes('ogg')) return 'recording.ogg'
  if (type.includes('mpeg') || type.includes('mp3')) return 'recording.mp3'
  if (type.includes('mp4') || type.includes('m4a')) return 'recording.m4a'
  return 'recording.wav'
}

const clampSample = (value: number) => Math.max(-1, Math.min(1, value))

const encodeWavMono16 = (buffer: AudioBuffer) => {
  const channelCount = buffer.numberOfChannels
  const sampleRate = buffer.sampleRate
  const frameCount = buffer.length
  const bytesPerSample = 2
  const blockAlign = bytesPerSample
  const byteRate = sampleRate * blockAlign
  const dataSize = frameCount * bytesPerSample
  const totalSize = 44 + dataSize
  const output = new ArrayBuffer(totalSize)
  const view = new DataView(output)

  const writeString = (offset: number, text: string) => {
    for (let i = 0; i < text.length; i += 1) {
      view.setUint8(offset + i, text.charCodeAt(i))
    }
  }

  writeString(0, 'RIFF')
  view.setUint32(4, 36 + dataSize, true)
  writeString(8, 'WAVE')
  writeString(12, 'fmt ')
  view.setUint32(16, 16, true)
  view.setUint16(20, 1, true)
  view.setUint16(22, 1, true)
  view.setUint32(24, sampleRate, true)
  view.setUint32(28, byteRate, true)
  view.setUint16(32, blockAlign, true)
  view.setUint16(34, 16, true)
  writeString(36, 'data')
  view.setUint32(40, dataSize, true)

  const channels = Array.from({ length: channelCount }, (_, index) => buffer.getChannelData(index))
  let offset = 44
  for (let i = 0; i < frameCount; i += 1) {
    let sample = 0
    for (let c = 0; c < channelCount; c += 1) {
      sample += channels[c][i] || 0
    }
    sample /= channelCount || 1
    const clamped = clampSample(sample)
    const pcm = clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff
    view.setInt16(offset, pcm, true)
    offset += 2
  }

  return new Blob([output], { type: 'audio/wav' })
}

const convertWebmToWav = async (blob: Blob) => {
  if (!AUDIO_CONTEXT) return blob
  const context = new AUDIO_CONTEXT()
  try {
    const arrayBuffer = await blob.arrayBuffer()
    const decoded = await context.decodeAudioData(arrayBuffer.slice(0))
    return encodeWavMono16(decoded)
  } catch {
    return blob
  } finally {
    await context.close()
  }
}

const mustTranscodeToWav = (blob: Blob) => {
  const type = blob.type.toLowerCase()
  return type.includes('webm') || type.includes('mp4') || type.includes('m4a')
}

const readHeaderHex = async (blob: Blob, bytes = 16) => {
  const slice = blob.slice(0, bytes)
  const buffer = await slice.arrayBuffer()
  const view = new Uint8Array(buffer)
  return Array.from(view)
    .map((value) => value.toString(16).padStart(2, '0'))
    .join('')
}

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
  const response = await api.get('/v1/admin/stats', {
    headers: getAdminHeaders()
  })
  return response.data
}

export async function fetchAdminTaxonomy() {
  const response = await api.get('/v1/admin/taxonomy', {
    headers: getAdminHeaders()
  })
  return response.data as { facilities_areas: unknown[] }
}

export async function updateAdminTaxonomy(facilitiesAreas: unknown[]) {
  const response = await api.put(
    '/v1/admin/taxonomy',
    { facilities_areas: facilitiesAreas },
    { headers: getAdminHeaders() }
  )
  return response.data as { facilities_areas: unknown[] }
}

export async function fetchRequests() {
  const response = await api.get('/v1/requests', {
    headers: getAdminHeaders()
  })
  return response.data
}

export async function fetchRequestsForEmail(email: string) {
  const response = await api.get('/v1/requests', {
    params: { reporter_email: email }
  })
  return response.data
}

export async function fetchRequestMessages(requestId: string, reporterEmail?: string) {
  const response = await api.get(`/v1/requests/${requestId}/messages`, {
    params: reporterEmail ? { reporter_email: reporterEmail } : undefined,
    headers: reporterEmail ? undefined : getAdminHeaders()
  })
  return response.data
}

export async function downloadIssuesExport() {
  const response = await api.get('/v1/admin/export/issues.xlsx', {
    headers: getAdminHeaders(),
    responseType: 'blob'
  })
  return response.data as Blob
}

export async function fetchDialogTrace(dialogId: string) {
  const response = await api.get(`/v1/admin/traces/${dialogId}`, {
    headers: getAdminHeaders()
  })
  return response.data as {
    dialog_id: string
    request: Record<string, unknown>
    traces: Array<{
      id: number
      request_id: string
      model: string
      schema_name: string
      prompt: string
      response_text: string
      created_at: string
    }>
  }
}

export async function transcribeAudio(audioBlob: Blob, prompt?: string) {
  const originalHeaderHex = await readHeaderHex(audioBlob)
  if (AUDIO_DEBUG) {
    console.log('[audio][front] original blob', {
      type: audioBlob.type,
      size: audioBlob.size,
      headerHex: originalHeaderHex
    })
  }

  const mustTranscode = mustTranscodeToWav(audioBlob)
  const uploadBlob = mustTranscode ? await convertWebmToWav(audioBlob) : audioBlob
  const uploadHeaderHex = await readHeaderHex(uploadBlob)
  if (AUDIO_DEBUG) {
    console.log('[audio][front] upload blob', {
      transcodedToWav: mustTranscode,
      type: uploadBlob.type,
      size: uploadBlob.size,
      headerHex: uploadHeaderHex
    })
  }
  if (mustTranscode && !uploadBlob.type.toLowerCase().includes('wav')) {
    throw new Error('Failed to transcode recorded audio to wav. Browser returned unsupported format.')
  }
  if (uploadBlob.type.toLowerCase().includes('webm') || uploadBlob.type.toLowerCase().includes('mp4')) {
    throw new Error('Recorded audio format is not supported by the configured transcription model.')
  }
  const uploadName = pickUploadName(uploadBlob)
  if (AUDIO_DEBUG) {
    console.log('[audio][front] upload filename', { uploadName, prompt })
  }
  const formData = new FormData()
  formData.append('file', uploadBlob, uploadName)
  if (prompt) {
    formData.append('prompt', prompt)
  }

  try {
    const response = await api.post('/v1/audio/transcribe', formData, {
      headers: {
        'Content-Type': 'multipart/form-data'
      }
    })
    if (AUDIO_DEBUG) {
      console.log('[audio][front] transcribe success', response.data)
    }
    return response.data as { text: string }
  } catch (error) {
    if (AUDIO_DEBUG) {
      console.error('[audio][front] transcribe error', error)
    }
    throw error
  }
}
