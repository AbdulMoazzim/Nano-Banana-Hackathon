"""Map a validated waste category to general disposal guidance."""

from typing import Any

GUIDANCE: dict[str, str] = {
    "plastic": "Check the item and resin type against your local recycling rules; empty and rinse when practical.",
    "paper_cardboard": "Keep clean and dry, then place in paper/cardboard recycling where accepted.",
    "metal": "Empty and rinse when practical; use metal recycling where accepted.",
    "glass": "Separate by local rules; some programs accept glass containers while others do not.",
    "organic": "Use food-scrap or garden-waste collection where available; otherwise follow local waste guidance.",
    "general": "Place in residual waste unless local guidance identifies a safer or more suitable route.",
    "electronic": "Use an approved e-waste collection point; do not place batteries or electronics in general recycling.",
    "unknown": "The material is uncertain. Check local guidance or ask a waste professional before sorting.",
}

PREPARATION_STEPS: dict[str, list[str]] = {
    "plastic": ["Empty all liquid or food residue.", "Rinse thoroughly.", "Replace cap if accepted locally."],
    "paper_cardboard": ["Flatten boxes to save space.", "Ensure material is clean and dry.", "Remove plastic tape or liners."],
    "metal": ["Empty and rinse thoroughly.", "Do not crush cans if automated sorting requires intact shape."],
    "glass": ["Rinse clean.", "Remove non-glass caps or corks.", "Avoid breaking glass."],
    "organic": ["Remove any plastic stickers or packaging.", "Place in compost or organic waste bin."],
    "general": ["Bag securely to prevent litter.", "Dispose in general waste bin."],
    "electronic": ["Remove batteries if detachable.", "Take to designated e-waste drop-off."],
    "unknown": ["Consult municipal waste guidelines before sorting."],
}

WARNINGS: dict[str, list[str]] = {
    "plastic": ["Local recycling capabilities vary significantly by plastic resin code.", "Do not recycle soft plastic film in curbside bins unless accepted."],
    "paper_cardboard": ["Greasy or food-soiled cardboard cannot be recycled."],
    "metal": ["Aerosol cans and hazardous material containers require special disposal."],
    "glass": ["Do not mix ceramics, lightbulbs, or window glass with food/beverage container glass."],
    "organic": ["Do not include plastic, treated wood, or animal waste unless permitted."],
    "general": ["Check if hazardous or electronic items can be diverted from landfill."],
    "electronic": ["Never place lithium batteries or electronics in standard household recycling."],
    "unknown": ["When in doubt, dispose in general waste or contact your local recycling center."],
}


def guidance_for(category: str) -> str:
    """Return cautious, non-location-specific guidance for a category."""
    return GUIDANCE.get(category, GUIDANCE["unknown"])


def decision_for(category: str) -> dict[str, Any]:
    """Return deterministic disposal decision, guidance, steps, and warnings."""
    cat = category if category in GUIDANCE else "unknown"
    return {
        "category": cat,
        "disposal_guidance": GUIDANCE.get(cat, GUIDANCE["unknown"]),
        "preparation_steps": PREPARATION_STEPS.get(cat, PREPARATION_STEPS["unknown"]),
        "warnings": WARNINGS.get(cat, WARNINGS["unknown"]),
    }

