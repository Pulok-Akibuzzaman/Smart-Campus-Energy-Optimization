# GridWise — 3-Minute Demo Video Script

**Total runtime:** 180 seconds (3:00)
**Tone:** demo-day energetic — show, don't lecture
**Speaker:** team member on camera; screen recording for the demo
**Tools:** OBS Studio (or Loom) at 1920×1080, 30 fps
**Capture order:** slide deck → live demo → closing

> Originally new in the merge. Tone borrowed from Pulok's
> `VIDEO_WALKTHROUGH_SCRIPT.md`; structure adapted for a live demo rather
> than a narrated slide deck.

---

## [0:00–0:20] COLD OPEN

**Visual:** Time-lapse of BUP campus buildings in early morning light; transition to a battery icon pulsing as the sun rises.

**On-screen text:** "BUP Campus Cafeteria runs on grid power 24/7. What if it didn't have to?"

**Speaker:**
> "Every hour, the cafeteria buys electricity from the grid — even when the sun is up and the battery is half-empty. We're Team Ai-Will-Fix-It, and this is GridWise: an LLM-assisted optimizer that decides, hour by hour, when to charge, when to discharge, and when to buy."

**Cue:** Snap to architecture diagram (slide 2).

---

## [0:20–0:50] ARCHITECTURE — "How it Works"

**Visual:** Animated pipeline diagram (5 boxes connected by arrows). Each box lights up as you describe it.

```
[Operator Notes] → [LLM Chain] → [Validator] → [LP Optimizer] → [Hourly Plan]
                      ↓ 4 providers ↓
                  [Groq → Gemini → OpenRouter → Puku]
                      ↓ if all fail
                  [Regex Safety Net]
```

**Speaker:**
> "Five moving parts. Operator notes go to an LLM chain — four hosted providers in priority order, plus a deterministic regex safety net that always returns something the validator can coerce. The validator enforces 12 strict checks; bad directives get rejected, not silently corrupted. The optimizer is pure linear programming — PuLP primary, scipy fallback. And after every solve, we replay the schedule independently to make sure what we report matches what the math actually does."

**Highlight on screen:** "**34/34 tests pass · 0.00 BDT diff on 10/10 public cases · 6 ms average solve**"

**Cue:** Cut to live demo.

---

## [0:50–1:30] LIVE DEMO — "Run a Case"

**Visual:** Screen recording. Open `http://localhost:8000/ui` (the debug console). Click "Samples" tab. Select Sample 04. Click "Run Math Path".

**Speaker (live):**
> "Here's the debug console — judges won't see this, it's gated behind an env flag, but it's how *we* verify everything works. Let me load sample 4 — that's the one with the no-charge-window from 1pm to 4pm — and run the math path."

**On-screen text appears as the optimizer runs:** "Solving…"

**Visual:** The optimizer finishes in ~30ms. The hourly plan renders in a table. The cost-vs-reference chart shows the team's cost landing exactly on the reference line.

**Speaker:**
> "Thirty milliseconds. And look — the team's total cost, 40,495 taka, is exactly the reference optimum. Not 40,495 minus twenty, not plus twenty — exactly. We match the reference cost to the paisa on all ten public cases."

**Cue:** Click "Directives" tab to show the parsed directives.

**Speaker:**
> "These are the parsed directives the LLM chain produced. Solar reduction at noon, minimum battery reserve at peak. Click. The validator accepted every one of them."

---

## [1:30–2:10] MATH — "Why It's Fast"

**Visual:** Slide showing the LP formulation as code. Highlight variables in one color, constraints in another, objective in a third.

```python
# 120 decision variables (5 per hour × 24 hours)
# 49 equality constraints (24 balance + 24 transitions + 1 EOD neutrality)
# Objective: minimize Σ grid[h] * tariff[h]
# 2-stage LP: stage 1 minimizes cost, stage 2 ties-break peak (only when needed)
```

**Speaker:**
> "Twenty-four hours, five decisions per hour — that's a hundred and twenty variables. We add forty-nine equality constraints: twenty-four for energy balance, twenty-four for battery transitions, and one to make sure we end the day where we started. The objective is just — minimize total grid cost. That's it. No magic, no metaheuristics. Linear programming solves it in milliseconds."

**Visual:** Show a side-by-side chart of cost-quality across the three branches (Aurna, Pulok, Ashik). Highlight that the merged branch matches Aurna's accuracy while keeping Ashik's resilience.

**Speaker:**
> "The interesting engineering is in the tie-breaker. When two schedules tie on cost, we want a deterministic one — same input, same output, every time. Our two-stage approach minimizes cost first, then peak grid, then total grid, then hour-by-hour lexicographic. That's why the merged branch beats any single one of the three on its own."

---

## [2:10–2:40] RESILIENCE — "What if Every LLM Fails?"

**Visual:** Open a terminal. Run `LLM_PROVIDER=invalid_key PYTHONPATH=src uvicorn gridwise.app:app &`. Show the request going through.

**Speaker:**
> "Let's prove the resilience. I'm starting the server with a deliberately invalid Groq key. Watch."

**Visual:** Run a curl POST to `/optimize-energy` with the sample-4 payload.

**Speaker:**
> "Groq's rejected — quota exceeded. The chain falls through to Gemini. Also rejected. OpenRouter. Rejected. Puku. Rejected. Regex safety net takes over. The request still returns a 200 with a valid schedule."

**Highlight on screen:** "**Provider used: regex · Status: 200 · Cost: 40,495 BDT**"

**Speaker:**
> "Same cost. Same plan. The regex safety net isn't a toy — it's deterministic, it's tested, and it gets the right answer on cases the LLM chain would have nailed anyway."

---

## [2:40–3:00] CLOSING — "Pull and Run"

**Visual:** Slide with the GitHub repo URL and a terminal showing `docker pull ashikonik/gridwise-bup-2026:1.0.0 && docker run -p 8000:8000 ashikonik/gridwise-bup-2026:1.0.0`.

**Speaker:**
> "That's GridWise. The full code is on GitHub — the team repo is the same place you've been watching. The Docker image is already pushed — pull it, run it, point it at your operator notes. The grid optimization happens by itself. Thanks for watching — and good luck to every team."

**On-screen text:** "Team Ai-Will-Fix-It · BUP CSE Fest 2026 · github.com/Pulok-Akibuzzaman/Smart-Campus-Energy-Optimization-Challenge-Team-Ai-Will-Fix-It · ashikonik/gridwise-bup-2026:1.0.0"

**End.**

---

## Recording checklist

- [ ] Camera: well-lit, neutral background, eye-level
- [ ] Microphone: lapel or shotgun, test levels
- [ ] Screen: 1920×1080, font sizes ≥ 18pt for legibility
- [ ] Slides: export as PNG, keep transitions under 0.5s
- [ ] Live demo: pre-stage the server with `ENABLE_UI=true`
- [ ] Pre-record: the math slide (no microphone), splice in later
- [ ] Audio: -6 dB peaks, normalize, remove plosives
- [ ] Export: 1080p H.264, ≤ 250 MB (upload-friendly)
- [ ] Backup: also export 720p for low-bandwidth judges
- [ ] Total runtime check: end exactly at 3:00, not 3:05
