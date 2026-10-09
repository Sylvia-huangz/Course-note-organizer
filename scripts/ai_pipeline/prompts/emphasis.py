"""
Prompt templates for Phase 3 — Emphasis Extraction.

Goal: Extract what the teacher EMPHASIZED (not just what they said).
This is the core intelligence of the dual-column format.
"""

EMPHASIS_SYSTEM = """You are an expert at identifying what teachers consider important in their lectures. Your job is to extract emphasis signals from a cleaned lecture narrative and produce structured teaching points.

## WHAT "EMPHASIS" MEANS

A point is "emphasized" when the teacher signals its importance through:
- **Explicit markers**: "this is important", "remember this", "this will be on the exam", "关键是", "重点是", "一定要记住", "考试会考"
- **Repetition**: saying the same thing multiple times in different ways
- **Slow-down**: spending disproportionate time on one concept
- **Examples given**: concepts the teacher bothers to illustrate with examples
- **Pitfall warnings**: "don't confuse X with Y", "common mistake", "很多人会犯这个错", "注意"
- **Contrast/comparison**: explicitly distinguishing two concepts

## OUTPUT RULES

1. **emphasis_points** (3-5 items): What the teacher WANTS you to remember. Not a summary of content — it's a summary of teacher INTENT.
   - Each point should be actionable: something the student should know, do, or avoid.
   - Order by importance (most emphasized first).

2. **pitfalls** (0-3 items): Common mistakes or misconceptions the teacher warned about.
   - Only include if the teacher explicitly warned about them.
   - Empty list if no pitfalls were mentioned.

3. **keywords** (5-8 items): Key technical terms from this segment.
   - Include both Chinese and English terms as used by the teacher.
   - These are retrieval/indexing terms.

4. **question** (1 item): A review question that tests understanding of the MAIN point.
   - NOT a trivia question. Should require understanding, not just recall.
   - If the segment doesn't warrant a deep question, ask about the main concept.

## FORMAT

Return ONLY valid JSON matching the schema. No markdown, no preamble."""


EMPHASIS_SCHEMA = {
    "type": "object",
    "properties": {
        "emphasis_points": {
            "type": "array",
            "items": {"type": "string"},
            "description": "3-5 key points the teacher emphasized, in importance order",
        },
        "pitfalls": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Common mistakes or misconceptions warned about (0-3)",
        },
        "keywords": {
            "type": "array",
            "items": {"type": "string"},
            "description": "5-8 key technical terms for indexing",
        },
        "question": {
            "type": "string",
            "description": "One review question testing understanding of the main point",
        },
        "confidence": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
            "description": "How confident are you in this extraction? Lower if the transcript is noisy or ambiguous.",
        },
    },
    "required": ["emphasis_points", "pitfalls", "keywords", "question", "confidence"],
}


def build_emphasis_prompt(
    cleaned_narrative: str,
    raw_transcript: str = "",
    emphasis_signals: list[str] | None = None,
    course_title: str = "",
    section_title: str = "",
) -> str:
    """Build the user prompt for emphasis extraction.

    Args:
        cleaned_narrative: Phase 2 output (clean teacher narrative).
        raw_transcript: Original raw transcript for tone/pacing clues.
        emphasis_signals: Pre-detected emphasis signals (from rule-based analysis).
        course_title: Course name for context.
        section_title: Section name for context.
    """
    context = ""
    if course_title or section_title:
        context = f"Course: {course_title}\n"
        if section_title:
            context += f"Section: {section_title}\n"
        context += "\n"

    signals_block = ""
    if emphasis_signals:
        signals_block = "## DETECTED EMPHASIS SIGNALS\n"
        signals_block += "These signals were automatically detected and may help you identify emphasized points:\n"
        for signal in emphasis_signals:
            signals_block += f"- {signal}\n"
        signals_block += "\n"

    raw_block = ""
    if raw_transcript:
        raw_block = f"""## RAW TRANSCRIPT (for tone/pacing reference)
{raw_transcript[:3000]}

"""

    return f"""{context}Extract what the teacher EMPHASIZED in this lecture segment.

## CLEANED NARRATIVE

{cleaned_narrative}

{raw_block}{signals_block}
Return the structured emphasis data as JSON."""
