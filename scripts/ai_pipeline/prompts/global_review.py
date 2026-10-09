"""
Prompt templates for Phase 5 — Global Review.

Goal: Cross-chunk consistency check, terminology unification,
summary generation, and topic index generation.
"""

GLOBAL_REVIEW_SYSTEM = """You are a senior academic editor reviewing a complete set of lecture notes. Your job is to ensure consistency, correctness, and completeness across all teaching units.

## YOUR TASKS

1. **Check for contradictions** — Does section 5 contradict section 2? Flag it.
2. **Unify terminology** — If the same concept is called different names across sections, pick the canonical term.
3. **Identify gaps** — Any chunk that seems too thin? Any concept introduced but never explained?
4. **Cross-reference** — Add "see Section X" annotations where concepts build on earlier material.
5. **Generate global summary** — 3-5 key takeaways that span the ENTIRE lesson (not just one section).
6. **Generate topic index** — Timestamp + topic + section mapping.

## FORMAT

Return ONLY valid JSON matching the schema below."""


GLOBAL_REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "contradictions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "section_a": {"type": "integer"},
                    "section_b": {"type": "integer"},
                    "issue": {"type": "string"},
                    "resolution": {"type": "string"},
                },
                "required": ["section_a", "section_b", "issue"],
            },
            "description": "Any contradictions found between sections",
        },
        "terminology_fixes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "section_index": {"type": "integer"},
                    "original_term": {"type": "string"},
                    "canonical_term": {"type": "string"},
                },
                "required": ["section_index", "original_term", "canonical_term"],
            },
            "description": "Terminology standardization across sections",
        },
        "gaps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "section_index": {"type": "integer"},
                    "description": {"type": "string"},
                    "suggested_fix": {"type": "string"},
                },
                "required": ["section_index", "description"],
            },
            "description": "Identified gaps or thin coverage",
        },
        "cross_references": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "from_section": {"type": "integer"},
                    "to_section": {"type": "integer"},
                    "note": {"type": "string"},
                },
                "required": ["from_section", "to_section", "note"],
            },
            "description": "Cross-references between sections",
        },
        "global_takeaways": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 3,
            "maxItems": 5,
            "description": "3-5 key takeaways spanning the entire lesson",
        },
        "global_pitfalls": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Common pitfalls that span multiple sections",
        },
        "overview": {
            "type": "string",
            "description": "One-paragraph overview of what this entire lesson covers",
        },
        "review_steps": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 2,
            "maxItems": 5,
            "description": "Recommended review steps in order",
        },
    },
    "required": ["contradictions", "terminology_fixes", "gaps", "cross_references", "global_takeaways", "global_pitfalls", "overview", "review_steps"],
}


def build_global_review_prompt(
    section_summaries: str,
    course_title: str = "",
    lesson_title: str = "",
    total_sections: int = 0,
    total_duration_minutes: float = 0.0,
) -> str:
    """Build the user prompt for global review.

    Args:
        section_summaries: Concatenated summaries of all sections
                           (title + emphasis_points + keywords per section).
        course_title: Course name.
        lesson_title: Lesson name.
        total_sections: Number of teaching units.
        total_duration_minutes: Total lecture duration.
    """
    context = f"Course: {course_title}\n" if course_title else ""
    if lesson_title:
        context += f"Lesson: {lesson_title}\n"
    context += f"Sections: {total_sections}\n"
    if total_duration_minutes > 0:
        context += f"Total duration: {total_duration_minutes:.0f} minutes\n"

    return f"""{context}
## SECTION SUMMARIES

{section_summaries}

## INSTRUCTIONS

Review all sections above as a complete lecture. Identify:
1. Any contradictions between sections
2. Terminology that needs standardization
3. Gaps in coverage
4. Cross-references between related sections
5. 3-5 global takeaways
6. Common pitfalls that span sections
7. A one-paragraph overview
8. Recommended review steps

Return the structured JSON."""
