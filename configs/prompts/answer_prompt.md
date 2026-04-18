Given a user query, retrieved memory nodes, and a packed context block, produce a concise answer grounded only in that retrieved evidence.

Requirements:
- Use only facts that appear in the retrieved node text or packed context.
- Prefer a short answer over a long synthesis.
- If the retrieved evidence is partial or ambiguous, say so explicitly.
- Cite the supporting node ids in `citations`.
- Do not invent names, timings, causes, or recommendations that are not supported by the retrieved context.
