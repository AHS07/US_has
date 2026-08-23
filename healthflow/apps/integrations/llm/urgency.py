"""
integrations/llm/urgency.py

Keyword-based urgency escalation rules.

Rules (phases.md Phase 4, architecture.md §LLM):
  - The rule engine runs BEFORE the LLM call.
  - If the rule engine finds a HIGH keyword, the urgency is set to "High"
    regardless of what the LLM later produces.
  - The rule engine result is attached as urgency_override in the audit log
    so reviewers can see when the override fired.
  - This layer is intentionally simple and auditable — no ML, no embeddings.
    It is the last line of defence: it must never miss an obvious emergency.

Adding new keywords: edit the KEYWORD_MAP dict below.
Each key is a severity level ("High" > "Medium"); values are lists of
lowercase substrings that trigger that level when found in symptom_text.
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Keyword map
# Ordered from most to least severe.
# ---------------------------------------------------------------------------

KEYWORD_MAP: dict[str, list[str]] = {
    "High": [
        # Cardiac
        "chest pain", "chest tightness", "heart attack", "cardiac arrest",
        "palpitation", "irregular heartbeat",
        # Respiratory
        "difficulty breathing", "can't breathe", "cannot breathe",
        "shortness of breath", "choking", "stopped breathing",
        # Neurological
        "stroke", "face drooping", "arm weakness", "speech difficulty",
        "loss of consciousness", "unconscious", "seizure", "convulsion",
        "sudden severe headache",
        # Bleeding / trauma
        "severe bleeding", "uncontrolled bleeding", "coughing blood",
        "vomiting blood", "blood in stool", "black stool",
        # Allergic / toxic
        "anaphylaxis", "allergic reaction", "severe allergic",
        "swollen throat", "tongue swelling",
        # Miscellaneous
        "suicidal", "overdose",
    ],
    "Medium": [
        "moderate pain", "high fever", "fever above 38", "fever above 39",
        "fever above 40", "vomiting", "severe nausea", "persistent nausea",
        "dizzy", "dizziness", "fainting", "fainted", "blurred vision",
        "severe headache", "migraine", "worsening", "getting worse",
        "spreading rash", "swelling",
    ],
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def evaluate_urgency(symptom_text: str) -> tuple[str, list[str]]:
    """
    Scan *symptom_text* for keywords and return:
        (urgency_level, matched_keywords)

    urgency_level is "High", "Medium", or "Low".
    matched_keywords is the list of terms that triggered the level (for audit).

    If both High and Medium keywords are found, High wins.
    """
    lower = symptom_text.lower()
    matched: dict[str, list[str]] = {"High": [], "Medium": []}

    for level, keywords in KEYWORD_MAP.items():
        for kw in keywords:
            # Use word-boundary-aware matching where possible
            pattern = re.compile(re.escape(kw), re.IGNORECASE)
            if pattern.search(lower):
                matched[level].append(kw)

    if matched["High"]:
        return "High", matched["High"]
    if matched["Medium"]:
        return "Medium", matched["Medium"]
    return "Low", []


def should_override_llm(rule_urgency: str, llm_urgency: str) -> bool:
    """
    Return True when the rule engine's urgency is more severe than the LLM's,
    meaning the rule engine result should override the LLM.

    Severity order: High > Medium > Low
    """
    order = {"Low": 0, "Medium": 1, "High": 2}
    return order.get(rule_urgency, 0) > order.get(llm_urgency, 0)
