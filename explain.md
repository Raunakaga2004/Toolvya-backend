# How This Backend Works (Beginner's Guide)

This file explains, from scratch, how **Django**, **Django REST Framework (DRF)**, and **Celery + Redis** work together in this project. It assumes you know basic Python but nothing about web frameworks. Read it top to bottom the first time; use it as a reference after.

---

## 1. The Big Picture

This backend is a **PDF tools API**: a frontend (or Postman, or curl) uploads PDF files, and the backend merges/splits/compresses/reorders them and hands back a download link. There's no database of users, no login — every "job" is anonymous and identified by a random ID.

The three pieces working together:

```
┌─────────────┐      HTTP request       ┌──────────────┐
│   Client    │ ───────────────────────▶│    Django    │
│ (browser,   │                          │   + DRF      │
│  Postman,   │◀─────────────────────────│  (this app)  │
│  curl)      │      HTTP response       └──────┬───────┘
└─────────────┘                                 │
                                                  │ "go process this PDF"
                                                  ▼
                                          ┌──────────────┐
                                          │    Redis     │  (message queue)
                                          └──────┬───────┘
                                                  │
                                                  ▼
                                          ┌──────────────┐
                                          │Celery Worker │  (does the actual
                                          │  (background)│   PDF merging/etc.)
                                          └──────────────┘
```

Why split it like this? Merging a 500-page PDF can take a few seconds. If Django did that work directly inside the HTTP request, the client would sit there waiting and the whole server would be tied up. Instead, Django just **records the job and hands it off**, replies immediately ("got it, working on it"), and a separate **Celery worker** process does the actual PDF work in the background. Redis is the pipe that carries "hey, do this job" messages from Django to the worker.

---

## 2. What is Django?

Django is a Python web framework. Its job is to take an incoming HTTP request (a URL + method + maybe a body) and turn it into an HTTP response (usually JSON here). The core pieces Django gives you:

- **URL routing** (`urls.py`) — maps a URL path like `/api/pdf/merge/` to a piece of Python code that handles it.
- **Views** (`views.py`) — the Python code that actually handles a request: reads input, does something, returns a response.
- **Models** (`models.py`) — Python classes that represent rows in a database table. Django turns `PDFJob.objects.create(...)` into an `INSERT INTO ...` SQL statement for you, so you never write raw SQL for basic operations.
- **Settings** (`config/settings.py`) — one file with every configuration knob: database connection, installed apps, security settings, etc.

Django organizes code into **apps** — self-contained Python packages, each usually owning one feature area. This project's apps live under `apps/`:

| App | What it's for |
|---|---|
| `apps.core` | Shared stuff: the home/health endpoints, the standard response format, the error handler. |
| `apps.pdf` | The actual PDF tools — this is where almost everything interesting lives. |
| `apps.users`, `apps.tools`, `apps.jobs`, `apps.files`, `apps.analytics` | Registered in `INSTALLED_APPS` but currently **empty** (no models, no views) — scaffolding for future features that isn't used yet. |

---

## 3. What is DRF (Django REST Framework)?

Plain Django is built for rendering HTML pages. DRF is a toolkit built **on top of** Django that makes it much nicer to build JSON APIs. It adds:

- **`APIView`** — a base class for view classes, DRF's version of a Django view. You subclass it and write `get()`, `post()`, etc. methods. It automatically parses incoming JSON/form data into `request.data`, and handles content negotiation (deciding the response should be JSON).
- **Serializers** — the DRF equivalent of a form. They do two jobs: (1) **validate** incoming data (is this really a PDF? are there at least 2 files?) and (2) **convert** Python objects (like a `PDFJob` model instance) into JSON-friendly dictionaries, and vice versa.
- **Throttling** — rate-limiting built in, so you can cap how many requests per minute a client can make.
- **Exception handling** — a central place that turns any error raised in a view (validation error, 404, etc.) into a consistent JSON error response.
- **drf-spectacular** — a separate library used here to auto-generate OpenAPI/Swagger docs (visible at `/api/docs/`) by reading your serializers and the `@extend_schema` decorators on your views.

Every request in this project passes through DRF's `APIView`, not Django's older raw view style — except the two tiny views in `apps.core` (`home`, `health_check`), which are plain Django function views because they're trivial and don't need validation or serialization.

---

## 4. The Life of One Request, Step by Step

Let's trace exactly what happens when a client does:

```
POST /api/pdf/merge/
Content-Type: multipart/form-data
files: one.pdf, two.pdf
```

**Step 1 — Django's URL router finds the view.**
`config/urls.py` has:
```python
path("api/pdf/", include("apps.pdf.urls")),
```
This says "any URL starting with `api/pdf/`, hand the rest to `apps/pdf/urls.py`". That file has:
```python
path("merge/", MergePDFAPIView.as_view(), name="pdf-merge"),
```
So `api/pdf/merge/` resolves to `MergePDFAPIView`.

**Step 2 — DRF's `APIView.as_view()` wraps the class.**
`.as_view()` returns a plain function Django can call, but that function does DRF setup first: it builds a DRF `Request` object (a wrapper around Django's request that knows how to parse JSON/multipart bodies), applies **throttling** (checks `ScopedRateThrottle` — is this client over the `pdf_tools` rate limit of 30/min? see `config/settings.py`), and then calls `self.post(request)` on your view since this is a POST.

**Step 3 — The view validates input with a serializer.**
```python
serializer = self.serializer_class(data=request.data, context={"request": request})
serializer.is_valid(raise_exception=True)
```
`MergePDFJobCreateSerializer` (in `serializers.py`) declares a `files` field that must have **at least 2** files. Its `validate_files()` method also calls `validate_uploaded_pdf()` (in `services.py`) on each file — checking it's non-empty, under the size limit, ends in `.pdf`, and is actually parseable as a PDF (not encrypted, has pages). If any of that fails, `is_valid(raise_exception=True)` raises a `ValidationError`, which DRF catches and turns into a `400 Bad Request` JSON response automatically — the view code never even reaches the next line.

**Step 4 — The view creates a `PDFJob` row and hands work to Celery.**
This is `PDFToolBaseAPIView.create_job()`, shared by all four tool views:
```python
job = PDFJob.objects.create(tool=..., params=..., input_count=len(files), expires_at=timezone.now())
input_paths = store_uploaded_files(job, files)   # saves files to disk under media/pdf_jobs/<job-id>/inputs/
job.input_paths = input_paths
job.save(...)
prepare_job_expiry(job)                          # sets expires_at to now + 24h
process_pdf_job.delay(str(job.id))               # <-- hands the job to Celery/Redis (see section 6)
job.refresh_from_db()                             # in dev, Celery already ran it synchronously — see below
return job
```
Note: if **anything** in this block raises (a disk write fails, whatever), the `except` clause deletes the job's files and the database row and re-raises — so a failed job creation leaves no orphaned data.

**Step 5 — The view builds a response with a serializer.**
```python
serializer = PDFJobSerializer(job, context={"request": request})
return success_response(serializer.data, http_status=status.HTTP_202_ACCEPTED)
```
`PDFJobSerializer` is a `ModelSerializer` — it knows how to turn a `PDFJob` model instance into a dict of JSON-safe fields (it reads the `Meta.fields` list). `success_response()` (in `apps/core/response.py`) is a tiny helper used everywhere in this project so **every** successful response has the same shape:
```json
{"success": true, "data": { ... }}
```
and 202 Accepted means "request understood, work has started, it's not finished yet" — appropriate here since the actual PDF merging may still be running.

**Step 6 — If something went wrong instead, the exception handler formats it.**
DRF lets you plug in a custom `EXCEPTION_HANDLER` (set in `config/settings.py` to `apps.core.exception_handler.core_exception_handler`). Whenever a view raises `ValidationError`, `Http404`, `PermissionDenied`, etc., DRF calls this function instead of letting the error crash the request. It reshapes DRF's default error body into this project's consistent shape:
```json
{"success": false, "error": {"code": "VALIDATION_ERROR", "message": "Invalid request.", "details": {...}}}
```
This is why **every** error response across every endpoint looks the same, no matter which view raised it — one function handles them all.

---

## 5. Models: How Data Is Stored

There's exactly one model in this whole project: `PDFJob` (`apps/pdf/models.py`). Django turns this Python class into a real SQL table (`pdf_pdfjob`) via a **migration** (`apps/pdf/migrations/0001_initial.py` — a generated file that describes the `CREATE TABLE` statement; run with `python manage.py migrate`).

Key fields:

| Field | Purpose |
|---|---|
| `id` (UUID) | Random unique ID, used in URLs like `/api/pdf/jobs/<id>/`. Using a random UUID instead of an auto-incrementing number means you can't guess other people's job IDs by counting. |
| `tool` | Which operation: `merge`, `split`, `compress`, `reorder`. |
| `status` | `pending` → `processing` → `completed` or `failed`, and eventually `expired`. |
| `input_paths` / `params` (JSON) | Where the uploaded files live, and any extra options (like the page order string). |
| `output_path`, `result_filename` | Where the finished file ended up. |
| `expires_at` | Jobs and their files are deleted 24 hours after creation (see `PDF_JOB_TTL_HOURS`) — this is a public anonymous tool, so files can't be kept forever. |

The model also has small helper methods like `mark_processing()`, `mark_completed()`, `mark_failed()` — each just updates `status` (and related fields) and saves. Centralizing these on the model means the Celery task and the views don't duplicate "how do I mark a job as failed" logic.

---

## 6. Why Celery + Redis? (This Is the Part Beginners Usually Find Confusing)

### The problem being solved

A regular Django view runs **synchronously**: the client's HTTP connection stays open the whole time the view function is running, and the moment the function returns, the response goes out. If merging PDFs took 10 seconds, the client's browser/HTTP client would just sit there for 10 seconds, and while that request is being handled, that worker process can't serve anyone else.

The fix: don't do slow work inside the view. Instead, **queue it up** and let a separate process do it, while the view responds immediately with "job created, check back later."

### What Redis actually is

Redis is an in-memory key-value database — think of it as a very fast, simple dictionary that lives in RAM and that multiple separate programs (processes) can all connect to over the network. It's commonly used as:
1. A **cache** (store expensive-to-compute values temporarily) — not how it's used here.
2. A **message broker / queue** — a place where one program can drop a message ("please do X") and another program can pick it up. **This is how it's used here.**

Redis is fast (in-memory, no disk I/O on the hot path) and simple to run (one process, `docker compose up -d redis` per this project's README).

### What Celery actually is

Celery is a Python library for running background tasks. It has two halves:
- **The producer** — your Django code, which calls `some_task.delay(args)`. This doesn't run the task itself; it just serializes the function name + arguments into a message and pushes it onto a queue (in Redis).
- **The consumer / worker** — a separate long-running process (`celery -A config worker -l info`, per the README) that sits there watching the queue. When a message shows up, it picks it up, calls the actual Python function with those arguments, and runs it to completion.

So in this project, `CELERY_BROKER_URL = redis://127.0.0.1:6379/0` (in `config/settings.py`) tells both Django and the worker "use this Redis instance as the queue." `CELERY_RESULT_BACKEND` is also Redis — that's where Celery could store a task's return value if anyone asked for it (this project doesn't check return values, since it tracks job status in the `PDFJob` row instead — see below).

### The actual flow in this project

```
apps/pdf/views.py                apps/pdf/tasks.py
─────────────────                 ─────────────────
create_job():
  job = PDFJob.objects.create(status="pending")
  process_pdf_job.delay(job.id)  ──message──▶  Redis queue
  return job (still "pending"/    (waits here until
   "processing" by the time the    a worker is free)
   client sees it, in production)
                                          │
                                          ▼
                                  Celery worker process
                                  picks up the message,
                                  calls process_pdf_job(job.id):
                                    job.mark_processing()
                                    ...actually merge/split/etc...
                                    job.mark_completed(...)
                                    (or job.mark_failed(...) on error)
```

The **view and the worker never talk to each other directly** — they only communicate by (a) putting a message on the Redis queue, and (b) both reading/writing the same `PDFJob` database row. That's the whole trick: the view returns instantly after step "queue the message," and the client is expected to **poll** `GET /api/pdf/jobs/<id>/` afterwards to see when `status` flips to `completed`.

### An important local-dev detail: `CELERY_TASK_ALWAYS_EAGER`

```python
CELERY_TASK_ALWAYS_EAGER = get_bool("CELERY_TASK_ALWAYS_EAGER", DEBUG)
```
When this is `True` (the default in local dev, per `.env.example`), Celery **skips Redis entirely** and just calls the task function directly, synchronously, right where `.delay()` was called — as if it were a normal function call. This is why, when you test locally, a job's `status` is already `completed` by the time the POST request returns (see the test suite in `apps/pdf/tests.py` — it asserts `status == COMPLETED` immediately after posting). In a real deployment (`CELERY_TASK_ALWAYS_EAGER=False`), `.delay()` really does go through Redis to a separate worker process, and the job stays `pending`/`processing` for a bit after the POST returns.

### The other thing Celery does here: scheduled cleanup

```python
CELERY_BEAT_SCHEDULE = {
    "cleanup-expired-pdf-jobs": {
        "task": "apps.pdf.tasks.cleanup_expired_pdf_jobs",
        "schedule": 3600.0,  # every hour
    }
}
```
`cleanup_expired_pdf_jobs` (in `tasks.py`) finds jobs whose `expires_at` has passed, marks them `expired`, and deletes their files from disk. This needs a **Celery Beat** process running alongside the worker (Beat is Celery's scheduler — it just queues this task once an hour) — separate from a worker actually executing it, though in a small deployment they're often run together. There's also a manual way to trigger the same cleanup: `python manage.py cleanup_pdf_jobs` (see `apps/pdf/management/commands/cleanup_pdf_jobs.py`), useful for a cron job if you don't want to run Celery Beat at all.

---

## 7. All the Endpoints

Every endpoint in this project returns the same JSON envelope shape:
- success: `{"success": true, "data": {...}}`
- error: `{"success": false, "error": {"code": "...", "message": "...", "details": {...}}}`

### `GET /`
**View:** `apps.core.views.home` (plain Django function view, not DRF)
Returns a small "is this API alive" payload: `{"service": "toolvaya-backend", "status": "ok", "version": "0.1.0"}`. Useful as a sanity check that the server is up at all.

### `GET /health/`
**View:** `apps.core.views.health_check`
Returns `{"status": "ok"}`. This is the kind of endpoint a load balancer or uptime monitor hits every few seconds to check the server hasn't crashed. It deliberately does nothing else (no database query) so it's always fast and never fails for reasons unrelated to "is the process running."

---

### `POST /api/pdf/merge/`
**View:** `MergePDFAPIView` · **Serializer:** `MergePDFJobCreateSerializer`
**Body:** `multipart/form-data` with a `files` field — 2 or more PDF files.

**Workflow:**
1. Serializer checks: at least 2 files, at most `PDF_MAX_INPUT_FILES` (10), each one passes `validate_uploaded_pdf` (real PDF, not empty, under `PDF_MAX_INPUT_BYTES`/50MB, not password-protected).
2. `create_job()` saves the files to `media/pdf_jobs/<job-id>/inputs/`, creates the `PDFJob` row (`tool="merge"`), and queues `process_pdf_job`.
3. The Celery task calls `merge_pdfs()` (`services.py`): opens each input PDF with `pypdf.PdfReader`, copies every page into one `pypdf.PdfWriter`, writes the result to `media/pdf_jobs/<job-id>/output/merge-<job-id>.pdf`.
4. Job is marked `completed` with the resulting page count.
**Response:** `202 Accepted` with the job's status payload (see "Job object shape" below), including a `download_url`.

### `POST /api/pdf/split/`
**View:** `SplitPDFAPIView` · **Serializer:** `SplitPDFJobCreateSerializer`
**Body:** `file` (one PDF) + optional `ranges` (e.g. `"1-3, 5-7"` — leave blank to split into every individual page).

**Workflow:**
1. Serializer validates the file, then parses `ranges` against the file's real page count (`parse_page_ranges` in `services.py`) — catches things like a range that goes past the last page, or garbage text.
2. `create_job()` stores the file and queues the task with `params={"ranges": ...}`.
3. The task re-derives the page count from the *stored* file (not trusting anything from the original request) and calls `split_pdf()`: for each range, builds a small `pypdf.PdfWriter` with just those pages, and zips all the resulting mini-PDFs into one `.zip` file.
**Response:** `202 Accepted`. The eventual download is a `.zip` archive.

### `POST /api/pdf/compress/`
**View:** `CompressPDFAPIView` · **Serializer:** `CompressPDFJobCreateSerializer`
**Body:** `file` (one PDF).

**Workflow:**
1. Serializer validates the file (same checks as above).
2. The Celery task calls `compress_pdf()`: reads every page, calls pypdf's `page.compress_content_streams()` on each (this re-encodes the page's internal drawing instructions more compactly — it's a lossless structural compression, not image recompression), and writes the result.
**Response:** `202 Accepted` with a `.pdf` download.

### `POST /api/pdf/reorder/`
**View:** `ReorderPDFAPIView` · **Serializer:** `ReorderPDFJobCreateSerializer`
**Body:** `file` (one PDF) + `order` (e.g. `"3,1,2"` — the new page order, 1-indexed).

**Workflow:**
1. Serializer validates the file, reads its page count, and validates `order` (`parse_page_order`): must contain **every** page number from 1 to N exactly once — no duplicates, none missing.
2. The Celery task builds a new PDF by copying pages from the original file in the requested order.
**Response:** `202 Accepted` with a `.pdf` download.

---

### `GET /api/pdf/jobs/<job_id>/`
**View:** `PDFJobDetailAPIView`
Poll this to check a job's progress. `job_id` is the UUID returned by one of the four POST endpoints above.

**Workflow:**
1. `get_job_or_404(job_id)` first checks `job_id` actually *looks like* a UUID (`uuid.UUID(job_id)`) — if not, raises DRF's `Http404` immediately, which the exception handler turns into a proper JSON `404`. (Earlier in this project's history, the URL pattern used Django's built-in `<uuid:job_id>` converter, which rejected malformed IDs *before* the request even reached this view — bypassing the JSON exception handler entirely and leaking Django's raw HTML debug-404 page instead. Switching to `<str:job_id>` + this explicit check keeps every error path consistent.)
2. If the UUID is well-formed but no such job exists, `get_object_or_404` raises the same kind of `Http404` → same JSON 404.
3. If the job's `expires_at` has passed, it's marked `expired` and its files are deleted on the spot (lazy cleanup — no need to wait for the hourly Celery Beat sweep).
4. Otherwise, returns the job's current state (see "Job object shape" below).

**Response:** `200 OK` with the job object.

### `GET /api/pdf/jobs/<job_id>/download/`
**View:** `PDFJobDownloadAPIView`
Downloads the finished file once the job is `completed`.

**Workflow:**
1. Same `get_job_or_404` UUID/existence check as above.
2. If expired → `404 JOB_EXPIRED`.
3. If not yet `completed` (or the output file is missing on disk) → `409 Conflict, RESULT_NOT_READY` — the client is expected to poll the status endpoint and retry the download later.
4. Otherwise increments `download_count` and streams the file back with `FileResponse`, with the right `Content-Type` (`application/pdf` or `application/zip`) and a `Content-Disposition: attachment` header so browsers save it as a file instead of trying to display it inline.

**Response:** `200 OK` with the raw file bytes — not JSON, since this is a file download.

---

### Job object shape

Every "job" response (`PDFJobSerializer`) looks like this:
```json
{
  "id": "db223187-16b2-461c-b235-c71d89dae506",
  "tool": "merge",
  "status": "completed",
  "input_count": 2,
  "page_count": 3,
  "result_filename": "merge-db223187-....pdf",
  "error_message": "",
  "created_at": "...", "updated_at": "...", "started_at": "...", "completed_at": "...",
  "expires_at": "...",
  "download_count": 0,
  "download_url": "http://.../api/pdf/jobs/<id>/download/",
  "status_url": "http://.../api/pdf/jobs/<id>/",
  "is_expired": false
}
```
`download_url` is only populated once `status == "completed"` (see `get_download_url` in `serializers.py`) — the frontend can just check "is this null?" instead of re-deriving the URL itself.

---

## 8. A Few More DRF/Django Concepts Used Here

- **Throttling** (`ScopedRateThrottle`, scope `pdf_tools`, 30/min): DRF tracks how many requests each client (by IP, if anonymous) has made recently, in the Django cache. Every PDF endpoint shares this same `pdf_tools` bucket, so a client is limited to 30 total requests/minute across merge+split+compress+reorder+status+download combined, not 30 of each.
- **`extend_schema`**: a decorator from `drf-spectacular` that documents a view's request/response shape so the auto-generated Swagger UI at `/api/docs/` shows accurate docs — it has no effect on runtime behavior.
- **CORS** (`corsheaders` middleware + `CORS_ALLOWED_ORIGINS`): browsers block a webpage on one domain from calling an API on another domain unless the API explicitly allows it via CORS headers. This middleware adds those headers for whatever origins are listed in the `CORS_ALLOWED_ORIGINS` env var.
- **`MultiPartParser`/`FormParser`**: DRF needs to be told how to parse the request body. File uploads use `multipart/form-data` encoding, so the PDF views declare `parser_classes = [MultiPartParser, FormParser]` to handle that (the project-wide default in settings also includes `JSONParser` for plain JSON bodies elsewhere).
- **Migrations**: whenever you change `models.py`, you run `python manage.py makemigrations` to generate a new file describing the schema change, then `python manage.py migrate` to actually apply it to the database. Migrations are how Django keeps the database schema in sync with your Python model definitions, and how that schema history gets version-controlled.

---

## 9. Glossary

| Term | Meaning |
|---|---|
| **Request/response cycle** | The whole process of a client sending an HTTP request and the server sending back a response. |
| **View** | A Python function/class that handles one URL and returns a response. |
| **Serializer** | DRF's tool for validating input and converting model instances to/from JSON. |
| **Model** | A Python class representing a database table; each instance is one row. |
| **Migration** | A generated file describing a change to the database schema. |
| **Broker** | The message queue a task-producer (Django) and task-consumer (Celery worker) both connect to — Redis, here. |
| **Task** | A Python function decorated with `@shared_task`, runnable in the background by a Celery worker. |
| **Eager mode** | Celery config where `.delay()` runs the task immediately/synchronously instead of queuing it — used in local dev so you don't need Redis + a worker running just to test. |
| **Throttling** | Rate-limiting: capping how many requests a client can make in a time window. |
| **UUID** | A 128-bit random identifier, astronomically unlikely to collide — used here as job IDs instead of sequential numbers so job IDs can't be guessed/enumerated. |
