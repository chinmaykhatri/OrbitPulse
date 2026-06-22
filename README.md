# OrbitPulse

**Autonomous Space Traffic Decision Engine**

Real orbital data. Real physics. Real collision predictions.

OrbitPulse ingests the full CelesTrak catalog (~25,000 tracked objects), propagates orbits with SGP4 over a 72-hour window, detects conjunctions using two-pass screening, scores risk, plans avoidance maneuvers, runs game-theoretic negotiation between operators, and simulates fragmentation events — all in a single application.

---

## Architecture

```
┌──────────────┐    ┌───────────────┐    ┌─────────────┐
│  CelesTrak   │───▶│   Ingestion   │───▶│  PostgreSQL  │
│  (TLE/GP)    │    │   Pipeline    │    │  (6 tables)  │
└──────────────┘    └───────┬───────┘    └──────┬──────┘
                            │                    │
                    ┌───────▼───────┐    ┌───────▼──────┐
                    │  SGP4 Engine  │───▶│    Redis      │
                    │  (NumPy vec)  │    │ (pos arrays)  │
                    └───────┬───────┘    └──────┬───────┘
                            │                    │
                    ┌───────▼───────┐            │
                    │  2-Pass       │◀───────────┘
                    │  Detector     │
                    └───────┬───────┘
                            │
              ┌─────────────┼──────────────┐
              │             │              │
      ┌───────▼──────┐ ┌───▼────┐ ┌───────▼───────┐
      │  Maneuver    │ │ Triage │ │ Fragmentation  │
      │  Planner     │ │ Funnel │ │ Simulator      │
      └───────┬──────┘ └────────┘ └────────────────┘
              │
      ┌───────▼───────┐
      │  Negotiation  │
      │  Protocol     │
      └───────────────┘
```

## Features

### Orbital Engine
- **SGP4 propagation** with WGS72 model and IAU GMST geodetic conversion
- **Full catalog propagation**: 25,000 objects × 4,320 timesteps (72h at 60s intervals)
- **ISS validation**: Self-checks altitude range (380–440 km) against TLE epoch
- **Redis batch storage**: NumPy binary blobs via pipelined SET operations

### Conjunction Detection
- **Altitude band pre-filter**: 50 km bins eliminate ~95% of pairs before propagation
- **Two-pass screening**: Coarse (60s steps, 20 km threshold) → Fine (1s steps, 10 km threshold)
- **Risk scoring**: Weighted formula (distance 50%, velocity 30%, size 20%) with convergence trend multiplier (±30%)
- **Three-tier triage**: ACTION / WATCHLIST / DISMISSED with hard-override rules

### Maneuver Planning
- **Tsiolkovsky rocket equation** for realistic fuel cost calculation
- **5 candidate burns** at configurable Δv steps (0.05–1.0 m/s)
- **Mission life impact**: fuel percentage of remaining mission budget
- **Scoped re-screening**: verify each maneuver doesn't create new conjunctions

### Negotiation Protocol
- **Game-theoretic utility function**: weighted (fuel 40%, mission 30%, priority 30%)
- **Multi-round protocol** with structured proposals and responses
- **SHA-256 contract hashing** for audit trail integrity
- **Fallback**: lower-priority satellite maneuvers if negotiation fails

### Fragmentation Simulation
- **NASA Standard Breakup Model**: log-normal velocity distribution (σ=0.4)
- **Uniform spherical direction sampling** for debris cloud
- **Redis simulation lock**: prevents concurrent breakup simulations
- **Auto-expiry**: fragments cleaned up after 60 minutes

### SOCRATES Validation
- Cross-validates predictions against CelesTrak's SOCRATES (Satellite Orbital Conjunction Reports)
- Delta-km computation for each matched conjunction pair
- Confidence dashboard showing prediction accuracy

### Frontend Command Center
- **Interactive 3D globe**: Canvas2D orbital renderer (5,000+ satellites at 60fps)
- **Triage funnel**: clickable 3-tier filter with proportional bars
- **Alert cards**: tier-colored with convergence trend indicators
- **72h Risk Timeline**: Recharts bar chart colored by triage tier
- **Maneuver trade-off matrix**: data table with AI recommendation
- **Negotiation viewer**: round-by-round display with contract hash
- **Fragmentation trigger**: slider + NASA model simulation
- **Real-time WebSocket**: position updates, pipeline status, conjunction alerts

---

## Quick Start

### Prerequisites
- Docker & Docker Compose
- Node.js 20+ (for frontend development)
- Python 3.11+ (for backend development)

### One-command launch
```bash
docker compose up --build
```

This starts:
- **PostgreSQL** on port 5432
- **Redis** on port 6379
- **Backend** (FastAPI) on port 8000
- **Frontend** (Next.js) on port 3000

Open http://localhost:3000 — the pipeline loading screen will show while CelesTrak data is ingested and orbits are propagated (60–120 seconds on first run).

### Development mode

**Backend:**
```bash
cd backend
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

**Frontend:**
```bash
cd frontend
npm install
npm run dev
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://...localhost/orbitpulse` | Async PostgreSQL connection |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis for position cache |
| `CLAUDE_API_KEY` | (empty) | Anthropic API key for AI explanations |
| `DEMO_SECRET_KEY` | `orbitpulse-demo-2026` | X-Demo-Key header value |
| `CORS_ORIGINS` | `http://localhost:3000` | Allowed CORS origins |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Backend API URL |
| `NEXT_PUBLIC_WS_URL` | `ws://localhost:8000` | WebSocket URL |

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/health` | Pipeline readiness + object count |
| GET | `/api/iss` | ISS position with validation |
| GET | `/api/positions` | All satellite positions (WebSocket recommended) |
| GET | `/api/conjunctions` | Conjunction list (filterable by tier) |
| GET | `/api/conjunctions/{id}` | Conjunction detail with object metadata |
| GET | `/api/funnel` | Triage funnel statistics |
| GET | `/api/timeline/{norad_id}` | 72h risk timeline for satellite |
| POST | `/api/maneuvers/{conj_id}` | Generate maneuver trade-off matrix |
| POST | `/api/negotiate/{conj_id}` | Run negotiation protocol |
| POST | `/api/simulate/fragment/{norad_id}` | Trigger fragmentation simulation |
| GET | `/api/socrates` | SOCRATES cross-validation |
| GET | `/api/pipeline/status` | Detailed pipeline stage info |
| WS | `/ws/live` | Real-time positions + alerts |

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Backend** | Python 3.11, FastAPI, SQLAlchemy 2.0, asyncpg |
| **Orbital Mechanics** | sgp4 2.23, NumPy (vectorized), IAU GMST |
| **Database** | PostgreSQL 16 (6 tables, Alembic migrations) |
| **Cache** | Redis 7 (NumPy binary blobs, pipeline locks) |
| **Scheduler** | APScheduler (6-hour re-ingestion cycle) |
| **Frontend** | Next.js 16, TypeScript, Recharts, Canvas2D |
| **Real-time** | WebSocket (native FastAPI, exponential backoff reconnect) |
| **Deployment** | Docker Compose, Railway-ready |

---

## Project Structure

```
orbitpulse2/
├── backend/
│   ├── api/              # FastAPI routers (5 modules)
│   ├── core/             # Physics engines (8 modules)
│   │   ├── propagator.py     # SGP4 wrapper
│   │   ├── engine.py         # Full catalog propagation
│   │   ├── detector.py       # Two-pass conjunction screening
│   │   ├── risk_scoring.py   # Weighted risk + triage
│   │   ├── maneuver_planner.py   # Tsiolkovsky + burn sim
│   │   ├── negotiation.py    # Game-theoretic protocol
│   │   ├── fragmentation.py  # NASA breakup model
│   │   └── socrates.py       # SOCRATES validation
│   ├── ingestion/        # CelesTrak data pipeline
│   ├── db/               # SQLAlchemy models + session
│   ├── cache/            # Redis position cache
│   ├── schemas/          # Pydantic request/response models
│   ├── middleware/        # X-Demo-Key protection
│   ├── ws/               # WebSocket handler
│   ├── tests/            # pytest test suite
│   ├── alembic/          # Database migrations
│   └── main.py           # FastAPI app + startup pipeline
├── frontend/
│   └── src/
│       ├── app/          # Next.js App Router
│       ├── components/   # 11 React components
│       ├── hooks/        # WebSocket + polling hooks
│       ├── lib/          # Typed API client
│       └── types/        # TypeScript type definitions
├── docker-compose.yml
└── README.md
```

---

## License

MIT
