"""
Evaluation framework for AI pipeline output.

Currently covers:
- Emphasis extraction eval: precision/recall/F1 per chunk vs human ground truth
- Failure mode classification: hallucination, miss, partial, wrong_section
- LLM-as-judge option for semantic comparison (fallback: n-gram Jaccard)
"""
