# OrbitPulse — Complete System Design Specification

## What This Product Is

OrbitPulse is an autonomous space traffic decision engine. It ingests real orbital data from CelesTrak, propagates 25,000+ objects using industry-standard SGP4 physics, detects and triages collisions, recommends maneuvers with full fuel-cost trade-offs, and coordinates multi-operator collision avoidance — all rendered on a live 3D globe with real-time WebSocket updates.

**Target**: Japan competition submission. Production-grade. No shortcuts.

---

## Architecture

**Approach**: Monorepo, layered pipeline architecture.

```
orbitpulse2/
├── backend/                # FastAPI + Python
│   ├── core/               # SGP4 engine, conjunction detector, maneuver planner
│   ├── api/                # REST endpoints + WebSocket
│   ├── ingestion/          # CelesTrak data feeder (scheduled)
│   ├── agents/             # Negotiation protocol + Claude integration
│   └── db/                 # PostgreSQL models + Alembic migrations
├── frontend/               # Next.js 14 (App Router) + CesiumJS
│   ├── components/         # Globe, AlertQueue, RiskTimeline, TradeOffMatrix
│   ├── hooks/              # WebSocket, data fetching
│   └── app/                # App Router pages
├── docker-compose.yml      # Local dev (Postgres + Redis + backend + frontend)
└── docs/                   # Specs, plans
```

**Tech Stack**:
- Backend: FastAPI, Python 3.12, SGP4, Skyfield, NumPy, SQLAlchemy, Alembic, APScheduler
- Frontend: Next.js 14 (App Router), CesiumJS (via resium), Recharts, TypeScript
- Database: PostgreSQL (Neon serverless)
- Cache: Redis (Railway addon)
- AI: Claude API (hybrid — rule-based decisions, Claude narration, template fallback)
- Deployment: Vercel (frontend) + Railway (backend) + Neon (Postgres)

**Pipeline flow**: `Ingestion → Propagation → Detection → Triage → API → Frontend`

---

## Block 1: Data Layer & Ingestion

### Database Schema

#### `objects`
| Column | Type | Notes |
|---|---|---|
| `norad_id` | INTEGER PK | NORAD catalog number |
| `name` | TEXT | Object name |
| `object_type` | ENUM | PAYLOAD, ROCKET_BODY, DEBRIS |
| `rcs_size` | ENUM | SMALL, MEDIUM, LARGE |
| `country_code` | TEXT | |
| `launch_date` | DATE | |
| `decay_date` | DATE | nullable |
| `tle_line1` | TEXT | Latest TLE line 1 |
| `tle_line2` | TEXT | Latest TLE line 2 |
| `tle_epoch` | TIMESTAMP | TLE epoch time |
| `updated_at` | TIMESTAMP | Auto-updated |

#### `conjunctions`
| Column | Type | Notes |
|---|---|---|
| `id` | SERIAL PK | |
| `obj_a_id` | INTEGER FK | → objects.norad_id |
| `obj_b_id` | INTEGER FK | → objects.norad_id |
| `tca_time` | TIMESTAMP | Time of closest approach |
| `miss_distance_km` | FLOAT | Minimum distance at TCA |
| `prev_miss_distance_km` | FLOAT | Previous detection cycle's miss distance (for trend) |
| `relative_velocity_kms` | FLOAT | Relative velocity at TCA |
| `risk_score` | FLOAT | 0.0 to 1.0 |
| `tier` | ENUM | ACTION, WATCHLIST, DISMISSED |
| `dismiss_reason` | TEXT | Human-readable dismissal reason |
| `both_maneuverable` | BOOLEAN | Both objects are PAYLOAD type |
| `created_at` | TIMESTAMP | |
| `updated_at` | TIMESTAMP | Auto-updated |

#### `maneuvers`
| Column | Type | Notes |
|---|---|---|
| `id` | SERIAL PK | |
| `conjunction_id` | INTEGER FK | → conjunctions.id |
| `satellite_id` | INTEGER FK | → objects.norad_id |
| `direction` | ENUM | PROGRADE, RETROGRADE |
| `delta_v_ms` | FLOAT | Burn magnitude in m/s |
| `burn_time` | TIMESTAMP | When to execute burn |
| `new_miss_distance_km` | FLOAT | Post-maneuver miss distance |
| `fuel_cost_kg` | FLOAT | Fuel consumed |
| `mission_life_impact_days` | FLOAT | Mission life cost |
| `mission_life_impact_pct` | FLOAT | % of remaining mission life |
| `secondary_conjunctions` | INTEGER | New conjunctions created |
| `status` | ENUM | CANDIDATE, RECOMMENDED, REJECTED, APPROVED |
| `rejection_reason` | TEXT | Why rejected (if applicable) |
| `created_at` | TIMESTAMP | |
| `updated_at` | TIMESTAMP | Auto-updated |

#### `negotiations`
| Column | Type | Notes |
|---|---|---|
| `id` | SERIAL PK | |
| `conjunction_id` | INTEGER FK | → conjunctions.id |
| `round_number` | INTEGER | |
| `proposer_id` | INTEGER | NORAD ID of proposing satellite's operator |
| `proposal` | TEXT | Structured proposal text |
| `response` | TEXT | Response text |
| `accepted` | BOOLEAN | Termination condition |
| `created_at` | TIMESTAMP | |
| `updated_at` | TIMESTAMP | Auto-updated |

#### `fragmentation_events`
| Column | Type | Notes |
|---|---|---|
| `id` | SERIAL PK | |
| `parent_norad_id` | INTEGER FK | → objects.norad_id |
| `fragment_norad_id` | INTEGER | Synthetic negative NORAD ID |
| `spawned_at` | TIMESTAMP | |
| `expires_at` | TIMESTAMP | Cleanup deadline |

#### `satellite_profiles`
| Column | Type | Notes |
|---|---|---|
| `id` | SERIAL PK | |
| `norad_id` | INTEGER FK | → objects.norad_id |
| `fuel_remaining_pct` | FLOAT | 0-100% |
| `fuel_remaining_kg` | FLOAT | Absolute fuel mass |
| `dry_mass_kg` | FLOAT | Dry mass for Tsiolkovsky |
| `mission_priority` | INTEGER | 1-10 (10 = highest) |
| `maneuver_budget_ms` | FLOAT | Max delta-v budget |
| `isp_rating` | FLOAT | Specific impulse in seconds |
| `remaining_mission_days` | INTEGER | For mission life impact % |
| `operator_name` | TEXT | |
| `created_at` | TIMESTAMP | |
| `updated_at` | TIMESTAMP | Auto-updated |

### Ingestion Pipeline

- **Scheduler**: APScheduler, every 6 hours (CelesTrak fair use: no more than once per 2 hours per group)
- **Sources**:
  - `https://celestrak.org/NORAD/elements/gp.php?GROUP=active&FORMAT=tle`
  - `https://celestrak.org/NORAD/elements/gp.php?GROUP=stations&FORMAT=tle`
  - `https://celestrak.org/NORAD/elements/gp.php?GROUP=starlink&FORMAT=tle`
  - Satellite catalog CSV for object classification
- **Process**: Fetch → Parse TLEs → Upsert into `objects` (latest TLE always overwrites) → Trigger propagation + detection pipeline
- **No manual refresh button** — prevents accidental API hammering during testing/demo

---

## Block 2: Orbital Engine

### Two-Pass Propagation Architecture

| Pass | Timestep | Scope | Purpose |
|---|---|---|---|
| **Pass 1 (Coarse)** | 60s | All ~25,000 objects × 72h | Find candidate pairs within 20km bounding box |
| **Pass 2 (Fine)** | 1s | Only candidate pairs × 10-min window around predicted TCA | Precise miss distance, exact TCA, relative velocity |

### Core Library

- **SGP4**: `sgp4` Python package — official NORAD SGP4/SDP4 implementation
- **Vectorized API**: `SatrecArray` processes all satellites at once per timestep using NumPy
- **Performance**: Full catalog propagation in ~30-60 seconds (vectorized)

### Coordinate Conversions

- **Skyfield** for all coordinate conversions (no Astropy dependency)
- SGP4 outputs TEME (True Equator Mean Equinox)
- For globe rendering: TEME → ECEF (GST rotation) → geodetic (WGS84 ellipsoid)
- For conjunction detection: stay in TEME frame (distances computed in inertial frame)

### Position Caching

| Environment | Storage | Details |
|---|---|---|
| Production | Redis — serialized NumPy bytes, keyed by `norad:{id}` | Railway Redis addon |
| Development | Module-level `dict[int, np.ndarray]`, uvicorn `--workers 1` | Documented constraint |

- Position matrix shape: `(N_timesteps, 3)` per object
- Maneuver planner writes only the modified satellite's entry back to Redis

### ISS Verification

- Endpoint: `GET /api/iss/position`
- Returns: `{ lat, lon, alt_km, validated, tle_epoch }`
- **Validation logic**: Propagate ISS TLE to its own epoch time → result matches TLE-encoded position to numerical precision → proves SGP4 correctness
- The ✓ in the UI means "SGP4 propagation validated against TLE epoch"
- n2yo.com comparison is a live demo flourish opened manually, not a system dependency

---

## Block 3: Conjunction Detector & Triage

### Detection Pipeline

**Stage 1 — Altitude Band Filter (Pre-screening)**:
- Compute apogee/perigee from TLE orbital elements for each object
- Build sorted interval tree of `[perigee - 20km, apogee + 20km]` ranges
- Only overlapping pairs proceed to Pass 1
- Eliminates ~99% of 312M possible pairs without any propagation

**Stage 2 — Coarse Screening (Pass 1)**:
- At each 60s timestep, compute Euclidean distance in TEME between pair positions
- Flag pairs where any timestep shows distance < 20km
- Record approximate TCA window (minimum distance timestep ± 5 minutes)

**Stage 3 — Fine Screening (Pass 2)**:
- Re-propagate both objects at 1s intervals across the 10-minute TCA window
- Find exact minimum distance and exact TCA time
- Compute relative velocity at TCA

### Risk Scoring

```python
def compute_risk_score(miss_km, rel_vel_kms, size_a, size_b, prev_miss_km):
    # Base score from three factors (weights sum to 1.0)
    f_dist = math.exp(-miss_km / 2.0)
    f_vel = min(rel_vel_kms / 15.0, 1.0)
    size_map = {'LARGE': 1.0, 'MEDIUM': 0.6, 'SMALL': 0.3}
    f_size = max(size_map.get(size_a, 0.3), size_map.get(size_b, 0.3))
    
    base = 0.50 * f_dist + 0.30 * f_vel + 0.20 * f_size
    
    # Trend as post-multiplier: 0.7x (diverging) to 1.3x (converging)
    if prev_miss_km is not None and prev_miss_km > miss_km:
        trend_mult = 1.0 + 0.3 * min((prev_miss_km - miss_km) / prev_miss_km, 1.0)
    elif prev_miss_km is not None:
        trend_mult = 0.7
    else:
        trend_mult = 1.0  # first observation, neutral
    
    return min(base * trend_mult, 1.0)
```

### Triage Tier Assignment

| Tier | Criteria |
|---|---|
| **ACTION** | `risk_score >= 0.7` OR `(miss_distance_km < 1.0 AND relative_velocity_kms > 5.0)` |
| **WATCHLIST** | `risk_score >= 0.3 AND miss_distance_km < 5.0` |
| **DISMISSED** | Everything else — stored with auto-generated `dismiss_reason` |

### Triage Funnel

`GET /api/funnel` returns: `{ total_screened, watchlist, action_required, last_updated }`

### Risk Timeline

`GET /api/timeline/{norad_id}` — all conjunctions for a satellite sorted by `tca_time`, colored by tier.

### SOCRATES Validation

- Fetch: `https://celestrak.org/SOCRATES/sort-minRange.csv` — top 20 closest approaches for the coming week
- Match against our conjunctions: by NORAD ID pair within ±2 minute TCA window
- **API**: `GET /api/validation/socrates` returns:
  ```json
  {
    "matches": [{
      "our_prediction": { "miss_distance_km": 3.2, "tca_time": "..." },
      "socrates_prediction": { "miss_distance_km": 3.1, "tca_time": "..." },
      "delta_km": 0.1,
      "norad_ids": [25544, 48274]
    }]
  }
  ```
- Frontend shows "Validated ✓" badge on matching alerts
- The small delta (expected: TLE epoch differences between fetch times) demonstrates domain knowledge

---

## Block 4: Multi-Trajectory Planner & Trade-Off Matrix

### When It Fires

Automatically when a conjunction is triaged as ACTION. Also triggerable manually from the frontend.

### Maneuver Generation

1. **Burn magnitudes**: 0.05, 0.10, 0.25, 0.50, 1.0 m/s (5 logarithmic steps)
2. **Directions**: prograde (raise orbit, arrive late at crossing) and retrograde (lower orbit, arrive early)
3. **Burn timing**: from "now" to "TCA minus 2 orbits" (earlier = more fuel-efficient)
4. Up to 5 candidates generated per conjunction

### For Each Candidate

1. Apply delta-v to satellite's velocity vector at burn time
2. Re-propagate modified orbit using SGP4 for 72h
3. **Scoped re-screen** (domino check): query interval tree for modified orbital parameters → fine screening on subset only (seconds, not minutes)
4. Compute: new miss distance, fuel cost, mission life impact

### Fuel Cost Calculation

```python
def fuel_cost_kg(delta_v_ms, dry_mass_kg, isp_s):
    """Tsiolkovsky rocket equation"""
    g0 = 9.80665
    return dry_mass_kg * (math.exp(delta_v_ms / (isp_s * g0)) - 1)
```

`dry_mass_kg` and `isp_s` from `satellite_profiles` table.

### Mission Life Impact

Expressed as both absolute days and percentage of `remaining_mission_days` from `satellite_profiles`.

### Auto-Rejection

Candidates with `secondary_conjunctions > 0` → `status = REJECTED`, `rejection_reason = "Creates N new conjunctions: [NORAD IDs]"`

### Recommendation (Hybrid AI)

- **Rule-based ranking**: lowest fuel cost among candidates with zero secondary conjunctions
- **Claude API**: reads full trade-off matrix as JSON, produces natural language recommendation explaining which options were rejected and why
- **Fallback**: if Claude API unavailable, template engine generates formulaic recommendation
- Response includes `source: "claude"` or `source: "template"`
- **Cached per conjunction** — no re-call on page refresh

### Trade-Off Matrix API

`GET /api/maneuvers/{conjunction_id}`:
```json
{
  "conjunction": { "obj_a": "ISS", "obj_b": "COSMOS 2251 DEB", ... },
  "candidates": [
    {
      "id": 1, "direction": "prograde", "delta_v_ms": 0.05,
      "new_miss_distance_km": 12.4, "fuel_cost_kg": 0.3,
      "mission_life_impact": { "days": -2, "pct_of_remaining": 0.03 },
      "secondary_conjunctions": 0, "status": "RECOMMENDED"
    },
    { "...more candidates..." }
  ],
  "recommendation": { "chosen_id": 1, "reasoning": "...", "source": "claude" }
}
```

### Maneuver Approval

`POST /api/maneuvers/{id}/approve`:
```json
{
  "approved": true,
  "maneuver_id": 1,
  "satellite_norad_id": 25544,
  "new_orbit_path": [[lat, lon, alt_km], ...],
  "burn_executed_at": "2026-06-22T04:22:00Z",
  "new_miss_distance_km": 12.4,
  "alert_status": "RESOLVED"
}
```
`new_orbit_path`: 180 positions at 30s intervals (90 min), pre-computed server-side.

---

## Block 5: Agent-to-Agent Negotiation Protocol

### Trigger

Conjunction is ACTION AND `both_maneuverable = true`.

### Protocol Structure

| Round | Actor | Action |
|---|---|---|
| 1 | System | Presents conjunction context + each satellite's maneuver costs |
| 2 | Agent A | Proposes who should burn and at what delta-v |
| 3 | Agent B | Accepts, counter-proposes, or rejects with reasoning |
| 4+ | Iteration | Until acceptance or max rounds (default: 4) |
| Fallback | System | Imposes globally optimal solution if no agreement |

### Agent Utility Function

```python
def agent_utility(profile, proposed_delta_v):
    fuel_pct_cost = fuel_cost_kg(proposed_delta_v, profile.dry_mass, profile.isp) / profile.fuel_remaining_kg
    mission_priority_weight = profile.mission_priority  # 1-10
    return max(0.0, 1.0 - (fuel_pct_cost * mission_priority_weight / 10.0))
```

### Decision Rules

| Condition | Action |
|---|---|
| Proposed burn costs < 5% fuel AND utility > 0.7 | **Accept** |
| Utility between 0.3 and 0.7 | **Counter-propose** (split burn) |
| Utility < 0.3 | **Reject** (propose other satellite burns) |

### Validation Gate

System validates every proposal against actual computed maneuver costs. Agents cannot misrepresent fuel state.

### Fallback Objective Function

```python
def fallback_assignment(profile_a, profile_b, maneuver_a, maneuver_b):
    """Minimize weighted sum of (fuel_cost_pct × mission_priority).
    Protects high-priority low-fuel satellites even in deadlock."""
    cost_a = (fuel_cost_kg(maneuver_a.delta_v, profile_a.dry_mass, profile_a.isp) 
              / profile_a.fuel_remaining_kg) * profile_a.mission_priority
    cost_b = (fuel_cost_kg(maneuver_b.delta_v, profile_b.dry_mass, profile_b.isp) 
              / profile_b.fuel_remaining_kg) * profile_b.mission_priority
    return 'a' if cost_a < cost_b else 'b'
```

### Claude Narration

After rule-based negotiation completes, Claude reads the full log and produces a human-readable summary. Claude is never in the decision loop, only the explanation loop.

### Contract Output

```json
{
  "conjunction_id": 42,
  "rounds": [
    { "round": 1, "proposer": "system", "proposal": "Context: ..." },
    { "round": 2, "proposer": "agent_a", "proposal": "...", "reasoning": "..." },
    { "round": 3, "proposer": "agent_b", "response": "ACCEPT", "reasoning": "..." }
  ],
  "outcome": {
    "maneuvering_satellite": 51203,
    "burn": { "delta_v_ms": 0.05, "direction": "prograde", "burn_time": "..." },
    "contract_hash": "sha256:a1b2c3...",
    "fallback_used": false,
    "summary": "Claude-generated narrative..."
  }
}
```

### API

`POST /api/negotiate/{conjunction_id}` — idempotent (cached result on re-call).

---

## Block 6: Fragmentation Simulation (Kessler Syndrome Demo)

### Trigger

Operator selects satellite → clicks "Simulate Breakup."

### Fragment Generation

- **Count**: 50 fragments (configurable up to 200)
- **Velocity distribution**: exponential (mean 50 m/s, cap 300 m/s), uniform direction on sphere
- **IDs**: synthetic negative NORAD IDs (-1 to -200)
- **Type**: `DEBRIS`, `SMALL`
- **Tracked in**: `fragmentation_events` table with `expires_at = now + 1 hour`

```python
def generate_fragment_velocities(n_fragments):
    magnitudes = np.minimum(np.random.exponential(50, n_fragments), 300)
    phi = np.random.uniform(0, 2 * np.pi, n_fragments)
    cos_theta = np.random.uniform(-1, 1, n_fragments)
    sin_theta = np.sqrt(1 - cos_theta**2)
    directions = np.column_stack([
        sin_theta * np.cos(phi), sin_theta * np.sin(phi), cos_theta
    ])
    return directions * magnitudes[:, np.newaxis]
```

### Propagation

- Fragments use **RK4 two-body numerical integration** (not SGP4)
- ~30 lines of NumPy, no poliastro dependency
- State vectors stored in Redis, keyed by synthetic ID
- Conjunction screening: same distance checks against state vector positions

### Real-Time Experience

- WebSocket pushes new alerts as fragments generate conjunctions
- Funnel numbers update live
- Globe renders fragment trajectories spreading from breakup point (red dots)
- Fragment-caused alerts use `fragment_detected` WebSocket type (styled differently)

### Cleanup

- Background task every 5 minutes: delete expired fragments, clear their conjunctions

### API

- `POST /api/simulate/fragmentation/{norad_id}` — trigger breakup (protected by `X-Demo-Key` header + simulation lock)
- `DELETE /api/simulate/fragmentation` — manual cleanup

---

## Block 7: Command Center (Frontend)

### Layout

```
┌─────────────────────────────────────────────────────────────┐
│  ORBITPULSE  [Live/Demo] [ISS: 51.6°N 32.1°E 408km ✓] [●] │
├────────────────────────────────────┬────────────────────────┤
│                                    │ TRIAGE FUNNEL          │
│                                    │ 14,212 screened        │
│                                    │ 207 watchlist          │
│        3D CESIUM GLOBE             │ 3 ACTION ⚠️            │
│   (5,000 of 25,000 objects)        │                        │
│   [Show All] toggle                │ ALERT CARDS            │
│                                    │ ┌────────────────────┐ │
│                                    │ │ ISS × DEB          │ │
│                                    │ │ 0.8km  12h  0.87   │ │
│                                    │ └────────────────────┘ │
├────────────────────────────────────┴────────────────────────┤
│  DETAIL PANEL (opens on alert click)                        │
│  ┌────────────┐ ┌────────────┐ ┌──────────────────────────┐ │
│  │ 72h Risk   │ │ Trade-Off  │ │ Negotiation Log          │ │
│  │ Timeline   │ │ Matrix     │ │ (if both_maneuverable)   │ │
│  └────────────┘ └────────────┘ └──────────────────────────┘ │
│  [AI Recommendation]  [Approve Maneuver ✓]                  │
└─────────────────────────────────────────────────────────────┘
```

### Components

| Component | Library | Data Source |
|---|---|---|
| `Globe` | CesiumJS (resium) | Initial: `GET /api/objects/catalog`. Updates: WebSocket `positions_update` |
| `AlertQueue` | React | WebSocket `alert_new` + `GET /api/conjunctions?tier=ACTION,WATCHLIST` |
| `TriageFunnel` | React | WebSocket `funnel_update` + `GET /api/funnel` |
| `RiskTimeline` | Recharts BarChart | `GET /api/timeline/{norad_id}` |
| `TradeOffMatrix` | React table | `GET /api/maneuvers/{conjunction_id}` |
| `NegotiationLog` | React | `POST /api/negotiate/{conjunction_id}` |
| `FragmentationPanel` | React | `POST /api/simulate/fragmentation/{norad_id}` |
| `SOCRATESValidator` | React | `GET /api/validation/socrates` |
| `ISSTracker` | React | `GET /api/iss/position` (polls every 10s) |

### Globe Rendering

- **Default**: 5,000 objects (all payloads + ISS + major debris). Label: "Showing 5,000 of 25,000 tracked objects"
- **"Show All" toggle**: renders all 25,000 with performance warning
- **Colors**: Active payloads = cyan, debris = gray, fragments = red
- **Orbits**: translucent lines
- **Camera fly-to**: on alert click, `viewer.camera.flyTo()` to conjunction point
- **Orbit redraw**: on maneuver approval, satellite path transitions to new trajectory
- **Fragmentation visual**: dots expand from parent along computed trajectories

### Position Updates

- **Initial load**: `GET /api/objects/catalog` — full static metadata, loaded once
- **Real-time**: WebSocket `positions_update` — flat array `[[norad_id, lat, lon, alt], ...]` (~300KB per update)
- No full-catalog HTTP polling

### Design

- **Theme**: Dark space operations — `#0a0e1a` base, `#1a1f36` cards
- **Panels**: Solid semi-transparent `rgba(10, 14, 26, 0.85)` + `border: 1px solid rgba(255,255,255,0.08)` (no CSS glassmorphism over WebGL)
- **Colors**: cyan `#06b6d4` (active), red `#ef4444` (ACTION), amber `#f59e0b` (WATCHLIST), green `#22c55e` (safe)
- **Font**: Inter (Google Fonts)
- **Animations**: alert card pulse on new, funnel numbers animate on change, risk timeline bars grow on hover, globe atmospheric glow

### Demo Mode

- Top bar toggle: "Live Mode" / "Demo Scenario"
- Demo Scenario injects pre-configured ACTION-tier conjunction (ISS vs debris) + both_maneuverable conjunction (Starlink vs Starlink)
- All downstream systems run identically — honest label on seeded alerts

---

## Block 8: API Contract

### REST Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health` | Health + readiness check |
| `GET` | `/api/objects/catalog` | Full catalog (one-time load) |
| `GET` | `/api/iss/position` | ISS position + validation |
| `GET` | `/api/funnel` | Triage funnel counts |
| `GET` | `/api/conjunctions` | Filtered conjunctions list |
| `GET` | `/api/conjunctions/{id}` | Conjunction detail |
| `GET` | `/api/timeline/{norad_id}` | 72h risk timeline |
| `GET` | `/api/maneuvers/{conjunction_id}` | Trade-off matrix |
| `POST` | `/api/maneuvers/{id}/approve` | Approve maneuver |
| `POST` | `/api/negotiate/{conjunction_id}` | Trigger/get negotiation |
| `POST` | `/api/simulate/fragmentation/{norad_id}` | Trigger breakup sim |
| `DELETE` | `/api/simulate/fragmentation` | Cleanup all sims |
| `GET` | `/api/validation/socrates` | SOCRATES comparison |

### Endpoint Protection

- All `POST` endpoints require `X-Demo-Key: <static_secret>` header
- Fragmentation endpoint checks Redis simulation lock → 409 Conflict if already running

### WebSocket

Single connection: `ws://host/ws/live`

```typescript
type WSMessage = 
  | { type: "positions_update", data: number[][] }
  | { type: "alert_new", data: Conjunction }
  | { type: "alert_update", data: Conjunction }
  | { type: "funnel_update", data: FunnelStats }
  | { type: "negotiation_round", data: NegotiationRound }
  | { type: "maneuver_approved", data: ApprovedManeuver }
  | { type: "fragment_detected", data: Conjunction }
  | { type: "pipeline_status", data: { stage: string, progress_pct: number } }
```

### Error Handling

```json
{ "error": "string", "detail": "string", "code": "ERROR_CODE" }
```
Status codes: 400, 404, 409 (simulation lock), 503 (pipeline running).

---

## Block 9: Deployment

### Platforms

| Service | Platform | Details |
|---|---|---|
| Frontend | Vercel | Auto-deploy from Git, edge CDN |
| Backend | Railway | Docker, single worker, Redis addon |
| Database | Neon | Serverless Postgres, connection pooling |

### Cold Start Protection

1. **Startup propagation**: On container boot, immediately fetch TLEs and propagate before serving traffic
2. **Keep-warm ping**: Frontend `useEffect` calls `/api/health` every 5 minutes

### Environment Variables

| Var | Where |
|---|---|
| `DATABASE_URL` | Backend |
| `REDIS_URL` | Backend |
| `CLAUDE_API_KEY` | Backend |
| `DEMO_SECRET_KEY` | Backend + Frontend |
| `NEXT_PUBLIC_API_URL` | Frontend |
| `NEXT_PUBLIC_WS_URL` | Frontend |
| `NEXT_PUBLIC_CESIUM_TOKEN` | Frontend |

### Demo Checklist

1. Run full ingestion cycle 1 hour before demo
2. Verify ISS position ✓ is green
3. Verify Demo Scenario mode produces ACTION alerts
4. Test fragmentation simulation + cleanup
5. Test negotiation protocol on both_maneuverable conjunction
6. Test WebSocket from deployed Vercel → Railway (CORS!)
7. Open n2yo.com in second tab for ISS comparison
8. Open SOCRATES page for side-by-side validation

---

## What Is Real and What Is Simulated

**Real and verifiable**: every object, every orbit, every position, every conjunction prediction. Same data source the industry uses, cross-checkable against independent trackers.

**Simulated and disclosed**: maneuver execution, operator fuel profiles, fragmentation clouds. The math is real. The execution is simulated.

**Honest framing**: Demo Scenario mode is labeled. SOCRATES validation is live. ISS verification is self-validating. The ✓ means "our physics matches our data," not "we scraped a website."
