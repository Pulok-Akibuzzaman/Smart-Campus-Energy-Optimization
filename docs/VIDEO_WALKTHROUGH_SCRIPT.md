# 3-Minute Architecture & Solution Video Script
**Competition: BUP CSE FEST 2026 Hackathon — GridWise Challenge**
**Target Duration: Exactly 2 minutes 45 seconds (Limit: 3 minutes max)**

---

### Timeline Overview
- **0:00 – 0:30 (30s)**: Problem & Mission Overview
- **0:30 – 1:15 (45s)**: Architecture: Decoupled LLM $\rightarrow$ Guardrail $\rightarrow$ LP Optimizer
- **1:15 – 2:00 (45s)**: Mathematical Formulation & Energy Constraints
- **2:00 – 2:35 (35s)**: Live Demo (Server Startup, Health Check, 10 Benchmark Cases)
- **2:35 – 2:45 (10s)**: Deployment, Docker & Conclusion

---

### Section 1: Problem & Mission Overview (0:00 – 0:30)
**[Visual: Show Problem Statement Title Page or Slide]**
> *"Hello judges and organizers. Today, we present our complete, production-ready solution for the BUP CSE FEST 2026 GridWise Hackathon.*
> 
> *Our goal is to optimize a smart university campus microgrid over a 24-hour horizon. The challenge combines natural-language operational notes from human grid operators with mathematical dispatch optimization—minimizing total electricity cost from the grid while strictly obeying solar availability, battery state-of-charge dynamics, and operator directives."*

---

### Section 2: Decoupled Architecture (0:30 – 1:15)
**[Visual: Show README Architecture Diagram or Slide]**
> *"A central principle of our architecture is that human language is never directly trusted as mathematical constraints. We built a three-tier decoupled pipeline:*
> 
> *First, the **LLM Interpreter**: We prompt a language model with strict JSON formatting and few-shot examples to map natural-language operator notes into one of five structured directives—such as `solar_reduction`, `minimum_battery_reserve`, `no_charge_window`, `no_discharge_window`, and `max_grid_window`—or classify distractors as `no_op`.*
> 
> *Second, **Deterministic Guardrails**: The output is validated by a rigorous sanitization layer. We enforce start-inclusive, end-exclusive whole-hour intervals, guarantee sorted ascending hours from 0 to 23, clamp solar reduction factors between 0 and 1, convert relative percentages to absolute kilowatt-hours, and sanitize `no_op` semantics.*
> 
> *Third, the validated directives feed directly into our **Mathematical Optimizer**."*

---

### Section 3: Exact Mathematical LP Optimization (1:15 – 2:00)
**[Visual: Show `optimizer.py` code]**
> *"For the optimization engine, we formulated the 24-hour dispatch problem as an exact Mixed-Integer Linear Program using PuLP with the HiGHS and CBC solvers.*
> 
> *Our formulation guarantees:*
> 1. *Strict hourly energy balance: grid import plus used solar plus battery discharge equals demand plus battery charge.*
> 2. *Binary mutual exclusivity: charging and discharging never occur simultaneously.*
> 3. *Hourly charge and discharge rate bounds.*
> 4. *Dynamic battery state transitions with reserve bounds.*
> 5. *Crucially, end-of-day battery neutrality: the battery state at hour 23 precisely equals its initial energy.*
> 
> *Because this is an exact LP, it solves in less than 20 milliseconds per day and is guaranteed to find the true global mathematical minimum cost."*

---

### Section 4: Live Execution & Test Demo (2:00 – 2:35)
**[Visual: Screen recording of Terminal running `python test_server.py` or `python run_samples.py`]**
> *"Let's see the system in action.*
> 
> *Here, we start our FastAPI service. A quick GET request to `/health` returns status `ok` in single-digit milliseconds.*
> 
> *Next, we execute our automated verification suite across all 10 canonical public sample cases from the competition pack.*
> 
> *As you can see, every single sample case passes all physical constraints, energy balances, and directive rules, matching the official benchmark costs down to 0.00 BDT difference. The average execution time is just 17 milliseconds per case, well within the 5-second P95 requirement."*

---

### Section 5: Deployment, Docker & Conclusion (2:35 – 2:45)
**[Visual: Show Dockerfile & Live API URL in Postman/Browser]**
> *"Our service is containerized with a lightweight Docker image and deployed publicly. All code, configuration, and reproducibility quickstarts are documented in our repository.*
> 
> *Thank you for your time!"*
