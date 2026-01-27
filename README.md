# Facility & Repair Intake Bot

Containerized MVP for the facility/repair request intake service described in `DESIGN.MD`. The stack is intentionally lightweight to keep the focus on UI/UX rather than heavy data models.

## What’s included

- **Python + FastAPI backend** with LLM slot-filling (`/v1/intake/text`) and clarification flow (`/v1/requests/{id}/clarify`).
- **Messenger-style requester UI** using the open-source [`react-chat-ui`](https://github.com/brandonmowat/react-chat-ui) component.
- **Separated admin stats screen** for quick operational visibility.
- **Docker + docker-compose** for local boot.

## Quick start

### 1) Configure OpenAI proxy credentials

Set the proxy-backed OpenAI API key (required for real LLM extraction; a basic fallback parser is used if missing):

```bash
export OPENAI_API_KEY="your_key_here"
```

Optional overrides:

```bash
export OPENAI_BASE_URL="https://api.proxyapi.ru/openai/v1"
export OPENAI_MODEL="gpt-5.1-mini"
```

### 2) Run the containers

```bash
docker-compose up --build
```

### 3) Open the UI

- Requester chat UI: [http://localhost:5173](http://localhost:5173)
- Admin stats view: [http://localhost:5173/admin](http://localhost:5173/admin)

## Service flow

1. **Requester describes an issue** in the chat UI.
2. **Backend calls the LLM** using the proxy-based OpenAI client.
3. **Slots are extracted** into requests (split if multiple issues).
4. If information is missing, **clarifying questions appear in chat**.
5. Admin stats show counts by status.

## API highlights

### POST `/v1/intake/text`

Submits raw free-text from the chat UI.

```json
{
  "message_id": "string",
  "thread_id": "string|null",
  "tenant_id": "string",
  "branch_id": "string",
  "channel": "chatbot",
  "message_text": "string",
  "user_context": { "name": "string|null", "role": "string|null" },
  "received_at": "ISO-8601"
}
```

### POST `/v1/requests/{request_id}/clarify`

Provides additional text or answers to missing slots.

```json
{
  "additional_text": "string",
  "answers": { "field.path": "value" }
}
```

### GET `/v1/admin/stats`

Returns a simple count of requests by status.

## Notes

- Data is stored **in-memory** for simplicity; restarting the backend clears it.
- The fallback parser still returns slot-filling prompts when the LLM key is missing.
- The UI is intentionally messenger-like with bubble chat to make slot-filling feel native.
