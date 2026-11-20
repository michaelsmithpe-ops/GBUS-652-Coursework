"""The three output tools (one per agent). Each agent must call its tool exactly once.

These give each agent's answer a fixed structure so the display, run log, and grader can
read it reliably. strict=True makes the API guarantee the input matches the schema.
Matches prompts/tools.md.
"""

from __future__ import annotations


def _obj(props: dict, desc: str = "") -> dict:
    out = {"type": "object", "properties": props, "required": list(props),
           "additionalProperties": False}
    if desc:
        out["description"] = desc
    return out


def _s(desc: str) -> dict:
    return {"type": "string", "description": desc}


def _enum(values: list[str], desc: str) -> dict:
    return {"type": "string", "enum": values, "description": desc}


_LIST = {"type": "array", "items": {"type": "string"}}
_CITES = {**_LIST, "description": "Every ID relied on: ROE-x.y, N-xx, H-xx, C-xx, sensor ID + timestamp."}

SUBMIT_ASSESSMENT = {
    "name": "submit_assessment",
    "description": "Submit your final assessment and recommendation. Call exactly once, at the end.",
    "strict": True,
    "input_schema": _obj({
        "tracks": {"type": "array", "items": _obj({
            "track_id": _s("e.g. T-1"),
            "classification": _enum(["not a drone", "friendly drone", "unknown drone"], "What it is"),
            "position": _s("Latest best position on the grid, e.g. '(-1650, 520)'"),
            "altitude_m": {"type": "number"},
            "heading_deg": {"type": "number"},
            "speed_mps": {"type": "number"},
            "sensors_reporting": _LIST,
            "confidence": _enum(["HIGH", "MEDIUM", "LOW"], "Track confidence (ROE-2.5)"),
            "pid": {"type": "boolean", "description": "Positive identification (ROE-2.3)"},
            "pvid": {"type": "boolean", "description": "Positive visual identification (ROE-2.4)"},
        })},
        "threat_level": _enum(["NONE", "LOW", "MEDIUM", "HIGH", "CRITICAL"], "ROE-3.1"),
        "indicators_up": {**_LIST, "description": "Indicators that raise the threat (ROE-3.2)"},
        "indicators_down": {**_LIST, "description": "Indicators that lower the threat (ROE-3.3)"},
        "recommended_rung": {"type": "integer", "description": "0-6 on the escalation ladder (ROE-4.1)"},
        "recommended_action": _s("The recommended action in plain words"),
        "options": {"type": "array", "items": _obj({
            "option": _enum(["D-JAM", "D-INT", "D-LAS", "D-GUN"], "Defeat option"),
            "status": _enum(["ALLOWED", "BLOCKED", "NOT NEEDED"], "Status now"),
            "reasons": _s("Every reason, each with its ID"),
            "citations": _LIST,
        })},
        "notifications": {"type": "array", "items": _obj({"who": _s("Who to notify"),
                                                          "why": _s("Why, with the ROE-6 rule")})},
        "confidence": _enum(["HIGH", "MEDIUM", "LOW"], "Confidence in the recommendation"),
        "what_would_change": _s("New information that would change the recommendation"),
        "citations": _CITES,
    }),
}

SUBMIT_REVIEW = {
    "name": "submit_review",
    "description": "Submit your independent review of the analyst's proposal. Call exactly once, at the end.",
    "strict": True,
    "input_schema": _obj({
        "own_assessment": _s("Your brief independent view, written before comparing: track picture, "
                             "threat level, which options are allowed"),
        "verdict": _enum(["APPROVE", "REJECT"], "APPROVE or REJECT the recommended action"),
        "discrepancies": {"type": "array", "items": _obj({
            "issue": _s("What the analyst got wrong or missed"),
            "correct_fact": _s("The correct fact"),
            "citations": _LIST,
        })},
        "reasons": _s("Why you approve or reject"),
        "would_accept": _s("If rejecting: what you would accept instead. Otherwise empty."),
        "notes": _s("Minor issues; any view that a stronger response is justified"),
        "citations": _CITES,
    }),
}

SUBMIT_ADVICE = {
    "name": "submit_advice",
    "description": "Submit your advice to the control room. Call exactly once, at the end.",
    "strict": True,
    "input_schema": _obj({
        "advice": _enum(["CONCUR", "CONCUR WITH CAUTIONS", "RECOMMEND STOP"], "Your advice"),
        "new_information": {"type": "array", "items": _obj({
            "control_room_id": _s("C-xx"),
            "info": _s("What it says and why it matters"),
        })},
        "pvid_status": _s("For laser or gun: whether the control room has PVID, and from what source. "
                          "Otherwise 'not applicable'."),
        "override_assessment": _s("If the operator overrode: operator's reason vs. reviewer's reasons. "
                                  "Otherwise 'no override'."),
        "concerns": _s("Specific risks for the control room to watch"),
        "safer_alternative": _s("A safer response that would still work, if one exists"),
        "citations": _CITES,
    }),
}
