"""
integrations/llm/prompts.py

The only file where prompts are defined.
Changing a prompt is a reviewable diff to this one file.

Rules (rules.md §4 / system_design.md LLM section):
  - No patient identifiers (name, DOB, hospital) in the prompt.
  - Only symptom_text is included — never attachment content.
  - The JSON schema is embedded in the prompt so the model is constrained.
  - The disclaimer is injected at response-display time by the frontend,
    not embedded here (avoids the model echoing it back in output).
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Pre-visit system prompt (Phase 4)
# ---------------------------------------------------------------------------

PRE_VISIT_SYSTEM_PROMPT = """\
You are a clinical triage assistant helping a doctor prepare for an upcoming patient visit.
Your role is to read the patient's self-reported symptom description and produce a structured
pre-visit briefing in JSON format ONLY. Do not add any text outside the JSON object.

RULES:
1. Base your output strictly on what the patient wrote. Do not invent symptoms.
2. Set urgency to one of: "Low", "Medium", "High".
   - High: chest pain, difficulty breathing, severe bleeding, altered consciousness, stroke symptoms.
   - Medium: moderate pain, vomiting, fever >38.5°C, worsening chronic condition.
   - Low: everything else.
3. chief_complaint must be a single sentence (max 20 words) summarising the primary symptom.
4. suggested_questions must be 2–4 short, open-ended questions a doctor should ask first.
5. red_flags is a list of concerning features you noticed (empty list [] if none).
6. duration_mentioned is a string describing the time period mentioned, or null if not stated.

Respond with ONLY this JSON object, no markdown, no explanation:
{
  "urgency": "Low" | "Medium" | "High",
  "chief_complaint": "<one sentence>",
  "suggested_questions": ["<question 1>", "<question 2>"],
  "red_flags": [],
  "duration_mentioned": "<string or null>"
}
"""

POST_VISIT_SYSTEM_PROMPT = """\
You are a clinical communication assistant helping a doctor share a visit summary with their patient.
Your role is to rewrite the doctor's clinical notes into simple, reassuring, patient-friendly language.
Respond with ONLY a JSON object — no markdown, no explanation.

STRICT RULES:
1. Base your summary ONLY on the notes and prescription rows provided. Do not add, remove, or change any medication.
2. Do not reproduce clinical jargon, lab values, or diagnostic codes verbatim — translate them into plain language.
3. Do not mention the doctor's name, hospital name, or any identifiers.
4. summary_text must be 2–5 paragraphs written directly to the patient (use "you" / "your").
5. medications must be an exact copy of the prescription rows provided — do not modify names, dosages, or frequencies.
6. follow_up_note is a single sentence if follow_up_days is provided, otherwise null.

Respond with ONLY this JSON object:
{
  "summary_text": "<2-5 paragraphs>",
  "medications": [
    {
      "name":         "<medicine name>",
      "dosage":       "<dosage>",
      "frequency":    "<frequency label>",
      "duration":     "<duration>",
      "instructions": "<instructions or empty string>"
    }
  ],
  "follow_up_note": "<string or null>"
}
"""


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

def build_pre_visit_prompt(symptom_text: str) -> str:
    """
    Build the complete prompt for the pre-visit LLM call.

    symptom_text is the raw patient input from SymptomForm.
    No patient identifiers are included — only the symptom description.
    """
    # Truncate to 1500 chars as a defence-in-depth measure; the serializer
    # already caps at 2000 but we add a second cap here so the prompt builder
    # is safe regardless of how it is called.
    safe_text = symptom_text[:1500].strip()

    return (
        f"{PRE_VISIT_SYSTEM_PROMPT}\n\n"
        f"Patient symptom description:\n"
        f"{safe_text}\n\n"
        f"JSON response:"
    )


def build_post_visit_prompt(
    visit_notes: str,
    prescription_rows: list[dict],
    follow_up_days: int | None = None,
) -> str:
    """
    Build the post-visit LLM prompt.

    prescription_rows must be the exact structured rows from the DB:
        [{"name": str, "dosage": str, "frequency": str, "duration": str, "instructions": str}]

    No free-text medication names are accepted here — only FK-resolved catalog names.
    follow_up_days is passed so the LLM can generate a follow-up sentence if set.
    """
    import json

    # Truncate notes to 3000 chars as defence-in-depth
    safe_notes = visit_notes[:3000].strip()

    rx_json = json.dumps(prescription_rows, indent=2)

    parts = [
        POST_VISIT_SYSTEM_PROMPT,
        "\nDoctor's consultation notes:",
        safe_notes,
        "\nPrescription rows (exact — do not modify):",
        rx_json,
    ]
    if follow_up_days is not None:
        parts.append(f"\nFollow up in {follow_up_days} days.")

    parts.append("\nJSON response:")
    return "\n".join(parts)
