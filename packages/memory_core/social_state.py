from __future__ import annotations

"""Derived social-state digest helpers
Builds provenance-first summaries of commitments revisions guidance and tensions"""

from dataclasses import dataclass
from datetime import datetime

from packages.schemas.models import MemoryNode, MemoryLevel, NodeType, SocialStateDigestResponse, SocialStateItem


REVISION_MARKERS = (
    "changed the plan",
    "now ",
    "moved from",
    "actually",
    "current",
    "revision",
    "correct",
    "final deliverable",
    "ship on",
)

GUIDANCE_MARKERS = (
    "works best",
    "prefers",
    "avoid",
    "comfortable",
    "communication thread",
    "collaboration thread",
    "written expectations",
    "day-of surprises",
)

TENSION_MARKERS = (
    "risk",
    "uneasy",
    "failed intermittently",
    "tension",
    "argument",
    "conflict",
    "avoid",
    "do not surprise",
)

ACTION_MARKERS = (
    "follow-up",
    "reminder to myself",
    "added backup plan",
    "send ",
    "bring ",
    "prepare",
    "ownership",
    "handles",
)


@dataclass(frozen=True)
class _Candidate:
    """Internal digest candidate"""
    node: MemoryNode
    text: str
    entity: str | None = None
    label: str | None = None
    confidence: float | None = None


def _node_sort_key(node: MemoryNode) -> tuple[int, float, datetime]:
    """Rank summaries above leaves then newer nodes"""
    level_rank = {
        MemoryLevel.L2: 3,
        MemoryLevel.L1: 2,
        MemoryLevel.L0: 1,
        MemoryLevel.L3: 0,
    }.get(node.level, 0)
    return (level_rank, node.importance_score, node.timestamp_end)


def _support_node_ids(node: MemoryNode) -> list[str]:
    """Prefer support ids when available"""
    return list(node.support_ids) if node.support_ids else [node.node_id]


def _primary_entity(node: MemoryNode) -> str | None:
    """Use the leading entity as the display anchor"""
    return node.entities[0] if node.entities else None


def _dedupe_items(candidates: list[_Candidate], *, limit: int = 4) -> list[SocialStateItem]:
    """Collapse repeated candidates into digest items"""
    seen: set[tuple[str, str | None, str | None]] = set()
    items: list[SocialStateItem] = []
    for candidate in sorted(candidates, key=lambda item: _node_sort_key(item.node), reverse=True):
        key = (candidate.text.strip().lower(), candidate.entity, candidate.label)
        if key in seen:
            continue
        seen.add(key)
        items.append(
            SocialStateItem(
                text=candidate.text,
                support_node_ids=_support_node_ids(candidate.node),
                entity=candidate.entity,
                label=candidate.label,
                confidence=candidate.confidence,
            )
        )
        if len(items) >= limit:
            break
    return items


def _structured_items(nodes: list[MemoryNode], field_name: str, *, label: str | None = None) -> list[_Candidate]:
    """Lift structured fields into candidate rows"""
    candidates: list[_Candidate] = []
    for node in nodes:
        values = getattr(node, field_name)
        for value in values:
            if not value:
                continue
            candidates.append(
                _Candidate(
                    node=node,
                    text=value,
                    entity=_primary_entity(node),
                    label=label,
                )
            )
    return candidates


def _heuristic_commitments(nodes: list[MemoryNode]) -> list[_Candidate]:
    """Infer commitments from plan-like text"""
    candidates: list[_Candidate] = []
    for node in nodes:
        lowered = node.text.lower()
        if "initial plan" in lowered or "obsolete" in lowered:
            continue
        if node.node_type == NodeType.PLAN or ("ownership thread" in lowered) or ("backup plan" in lowered):
            if any(token in lowered for token in ("bring", "send", "present", "backup", "owner", "handles", "signs off", "supports")):
                candidates.append(_Candidate(node=node, text=node.text, entity=_primary_entity(node), label="commitment"))
    return candidates


def _heuristic_revisions(nodes: list[MemoryNode]) -> list[_Candidate]:
    """Infer revisions from update language"""
    candidates: list[_Candidate] = []
    for node in nodes:
        lowered = node.text.lower()
        if any(marker in lowered for marker in REVISION_MARKERS):
            candidates.append(_Candidate(node=node, text=node.text, label="revision"))
    return candidates


def _heuristic_guidance(nodes: list[MemoryNode]) -> list[_Candidate]:
    """Infer guidance from interpersonal cues"""
    candidates: list[_Candidate] = []
    for node in nodes:
        lowered = node.text.lower()
        if any(marker in lowered for marker in GUIDANCE_MARKERS):
            candidates.append(
                _Candidate(
                    node=node,
                    text=node.text,
                    entity=_primary_entity(node),
                    label="guidance",
                )
            )
    return candidates


def _heuristic_tensions(nodes: list[MemoryNode]) -> list[_Candidate]:
    """Infer tensions from risk and conflict cues"""
    candidates: list[_Candidate] = []
    for node in nodes:
        lowered = node.text.lower()
        if any(marker in lowered for marker in TENSION_MARKERS):
            candidates.append(
                _Candidate(
                    node=node,
                    text=node.text,
                    entity=_primary_entity(node),
                    label="tension",
                )
            )
    return candidates


def _heuristic_next_actions(nodes: list[MemoryNode]) -> list[_Candidate]:
    """Infer next actions from plans and reflections"""
    candidates: list[_Candidate] = []
    for node in nodes:
        lowered = node.text.lower()
        if node.node_type in {NodeType.PLAN, NodeType.REFLECTION} and any(marker in lowered for marker in ACTION_MARKERS):
            candidates.append(
                _Candidate(
                    node=node,
                    text=node.text,
                    entity=_primary_entity(node),
                    label="next_action",
                )
            )
    return candidates


def build_social_state_digest(agent_id: str, nodes: list[MemoryNode]) -> SocialStateDigestResponse:
    """Build a digest from current and stale nodes"""
    stale_summary_count = sum(1 for node in nodes if node.stale_flag and node.node_type == NodeType.SUMMARY)
    active_nodes = [node for node in nodes if not node.stale_flag]
    snapshot_at = max((node.timestamp_end for node in active_nodes), default=None)

    # Blend structured fields with lightweight heuristics
    active_commitments = _dedupe_items(
        [
            *_structured_items(active_nodes, "commitments", label="commitment"),
            *_heuristic_commitments(active_nodes),
        ]
    )
    active_revisions = _dedupe_items(
        [
            *_structured_items(active_nodes, "revisions", label="revision"),
            *_heuristic_revisions(active_nodes),
        ]
    )
    relationship_guidance = _dedupe_items(
        [
            *_structured_items(active_nodes, "relationship_guidance", label="guidance"),
            *_heuristic_guidance(active_nodes),
        ]
    )
    open_tensions = _dedupe_items(_heuristic_tensions(active_nodes))
    likely_next_actions = _dedupe_items(
        [
            *_structured_items(active_nodes, "self_model_updates", label="next_action"),
            *_heuristic_next_actions(active_nodes),
        ]
    )

    return SocialStateDigestResponse(
        agent_id=agent_id,
        snapshot_at=snapshot_at,
        active_commitments=active_commitments,
        active_revisions=active_revisions,
        relationship_guidance=relationship_guidance,
        open_tensions=open_tensions,
        likely_next_actions=likely_next_actions,
        stale_summary_count=stale_summary_count,
    )
