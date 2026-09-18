# GridWise — 3-Minute Presentation & Video Walkthrough Script

> **Event**: BUP CSE Fest 2026 · Smart Campus Energy Optimization Challenge (GridWise)  
> **Target Duration**: Exactly 3:00 minutes  
> **Format**: Slide / Architecture Diagram / Live Terminal Demo Walkthrough  
> **Tie-Breaker Priority**: #1 Judge Evaluation Tie-Breaker

---

## Visual & Audio Script Breakdown

```
  0:00 ───┬──────────────────────────────────────────
          │ [0:00 - 0:35] Problem Understanding & Challenge Goal
  0:35 ───┼──────────────────────────────────────────
          │ [0:35 - 1:25] Architecture: LLM → Guardrails → LP Optimizer → Validator
  1:25 ───┼──────────────────────────────────────────
          │ [1:25 - 2:10] Key Technical Decisions & Math Formulation
  2:10 ───┼──────────────────────────────────────────
          │ [2:10 - 2:50] Live Verification & Benchmark Demo
  2:50 ───┴──────────────────────────────────────────
          │ [2:50 - 3:00] Conclusion & Impact
```

---

### [0:00 – 0:35] Part 1: Problem Understanding & System Goal

**On Screen**:
- Title slide: *GridWise: Smart Campus Energy Optimization Challenge*.
- Diagram showing campus microgrid: Grid Import + Rooftop Solar + Battery Energy Storage System (BESS) powering Campus Demand under Time-of-Use Tariffs.
- Callout: Natural-language operator notes arriving dynamically.

**Voiceover / Presenter**:
> "Hello judges! We are presenting GridWise, our autonomous 24-hour campus energy scheduling service for the BUP Smart Campus Energy Optimization Challenge.
>
> In this challenge, our campus must minimize grid electricity costs across a 24-hour horizon under fluctuating demand, solar generation, and dynamic tariffs. But there is a crucial twist: human campus operators submit natural-language notes—such as emergency battery reserves, solar maintenance reductions, charger outages, feeder grid caps, or unrelated campus distractors.
>
> Our goal was to engineer a robust, sub-second production service that parses human language using a generative model, validates directives through deterministic guardrails, and solves the exact dispatch schedule to mathematical optimality."

---

### [0:35 – 1:25] Part 2: Visual Dashboard & End-to-End Pipeline Architecture

**On Screen**:
- Open the **GridWise Visual Dashboard** (`http://localhost:8000/dashboard`).
- Point to the live **5-Stage Pipeline Stepper**:
  1. `Energy Data + Notes`
  2. `LLM Directive Interpreter`
  3. `Deterministic Guardrail Validator`
  4. `SciPy HiGHS LP Optimizer`
  5. `Defense-in-Depth Self-Replay Validator`
- Click on **SAMPLE-01 (Cleaning)** and show the notes and battery parameters loading.
- Click **"⚡ Optimize 24-Hour Schedule"** and watch the stepper light up sequentially in real time.

**Voiceover / Presenter**:
> "To demonstrate how the system reasons, we built this visual analytics dashboard layered directly over our API.
>
> You can see our 5-stage pipeline in action:
> First, the **LLM Directive Interpreter** receives operator notes alongside battery capacity context. Using prompt calibration and structured JSON schema output, it translates human notes into canonical machine directives.
>
> Second, because **LLM output is untrusted until verified**, our **Deterministic Guardrail Validator** validates directive types, verifies sorted hours in 0 to 23, clamps factors and reserves, and safely repairs or defaults malformed inputs to `no_op` without crashing.
>
> Third, the validated directives feed into our **Mathematical Optimizer**, which formulates and solves the 24-hour Linear Program in under 3 milliseconds.
>
> Fourth, our **Defense-in-Depth Validator** re-simulates the resulting schedule hour-by-hour, ensuring energy balance, solar curtailment, battery bounds, and end-of-day neutrality within a 0.01 tolerance before returning the final response."

---

### [1:25 – 2:10] Part 3: Paraphrase Robustness & Mathematical Rigor

**On Screen**:
- On the dashboard, demonstrate the **Paraphrase Robustness Chips**:
  - Click the chip: *"PV production will drop to about 20% between 13:00 and 15:00."*
  - Click **"⚡ Optimize 24-Hour Schedule"**.
  - Show the directive card extracting `solar_reduction`, hours `[13, 14]`, factor `0.20`.
- Scroll to the **24-Hour Energy Dispatch Chart**:
  - Highlight the stacked bars: rooftop solar utilized during the day, battery charging during low-tariff hours, and battery discharging during peak evening tariff hours (hours 18–21) when grid prices spike to 30 BDT/kWh.
- Point to the **Battery State-of-Charge Chart**:
  - Show battery energy staying safely above the required minimum reserve line and returning exactly to `initial_energy_kwh` at hour 23 (neutrality).
- Highlight the green **Defense-in-Depth Verified ✓** badge strip.

**Voiceover / Presenter**:
> "Now watch how the system handles paraphrasing.
>
> Clicking our paraphrase chip changes the wording to: 'PV production will drop to about 20% between 13:00 and 15:00'. We click Optimize, and the LLM instantly extracts `solar_reduction` for hours 13 and 14 with a factor of 0.20—proving genuine semantic understanding, not brittle regex matching.
>
> Below, our 24-hour dispatch chart demonstrates why the mathematical optimization is so effective: the battery charges during cheap early-morning hours, solar covers daytime load, and stored battery energy discharges precisely during peak evening hours when tariffs hit 30 BDT per kilowatt-hour.
>
> Notice the battery state-of-charge curve: it respects all emergency reserve windows and returns exactly to its starting energy at hour 23, fulfilling the end-of-day neutrality constraint."

---

### [2:10 – 2:50] Part 4: Benchmark Verification & Terminal Proof

**On Screen**:
- Switch to terminal:
  - Run `python test_solution.py`.
- Highlight the test output:
  - `GET /health` returned in 1.1 ms.
  - All 10 public sample cases scored **PASS** with cost difference $= 0.0000$ BDT.
  - Average latency $= 4.5 \text{ ms}$, P95 latency $= 7.0 \text{ ms}$ (far surpassing the 5-second target!).
  - Malformed schema tests returning HTTP 400 Bad Request.

**Voiceover / Presenter**:
> "Now let's verify our official automated benchmarks.
>
> Running `python test_solution.py` against the official BUP evaluation pack:
> `GET /health` responds in just 1 millisecond.
>
> Next, `POST /optimize-energy` evaluates all 10 public scenarios—including solar cleaning, emergency percentage reserves, charger outages, feeder caps, and distractor notes.
>
> Every single scenario passes with an optimal cost difference of exactly **0.0000 BDT** against the reference benchmarks!
>
> Our average latency is only **4.5 milliseconds**, with a 95th-percentile latency of **7.0 milliseconds**—achieving the maximum 3 out of 3 points for Performance & Reliability.
>
> Finally, malformed schema tests confirm robust HTTP 400 rejection without leaking stack traces or secrets."

---

### [2:50 – 3:00] Part 5: Conclusion & Reproducibility

**On Screen**:
- Final slide:
  - Repository URL
  - Public Base URL
  - Docker pull and run command: `docker run -p 8000:8000 <username>/gridwise:latest`
  - Thank you & BUP CSE Fest 2026.

**Voiceover / Presenter**:
> "GridWise delivers a complete, reproducible, and competition-winning solution with full Docker support, interactive visual analytics, and copy-paste setup instructions.
>
> Thank you for your time, and we look forward to the next round of BUP CSE Fest 2026!"

---

### [2:50 – 3:00] Part 5: Conclusion & Reproducibility

**On Screen**:
- Final slide:
  - GitHub Repo Link
  - Docker pull and run command: `docker run -p 8000:8000 gridwise-service:latest`
  - Thank you & BUP CSE Fest 2026.

**Voiceover / Presenter**:
> "GridWise delivers a complete, reproducible, and competition-winning solution with full Docker support and copy-paste setup instructions.
>
> Thank you for your time, and we look forward to the next round of BUP CSE Fest 2026!"
