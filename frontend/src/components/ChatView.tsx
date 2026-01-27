import { useState } from 'react'
import { ChatFeed, Message } from 'react-chat-ui'
import { clarifyRequest, sendMessage } from '../api'

interface RequestSummary {
  request_id: string
  title: string
  urgency: string
  status: string
  clarifying_questions?: string[]
}

export default function ChatView() {
  const [messages, setMessages] = useState<Message[]>([
    new Message({
      id: 1,
      message: 'Hi! Describe the facility issue and I will draft the request.'
    })
  ])
  const [input, setInput] = useState('')
  const [pendingRequest, setPendingRequest] = useState<RequestSummary | null>(null)
  const [isSending, setIsSending] = useState(false)

  const appendMessage = (text: string, id: number) => {
    setMessages((prev) => [...prev, new Message({ id, message: text })])
  }

  const handleSend = async () => {
    if (!input.trim() || isSending) return
    const text = input.trim()
    setInput('')
    appendMessage(text, 0)
    setIsSending(true)

    try {
      const data = await sendMessage(text)
      const request = data.requests?.[0]
      if (request) {
        const summary = `Drafted: ${request.title} · urgency ${request.urgency || 'unknown'}.`
        appendMessage(summary, 1)
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
          appendMessage('Ready to submit. ✅', 1)
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
      appendMessage(`Updated request: ${updated.title} (${updated.status}).`, 1)
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
        appendMessage('All set! Request is ready for ops.', 1)
        setPendingRequest(null)
      }
    } finally {
      setIsSending(false)
    }
  }

  return (
    <div className="chat-card">
      <h2>Requester Chat</h2>
      <p className="tag">Messenger-style slot filling</p>
      <ChatFeed
        messages={messages}
        showSenderName
        bubbleStyles={{
          text: { fontSize: 14 },
          chatbubble: { borderRadius: 16, padding: 12 }
        }}
      />
      <div className="chat-input">
        <textarea
          placeholder={pendingRequest ? 'Answer the follow-up question…' : 'Describe the issue…'}
          value={input}
          onChange={(event) => setInput(event.target.value)}
        />
        <button type="button" onClick={pendingRequest ? handleClarify : handleSend}>
          {pendingRequest ? 'Send answer' : 'Send'}
        </button>
      </div>
    </div>
  )
}
