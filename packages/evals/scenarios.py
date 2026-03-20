from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class ScenarioEvent:
    text: str
    day_offset: int
    importance: float


@dataclass(frozen=True)
class Scenario:
    name: str
    agent_id: str
    events: list[ScenarioEvent]
    query: str
    query_day_offset: int
    expected_keywords: list[str]
    notes: list[str]
    preferred_mode: str = "balanced"


def delayed_commitment_scenario() -> Scenario:
    routine = [
        ScenarioEvent(text=f"Day {day} routine: reviewed dashboard metrics and ate lunch at the office.", day_offset=day, importance=0.2)
        for day in range(2, 14)
    ]
    key_events = [
        ScenarioEvent(
            text="Met Maria and promised to bring the finished item to the Friday Simile AI demo.",
            day_offset=1,
            importance=0.95,
        ),
        ScenarioEvent(
            text="Planned that the promised item for Maria is the finished prototype for Friday.",
            day_offset=1,
            importance=0.9,
        ),
        ScenarioEvent(
            text="Packed notes for the presentation but did not revisit the original promise explicitly.",
            day_offset=10,
            importance=0.35,
        ),
    ]
    return Scenario(
        name="delayed_commitment",
        agent_id="benchmark-agent-delayed-commitment",
        events=sorted(key_events + routine, key=lambda item: item.day_offset),
        query="What did I promise Maria to bring for the Simile AI demo?",
        query_day_offset=14,
        expected_keywords=["maria", "prototype", "demo", "promised"],
        notes=["Long-horizon recall after many irrelevant routines."],
    )


def routine_interruption_scenario() -> Scenario:
    events = [
        ScenarioEvent(text="Morning routine: coffee, standup, email triage.", day_offset=1, importance=0.15),
        ScenarioEvent(text="Morning routine: coffee, standup, backlog grooming.", day_offset=2, importance=0.15),
        ScenarioEvent(
            text="Had a tense argument with Jordan about a missed handoff and agreed to repair trust tomorrow.",
            day_offset=3,
            importance=0.92,
        ),
        ScenarioEvent(text="Morning routine: coffee, standup, roadmap updates.", day_offset=4, importance=0.15),
        ScenarioEvent(text="Morning routine: coffee, standup, sprint planning.", day_offset=5, importance=0.15),
    ]
    return Scenario(
        name="routine_interruption",
        agent_id="benchmark-agent-routine-interruption",
        events=events,
        query="What major conflict happened recently and with whom?",
        query_day_offset=6,
        expected_keywords=["argument", "jordan", "trust"],
        notes=["Rare pivotal event should survive routine repetition."],
    )


def relationship_context_scenario() -> Scenario:
    routine = [
        ScenarioEvent(text=f"Day {day} routine: worked through tickets and checked the sprint board.", day_offset=day, importance=0.2)
        for day in range(2, 10)
    ]
    events = [
        ScenarioEvent(
            text="Had coffee with Avery and learned that Avery prefers direct feedback and hates surprise meetings.",
            day_offset=1,
            importance=0.82,
        ),
        ScenarioEvent(
            text="Reflected that communication with Avery works best when expectations are sent in writing ahead of time.",
            day_offset=1,
            importance=0.86,
        ),
        ScenarioEvent(
            text="Prepared tomorrow's agenda for Avery with explicit bullet points and no surprise additions.",
            day_offset=8,
            importance=0.58,
        ),
    ]
    return Scenario(
        name="relationship_context",
        agent_id="benchmark-agent-relationship-context",
        events=sorted(events + routine, key=lambda item: item.day_offset),
        query="How should I communicate with Avery based on what I know about them?",
        query_day_offset=10,
        expected_keywords=["avery", "direct", "writing", "surprise"],
        notes=["Relationship context should remain recoverable as actionable guidance."],
    )


def commitment_revision_scenario() -> Scenario:
    events = [
        ScenarioEvent(text="Committed to shipping the prototype on Thursday.", day_offset=1, importance=0.9),
        ScenarioEvent(text="Reflected that the Thursday deadline is risky but still the plan.", day_offset=2, importance=0.75),
        ScenarioEvent(text="Updated the plan: the prototype will ship on Friday after extra QA.", day_offset=4, importance=0.95),
        ScenarioEvent(text="Told the team that Friday is the correct launch date now.", day_offset=5, importance=0.88),
        ScenarioEvent(text="Routine work: code review, standup, lunch.", day_offset=6, importance=0.15),
        ScenarioEvent(text="Routine work: docs cleanup and backlog grooming.", day_offset=7, importance=0.15),
    ]
    return Scenario(
        name="commitment_revision",
        agent_id="benchmark-agent-commitment-revision",
        events=events,
        query="When is the prototype actually supposed to ship now?",
        query_day_offset=8,
        expected_keywords=["friday", "qa", "launch"],
        notes=["Later corrective evidence should dominate outdated commitments."],
    )


def identity_shift_scenario() -> Scenario:
    routine = [
        ScenarioEvent(text=f"Day {day} routine: morning run and daily journaling.", day_offset=day, importance=0.2)
        for day in range(2, 12)
    ]
    events = [
        ScenarioEvent(text="Used to identify as a backend engineer who avoids presenting.", day_offset=1, importance=0.7),
        ScenarioEvent(text="Reflected that I now enjoy presenting research demos and should lean into that role.", day_offset=6, importance=0.94),
        ScenarioEvent(text="Volunteered to lead the live demo because presenting now feels energizing.", day_offset=9, importance=0.89),
    ]
    return Scenario(
        name="identity_shift",
        agent_id="benchmark-agent-identity-shift",
        events=sorted(events + routine, key=lambda item: item.day_offset),
        query="How do I describe my current relationship to presenting?",
        query_day_offset=12,
        expected_keywords=["presenting", "enjoy", "demo", "energizing"],
        notes=["The system should favor the updated self-model over obsolete self-description."],
    )


def all_scenarios() -> list[Scenario]:
    return [
        delayed_commitment_scenario(),
        routine_interruption_scenario(),
        relationship_context_scenario(),
        commitment_revision_scenario(),
        identity_shift_scenario(),
    ]


def base_time() -> datetime:
    return datetime(2025, 1, 1, 9, 0, 0)


def scenario_timestamp(day_offset: int) -> datetime:
    return base_time() + timedelta(days=day_offset)
