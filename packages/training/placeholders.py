from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TrainingArtifact:
    name: str
    objective: str
    status: str = "planned"


def planned_modules() -> list[TrainingArtifact]:
    return [
        TrainingArtifact(name="retriever_encoder", objective="Contrastive relevance training for query-node retrieval."),
        TrainingArtifact(name="retrieval_router", objective="Policy for summary-only vs drill-down retrieval under token budgets."),
        TrainingArtifact(name="summary_verifier", objective="Classify faithful vs unsupported vs contradicted summaries."),
        TrainingArtifact(name="summarizer_distillation", objective="Distill prompt summarization into a compact model after the verifier is stable."),
    ]

