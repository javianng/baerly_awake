# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is an AML (Anti-Money Laundering) agentic AI solution built for Julius Baer hackathon. The system consists of two main components:

1. **Part 1: Real-Time AML Monitoring & Alerts** (Backend 1) - Ingests regulatory circulars, analyzes transactions against rules, and generates role-based alerts
2. **Part 2: Document & Image Corroboration** (Backend 2) - Processes compliance documents, performs OCR, validates formatting, and detects image tampering

## Architecture

### Multi-Backend Microservices Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  NGINX (Port 80) - Reverse Proxy                           │
│  Routes: / → Frontend, /api/ → Backend 1, /llm-api/ → Backend 2  │
└─────────────────────────────────────────────────────────────┘
         │                    │                    │
    ┌────▼────┐         ┌────▼─────┐        ┌────▼─────┐
    │ Frontend│         │Backend 1 │        │Backend 2 │
    │Next.js  │         │FastAPI   │        │FastAPI   │
    │Port 3000│         │Port 5001 │        │Port 5002 │
    └─────────┘         └────┬─────┘        └──────────┘
                             │
                        ┌────▼─────┐
                        │PostgreSQL│
                        │Port 5432 │
                        └──────────┘
```

### Backend 1 (Real-Time AML Monitoring)

- **Port**: 5001
- **Database**: PostgreSQL (for transactions, rules, alerts)
- **Key Features**:
  - Transaction monitoring and analysis using Polars dataframes
  - Rule parsing and execution (supports Python code execution for custom rules)
  - Alert generation with role-based targeting (Front/Compliance/Legal)
  - MAS (Monetary Authority of Singapore) regulatory circular scraping
  - PDF comparison utilities for detecting document changes
- **Key Models**: `Transaction`, `Rule`, `Alert`, `User`
- **Routes**: `/api/data`, `/api/rules`, `/api/users`

### Backend 2 (Document & Image Corroboration)

- **Port**: 5002
- **Database**: In-memory (Dictionary-based storage)
- **Key Features**:
  - Document upload and processing (PDF, DOC, DOCX, TXT)
  - OCR using Tesseract and OpenCV
  - Image analysis (authenticity, tampering detection)
  - LLM integration via Groq API for document analysis
- **Routes**: `/api/documents`, `/api/images`

### Frontend (Next.js 15 with T3 Stack)

- **Port**: 3000
- **Stack**: Next.js 15, React 19, TypeScript, Tailwind CSS v4
- **Features**: Turbopack dev mode, type-safe environment variables with Zod

### NGINX Reverse Proxy

- **Configuration**: `frontend/nginx/nginx.conf`
- **Routing**:
  - `/` → Frontend (Next.js)
  - `/api/` → Backend 1 (AML Monitoring)
  - `/llm-api/` → Backend 2 (Document Corroboration)

## Development Commands

### Docker (Recommended)

```bash
# Start all services
docker-compose up

# Start with rebuild
docker-compose up --build

# Stop all services
docker-compose down

# View logs
docker-compose logs -f [service_name]
```

### Frontend (Next.js)

```bash
cd frontend

# Install dependencies
npm install

# Development (with Turbopack)
npm run dev

# Type checking
npm run typecheck

# Linting
npm run lint
npm run lint:fix

# Format checking and writing
npm run format:check
npm run format:write

# Full check (lint + typecheck)
npm run check

# Build and preview
npm run build
npm run preview
```

### Backend 1 (Python/FastAPI)

```bash
cd backend_1

# Install dependencies
pip install -r requirements.txt

# Run development server
python app.py
```

**Key Backend 1 modules:**

- `app/agents/rule_parser.py` - Parses and executes Python-based rules on transactions
- `app/utils/mas_scraper.py` - Scrapes MAS regulatory circulars
- `app/utils/pdf_comparison.py` - Compares PDFs to detect changes
- `app/database/connection.py` - PostgreSQL connection pool management

### Backend 2 (Python/FastAPI)

```bash
cd backend_2

# Install dependencies (requires Tesseract OCR installed on system)
pip install -r requirements.txt

# Set GROQ_API_KEY in .env file
# Run development server
python app.py
```

## Environment Configuration

Create a `.env` file in the root directory (use `.env.example` as template):

```bash
# Required for Backend 2 LLM features
GROQ_API_KEY=your_groq_api_key_here

# PostgreSQL (Backend 1)
POSTGRES_HOST=db
POSTGRES_PORT=5432
POSTGRES_DB=baer_aml
POSTGRES_USER=baer_aml
POSTGRES_PASSWORD=baer_aml
```

## Database Schema (Backend 1 - PostgreSQL)

Backend 1 uses PostgreSQL with tables for:

- `transactions` - Store transaction records from CSV imports
- `rules` - Store regulatory rules (can be Python code)
- `alerts` - Store generated alerts with severity and target roles
- `users` - Store user information

The database connection uses asyncpg for async PostgreSQL operations with connection pooling. The application gracefully falls back to in-memory storage if PostgreSQL is unavailable.

## Key Technical Patterns

### Rule Execution System (Backend 1)

Rules can be defined as Python functions that are parsed and executed dynamically:

- Rules are stored in the database with Python code
- `parse_function_code()` extracts function definitions
- `apply_rule_to_transaction()` executes rules against transaction data
- **Security Note**: This uses `exec()` for dynamic code execution - production systems should sandbox this

### Transaction Processing

- Uses Polars dataframes for efficient bulk transaction processing
- CSV upload endpoint at `/api/data/upload` accepts transaction CSVs
- Transactions are validated against Pydantic models before database insertion

### Document Analysis Pipeline (Backend 2)

1. Document upload validation
2. OCR extraction (Tesseract + OpenCV for preprocessing)
3. LLM analysis via Groq API
4. Risk scoring and finding generation
5. Audit trail creation

## Data Files

The repository includes sample data files for testing:

- `transactions_mock_1000_for_participants.csv` - 1000 sample transactions for Part 1
- `Swiss_Home_Purchase_Agreement_Scanned_Noise_forparticipants.pdf` - Sample document for Part 2

## Port Configuration

- **80**: NGINX reverse proxy (main entry point)
- **3000**: Frontend (Next.js) - exposed internally to NGINX
- **5001**: Backend 1 (AML Monitoring) - exposed internally to NGINX
- **5002**: Backend 2 (Document Corroboration) - exposed internally to NGINX
- **5432**: PostgreSQL - exposed on host for debugging

## Important Notes

- Backend 2 uses **in-memory storage** - data is lost on restart
- Backend 1 uses **PostgreSQL** - data persists across restarts
- Rule execution in Backend 1 uses dynamic Python code execution (`exec()`)
- Image analysis requires system-level dependencies (Tesseract OCR, OpenCV)
- The frontend is currently a T3 Stack template - main UI implementation is pending
- NGINX configuration is in `frontend/nginx/` (note: root `nginx/` directory was removed)
