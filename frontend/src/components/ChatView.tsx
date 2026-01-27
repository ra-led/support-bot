import { ReactNode, useEffect, useRef, useState } from 'react'
import { clarifyRequest, sendMessage, submitRequest } from '../api'

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

export default function ChatView() {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: 1,
      content: 'Hi! Describe the facility issue and I will draft the request.'
    }
  ])
  const [input, setInput] = useState('')
  const [pendingRequest, setPendingRequest] = useState<RequestSummary | null>(null)
  const [isSending, setIsSending] = useState(false)
  const [correctionRequestId, setCorrectionRequestId] = useState<string | null>(null)
  const feedRef = useRef<HTMLDivElement | null>(null)

  const appendMessage = (content: ReactNode, id: number) => {
    setMessages((prev) => [...prev, { id, content }])
  }

  useEffect(() => {
    if (feedRef.current) {
      feedRef.current.scrollTop = feedRef.current.scrollHeight
    }
  }, [messages, isSending])

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

      const data = await sendMessage(text)
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
          className="primary"
        >
          Submit
        </button>
        <button
          type="button"
          onClick={() => handleCorrection(requestId)}
          className="secondary"
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

  return (
    <div className="chat-card">
      <h2>Requester Chat</h2>
      <p className="tag">Messenger-style slot filling</p>
      <div className="chat-feed" ref={feedRef}>
        {messages.map((message, index) => (
          <div
            key={`${message.id}-${index}`}
            className={`chat-bubble ${message.id === 0 ? 'from-user' : 'from-bot'}`}
          >
            <span className="chat-sender">{message.id === 0 ? 'You' : 'Bot'}</span>
            <div className="chat-content">{message.content}</div>
          </div>
        ))}
        {isSending ? (
          <div className="chat-bubble from-bot typing">
            <span className="chat-sender">Bot</span>
            <div className="typing-dots">
              <span />
              <span />
              <span />
            </div>
          </div>
        ) : null}
      </div>
      <div className="chat-input">
        <textarea
          placeholder={
            correctionRequestId
              ? 'Tell me what needs to change…'
              : pendingRequest
              ? 'Answer the follow-up question…'
              : 'Describe the issue…'
          }
          value={input}
          onChange={(event) => setInput(event.target.value)}
        />
        <button
          type="button"
          onClick={pendingRequest ? handleClarify : handleSend}
          disabled={isSending}
        >
          {pendingRequest ? 'Send answer' : 'Send'}
        </button>
      </div>
    </div>
  )
}
