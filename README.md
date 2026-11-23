# Shopify + Google ADK 2.0 MVP

A lean, production-ready MVP combining **Shopify order operations** with **Google Agent Development Kit (ADK 2.0)** and a dual-workflow architecture, served via FastAPI with an interactive single-page dashboard.

---

## 1. High-Level Design (HLD)

The application models Shopify orders with parent-child line items and routes operations across two strictly isolated workflows:

```
                            +-----------------------------+
                            |     Single-Page Web UI      |
                            |   (HTML5 + Tailwind CSS)    |
                            +-----------------------------+
                                       |         |
                  [Workflow 1 Routes]  |         |  [Workflow 2 Routes]
                                       v         v
                            +-----------------------------+
                            |       FastAPI Server        |
                            |          (app.py)           |
                            +-----------------------------+
                                       |         |
                     +-----------------+         +-----------------+
                     |                                             |
                     v                                             v
     +-------------------------------+             +-------------------------------+
     |          Workflow 1           |             |          Workflow 2           |
     |   (PGlite / SQLite Engine)    |             |  (Firebase SQL Data Connect)  |
     +-------------------------------+             +-------------------------------+
       | (Sync Read/Write)   | (Async)               | (Relational Cloud SQL Pattern)|
       v                     v                       v                               |
    [W1 DB]            [worker.py Queue]          [W2 DB Adapter]                    |
                             |                       |                               |
                             +-----------------------+                               |
                                         ^                                           |
                                         |                                           |
                         +-------------------------------+                           |
                         |   Google ADK 2.0 Root Agent   |<--------------------------+
                         |      (Shopify Coordinator)    |
                         +-------------------------------+
```

### Key Workflow Separation
1. **Workflow 1 (`WORKFLOW_1_PGLITE` + `worker.py`):**
   - **Synchronous Path**: Direct, immediate reads and writes for orders and child line items against the PGlite / local store adapter.
   - **Asynchronous Path**: Dispatches background reconciliation tasks to `worker.py` via an async event queue, logging `[WORKFLOW_1_WORKER]` execution events.
2. **Workflow 2 (`WORKFLOW_2_DATA_CONNECT`):**
   - Connects relational PostgreSQL / Cloud SQL schemas mirroring **Firebase Data Connect / SQL Connect**.
   - Firebase Authentication is intentionally deferred beyond this sprint. No AWS dependencies are used (fully Google Cloud aligned).
3. **Google ADK 2.0 (`agent.py`):**
   - Defines `root_agent` using `google-adk` (`adk.Agent`) configured for `gemini-2.5-flash`.
   - Incorporates Shopify mock tools (`get_shopify_order`, `fulfill_shopify_line_items`) and workflow-aware routing tools.
   - Safe when `GOOGLE_API_KEY` is empty: seamlessly falls back to a deterministic semantic dispatcher so operations never crash.

---

## 2. Low-Level Design (LLD)

### Data Schema (Parent-Child)
- **Parent (`ShopifyOrder`)**: `id`, `shopify_order_number`, `customer_name`, `total_price`, `financial_status`, `fulfillment_status`, `workflow_source`, timestamps.
- **Child (`OrderLineItem`)**: `id`, `order_id` (foreign key with cascade), `sku`, `title`, `quantity`, `unit_price`.

### REST API Endpoints
- `GET /` — Serves single-page UI dashboard.
- `GET /api/orders?workflow={w1|w2|all}` — Lists orders with child line items, filterable by workflow.
- `POST /api/w1/orders` — Workflow 1 sync order creation.
- `POST /api/w1/orders/{order_id}/sync-async` — Workflow 1 async background worker trigger.
- `POST /api/w2/orders` — Workflow 2 relational order insert (Firebase Data Connect).
- `POST /api/agent/query` — Invokes Google ADK 2.0 root agent with prompt and returns workflow/tool attribution.
- `GET /api/logs` — Live execution logs audit trail.

---

## 3. Approved 8-File Architecture

```text
├── config.py             # Environment configurations (Google ADK keys, DB paths, settings)
├── schema.py             # Pydantic parent-child models, workflow enums, and log schemas
├── db_w1_pglite.py       # Workflow 1: PGlite & SQLite fallback store adapter
├── db_w2_dataconnect.py  # Workflow 2: Firebase Data Connect / SQL Connect relational adapter
├── worker.py             # Background queue worker for Workflow 1 async updates & logs
├── agent.py              # Google ADK 2.0 root_agent with Shopify & workflow tools
├── app.py                # FastAPI app, lifecycle hooks, REST routes, and static mounting
└── static/
    └── index.html        # Interactive Single-Page UI with live workflow inspection
```

---

## 4. Running the Application

### 1. Launch the Server
Run the FastAPI application using `uvicorn`:

```bash
uvicorn app:app --host 127.0.0.1 --port 8000 --reload
```

### 2. Access the UI
Open your browser at:
```
http://127.0.0.1:8000
```

### 3. Run Automated Tests
Execute the complete automated test suite (verifying parent-child relations, Workflow 1 sync/async, Workflow 2 Data Connect, and ADK fallback):

```bash
pytest -v test_mvp.py
```
*(All 10 tests run in isolation with zero external API dependencies)*

### 4. Adding a Google Gemini API Key (Optional)
The agent runs in deterministic safe mode without a key. To enable live LLM reasoning:
1. Create a `.env` file in the project root:
   ```env
   GOOGLE_API_KEY=your_actual_gemini_api_key_here
   ```
2. Restart `uvicorn app:app --reload`.

---

## 5. Deploying on Render

This project is configured for one-click deployment as a Web Service on [Render](https://render.com/):

1. **Create Web Service**:
   - Connect your GitHub repository: `https://github.com/RishabhandSven/subhanu_assessment`
   - **Environment**: `Python`
   - **Branch**: `main`

2. **Build and Start Commands**:
   - **Build Command**:
     ```bash
     pip install -r requirements.txt
     ```
   - **Start Command**:
     ```bash
     uvicorn app:app --host 0.0.0.0 --port $PORT
     ```

3. **Environment Variables (Optional)**:
   - `GOOGLE_API_KEY`: *(Optional)* Your Gemini API key for live LLM execution. If omitted, the root agent safely defaults to the deterministic workflow dispatcher.
   - `DEBUG`: `false`

