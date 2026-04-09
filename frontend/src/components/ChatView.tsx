import { ReactNode, useCallback, useEffect, useRef, useState } from 'react'
import {
  clarifyRequest,
  fetchRequestMessages,
  fetchRequestsForEmail,
  sendMessage,
  submitRequest,
  transcribeAudio
} from '../api'
import { useAudioRecorder } from '../hooks/useAudioRecorder'

type ChatMessage = {
  id: string
  role: 'user' | 'bot'
  content: ReactNode
}

interface RequestSummary {
  request_id: string
  title: string
  urgency: string
  status: string
  clarifying_questions?: string[]
}

interface ConversationMessage {
  sender: 'user' | 'bot'
  content: string
}

const urgencyLabel = (urgency?: string) => (urgency && urgency !== 'unknown' ? urgency : 'not set')

export default function ChatView() {
  const [messages, setMessages] = useState<ChatMessage[]>([
    { id: 'm-1', role: 'bot', content: 'Describe a facility issue and I will draft the request.' }
  ])
  const [input, setInput] = useState('')
  const [email, setEmail] = useState('')
  const [emailReady, setEmailReady] = useState(false)
  const [rememberSession, setRememberSession] = useState(false)
  const [requestList, setRequestList] = useState<RequestSummary[]>([])
  const [selectedRequestId, setSelectedRequestId] = useState<string | null>(null)
  const [pendingRequest, setPendingRequest] = useState<RequestSummary | null>(null)
  const [isSending, setIsSending] = useState(false)
  const [correctionRequestId, setCorrectionRequestId] = useState<string | null>(null)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [isTranscribing, setIsTranscribing] = useState(false)
  const [actionMessageId, setActionMessageId] = useState<string | null>(null)
  const messageCounterRef = useRef(2)
  const feedRef = useRef<HTMLDivElement | null>(null)

  const appendMessage = useCallback((role: ChatMessage['role'], content: ReactNode) => {
    const id = `m-${messageCounterRef.current}`
    messageCounterRef.current += 1
    setMessages((prev) => [...prev, { id, role, content }])
    return id
  }, [])

  const {
    isSupported,
    isRecording,
    hasRecording,
    audioBlob,
    error,
    clearError,
    start,
    stop,
    clear
  } = useAudioRecorder()

  useEffect(() => {
    const storedEmail = localStorage.getItem('supportBotEmail')
    if (storedEmail) {
      setEmail(storedEmail)
      setEmailReady(true)
      setRememberSession(true)
      void loadRequests(storedEmail)
    }
  }, [])

  useEffect(() => {
    if (feedRef.current) {
      feedRef.current.scrollTop = feedRef.current.scrollHeight
    }
  }, [messages, isSending])

  const loadRequests = async (reporterEmail: string) => {
    const data = await fetchRequestsForEmail(reporterEmail)
    setRequestList(data.requests || [])
  }

  const loadConversation = async (requestId: string) => {
    const data = await fetchRequestMessages(requestId)
    const loaded = (data.messages as ConversationMessage[]).map((message) => ({
      id: `m-${messageCounterRef.current++}`,
      role: message.sender,
      content: message.content
    }))
    setMessages(
      loaded.length
        ? loaded
        : [{ id: `m-${messageCounterRef.current++}`, role: 'bot', content: 'No messages recorded yet.' }]
    )
    setActionMessageId(null)
  }

  const appendActionButtons = (requestId: string) => {
    if (actionMessageId) {
      setMessages((prev) => prev.filter((message) => message.id !== actionMessageId))
    }
    const id = appendMessage(
      'bot',
      <div className="chat-actions">
        <button type="button" onClick={() => void handleSubmit(requestId)} className="btn success">
          Submit
        </button>
        <button type="button" onClick={() => handleCorrection(requestId)} className="btn subtle">
          Need correction
        </button>
      </div>
    )
    setActionMessageId(id)
  }

  const handleSend = async () => {
    if (!input.trim() || isSending) return
    setErrorMessage(null)
    const text = input.trim()
    setInput('')
    appendMessage('user', text)
    setIsSending(true)

    try {
      if (correctionRequestId) {
        const updated = await clarifyRequest(correctionRequestId, text)
        appendMessage('bot', `Updated request: ${updated.title} (${updated.status}).`)
        if (updated.clarifying_questions?.length) {
          appendMessage('bot', updated.clarifying_questions[0])
          setPendingRequest({
            request_id: updated.request_id,
            title: updated.title,
            urgency: updated.urgency,
            status: updated.status,
            clarifying_questions: updated.clarifying_questions
          })
        } else {
          appendMessage('bot', 'Thanks, update applied.')
          appendActionButtons(updated.request_id)
        }
        setCorrectionRequestId(null)
        return
      }

      const data = await sendMessage(text, email)
      const request = data.requests?.[0]
      if (!request) {
        appendMessage('bot', 'I could not detect an issue. Please rephrase and try again.')
        return
      }

      appendMessage('bot', `Drafted: ${request.title} (urgency: ${request.urgency || 'unknown'}).`)
      if (request.clarifying_questions?.length) {
        appendMessage('bot', request.clarifying_questions[0])
        setPendingRequest({
          request_id: request.request_id,
          title: request.title,
          urgency: request.urgency,
          status: request.status,
          clarifying_questions: request.clarifying_questions
        })
      } else {
        appendMessage('bot', 'All required slots are filled.')
        appendActionButtons(request.request_id)
        setPendingRequest(null)
      }

      setRequestList((prev) => [
        {
          request_id: request.request_id,
          title: request.title,
          urgency: request.urgency,
          status: request.status,
          clarifying_questions: request.clarifying_questions
        },
        ...prev
      ])
      setSelectedRequestId(request.request_id)
    } catch {
      setErrorMessage('Failed to send message. Please try again.')
    } finally {
      setIsSending(false)
    }
  }

  const handleClarify = async () => {
    if (!pendingRequest || !input.trim() || isSending) return
    setErrorMessage(null)
    const text = input.trim()
    setInput('')
    appendMessage('user', text)
    setIsSending(true)

    try {
      const updated = await clarifyRequest(pendingRequest.request_id, text)
      appendMessage('bot', `Updated request: ${updated.title} (${updated.status}).`)
      if (updated.clarifying_questions?.length) {
        appendMessage('bot', updated.clarifying_questions[0])
        setPendingRequest({
          request_id: updated.request_id,
          title: updated.title,
          urgency: updated.urgency,
          status: updated.status,
          clarifying_questions: updated.clarifying_questions
        })
      } else {
        appendMessage('bot', 'All required slots are filled.')
        appendActionButtons(updated.request_id)
        setPendingRequest(null)
      }
    } catch {
      setErrorMessage('Failed to update request. Please try again.')
    } finally {
      setIsSending(false)
    }
  }

  const handleSubmit = async (requestId: string) => {
    if (isSending) return
    if (actionMessageId) {
      setMessages((prev) => prev.filter((message) => message.id !== actionMessageId))
      setActionMessageId(null)
    }
    setIsSending(true)
    setErrorMessage(null)
    try {
      await submitRequest(requestId)
      appendMessage('bot', 'Submitted. Your request is now in queue.')
      setRequestList((prev) =>
        prev.map((item) => (item.request_id === requestId ? { ...item, status: 'submitted' } : item))
      )
    } catch {
      setErrorMessage('Failed to submit request. Please try again.')
    } finally {
      setIsSending(false)
    }
  }

  const handleCorrection = (requestId: string) => {
    if (actionMessageId) {
      setMessages((prev) => prev.filter((message) => message.id !== actionMessageId))
      setActionMessageId(null)
    }
    setCorrectionRequestId(requestId)
    appendMessage('bot', 'Tell me what to correct and I will update the draft.')
  }

  const handleEmailSubmit = async () => {
    if (!email.trim()) return
    const normalized = email.trim().toLowerCase()
    setEmail(normalized)
    setEmailReady(true)
    if (rememberSession) {
      localStorage.setItem('supportBotEmail', normalized)
    } else {
      localStorage.removeItem('supportBotEmail')
    }
    await loadRequests(normalized)
  }

  const handleSelectRequest = async (requestId: string) => {
    setSelectedRequestId(requestId)
    setPendingRequest(null)
    setCorrectionRequestId(null)
    await loadConversation(requestId)
  }

  const handleNewRequest = () => {
    setSelectedRequestId(null)
    setPendingRequest(null)
    setCorrectionRequestId(null)
    setMessages([{ id: `m-${messageCounterRef.current++}`, role: 'bot', content: 'Describe the next facility issue.' }])
    setActionMessageId(null)
    setInput('')
  }

  const handleTranscribeRecording = async () => {
    if (!audioBlob || isTranscribing) return
    setErrorMessage(null)
    setIsTranscribing(true)
    try {
      const response = await transcribeAudio(
        audioBlob,
        'transcribe this voice message, return only message content'
      )
      if (response.text?.trim()) {
        setInput((prev) => (prev ? `${prev} ${response.text.trim()}` : response.text.trim()))
      } else {
        setErrorMessage('Transcription returned empty text.')
      }
      clear()
    } catch {
      setErrorMessage('Audio transcription failed. Please try again.')
    } finally {
      setIsTranscribing(false)
    }
  }

  if (!emailReady) {
    return (
      <div className="email-gate">
        <div className="panel email-panel">
          <h2>Requester Chat</h2>
          <p className="muted">Enter your contact email to start.</p>
          <label className="form-label" htmlFor="contact-email">
            Contact email
          </label>
          <input
            id="contact-email"
            type="email"
            placeholder="you@clinic.com"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            className="text-input"
          />
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={rememberSession}
              onChange={(event) => setRememberSession(event.target.checked)}
            />
            <span>Remember this email</span>
          </label>
          <button type="button" onClick={() => void handleEmailSubmit()} className="btn primary">
            Start conversation
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="chat-layout">
      <aside className="panel chat-sidebar">
        <div className="sidebar-header">
          <div>
            <strong>Conversations</strong>
            <p className="muted sidebar-subtitle">{email}</p>
          </div>
          <button type="button" onClick={handleNewRequest} className="btn subtle">
            New request
          </button>
        </div>
        <div className="sidebar-list">
          {requestList.length === 0 ? (
            <p className="muted">No requests yet.</p>
          ) : (
            requestList.map((request) => (
              <button
                key={request.request_id}
                type="button"
                className={`conversation-item ${selectedRequestId === request.request_id ? 'active' : ''}`}
                onClick={() => void handleSelectRequest(request.request_id)}
              >
                <div className="conversation-main">
                  <span className="conversation-title">{request.title}</span>
                  <span className="conversation-subline">Urgency: {urgencyLabel(request.urgency)}</span>
                </div>
                <span className={`status-pill status-${request.status}`}>{request.status.replace('_', ' ')}</span>
              </button>
            ))
          )}
        </div>
      </aside>

      <section className="panel chat-card">
        <div className="chat-head">
          <div>
            <h2>Facility Chat</h2>
            <p className="muted chat-subtitle">Describe issues in free text, then review and submit.</p>
          </div>
          {pendingRequest ? <span className="status-pill status-needs_clarification">Awaiting details</span> : null}
        </div>

        <div className="chat-feed" ref={feedRef}>
          {messages.map((message, index) => (
            <div
              key={message.id || `${message.role}-${index}`}
              className={`chat-bubble ${message.role === 'user' ? 'from-user' : 'from-bot'}`}
            >
              <span className="chat-role">{message.role === 'user' ? 'You' : 'Assistant'}</span>
              <div className="chat-content">{message.content}</div>
            </div>
          ))}
          {isSending ? <div className="typing-indicator">Assistant is drafting...</div> : null}
        </div>

        {errorMessage ? <p className="error-text">{errorMessage}</p> : null}
        {error ? <p className="error-text">{error}</p> : null}

        <div className="composer">
          <textarea
            placeholder={
              correctionRequestId
                ? 'Tell me what needs to change...'
                : pendingRequest
                ? 'Answer the follow-up question...'
                : selectedRequestId
                ? 'Add follow-up details...'
                : 'Describe the issue...'
            }
            value={input}
            onChange={(event) => {
              setInput(event.target.value)
              if (error) clearError()
            }}
            className="composer-input"
          />
          <div className="composer-footer">
            <div className="voice-state">
              {isRecording ? (
                <span className="recording-indicator">
                  <span className="recording-dot" />
                  Recording...
                </span>
              ) : null}
              {hasRecording ? <span className="muted">Recording ready for Whisper transcription</span> : null}
              {isTranscribing ? <span className="muted">Transcribing voice message...</span> : null}
              {!isRecording && !hasRecording && !isTranscribing ? (
                <span className="muted">Enter to send, Shift+Enter for newline.</span>
              ) : null}
            </div>
            <div className="composer-actions">
              {isSupported ? (
                <>
                  <button
                    type="button"
                    onClick={isRecording ? stop : () => void start()}
                    className={`btn ${isRecording ? 'danger' : 'subtle'}`}
                  >
                    {isRecording ? 'Stop recording' : 'Record voice'}
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleTranscribeRecording()}
                    disabled={!hasRecording || isTranscribing}
                    className="btn subtle"
                  >
                    Transcribe
                  </button>
                </>
              ) : (
                <span className="muted">Voice not supported in this browser</span>
              )}
              <button
                type="button"
                onClick={() => void (pendingRequest ? handleClarify() : handleSend())}
                disabled={isSending || isTranscribing}
                className="btn primary"
              >
                {pendingRequest ? 'Send answer' : 'Send'}
              </button>
            </div>
          </div>
        </div>
      </section>
    </div>
  )
}
