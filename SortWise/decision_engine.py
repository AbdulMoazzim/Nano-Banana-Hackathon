"""Map a validated waste category to general disposal guidance."""

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


def guidance_for(category: str) -> str:
    """Return cautious, non-location-specific guidance for a category."""
    return GUIDANCE.get(category, GUIDANCE["unknown"])
