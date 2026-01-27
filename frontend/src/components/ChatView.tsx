import { ReactNode, useEffect, useRef, useState } from 'react'
import {
  clarifyRequest,
  fetchRequestMessages,
  fetchRequestsForEmail,
  sendMessage,
  submitRequest
} from '../api'

type ChatMessage = {
  id: number
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

export default function ChatView() {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: 1,
      content: 'Hi! Describe the facility issue and I will draft the request.'
    }
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
  const feedRef = useRef<HTMLDivElement | null>(null)
  const [typingDots, setTypingDots] = useState('')

  useEffect(() => {
    const storedEmail = localStorage.getItem('supportBotEmail')
    if (storedEmail) {
      setEmail(storedEmail)
      setEmailReady(true)
      setRememberSession(true)
      loadRequests(storedEmail)
    }
  }, [])

  useEffect(() => {
    if (!isSending) {
      setTypingDots('')
      return
    }
    const frames = ['', '.', '..', '...']
    let index = 0
    const interval = window.setInterval(() => {
      index = (index + 1) % frames.length
      setTypingDots(frames[index])
    }, 400)
    return () => window.clearInterval(interval)
  }, [isSending])

  const appendMessage = (content: ReactNode, id: number) => {
    setMessages((prev) => [...prev, { id, content }])
  }

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
      id: message.sender === 'user' ? 0 : 1,
      content: message.content
    }))
    setMessages(
      loaded.length
        ? loaded
        : [
            {
              id: 1,
              content: 'No messages recorded yet.'
            }
          ]
    )
  }

  const handleSend = async () => {
    if (!input.trim() || isSending) return
    const text = input.trim()
    setInput('')
    appendMessage(text, 0)
    setIsSending(true)

    try {
      if (correctionRequestId) {
        const updated = await clarifyRequest(correctionRequestId, text)
        appendMessage(
          <>
            Updated request: <strong>{updated.title}</strong> ({updated.status}).
          </>,
          1
        )
        if (updated.clarifying_questions?.length) {
          appendMessage(updated.clarifying_questions[0], 1)
          setPendingRequest({
            request_id: updated.request_id,
            title: updated.title,
            urgency: updated.urgency,
            status: updated.status,
            clarifying_questions: updated.clarifying_questions
          })
        } else {
          appendMessage('Thanks! I updated the request.', 1)
          appendActionButtons(updated.request_id)
        }
        setCorrectionRequestId(null)
        return
      }

      const data = await sendMessage(text, email)
      const request = data.requests?.[0]
      if (request) {
        appendMessage(
          <>
            <strong>Drafted:</strong> {request.title} · <strong>urgency</strong>{' '}
            {request.urgency || 'unknown'}.
          </>,
          1
        )
        if (request.clarifying_questions?.length) {
          appendMessage(request.clarifying_questions[0], 1)
          setPendingRequest({
            request_id: request.request_id,
            title: request.title,
            urgency: request.urgency,
            status: request.status,
            clarifying_questions: request.clarifying_questions
          })
        } else {
          appendMessage('All required slots are filled.', 1)
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
      } else {
        appendMessage('I could not detect an issue. Try rephrasing?', 1)
      }
    } finally {
      setIsSending(false)
    }
  }

  const handleClarify = async () => {
    if (!pendingRequest || !input.trim() || isSending) return
    const text = input.trim()
    setInput('')
    appendMessage(text, 0)
    setIsSending(true)

    try {
      const updated = await clarifyRequest(pendingRequest.request_id, text)
      appendMessage(
        <>
          Updated request: <strong>{updated.title}</strong> ({updated.status}).
        </>,
        1
      )
      if (updated.clarifying_questions?.length) {
        appendMessage(updated.clarifying_questions[0], 1)
        setPendingRequest({
          request_id: updated.request_id,
          title: updated.title,
          urgency: updated.urgency,
          status: updated.status,
          clarifying_questions: updated.clarifying_questions
        })
      } else {
        appendMessage('All required slots are filled.', 1)
        appendActionButtons(updated.request_id)
        setPendingRequest(null)
      }
    } finally {
      setIsSending(false)
    }
  }

  const appendActionButtons = (requestId: string) => {
    appendMessage(
      <div className="chat-actions">
        <button
          type="button"
          onClick={() => handleSubmit(requestId)}
          className="nes-btn primary"
        >
          Submit
        </button>
        <button
          type="button"
          onClick={() => handleCorrection(requestId)}
          className="nes-btn warning"
        >
          Need correction
        </button>
      </div>,
      1
    )
  }

  const handleSubmit = async (requestId: string) => {
    if (isSending) return
    setIsSending(true)
    try {
      await submitRequest(requestId)
      appendMessage('Submitted ✅ Your request is on the way.', 1)
      setRequestList((prev) =>
        prev.map((item) =>
          item.request_id === requestId ? { ...item, status: 'submitted' } : item
        )
      )
    } finally {
      setIsSending(false)
    }
  }

  const handleCorrection = (requestId: string) => {
    setCorrectionRequestId(requestId)
    appendMessage(
      'Happy to tweak it — what should I correct or add?',
      1
    )
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
    setMessages([
      {
        id: 1,
        content: 'Describe the next facility issue and I will draft the request.'
      }
    ])
  }

  if (!emailReady) {
    return (
      <div className="chat-card contact-screen nes-container">
        <h2>Requester Chat</h2>
        <p className="muted">Enter your contact email to start</p>
        <div className="contact-form nes-field">
          <label htmlFor="contact-email">Contact email</label>
          <input
            id="contact-email"
            type="email"
            placeholder="you@clinic.com"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            className="nes-input"
          />
          <label className="checkbox-row nes-checkbox">
            <input
              type="checkbox"
              checked={rememberSession}
              onChange={(event) => setRememberSession(event.target.checked)}
            />
            <span>Use cookies to remember me</span>
          </label>
          <button type="button" onClick={handleEmailSubmit} className="nes-btn primary">
            Start conversation
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="chat-layout">
      <aside className="chat-sidebar nes-container">
        <div className="sidebar-header">
          <div>
            <strong>Conversations</strong>
            <p className="muted">{email}</p>
          </div>
          <button type="button" onClick={handleNewRequest} className="nes-btn">
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
                className={`conversation-item ${
                  selectedRequestId === request.request_id ? 'active' : ''
                }`}
                onClick={() => handleSelectRequest(request.request_id)}
              >
                <span>{request.title}</span>
                <span className="nes-badge">{request.status}</span>
              </button>
            ))
          )}
        </div>
      </aside>
      <div className="chat-card nes-container">
        <h2>Requester Chat</h2>
        <div className="chat-feed" ref={feedRef}>
          <section className="message-list">
            {messages.map((message, index) => (
              <section
                key={`${message.id}-${index}`}
                className={`message ${message.id === 0 ? '-right' : '-left'}`}
              >
                {message.id !== 0 ? <i className="nes-bcrikko" /> : null}
                <div
                  className={`nes-balloon ${
                    message.id === 0 ? 'from-right' : 'from-left'
                  }`}
                >
                  <p>{message.content}</p>
                </div>
                {message.id === 0 ? <i className="nes-bcrikko" /> : null}
              </section>
            ))}
            {isSending ? (
              <section className="message -left">
                <i className="nes-bcrikko" />
                <div className="nes-balloon from-left">
                  <p>{typingDots || '.'}</p>
                </div>
              </section>
            ) : null}
          </section>
        </div>
        <div className="chat-input">
          <textarea
            placeholder={
              correctionRequestId
                ? 'Tell me what needs to change…'
                : pendingRequest
                ? 'Answer the follow-up question…'
                : selectedRequestId
                ? 'Add a follow-up to this request…'
                : 'Describe the issue…'
            }
            value={input}
            onChange={(event) => setInput(event.target.value)}
            className="nes-textarea"
          />
          <button
            type="button"
            onClick={pendingRequest ? handleClarify : handleSend}
            disabled={isSending}
            className="nes-btn"
          >
            {pendingRequest ? 'Send answer' : 'Send'}
          </button>
        </div>
      </div>
    </div>
  )
}
