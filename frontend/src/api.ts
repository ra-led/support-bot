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

export async function downloadIssuesExport() {
  const response = await api.get('/v1/admin/export/issues.xlsx', {
    responseType: 'blob'
  })
  return response.data as Blob
}

export async function transcribeAudio(audioBlob: Blob, prompt?: string) {
  const isWebm = audioBlob.type.toLowerCase().includes('webm')
  const uploadBlob = isWebm ? await convertWebmToWav(audioBlob) : audioBlob
  if (uploadBlob.type.toLowerCase().includes('webm')) {
    throw new Error('Recorded audio format webm is not supported by the configured transcription model.')
  }
  const uploadName = pickUploadName(uploadBlob)
  const formData = new FormData()
  formData.append('file', uploadBlob, uploadName)
  if (prompt) {
    formData.append('prompt', prompt)
  }

  const response = await api.post('/v1/audio/transcribe', formData, {
    headers: {
      'Content-Type': 'multipart/form-data'
    }
  })
  return response.data as { text: string }
}
