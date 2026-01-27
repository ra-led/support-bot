# Facility & Repair Intake Bot

Containerized MVP for the facility/repair request intake service described in `DESIGN.MD`. The stack is intentionally lightweight to keep the focus on UI/UX rather than heavy data models.

## What’s included

- **Python + FastAPI backend** with LLM slot-filling (`/v1/intake/text`) and clarification flow (`/v1/requests/{id}/clarify`).
- **Messenger-style requester UI** with a lightweight custom chat layout to keep dependencies minimal.
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

### 1b) Point the frontend at the backend API (optional)

When deploying remotely, set the frontend API base URL so the UI doesn't default to `localhost`:

```bash
export VITE_API_URL="https://your-backend.example.com"
```

### Optional: Use the bundled nginx reverse proxy (recommended for remote)

The `nginx` service serves the frontend and proxies `/api/*` to the backend to avoid CORS issues:

- Frontend: `http://<host>:8080`
- Backend via proxy: `http://<host>:8080/api/...`

If you access the UI through nginx on port 8080, the frontend will automatically call `/api` on the same origin.

### 2) Run the containers

```bash
docker-compose up --build
```

### 3) Open the UI

- Requester chat UI: [http://localhost:5173](http://localhost:5173)
- Admin stats view: [http://localhost:5173/admin](http://localhost:5173/admin)
- Backend API: [http://localhost:5051/health](http://localhost:5051/health)

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

- Data is stored in a lightweight **SQLite** file (`data.db`) for simplicity.
- The fallback parser still returns slot-filling prompts when the LLM key is missing.
- The UI is intentionally messenger-like with bubble chat to make slot-filling feel native.
