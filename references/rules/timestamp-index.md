# Timestamp Index Rules

Every final note package must start with a timestamped topic index table before the main body.

## Table Contract

Use this column order:

```markdown
## Video Topic Index

| Timestamp | Topic | Subtopic or Event | Note Section |
|---|---|---|---|
| 00:03:12 | Topic name | Key subtopic | 1.1 |
```
```

## Scope

- Follow the real lecture order.
- Include major topics and important subtopics.
- Add separate rows for examples, demos, or board-derivation starts when they matter for later review.
- For multi-video lessons, create one table per video or clearly label the source clip.

## Timestamp Precision

- Prefer `HH:MM:SS`.
- Allow `MM:SS` for short clips.
- If only an approximate point is known, write `Approx. 00:12:00`.
- Never invent false precision.

## Mapping Rule

The `Note Section` column must point to the section identifier used later in the Markdown body.
