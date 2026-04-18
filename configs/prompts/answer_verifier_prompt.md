Given an answer and its supporting memories, return a structured verification result with:
- `quality_status`: one of `verified`, `unsupported`, or `contradicted`
- `unsupported_claims`
- `contradictions`
- `omissions`
- `scores`

Answer verification guidance:
- Judge the answer against the support text first.
- Treat relative order and coarse timing as valid evidence when the support timestamps and text are compatible.
- Treat exact date/time strings as hard evidence only when they are explicit in the support text.
- Mark unsupported details as `unsupported`, not `contradicted`, unless the support text directly conflicts.
- If the answer is cautious and explicitly limited by the retrieved evidence, prefer `verified`.
