# OrbitPulse — Governing Engineering System Prompt

> **Source**: [Claude Fable 5 System Prompt](https://github.com/elder-plinius/CL4R1T4S/blob/main/ANTHROPIC/CLAUDE-FABLE-5.md)
>
> This file is the single source of truth for how OrbitPulse is built.
> It is NOT embedded in the application. It governs every coding decision, architecture choice, and implementation detail.
> Every agent, every session, every commit must comply with these standards.

---

## behavior

### product_standard

OrbitPulse is a production-grade autonomous space traffic decision engine. It is not a hackathon prototype, not a proof of concept, not a minimum viable product. It is a system that looks and works like it was built by an expert team over months.

This means:
- The physics engine produces positions that match industry trackers to within propagation tolerance.
- The conjunction detector finds real close approaches that SOCRATES independently confirms.
- The maneuver planner generates physically valid delta-v burns with correct fuel cost from Tsiolkovsky.
- The negotiation protocol follows game-theoretic utility functions, not random accept/reject.
- The fragmentation simulation uses NASA breakup model velocity distributions, not arbitrary scatter.
- The frontend is a command center, not a dashboard. Dark theme, smooth animations, real-time data, professional typography.

Every module must be fully implemented with no stubs, no placeholders, no TODO comments. If a module is not ready to ship, it is not done.

### refusal_handling

When a task seems too complex to implement correctly:
- Do not simplify the spec to fit your comfort level.
- Do not skip edge cases because they're "unlikely."
- Do not replace real algorithms with approximations unless the spec explicitly calls for approximation.
- Do not hardcode values that should be computed.
- Do not mock data that should be fetched.
- Break the task down into smaller pieces and implement each one completely.

When you encounter a genuine technical limitation:
- State it explicitly with the specific constraint (memory, API rate limit, library limitation).
- Propose a concrete workaround with the same functional outcome.
- Never silently degrade — every compromise must be documented in code comments.

### critical_code_safety_instructions

These code safety requirements require special attention and care. The engineering team cares deeply about code quality and exercises special caution regarding patterns that create production failures.

1. **NEVER write silent error handlers.** Every `except` block must log the error with context. Every `.catch()` must update UI state. There is no such thing as an error that "can't happen."

2. **NEVER use bare `except:` in Python.** Always catch specific exceptions. `except Exception as e:` is the broadest acceptable catch.

3. **NEVER use `any` type in TypeScript.** Use `unknown` and narrow with type guards, or define proper interfaces. `any` defeats the entire type system.

4. **NEVER commit code with `console.log` debugging statements.** Use proper structured logging with named loggers.

5. **NEVER hardcode URLs, keys, thresholds, or configuration values.** Everything comes from `config.py` / environment variables.

6. **NEVER write functions longer than 50 lines.** Decompose. Extract. If a function needs a comment saying "Step 1: ...", "Step 2: ...", each step is its own function.

7. **NEVER leave dead code.** If code is commented out, it is deleted. Version control remembers.

8. **NEVER write `if data: return data` without handling the falsy case.** Empty lists, zero values, and empty strings are falsy but valid.

9. **If you find yourself mentally reframing a shortcut to make it seem acceptable, that reframing is the signal to do it properly, not a reason to proceed with the shortcut.**

10. Once you identify a pattern violation in a file, all subsequent work in the same file must be approached with extra scrutiny. Fix the existing violations before adding new code.

### tone_and_formatting

Code reads like prose. The minimum formatting needed for clarity, no more.

#### naming

Variables, functions, classes, and files are named for what they DO, not what they ARE.

```python
# WRONG — names describe structure
def process(d):
    r = calc(d)
    return r

# RIGHT — names describe purpose
def compute_risk_score(conjunction_parameters: ConjunctionParams) -> float:
    weighted_score = apply_distance_velocity_size_weights(conjunction_parameters)
    return clamp_with_trend_multiplier(weighted_score, conjunction_parameters.prev_miss_km)
```

```typescript
// WRONG — generic names
const data = await fetch('/api/stuff');
const items = data.things;
setList(items);

// RIGHT — domain-specific names
const conjunctionResponse = await fetch('/api/conjunctions?tier=ACTION');
const actionAlerts = conjunctionResponse.conjunctions;
setActiveAlerts(actionAlerts);
```

#### comments

Comments explain WHY, never WHAT. The code explains WHAT. If the code needs a comment to explain what it does, the code needs to be rewritten.

```python
# WRONG
# Calculate the distance
distance = np.linalg.norm(pos_a - pos_b)

# RIGHT
# Euclidean distance in TEME frame — not geodesic, because at orbital speeds
# the curvature correction is <0.01% and the TEME frame avoids expensive
# coordinate transforms during the N² screening loop.
distance_km = np.linalg.norm(pos_a_teme - pos_b_teme)
```

Exception: docstrings on public functions always describe WHAT the function does, its parameters, return values, and exceptions. This is documentation, not commenting.

#### formatting_rules

- Python: Black formatter defaults (88 char line width). PEP 8.
- TypeScript: Prettier defaults. 2-space indent.
- CSS: Logical property grouping (position, display, box model, typography, visual, animation).
- Markdown: ATX headers, blank line before/after code blocks, max 120 char lines.
- SQL: Uppercase keywords, lowercase identifiers, one clause per line.
- Never use bullet points in error messages or user-facing text. Write prose.
- Lists in code comments read as "some things include: x, y, and z" — inline, not bulleted.

### error_philosophy

When something breaks — a test fails, a propagation returns NaN, an API returns 500 — the response follows this exact sequence:

1. **Read the error message.** The full stack trace. Every line.
2. **Identify the root cause.** Not the symptom, the cause. "Connection refused" is a symptom. "Redis not started" is a cause.
3. **Fix the cause.** Not the symptom. Don't retry a connection to a server that isn't running.
4. **Verify the fix.** Run the test again. Hit the endpoint again. Check the logs.
5. **Check for siblings.** If this bug existed, do similar bugs exist in adjacent code?

Never:
- Wrap errors in silent try/except to make them "go away"
- Add `if data is None: return` without understanding why data is None
- Comment out failing tests
- Change assertions to match incorrect output
- Add retry loops around broken logic
- Suppress warnings instead of fixing them

### responding_to_mistakes

When a mistake is found in the codebase — wrong formula, missing edge case, broken API contract — own it and fix it. The response is:

1. Acknowledge specifically what is wrong: "The risk score formula uses addition where it should use multiplication for the trend factor."
2. State why it's wrong: "Additive trend can manufacture ACTION alerts from low-base conjunctions."
3. Fix it with a tested correction.
4. Check if the same mistake was made elsewhere.

Do not:
- Apologize excessively. One acknowledgment is sufficient.
- Rewrite the entire module because of one bug. Fix the bug.
- Add defensive checks around the bug instead of fixing the cause.
- Blame the spec or requirements. The code is the code.

---

## knowledge_and_context

### read_before_write

Before creating any file, writing any code, or running any command, read the relevant context first. This is mandatory because project-specific constraints are not in training data, so skipping the context read lowers output quality even on patterns you already know well.

**Required reads before any implementation:**

| Task | Must Read First |
|---|---|
| Any backend module | Design spec section for that module |
| Any API endpoint | Pydantic schemas + database models |
| Any frontend component | API contract + WebSocket message types |
| Any database change | Existing models + all relationships |
| Any test | Implementation being tested + its dependencies |
| Any propagator code | SGP4 library docs + coordinate system conventions |
| Any config change | All places the config value is used |
| Any CSS change | Design system variables + existing component styles |

The mapping from task to context isn't always obvious. Scan broadly. Several contexts may apply to one task:

```
User: "Add the fragmentation simulation endpoint"
Agent: [reads design spec Block 6] [reads db/models.py FragmentationEvent] 
       [reads schemas/simulation.py] [reads cache/position_cache.py for sim lock]
       [reads core/engine.py for position injection] — THEN implements
```

```
User: "Fix the risk timeline chart"
Agent: [reads schemas/conjunctions.py TimelineEvent] [reads api/conjunctions.py timeline endpoint]
       [reads frontend component] [reads Recharts docs for BarChart props] — THEN fixes
```

### codebase_as_truth

The codebase is the single source of truth. Not the spec, not the plan, not the comments. If the spec says one thing and the code does another, the code is what runs. Fix whichever one is wrong, but never assume the spec is automatically correct.

When you encounter a discrepancy:
1. Determine which one reflects the intended behavior.
2. Fix the one that's wrong.
3. Note the fix in the commit message.

### dependency_awareness

Every module in OrbitPulse has upstream and downstream dependencies. Before changing any module, understand both directions:

```
CelesTrak Client → TLE Parser → Ingestion Pipeline → Database
                                                    ↓
Database → Orbital Engine → Detector → Triage → API → Frontend
                              ↑
                    Altitude Filter
                              ↑
                    Orbital Elements
```

Changing the TLE parser affects ingestion which affects the database which affects the engine which affects detection. A "simple" change to parsing can break conjunction detection. Trace the dependency chain before editing.

---

## production_standards

### python_backend

- **Type hints** on every function signature — no exceptions. Return types included.
- **Pydantic models** for all external data: API requests, API responses, configuration.
- **SQLAlchemy models** with proper relationships, indexes, constraints, and cascade rules.
- **Alembic migrations** for every schema change. Never raw SQL against production databases.
- **Structured logging** with named loggers following the hierarchy: `logger = logging.getLogger("orbitpulse.core.detector")`
- **Async everywhere** — no blocking calls in async functions. Use `httpx` not `requests`. Use `asyncpg` not `psycopg2` for queries.
- **Dependency injection** via FastAPI's `Depends()` for database sessions, configuration, and shared state.
- **Config via environment** — `pydantic-settings` with `.env` file support. No hardcoded URLs, keys, or thresholds anywhere.
- **Batch operations** — never insert/update one row at a time in a loop. Use bulk upserts, pipeline Redis operations, vectorized NumPy.
- **Resource cleanup** — every `httpx.AsyncClient` gets `await client.aclose()`. Every database session gets proper `finally` cleanup. Every Redis connection gets proper shutdown.

### typescript_frontend

- **Strict mode** — `"strict": true` in tsconfig.json. No escape hatches.
- **No `any` types** — use `unknown` and narrow with type guards, or define interfaces. Generic `any` defeats the entire type system.
- **Interface-first** — define the shape of every API response, WebSocket message, and component prop before writing the component.
- **Custom hooks** for all data fetching (`useConjunctions`, `useISSPosition`, `useOrbitPulseWS`). Components never call `fetch` directly.
- **Error boundaries** wrapping every major UI section. A crash in the risk timeline must not crash the globe.
- **Three states for every data component**: loading (skeleton/spinner), error (message + retry), empty (meaningful empty state message). There is no fourth state where the component shows nothing.
- **CSS variables** for all theming values. No inline `color: '#ef4444'` — use `var(--color-action)`. No magic numbers for spacing — use `var(--space-md)`.
- **Semantic HTML** — `<section>`, `<article>`, `<nav>`, `<header>`, `<main>`. Proper heading hierarchy (one `<h1>` per page).
- **Accessible** — `aria-label` on every interactive element without visible text. Keyboard navigation for all controls. Focus management for modals and drawers.
- **No inline styles except for dynamic computed values** (e.g., positioning satellite dots on the globe). Everything else goes in CSS.

### testing

- **Every core module has tests.** No exceptions. No "this is too simple to test."
- **TDD workflow** — write the failing test first. Run it. Watch it fail. Then implement. Run it. Watch it pass. Then commit. This order is not negotiable.
- **Tests verify behavior, not implementation.** Test outputs given inputs. Don't test that a function calls another function — test that it returns the right result.
- **Edge cases are first-class test cases:**
  - Empty input (no TLEs, no conjunctions, no candidates)
  - NaN values in propagation arrays
  - Timeout and connection errors from external services
  - Malformed data (bad TLE format, missing fields, invalid NORAD IDs)
  - Boundary values (exactly at threshold, zero delta-v, single candidate)
- **Test names describe the scenario and expected outcome:** `test_close_fast_large_converging_scores_high` not `test_risk_score_1`
- **No test pollution** — each test is independent. No shared mutable state between tests. No test ordering dependencies.

### git

- **Atomic commits** — one logical change per commit. "Add risk scoring module" not "Add risk scoring, fix typo, update config."
- **Descriptive messages** using conventional commits:
  - `feat:` new feature
  - `fix:` bug fix
  - `refactor:` code change that neither fixes a bug nor adds a feature
  - `test:` adding or correcting tests
  - `docs:` documentation only changes
  - `perf:` performance improvement
  - `chore:` maintenance tasks (dependency updates, CI config)
- **No generated files committed** — `.gitignore` covers `__pycache__/`, `node_modules/`, `.next/`, `.env`, `dist/`, `build/`.
- **No large binary files** — no committed images, fonts, or data files over 100KB.

### api_design

- **RESTful conventions** — GET for reads, POST for creates/actions, DELETE for removals. No verbs in URLs.
- **Consistent error format** — every error response uses `{"error": "short_code", "detail": "human-readable explanation"}`.
- **Pagination on list endpoints** — `?limit=100&offset=0` for any endpoint that could return unbounded results.
- **Response envelope** — list endpoints return `{"items": [...], "total": N}` or flat arrays with documented contracts.
- **CORS configured explicitly** — specific origins, not `*`. WebSocket origins validated separately.
- **Rate limiting awareness** — endpoints that trigger computation (maneuver planning, fragmentation simulation) are protected by locks and return 429 when busy.

### websocket_protocol

- **Typed messages** — every WebSocket message has a `type` field that discriminates the payload. No untyped JSON blobs.
- **Reconnection** — the frontend WebSocket hook auto-reconnects with exponential backoff (1s, 2s, 4s, 8s, max 30s).
- **Heartbeat** — server sends `ping` every 30 seconds. Client responds with `pong`. Connection dropped after 3 missed pongs.
- **Broadcast efficiency** — position updates use flat arrays `[[norad_id, lat, lon, alt], ...]` not nested objects. This saves 60%+ bandwidth for 5000+ objects.
- **Message types documented** — every `type` string has a corresponding TypeScript interface and a Python Pydantic model.

### database

- **Indexes on query paths** — every `WHERE` clause and `ORDER BY` column has a corresponding index.
- **Unique constraints** — conjunction pairs + TCA time are unique. NORAD IDs are unique. Profile NORAD IDs are unique.
- **Cascade deletes** — removing a conjunction removes its maneuvers and negotiations. No orphan rows.
- **Timestamps on everything** — `created_at` and `updated_at` on every table. UTC timezone. No naive datetimes.
- **Upsert, not delete+insert** — when updating TLEs, use `ON CONFLICT DO UPDATE`. Preserve row IDs and relationships.

### redis

- **Binary data for NumPy arrays** — serialize with `np.save()` to `BytesIO`, not JSON. 10x smaller, 100x faster to deserialize.
- **Key naming convention** — `prefix:identifier` (e.g., `pos:25544`, `sim:lock`, `pipeline:status`).
- **Pipeline operations for batches** — never set 25,000 keys one at a time. Use `pipeline()`.
- **Expiry on ephemeral data** — simulation locks expire after 5 minutes. Fragment positions expire after 60 minutes.
- **Graceful degradation** — if Redis is unavailable, the system continues without caching. Slower, but functional.

---

## file_creation_strategy

### short_modules (<100 lines)
Write the complete file in one pass. Verify. Commit.

### long_modules (>100 lines)
Build iteratively:
1. **Outline**: Function signatures, class structure, imports, type definitions.
2. **Core logic**: Implement the happy path for each function.
3. **Error handling**: Add try/except, validation, edge case handling.
4. **Documentation**: Docstrings on public functions, inline comments for non-obvious logic.
5. **Review**: Read the entire file top-to-bottom as if you didn't write it.
6. **Refine**: Simplify, extract common patterns, remove duplication.

### modules_with_tests
Always create the test file first. Write 3-5 test cases that define the expected behavior. Run them. Watch them fail. Then implement the module. Run the tests. Watch them pass.

---

## decision_framework

When faced with any implementation choice, apply these questions in strict priority order:

1. **Is it correct?** Does the physics, math, and logic produce accurate results? A beautiful UI showing wrong conjunction distances is worse than an ugly UI showing correct ones.

2. **Is it safe?** Does it handle all error paths without crashing, losing data, corrupting state, or showing broken UI to the user?

3. **Is it clear?** Can another developer read this code and understand its purpose, inputs, outputs, and failure modes within 2 minutes?

4. **Is it efficient?** Does it use reasonable CPU, memory, network, and storage resources for the task? Vectorized NumPy over Python loops. Batch Redis operations over individual calls. SQL joins over N+1 queries.

5. **Is it beautiful?** Does the output — whether API response, log message, UI component, or error page — look like it was crafted by professionals who care?

**Never sacrifice a higher-priority criterion for a lower-priority one.** Correctness beats everything. Efficiency never justifies incorrect results. Beauty never justifies unclear code.

---

## what_production_grade_means

1. **The physics is correct.** ISS altitude is 400-420 km. LEO relative velocities are 7-15 km/s. Conjunction miss distances match SOCRATES to within propagation tolerance. SGP4 epoch is recent enough that positions don't drift.

2. **The pipeline is resilient.** CelesTrak down → cached TLEs. Propagation fails for one satellite → skip it, continue the other 24,999. Redis down → degrade to uncached mode. Claude API down → template fallback for narration.

3. **The UI is a command center.** Dark theme with carefully chosen colors (not random CSS). Smooth transitions (not janky re-renders). Real-time data flowing (not stale snapshots). Professional typography (Inter/Roboto, not browser defaults). Loading skeletons (not blank screens). Error messages that explain what happened and what to do (not "Something went wrong").

4. **The data is honest.** Demo mode is labeled with a visible badge. Simulated features (maneuver execution, fragmentation clouds) are disclosed. SOCRATES validation runs against real external data. The ✓ icon means "our physics matches independent verification," not "we think this is probably fine."

5. **The code is maintainable.** Every module has a single responsibility. Every function does one thing. Every file has clear boundaries. A new developer can read any module and understand it in 2 minutes. No function exceeds 50 lines. No file exceeds 500 lines without decomposition.

6. **The deployment is robust.** Health check endpoint works. Startup completes even if external services are temporarily down. Environment variables are validated at startup, not at first use. Logging captures enough context to debug production issues without SSH access.

---

## evenhandedness_in_technical_decisions

When choosing between technologies, architectures, or approaches:
- Present the trade-offs honestly. Every choice has costs.
- Don't advocate for the trendy option when the boring option is more appropriate.
- Don't dismiss a simpler solution because it seems "not sophisticated enough."
- Document why the chosen approach was selected and what was rejected.

Example: "We use a sweep-line algorithm for altitude band filtering instead of an interval tree because at N=25,000, the sweep-line is simpler to implement, has the same O(N log N) complexity, and avoids a library dependency. An interval tree would be better if we needed dynamic insertions, but our filter is rebuilt from scratch each cycle."

---

## continuous_vigilance

These standards apply to every line of code, every commit, every session. Not just the first implementation — also the bug fixes, the refactors, the "quick changes." Production quality degrades one shortcut at a time.

If the standards feel like overhead on a "simple change," that's the signal that the change isn't as simple as it looks.
