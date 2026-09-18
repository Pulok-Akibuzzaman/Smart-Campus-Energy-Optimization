# GridWise — 18-Slide Storyboard

**Total runtime:** 180 seconds (3:00)
**Slide rate:** 10 sec/slide (slides 16–18 are slightly longer for closing
pacing — see per-slide durations below).
**Export target:** PNG @ 1920×1080, transitions ≤ 0.5 s.
**Companion to:** [`VIDEO_SCRIPT.md`](./VIDEO_SCRIPT.md) — every slide here
corresponds to a section in the script.

> Originally new in the merge. Pulok's storyboard was 30 slides at 6 s
> apiece; this compressed version (18 slides @ 10 s) is closer to the
> demo-day energetic pace the script calls for.

---

## Conventions used in every slide

- **Title bar (top)**: slide number · section name · timestamp cue
- **Visual zone (centre, 80% of frame)**: the thing you'll point at
- **Caption bar (bottom)**: one-line takeaway or transition text
- **Cue (right)**: ½-second transition to the next slide

---

## Section A — COLD OPEN (slides 1–2, 20 s)

### Slide 1 — "The 24/7 Problem"
**Duration:** 0:00–0:10
**Visual:** Time-lapse: BUP campus at dawn. Cafeteria roof in silhouette.
Battery icon overlaid in the corner, blinking green at 47%.
**Caption:** "BUP Campus Cafeteria · 02:47 AM · battery 47%"
**Speaker note:** *"It's half past two in the morning. The cafeteria is asleep.
But the grid meter is still ticking — buying electricity even though we'll
have solar by sunrise."*
**Cue:** Quick zoom-in on the battery icon.

### Slide 2 — "What If?"
**Duration:** 0:10–0:20
**Visual:** Battery drains to 0%, then sun rises over the roof, battery
jumps to 100%. Same icon, but with a lightning-bolt beside it labelled
"GridWise".
**Caption:** "What if it didn't have to?"
**Speaker note:** *"What if the system could decide — every hour, every
day — when to charge from solar, when to discharge to loads, and when to
buy from the grid? That's GridWise."*
**Cue:** Snap cut to architecture diagram.

---

## Section B — ARCHITECTURE (slides 3–5, 30 s)

### Slide 3 — "Five Moving Parts"
**Duration:** 0:20–0:30
**Visual:** Five boxes in a row, dim:

```
[Operator Notes] [LLM Chain] [Validator] [LP Optimizer] [Hourly Plan]
```
**Caption:** "Operator Notes → Validator → Optimizer → Plan"
**Speaker note:** *"Five moving parts. Operator notes go in. A validated
hourly plan comes out. The validator enforces strict checks; the optimizer
is pure linear programming."*
**Cue:** Box-by-box lighting animation begins.

### Slide 4 — "Four Providers, One Safety Net"
**Duration:** 0:30–0:40
**Visual:** LLM Chain box expands into 5 sub-boxes:

```
[Groq] → [Gemini] → [OpenRouter] → [Puku] → [Regex Safety Net]
```
The arrow turns red on the failed provider; the regex box glows green when
it takes over.
**Caption:** "Chain fails over · Regex always returns something valid"
**Speaker note:** *"Four hosted LLM providers in priority order — Groq,
Gemini, OpenRouter, Puku. If all four fail, the regex safety net takes
over. The validator can coerce its output; the request still returns 200."*
**Cue:** Zoom into the Validator + Optimizer boxes.

### Slide 5 — "By the Numbers"
**Duration:** 0:40–0:50
**Visual:** Big-number card, three KPIs in a row:

```
┌─────────────────┬─────────────────┬─────────────────┐
│ 34/34 tests pass │ 0.00 BDT diff   │ 6 ms avg solve  │
└─────────────────┴─────────────────┴─────────────────┘
```
**Caption:** "All ten public cases match reference optimum, to the paisa."
**Speaker note:** *"Thirty-four of thirty-four tests pass. Zero — repeat,
zero — BDT diff on all ten public cases. Six milliseconds average solve
time. Linear programming does this."*
**Cue:** Hard cut to live demo.

---

## Section C — LIVE DEMO (slides 6–10, 40 s)

### Slide 6 — "The Debug Console"
**Duration:** 0:50–1:00
**Visual:** Screen recording, full browser. URL bar shows
`http://localhost:8000/ui`. Cursor moves to the "Samples" tab.
**Caption:** "`/ui` — gated behind ENABLE_UI=true"
**Speaker note:** *"Here's the debug console. Judges won't see this — it's
gated behind an env flag — but it's how we verify everything works."*
**Cue:** Click "Samples" tab.

### Slide 7 — "Pick a Hard Case"
**Duration:** 1:00–1:10
**Visual:** Sample list. Cursor hovers over Sample 04. Tooltip:
"No-charge window 1pm–4pm · peak-reserve at 7pm".
**Caption:** "Sample 04 · six directives · no-charge + reserve"
**Speaker note:** *"Sample 4 is one of the harder cases — it has a
no-charge window in the afternoon and a minimum battery reserve at peak
evening. Let's run it."*
**Cue:** Click "Run Math Path" button.

### Slide 8 — "Solving…"
**Duration:** 1:10–1:15
**Visual:** Hourly plan table renders row by row, top-down. Spinner
replaced by a checkmark. Time-elapsed overlay: "31 ms".
**Caption:** "31 ms · PuLP · CBC"
**Speaker note:** *"Thirty-one milliseconds. That's the whole solve. Look
at the table — every hour has a value, every constraint is satisfied."*
**Cue:** Scroll to the bottom of the plan.

### Slide 9 — "Matches Reference"
**Duration:** 1:15–1:25
**Visual:** Cost-vs-reference chart. Team line lands exactly on reference.
Total cost card: "40,495 BDT".
**Caption:** "Cost = 40,495 BDT (reference: 40,495 BDT) · diff +0.00"
**Speaker note:** *"Forty thousand four hundred ninety-five taka. The
reference optimum. Not minus twenty, not plus twenty — exactly. We match
the reference cost to the paisa on every public case."*
**Cue:** Click "Directives" tab.

### Slide 10 — "Directives Pass"
**Duration:** 1:25–1:30
**Visual:** Directives list. Six chips, all green: "Solar reduction 12:00",
"Reserve 30 kWh 19:00", etc. Validator-result column shows "✓ accepted" on
every row.
**Caption:** "Validator: 6/6 accepted"
**Speaker note:** *"Six directives in. Six accepted. None rejected, none
silently corrupted."*
**Cue:** Cut to math.

---

## Section D — MATH (slides 11–13, 40 s)

### Slide 11 — "Decision Variables"
**Duration:** 1:30–1:40
**Visual:** Annotated LP code. Variables highlighted in one colour:

```python
grid = [LpVariable(f"grid_{h}")   for h in range(24)]  # 24 vars
solar = ...                                        # 24 vars
charge = ...                                       # 24 vars
discharge = ...                                    # 24 vars
E = ...                                            # 24 vars
                                                  # 120 total
```
**Caption:** "120 variables · 5 per hour × 24 hours"
**Speaker note:** *"Twenty-four hours. Five decisions per hour — grid
purchase, solar used, charge, discharge, battery energy. That's a hundred
and twenty decision variables."*
**Cue:** Highlight constraints.

### Slide 12 — "49 Equality Constraints"
**Duration:** 1:40–1:50
**Visual:** Constraints in another colour:

```python
# 24 balance + 24 transitions + 1 EOD neutrality = 49
prob += grid[h] + solar[h] + discharge[h] == demand[h] + charge[h]
prob += E[h] == E[h-1] + charge[h] - discharge[h]
prob += E[23] == initial  # end-of-day neutrality
```
**Caption:** "49 equality constraints · pure LP"
**Speaker note:** *"Forty-nine equality constraints. Twenty-four for
energy balance, twenty-four for battery transitions, one to keep the
battery where it started. That's the whole problem."*
**Cue:** Highlight objective.

### Slide 13 — "Why Three Branches Became One"
**Duration:** 1:50–2:10
**Visual:** Three small chart cards side-by-side: Aurna, Pulok, Ashik on
top row; "Merged" on bottom row, highlighted. Each card shows
"avg quality_ratio". Merged card shows "0.9999".
**Caption:** "Matched Aurna's accuracy, kept Ashik's resilience"
**Speaker note:** *"The merged branch matches Aurna's accuracy on the
public cases while keeping Ashik's resilience on hidden cases where
multiple optima exist. Three independent codebases, one deterministic
schedule."*
**Cue:** Cut to terminal.

---

## Section E — RESILIENCE (slides 14–15, 30 s)

### Slide 14 — "Invalid Key"
**Duration:** 2:10–2:25
**Visual:** Terminal. Command runs:

```
$ LLM_PROVIDER=invalid_key PYTHONPATH=src uvicorn gridwise.app:app &
```

Server starts. Healthcheck shows green. Then a curl POST is fired.
**Caption:** "LLM_PROVIDER=invalid_key · server still up"
**Speaker note:** *"Let's prove the resilience. Server starts even with a
deliberately invalid key. Watch what happens when we send a request."*
**Cue:** Run the curl.

### Slide 15 — "Every Provider Fails — Plan Still Arrives"
**Duration:** 2:25–2:40
**Visual:** Request log scrolls. Four red ✗ marks for Groq, Gemini,
OpenRouter, Puku. Then green ✓ for "regex safety net". Final response:

```
{
  "status": 200,
  "provider_used": "regex",
  "total_cost_bdt": 40495.0
}
```
**Caption:** "Same cost · same plan · regex isn't a toy"
**Speaker note:** *"Groq's rejected — quota exceeded. Gemini rejected.
OpenRouter rejected. Puku rejected. Regex safety net takes over. Same
cost. Same plan. Two hundred OK. The regex path isn't a toy — it's
tested, and it gets the right answer."*
**Cue:** Cut to closing.

---

## Section F — CLOSING (slides 16–18, 20 s)

### Slide 16 — "Pull"
**Duration:** 2:40–2:50
**Visual:** Big terminal command:

```
$ docker pull ashikonik/gridwise-bup-2026:1.0.0
```
Output scrolls: layers download.
**Caption:** "Public image · 1.0.0 · non-root · urllib healthcheck"
**Speaker note:** *"Pull the image. It's already on Docker Hub — layer
downloads in seconds."*
**Cue:** Slide transition to next.

### Slide 17 — "Run"
**Duration:** 2:50–2:55
**Visual:** Terminal command + boot log + curl `/health`:

```
$ docker run -p 8000:8000 ashikonik/gridwise-bup-2026:1.0.0
{"status":"ok"}
```
**Caption:** "Point at your operator notes · grid optimization happens"
**Speaker note:** *"Run it. Point it at your operator notes. The grid
optimization happens by itself."*
**Cue:** Final card.

### Slide 18 — "End Card"
**Duration:** 2:55–3:00
**Visual:** Final card. Centre logo. Below: "Team Ai-Will-Fix-It · BUP
CSE Fest 2026". Below that: two URLs side-by-side, the GitHub repo on the
left, the Docker image on the right.
**Caption:** "github.com/Pulok-Akibuzzaman/Smart-Campus-Energy-Optimization-Challenge-Team-Ai-Will-Fix-It · ashikonik/gridwise-bup-2026:1.0.0"
**Speaker note:** *"Team Ai-Will-Fix-It. Thanks for watching — and good
luck to every team."*
**Cue:** Fade to black. End.

---

## Recording checklist (storyboard-specific)

- [ ] Export slides as PNG (1920×1080, 30 fps, animations retained as
      short loops ≤ 1.5 s)
- [ ] Transitions: hard cuts, ≤ 0.5 s
- [ ] Live demo screen-recording starts at slide 6 — pre-stage the server
      with `ENABLE_UI=true` BEFORE recording
- [ ] Pre-record slide 13 (math) as a voice-over; splice in for clean
      pacing
- [ ] Speaker audio peaks at –6 dB; normalize across all 18 slides
- [ ] End card visible for last 5 seconds (slide 18 = 5 s on screen)
- [ ] Total runtime check: hard cap at 3:00 (180 s); trim slide 13 if
      needed

## Provenance

Originally new in the merge. Pulok's VIDEO_WALKTHROUGH_SCRIPT.md had a
30-slide storyboard at 6 s each; this condenses to 18 slides at 10 s to
match the demo-day energetic tempo of `VIDEO_SCRIPT.md`.
