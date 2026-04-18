Given a summary and its supporting memories, return a structured verification result with:
- `quality_status`: one of `verified`, `unsupported`, or `contradicted`
- `unsupported_claims`
- `contradictions`
- `omissions`
- `scores`

Temporal evidence policy:
- Relative order counts as real evidence.
  Example: "this happened before the demo"
- Coarse time usually counts as evidence.
  Example: same day, same morning, same week, recent vs old
- Exact date/time strings only count as hard evidence if they are explicit in the supporting memory text.
- Timestamp metadata on the support objects is soft evidence for ordering and coarse temporal reasoning, but it is not a canonical exact-fact source for clock times.
- If the summary introduces exact temporal precision that the support text does not explicitly state, treat that as `unsupported`, not `contradicted`.

Verification guidance:
- Use support text first for literal fact checking.
- Use timestamp metadata only for sequence, recency, and coarse temporal buckets.
- Do not penalize a summary merely because it uses a relative or coarse temporal phrase that is compatible with the support timestamps.
- Only use `contradicted` when the supports directly conflict with the summary.
