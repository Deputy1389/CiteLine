# CiteLine MVP

**CiteLine** is a deterministic engine for turning raw medical records (PDFs) into structured, auditable chronologies for personal injury (PI) cases.

## Features
- **Deterministic Pipeline:** Rules-based extraction for 100% auditability.
- **Evidence Graph:** Every extracted event is linked to a specific source snippet and bounding box.
- **Auto-Chronology:** Generates sorted timeline of medical visits, imaging, and bills.
- **API-First:** Full control via REST API.

## Prerequisites
- Python 3.10+
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) (must be in system PATH)

## Installation

1.  **Clone the repository:**
    ```powershell
    git clone https://github.com/your-org/citeline.git
    cd citeline
    ```

2.  **Install dependencies:**
    ```powershell
    pip install -e .
    ```

3.  **Configure environment:**
    Copy `.env.example` to `.env`:
    ```powershell
    cp .env.example .env
    ```
    Edit `.env` if needed (defaults are usually fine for local dev).

4.  **Initialize Database:**
    The database (`citeline.db`) will be automatically created on the first run.

## Running the Application

1.  **Start the API server:**
    ```powershell
    uvicorn apps.api.main:app --reload --port 8000
    ```

2.  **Start the Worker Runner (in a new terminal):**
    ```powershell
    python -m apps.worker.runner
    ```
    The runner polls the database for pending runs and executes the pipeline.

Processing logs will appear in the worker console.

## Usage Guide (API)

Here is a standard workflow to process a case.

### 1. Create a Firm
```powershell
curl -X POST "http://localhost:8000/firms" ^
     -H "Content-Type: application/json" ^
     -d "{\"name\": \"Morgan & Morgan\"}"
```
*Note the `id` returned (e.g., `firm_123`).*

### 2. Create a Matter (Case)
```powershell
curl -X POST "http://localhost:8000/firms/{firm_123}/matters" ^
     -H "Content-Type: application/json" ^
     -d "{\"title\": \"Smith v. Jones\", \"timezone\": \"America/New_York\"}"
```
*Note the `id` returned (e.g., `matter_456`).*

### 3. Upload a Medical Record
```powershell
curl -X POST "http://localhost:8000/matters/{matter_456}/documents" ^
     -F "file=@C:/path/to/medical_records.pdf"
```
*Note the `id` returned (e.g., `doc_789`).*

### 4. Start a Run
```powershell
curl -X POST "http://localhost:8000/matters/{matter_456}/runs" ^
     -H "Content-Type: application/json" ^
     -d "{\"max_pages\": 100}"
```
*Note the `id` returned (e.g., `run_abc`).*

### 5. Check Status
```powershell
curl "http://localhost:8000/runs/{run_abc}"
```
Repeat until `status` is `"success"`.

### 6. Get Exports (Chronology)
```powershell
curl "http://localhost:8000/matters/{matter_456}/exports/latest"
```
This returns URIs for the generated PDF, CSV, and JSON evidence graph.

### 7. Download Artifacts
You can also download artifacts directly:
```powershell
# Download PDF
curl -O -J "http://localhost:8000/runs/{run_abc}/artifacts/pdf"

# Download CSV
curl -O -J "http://localhost:8000/runs/{run_abc}/artifacts/csv"
```

## Running Tests

Run the full test suite (unit + integration):

```powershell
pytest
```
