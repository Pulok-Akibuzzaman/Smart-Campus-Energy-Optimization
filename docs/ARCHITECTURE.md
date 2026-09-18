# Architecture

## Pipeline

```
                ┌───────────────────────────────────────────────────┐
                │                POST /optimize-energy                │
                └───────────────────────────────────────────────────┘
                                        │
                     1. Pydantic schema validation (Section 07)
                     — malformed JSON → 400, no crash
                                        │
                                        ▼
                ┌───────────────────────────────────────────────────┐
                │     LLM INTERPRETER (provider chain, §5)           │
                │  Groq → Gemini → OpenRouter → regex safety net     │
                │  Output: raw structured JSON per note              │
                └───────────────────────────────────────────────────┘
                                        │
                                        ▼
                ┌───────────────────────────────────────────────────┐
                │           GUARDRAIL VALIDATOR (deterministic)        │
                │  - directive_type ∈ allowed enum                     │
                │  - hours: unique ints 0-23 ascending                 │
                │  - factor ∈ [0,1] for solar_reduction                │
                │  - reserve/grid-cap ≥ 0 and finite                   │
                │  - applies=false only for no_op                      │
                │  - required structured_adjustment shape per type     │
                │  - malformed/unsupported type → coerce to no_op      │
                │    + log (never invent an unsupported directive)     │
                └───────────────────────────────────────────────────┘
                                        │
                                        ▼
                ┌───────────────────────────────────────────────────┐
                │      DIRECTIVE → CONSTRAINT TRANSLATOR               │
                │  Converts each valid directive into per-hour         │
                │  arrays used by the LP (§5.3):                       │
                │    solar_reduction     -> effective_solar[h] *= f    │
                │    minimum_battery_res -> min_battery[h] = max(...)  │
                │    no_charge_window    -> charge[h] = 0              │
                │    no_discharge_window -> discharge[h] = 0           │
                │    max_grid_window     -> grid[h] ≤ cap[h]            │
                │    no_op               -> no change                  │
                └───────────────────────────────────────────────────┘
                                        │
                                        ▼
                ┌───────────────────────────────────────────────────┐
                │              MATH OPTIMIZER (PuLP / scipy)          │
                │  minimize Σ grid[h] · tariff[h]                     │
                │  subject to:                                         │
                │    energy balance: g + s + d == demand + c           │
                │    battery dynamics: E[h] == E[h-1] + c - d         │
                │    E[0] = E[23] = initial_energy_kwh                 │
                │    min_battery[h] ≤ E[h] ≤ capacity                  │
                │    0 ≤ charge ≤ max_charge (forced 0 in window)      │
                │    0 ≤ discharge ≤ max_discharge (forced 0 in win)   │
                │    0 ≤ solar ≤ effective_solar                       │
                │    0 ≤ grid (≤ cap[h] in max_grid_window)            │
                └───────────────────────────────────────────────────┘
                                        │
                                        ▼
                ┌───────────────────────────────────────────────────┐
                │            REPLAY VALIDATOR (self-check)             │
                │  Re-runs the constraints on the optimizer output:    │
                │    - energy balance per hour                         │
                │    - battery dynamics + bounds + rate limits         │
                │    - effective-solar usage                           │
                │    - directive constraints (charge/discharge windows,│
                │      reserve, grid cap)                              │
                │    - end-of-day neutrality                           │
                │    - totals re-derived from hourly_plan              │
                └───────────────────────────────────────────────────┘
                                        │
                                        ▼
                              200 OK — OptimizeResponse
```

## Module boundaries

| Module | Responsibility | Failure mode |
|---|---|---|
| `schemas.py` | Wire-level Pydantic models | Invalid request → 400 |
| `interpreter.py` | LLM provider chain + regex | All fail → regex safety net |
| `validator.py` | Section 08 guardrails | Malformed entry → coerce to no_op |
| `constraints.py` | Pure data transform | Defensive cleanup of bad hours |
| `optimizer.py` | LP solve | PuLP fails → scipy fallback → 500 |
| `replay.py` | Self-check + totals | Reports violations (logged, response still shipped) |
| `app.py` | FastAPI wiring + global exception handlers | Any uncaught → controlled 500 |

## Design principles (from `/ecc` RULES.md)

1. **Delegate to specialized modules** — each layer has one job.
2. **Tests before submission** — `tests/test_public_samples.py` exercises the math path against all 10 public cases.
3. **Validate inputs** — Pydantic + deterministic guardrails.
4. **Immutability** — all constraint arrays are fresh per request.
5. **Established patterns** — FastAPI exception handlers, dependency injection via env.
6. **No secrets in output** — config loader logs only key-presence, never values.
