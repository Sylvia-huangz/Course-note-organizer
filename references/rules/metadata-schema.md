# Metadata Schema

Append a visible JSON code block to every final note package.

## Minimum Fields

```json
{
  "course_title": "Thermodynamics",
  "lesson_title": "Second Law and Entropy",
  "keywords": ["entropy", "heat engine", "reversible process"],
  "core_concepts": ["Second law statement", "entropy balance"],
  "formulas": ["\\Delta S = \\int \\frac{\\delta Q_{rev}}{T}"],
  "estimated_review_time_minutes": 35,
  "timeline_topics": [
    {
      "timestamp": "00:12:48",
      "topic": "Entropy definition"
    }
  ],
  "exam_assignment_relevance": [
    "Upcoming quiz references the Second Law module."
  ],
  "repair_annotations_present": true
}
```

## Field Semantics

- `keywords`: short retrieval terms
- `core_concepts`: the concepts the learner should retain
- `formulas`: canonical formulas mentioned in the lesson
- `estimated_review_time_minutes`: realistic time to review the note
- `timeline_topics`: lightweight machine-readable mirror of the timestamp index
- `exam_assignment_relevance`: brief notes derived from Canvas context when relevant
- `repair_annotations_present`: true when context-assisted or transcript-assisted repairs appear in the note

## NotebookLM Guidance

Keep the metadata visible and explicit. NotebookLM and downstream agents can consume the summary plus this JSON block without re-parsing the full note body.
