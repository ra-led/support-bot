# Facility & Repair Request Intake Service (LLM Slot Filling)

## 1. Overview

### 1.1 Purpose
Build a web service that enables clinic branch employees to submit **facility/repair/work requests** through a **native LLM chatbot** (free-text). The service must:
- Extract structured fields from natural language (slot filling)
- Create one or multiple standardized requests per message
- Categorize breakdowns using a hierarchical taxonomy for operations
- Store breakdown categories for statistics/analytics (tenant-specific, configurable)

**Note:** Example emails are provided only for domain context and typical phrasing. Email ingestion is not required.

### 1.2 Key concepts
- **Slot filling**: Extract a defined schema of fields (“slots”) from free-text.
- **Operational taxonomy**: Standard, hierarchical categories used to route/triage work (Facilities Area → Impacted Service → Request Type).
- **Analytics tags**: Tenant-specific reporting fields (like the clinic XLSX), not universal across all branches/clinic types.

---

## 2. Users and roles

### 2.1 Roles
1) **Requester (Branch employee)**  
   Submits issues through chatbot; answers follow-up questions.

2) **Triage/Facilities Admin (Ops)**  
   Reviews extracted requests, corrects fields, assigns priority, routes to teams/vendors.

3) **Tenant Admin (Configuration)**  
   Manages taxonomy mappings, branch metadata, and analytics schema per tenant.

4) **Analyst/Manager**  
   Views dashboards and exports statistics by category, branch, time, etc.

---

## 3. Use cases (based on provided examples)

### UC-01: Single issue request (urgent plumbing)
**Input:** “Female toilet on L1 is blocked… urgent”  
**Expected:**
- One request created
- Category: Plumbing → Blockages → Toilet (example mapping)
- Location: Floor L1 + restroom
- Urgency: urgent
- Clarification if missing site/branch

### UC-02: Accessibility-impact issue (roller door)
**Input:** “One roller door not open… cuts off wheelchair ramp access”  
**Expected:**
- One request created
- Safety/Access impact = true
- Urgency high/urgent
- Category: Building Access/Doors → Roller/Automatic Doors → Fault/Repair

### UC-03: Multi-room lighting issue (multiple problems in one message)
**Input:** “Lights cannot be turned off in 178 and 179…”  
**Expected:**
- Either:
  - (Preferred) multiple requests split by room/issue; or
  - one request with multiple sub-items (but must be representable as multiple actionable tickets downstream)
- Location parsing: rooms [178,179]
- Category: Electrical → Lighting → Existing lighting issue
- Urgency high if impacts clinical capacity

### UC-04: Multi-issue task list (mixed maintenance + move furniture + keys)
**Input:** A list: filing cabinets removal, bathroom lock screws, picture hanging, TV relocation, keys…  
**Expected:**
- Multiple requests generated and separated
- Each with its own category and location context (if available)
- Clarifying questions for unknown locations/details (e.g., “Which bathrooms?”, “Which storage area?”)

### UC-05: Access card issue with ID
**Input:** “Staff ID (669015) not giving access”  
**Expected:**
- Category: Access & Security → Access card/permissions → Access issue
- Asset identifier stored: 669015
- Clarify which areas fail (if required)

### UC-06: Informational / no-action event report
**Input:** “Light stopped working earlier but now OK; just FYI”  
**Expected:**
- Create request with low urgency OR mark as “info-only” depending on policy
- Store as event for reliability stats
- No dispatch required unless configured

---

## 4. Product behavior

### 4.1 Message → Requests
A single user message may contain:
- One issue → one request
- Multiple issues → multiple requests
- A mix of “work request” and “info report” → should still be captured and categorized

### 4.2 Missing information policy
If required slots are missing or uncertain:
- Request status becomes **needs_clarification**
- Service returns **short targeted clarifying questions**
- Chatbot collects answers and resubmits them to complete slots

### 4.3 “Native format” integration
The intake API is designed for chatbot integration:
- The chatbot sends raw free-text and context (tenant, branch, user)
- The API returns structured requests + questions
- The chatbot shows questions to user and resubmits answers to finalize

---

## 5. Data model (logical)

### 5.1 Entities

#### Tenant
- `tenant_id`
- name
- settings (LLM policy, required slot policy, etc.)

#### Branch/Site
- `branch_id`
- `tenant_id`
- name
- address / timezone
- default campus/building labels (optional)

#### Message
- `message_id` (idempotency key)
- `tenant_id`, `branch_id`
- `channel` (chatbot)
- `sender` (name/email optional)
- `text` raw
- timestamps
- `thread_id` (optional)

#### Request
- `request_id`
- `tenant_id`, `branch_id`
- `title`, `description`
- urgency, safety/access impact, business impact
- location fields
- taxonomy pointers: `facilities_area_id`, `impacted_service_id`, `request_type_id`
- `status` (draft/needs_clarification/ready/submitted/closed)
- extraction metadata (confidence, missing slots)
- audit fields

#### Asset (optional child)
- `asset_id`
- `request_id`
- type (door, light, access card, cabinet, etc.)
- identifier (e.g., staff id)
- notes

#### Taxonomy tables
- `facilities_area` (level 1)
- `impacted_service` (level 2, belongs to facilities_area)
- `request_type` (level 3, belongs to impacted_service)
- Each has:
  - stable code
  - display label
  - active flag
  - tenant scope: global or per-tenant overrides

#### Analytics schema (tenant-configurable)
- `analytics_schema` (per tenant)
- `analytics_field_definition`
  - field key, label
  - type: boolean | enum | text | number
  - allowed values (for enums)
  - applicability rules (optional; e.g. only for certain branches)
- `analytics_field_value`
  - request_id
  - field_key
  - value

### 5.2 Multi-issue representation
Preferred: split into multiple Requests with a shared `source_message_id` (and optional `group_id`).

---

## 6. Slot schema (request fields)

### 6.1 Required slots for “ready”
- `title`
- `description`
- `urgency` (or default `unknown` with question)
- `facilities_area`
- `impacted_service`
- `location.campus_or_site` (or branch_id) and at least one of:
  - building/floor/room/free_text

### 6.2 Optional slots
- `request_type` (if taxonomy supports)
- `assets[]`
- `business_impact` (free-text)
- `safety_or_access_impact` (boolean)
- reporter contact info

### 6.3 Extraction metadata
Per request:
- `missing_required_fields[]`
- `clarifying_questions[]`
- confidence scores (overall + per slot)

---

## 7. Classification & taxonomy requirements

### 7.1 Operational taxonomy
The PDF form indicates the selection flow:
**Facilities Area → Impacted Service → Request Type**  
This hierarchy must be represented in the DB and returned to the client for UI dropdowns.

### 7.2 Tenant-specific analytics breakdowns
The XLSX demonstrates reporting columns and categories that are not universal across all clinic types.
Requirements:
- Analytics fields are configurable per tenant
- Must support:
  - boolean flags (e.g., “Toilets”)
  - enums (e.g., severity classes, subtypes)
  - text “other”
- Requests may store 0..N analytics field values

---

## 8. API design

### 8.1 Authentication
- OAuth2/JWT (recommended) or API keys per tenant (minimum viable)
- All endpoints scoped by tenant

### 8.2 Endpoints (v1)

#### POST /v1/intake/text
Accept free-text from chatbot and return extracted requests.
Request:
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
````

Response:

```json
{
  "requests": [ /* normalized request objects */ ],
  "message_saved": true
}
```

Idempotency:

* If `message_id` already processed, return the same output (or latest saved extraction) without duplication.

#### POST /v1/requests/{request_id}/clarify

Submit answers/new text to fill missing slots.
Request:

```json
{
  "additional_text": "string",
  "answers": { "field.path": "value" }
}
```

Response:

* updated request + updated missing fields/questions

#### GET /v1/requests/{request_id}

Return the request in normalized format.

#### GET /v1/taxonomy

Return taxonomy for UI:

```json
{
  "facilities_areas": [
    {
      "id": "A1",
      "label": "Electrical",
      "impacted_services": [
        { "id": "S1", "label": "Lighting", "request_types": [ ... ] }
      ]
    }
  ]
}
```

#### GET /v1/analytics/schema?tenant_id=...

Return tenant analytics field definitions.

#### POST /v1/analytics/schema (admin)

Create/update analytics fields (tenant admin only).

#### POST /v1/taxonomy (admin)

Create/update taxonomy items (tenant admin only).

---

## 9. LLM extraction design

### 9.1 Deterministic JSON output

* Use a strict JSON schema (or function-calling / tool schema) to force valid output.
* Reject non-JSON; re-prompt with a “fix JSON” step if needed.
* Always return `requests[]`, even if empty.

### 9.2 Multi-issue splitting

LLM must:

* detect multiple distinct tasks/issues
* output as multiple request objects

Heuristics to support LLM:

* bullet list detection
* multiple locations/rooms in one message
* multiple verbs: remove/install/tighten/hang/relocate

### 9.3 Confidence scoring

Return float 0..1:

* overall
* per-slot (categorization/location/urgency)
  Used to decide when to ask clarifying questions.

### 9.4 Clarifying questions generation

Rules:

* ask only for missing or ambiguous required slots
* keep questions short and specific
  Examples:
* “Which branch/site is this for?”
* “What room number or nearest landmark is the blocked toilet?”
* “Is this urgent (affecting today’s appointments) or can it be scheduled?”

### 9.5 PII handling

* Avoid extracting patient identifiers (not required)
* Redact or ignore if present in text
* Store message raw under tenant security rules

---

## 10. UI design (MVP screens)

> UI is described for completeness. Backend must support these flows even if UI is built later.

### 10.1 Requester UI (chatbot)

**Screen/flow:**

1. User types free-text: “AC in G13 is not working…”
2. Bot shows extracted summary:

   * “I’ll log: HVAC → AC not working, Location: G13, Priority: normal.”
3. If missing info, bot asks:

   * “Which branch is this for?” “Is it urgent?”
4. User answers, bot resubmits clarify endpoint
5. Bot confirms “Request ready / submitted”

### 10.2 Ops Triage UI (web)

**Queue view**

* Filters: branch, urgency, category, status (needs_clarification/ready)
* Columns: created time, title, location, urgency, facilities_area, impacted_service, confidence
* Badge: “Low confidence” / “Needs info”

**Request detail view**

* Raw message (read-only)
* Extracted fields (editable):

  * Title, description
  * Urgency
  * Taxonomy selectors (3-level dropdown)
  * Location fields
  * Assets
* “Clarification questions” panel
* Audit trail of changes
* Status actions: mark ready, mark submitted, close

### 10.3 Tenant Admin UI (configuration)

* Branch/site management
* Taxonomy management:

  * Add/edit facilities area, services, request types
  * Enable/disable items
* Analytics schema management:

  * Define fields (boolean/enum/text)
  * Set defaults and applicability rules
* Export settings (optional)

### 10.4 Analytics UI (reporting)

* Charts and tables by:

  * branch/site
  * category
  * time period
  * urgency
* Export CSV

---

## 11. Non-functional requirements

### 11.1 Multi-tenant isolation

* All records scoped by tenant_id
* Strict auth checks on every endpoint

### 11.2 Security

* Encrypt at rest (DB)
* Encrypt in transit (TLS)
* RBAC:

  * Requester: submit/see own
  * Ops: triage all branch requests
  * Tenant admin: config endpoints
* Data retention policy configurable per tenant

### 11.3 Reliability & idempotency

* `message_id` idempotency
* Safe retries from chatbot platform
* Store original message + extraction output

### 11.4 Observability

* Logs: request_id, message_id, tenant_id, status transitions
* Metrics:

  * % auto-ready vs needs_clarification
  * avg clarifying questions per request
  * correction rate by ops
  * top categories per branch
* Tracing for LLM calls

### 11.5 Performance

* Target p95 response (intake): configurable; keep under a few seconds where possible
* Support bursty workloads (clinic morning peaks)

---

## 12. Tech stack (recommended)

### 12.1 Backend

* REST API service (Node.js/NestJS or Python/FastAPI)
* Postgres for relational storage
* Redis optional for caching taxonomy/schema

### 12.2 LLM integration

* Provider-agnostic interface (adapter pattern)
* Prompt templates versioned in code
* Schema-enforced JSON output

### 12.3 Deployment

* Containerized (Docker)
* Config via env vars / secret manager
* CI/CD with migrations

---

## 13. Testing & acceptance

### 13.1 Test fixtures

Use the provided example texts (emails) as **fixture strings** to validate:

* multi-issue splitting (e.g., lists)
* category inference (lighting/plumbing/access)
* location extraction (floor/room numbers)
* clarification generation

### 13.2 Acceptance criteria

* For all fixture texts:

  * system returns valid JSON schema
  * returns one or more requests
  * produces clarifications when required slots missing
* Taxonomy and analytics schema are configurable without code changes
* Idempotency works: same message_id doesn’t duplicate requests

---

## 14. Open configuration points (must be implemented)

1. Required slot policy per tenant (e.g., must have room vs free-text ok)
2. Taxonomy catalog per tenant (global default + overrides)
3. Analytics fields per tenant (import from XLSX-like columns)
4. Classification mapping rules (optional):

   * e.g., if “toilet blocked” → Plumbing/Blockages/Toilet
5. “Info-only” handling:

   * either store as low-priority request or event record

---

## 15. Deliverables

* Backend API (v1) with authentication
* DB schema + migrations
* Taxonomy + analytics configuration endpoints
* LLM extraction module with schema enforcement
* Test suite with provided fixture texts
* Documentation:

  * API docs (OpenAPI/Swagger)
  * Admin configuration guide
  * Prompt/schema versioning guide

