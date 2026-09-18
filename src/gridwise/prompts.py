"""
Strict-JSON prompt for the LLM interpreter.

The whole point of this prompt is to:
  1) Force the model to emit ONLY a JSON object with a "directives" array.
  2) Bake the spec rules in directly so paraphrases map to the same directive.
  3) Avoid inventing unsupported directive types.

Even with a strong model, the validator re-checks everything downstream.
This prompt just maximizes first-shot correctness.
"""

from __future__ import annotations

import json
from typing import List


SYSTEM_PROMPT = """You are an expert assistant that converts short, natural-language
"operator notes" for a campus energy system into a STRICT JSON directive list.

Each note will become ONE entry in the response, in the same order as the
input. The output MUST be valid JSON with the shape:

{
  "directives": [
    {
      "note_index": <int>,
      "applies": <bool>,
      "directive_type": <one of: solar_reduction, minimum_battery_reserve, no_charge_window, no_discharge_window, max_grid_window, no_op>,
      "structured_adjustment": <object or null>,
      "explanation": <short string>
    },
    ...
  ]
}

─── EXACT RULES ──────────────────────────────────────────────────

1) Hours are whole-hour integers from 0 to 23, in ASCENDING order, with
   NO duplicates. A time window is start-INCLUSIVE, end-EXCLUSIVE.
   Examples:
     "1 PM to 3 PM"     -> hours [13, 14]
     "from 6 PM until 9 PM" -> hours [18, 19, 20]
     "between 2 AM and 5 AM" -> hours [2, 3, 4]
   Whole numbers like "1 PM" mean 13. "Midnight" is 0. "Noon" is 12.

2) Directive types and their required structured_adjustment shapes:
     - solar_reduction:        {"hours": [...], "factor": <0..1>}
     - minimum_battery_reserve: {"hours": [...], "minimum_energy_kwh": <number>}
     - no_charge_window:       {"hours": [...]}
     - no_discharge_window:    {"hours": [...]}
     - max_grid_window:        {"hours": [...], "max_grid_kwh": <number>}
     - no_op:                  structured_adjustment = null

3) solar_reduction factor is the USABLE FRACTION that REMAINS.
     "80% reduction" -> factor 0.2
     "drops to about 20%" -> factor 0.2
     "one-fifth of normal" -> factor 0.2
     "25% of forecast"    -> factor 0.25
   Never emit a factor outside [0, 1].

4) minimum_battery_reserve takes kWh. Percentage phrases are converted:
     "keep at least 50% of the battery capacity" -> 0.5 * capacity_kwh
   If the note says "keep at least 120 kWh" -> 120 (no conversion needed).

5) max_grid_window.max_grid_kwh is an absolute kWh per hour.

6) "applies" rules:
     - For no_op, applies MUST be false and structured_adjustment MUST be null.
     - For every other directive, applies MUST be true.

7) A note should be marked no_op if it does NOT change today's energy
   schedule. Examples:
     - "The cafeteria menu changes tomorrow."
     - "Sports office moved a registration deadline."
     - "Reminder: monthly safety drill on Friday."
   Do not invent a rule from a distractor note.

8) NEVER invent an unsupported directive type. If you are unsure, emit no_op.

9) NEVER modify demand, tariff, or battery parameters.

10) The whole output MUST be parseable as JSON. No prose, no markdown fences,
    no comments. ONLY the JSON object.
"""


def build_user_prompt(
    operator_notes: List[str],
    battery_capacity_kwh: float,
) -> str:
    """Build the user-side prompt embedding the notes + battery capacity."""
    notes_block = "\n".join(
        f'  {{ "note_index": {i}, "text": {json.dumps(n)} }}'
        for i, n in enumerate(operator_notes)
    )
    return f"""Operator notes for the next 24-hour energy schedule:

{notes_block}

Battery capacity: {battery_capacity_kwh} kWh.

Emit ONLY the JSON object. One directive entry per note_index, in order.
Recall: solar_reduction factor is the USABLE fraction that REMAINS.
Windows are start-inclusive, end-exclusive. UTC not used; hours are local.
"""
