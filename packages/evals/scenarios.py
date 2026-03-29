from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta


DEFAULT_SCENARIO_SEEDS: tuple[int, ...] = (11, 23, 37, 53)


@dataclass(frozen=True)
class ScenarioEvent:
    text: str
    day_offset: int
    importance: float


@dataclass(frozen=True)
class Scenario:
    name: str
    family_name: str
    agent_id: str
    seed: int
    events: list[ScenarioEvent]
    query: str
    query_day_offset: int
    expected_keywords: list[str]
    expected_slots: dict[str, list[str]]
    notes: list[str]
    preferred_mode: str = "balanced"


def _scenario_id(family_name: str, seed: int) -> str:
    return f"{family_name}__seed_{seed}"


def _agent_id(family_name: str, seed: int) -> str:
    return f"benchmark-agent-{family_name.replace('_', '-')}-seed-{seed}"


def _flatten_keywords(slot_values: dict[str, list[str]], extras: list[str]) -> list[str]:
    keywords: list[str] = []
    for values in slot_values.values():
        for value in values:
            lowered = value.lower()
            if lowered not in keywords:
                keywords.append(lowered)
    for extra in extras:
        lowered = extra.lower()
        if lowered not in keywords:
            keywords.append(lowered)
    return keywords


def delayed_commitment_scenario(seed: int) -> Scenario:
    rng = random.Random(seed)
    person = rng.choice(["Maria", "Nadia", "Leah", "Priya"])
    item = rng.choice(["finished prototype", "demo kit", "research brief", "launch deck"])
    event = rng.choice(["Simile AI demo", "partner review", "investor showcase", "Friday product demo"])
    routine_templates = [
        "reviewed dashboard metrics and ate lunch at the office",
        "worked through tickets and checked the sprint board",
        "cleared email, joined standup, and reviewed the roadmap board",
        "handled routine code review and backlog grooming",
    ]
    routine = [
        ScenarioEvent(
            text=f"Day {day} routine: {rng.choice(routine_templates)}.",
            day_offset=day,
            importance=0.2,
        )
        for day in range(2, 14)
    ]
    key_events = [
        ScenarioEvent(
            text=f"Met {person} and promised to bring the {item} to the {event}.",
            day_offset=1,
            importance=0.95,
        ),
        ScenarioEvent(
            text=f"Wrote a prep checklist for meeting {person} at the {event}: pack the {item}, badge, and charger.",
            day_offset=1,
            importance=0.72,
        ),
        ScenarioEvent(
            text=f"Packed presentation notes for the {event} but did not restate the promise to {person}.",
            day_offset=10,
            importance=0.35,
        ),
    ]
    expected_slots = {
        "person": [person.lower()],
        "item": [item.lower()],
        "event": [event.lower()],
        "action": ["bring"],
        "commitment": ["promised"],
    }
    return Scenario(
        name=_scenario_id("delayed_commitment", seed),
        family_name="delayed_commitment",
        agent_id=_agent_id("delayed_commitment", seed),
        seed=seed,
        events=sorted(key_events + routine, key=lambda item: item.day_offset),
        query=f"What commitment did I make to {person} about the {event}?",
        query_day_offset=14,
        expected_keywords=_flatten_keywords(expected_slots, []),
        expected_slots=expected_slots,
        notes=["Long-horizon recall after many irrelevant routines."],
    )


def routine_interruption_scenario(seed: int) -> Scenario:
    rng = random.Random(seed)
    person = rng.choice(["Jordan", "Noah", "Mina", "Theo"])
    conflict_issue = rng.choice(["missed handoff", "dropped approval", "broken dependency", "missed review"])
    routine_texts = [
        "coffee, standup, email triage",
        "coffee, standup, backlog grooming",
        "coffee, standup, roadmap updates",
        "coffee, standup, sprint planning",
    ]
    events = [
        ScenarioEvent(text=f"Morning routine: {routine_texts[0]}.", day_offset=1, importance=0.15),
        ScenarioEvent(text=f"Morning routine: {routine_texts[1]}.", day_offset=2, importance=0.15),
        ScenarioEvent(
            text=f"Had a tense argument with {person} about a {conflict_issue} and agreed to repair trust tomorrow.",
            day_offset=3,
            importance=0.92,
        ),
        ScenarioEvent(text=f"Morning routine: {routine_texts[2]}.", day_offset=4, importance=0.15),
        ScenarioEvent(text=f"Morning routine: {routine_texts[3]}.", day_offset=5, importance=0.15),
    ]
    expected_slots = {
        "person": [person.lower()],
        "conflict": ["argument"],
        "consequence": ["trust"],
    }
    return Scenario(
        name=_scenario_id("routine_interruption", seed),
        family_name="routine_interruption",
        agent_id=_agent_id("routine_interruption", seed),
        seed=seed,
        events=events,
        query="What major conflict happened recently and with whom?",
        query_day_offset=6,
        expected_keywords=_flatten_keywords(expected_slots, []),
        expected_slots=expected_slots,
        notes=["Rare pivotal event should survive routine repetition."],
    )


def relationship_context_scenario(seed: int) -> Scenario:
    rng = random.Random(seed)
    person = rng.choice(["Avery", "Mina", "Theo", "Sasha"])
    preference_pairs = [
        ("direct feedback", "surprise meetings", "in writing ahead of time"),
        ("clear agendas", "last-minute changes", "with explicit bullet points in advance"),
        ("concise updates", "rambling status calls", "as a short written summary"),
        ("blunt feedback", "soft hints", "as written expectations before the meeting"),
    ]
    preferred_style, disliked_style, strategy = rng.choice(preference_pairs)
    routine = [
        ScenarioEvent(
            text=f"Day {day} routine: {rng.choice(['worked through tickets and checked the sprint board', 'handled docs cleanup and backlog grooming', 'reviewed dashboards and closed small tasks'])}.",
            day_offset=day,
            importance=0.2,
        )
        for day in range(2, 10)
    ]
    events = [
        ScenarioEvent(
            text=f"Had coffee with {person} and learned that {person} prefers {preferred_style} and hates {disliked_style}.",
            day_offset=1,
            importance=0.82,
        ),
        ScenarioEvent(
            text=f"Reflected that communication with {person} works best when expectations are sent {strategy}.",
            day_offset=1,
            importance=0.86,
        ),
        ScenarioEvent(
            text=f"Prepared tomorrow's agenda for {person} with explicit bullet points and no surprise additions.",
            day_offset=8,
            importance=0.58,
        ),
    ]
    expected_slots = {
        "person": [person.lower()],
        "preference": [preferred_style.lower()],
        "avoid": [disliked_style.lower()],
        "strategy": [strategy.lower()],
    }
    return Scenario(
        name=_scenario_id("relationship_context", seed),
        family_name="relationship_context",
        agent_id=_agent_id("relationship_context", seed),
        seed=seed,
        events=sorted(events + routine, key=lambda item: item.day_offset),
        query=f"How should I communicate with {person} based on what I know about them?",
        query_day_offset=10,
        expected_keywords=_flatten_keywords(expected_slots, []),
        expected_slots=expected_slots,
        notes=["Relationship context should remain recoverable as actionable guidance."],
    )


def commitment_revision_scenario(seed: int) -> Scenario:
    rng = random.Random(seed)
    artifact = rng.choice(["prototype", "release candidate", "briefing deck", "demo build"])
    old_day, new_day = rng.choice(
        [("Thursday", "Friday"), ("Tuesday", "Wednesday"), ("Wednesday", "Friday"), ("Monday", "Tuesday")]
    )
    qualifier = rng.choice(["after extra QA", "after final QA", "after partner review", "after the last validation pass"])
    events = [
        ScenarioEvent(text=f"Committed to shipping the {artifact} on {old_day}.", day_offset=1, importance=0.9),
        ScenarioEvent(text=f"Reflected that the {old_day} deadline is risky but still the plan.", day_offset=2, importance=0.75),
        ScenarioEvent(text=f"Updated the plan: the {artifact} will ship on {new_day} {qualifier}.", day_offset=4, importance=0.95),
        ScenarioEvent(text=f"Told the team that {new_day} is the correct launch date now.", day_offset=5, importance=0.88),
        ScenarioEvent(text="Routine work: code review, standup, lunch.", day_offset=6, importance=0.15),
        ScenarioEvent(text="Routine work: docs cleanup and backlog grooming.", day_offset=7, importance=0.15),
    ]
    expected_slots = {
        "artifact": [artifact.lower()],
        "ship_day": [new_day.lower()],
        "qualifier": [qualifier.lower()],
    }
    return Scenario(
        name=_scenario_id("commitment_revision", seed),
        family_name="commitment_revision",
        agent_id=_agent_id("commitment_revision", seed),
        seed=seed,
        events=events,
        query=f"When is the {artifact} actually supposed to ship now?",
        query_day_offset=8,
        expected_keywords=_flatten_keywords(expected_slots, ["launch"]),
        expected_slots=expected_slots,
        notes=["Later corrective evidence should dominate outdated commitments."],
    )


def identity_shift_scenario(seed: int) -> Scenario:
    rng = random.Random(seed)
    old_identity, new_identity, activity, affect = rng.choice(
        [
            ("backend engineer who avoids presenting", "someone who enjoys presenting research demos", "lead the live demo", "energizing"),
            ("quiet implementer who avoids facilitation", "someone who likes facilitating design reviews", "facilitate the next design review", "clarifying"),
            ("individual contributor who avoids public speaking", "someone who now enjoys public speaking", "open the customer demo", "energizing"),
            ("engineer who stays offstage", "someone who likes narrating product demos", "volunteer to narrate the demo", "natural"),
        ]
    )
    routine = [
        ScenarioEvent(
            text=f"Day {day} routine: {rng.choice(['morning run and daily journaling', 'gym session and inbox cleanup', 'daily planning and short journal entry'])}.",
            day_offset=day,
            importance=0.2,
        )
        for day in range(2, 12)
    ]
    events = [
        ScenarioEvent(text=f"Used to identify as a {old_identity}.", day_offset=1, importance=0.7),
        ScenarioEvent(
            text=f"Reflected that I am now {new_identity} and should lean into that role.",
            day_offset=6,
            importance=0.94,
        ),
        ScenarioEvent(
            text=f"Volunteered to {activity} because it now feels {affect}.",
            day_offset=9,
            importance=0.89,
        ),
    ]
    expected_slots = {
        "current_identity": [new_identity.lower()],
        "activity": [activity.lower()],
        "affect": [affect.lower()],
    }
    return Scenario(
        name=_scenario_id("identity_shift", seed),
        family_name="identity_shift",
        agent_id=_agent_id("identity_shift", seed),
        seed=seed,
        events=sorted(events + routine, key=lambda item: item.day_offset),
        query="How do I describe my current relationship to presenting or facilitation?",
        query_day_offset=12,
        expected_keywords=_flatten_keywords(expected_slots, []),
        expected_slots=expected_slots,
        notes=["The system should favor the updated self-model over obsolete self-description."],
    )


SCENARIO_BUILDERS = {
    "delayed_commitment": delayed_commitment_scenario,
    "routine_interruption": routine_interruption_scenario,
    "relationship_context": relationship_context_scenario,
    "commitment_revision": commitment_revision_scenario,
    "identity_shift": identity_shift_scenario,
}


def all_scenarios(seeds: tuple[int, ...] = DEFAULT_SCENARIO_SEEDS) -> list[Scenario]:
    scenarios: list[Scenario] = []
    for family_name, builder in SCENARIO_BUILDERS.items():
        for seed in seeds:
            scenarios.append(builder(seed))
    return scenarios


def get_scenario(name: str, seeds: tuple[int, ...] = DEFAULT_SCENARIO_SEEDS) -> Scenario:
    scenarios = all_scenarios(seeds)
    exact = next((scenario for scenario in scenarios if scenario.name == name), None)
    if exact is not None:
        return exact
    family_match = next((scenario for scenario in scenarios if scenario.family_name == name), None)
    if family_match is not None:
        return family_match
    raise StopIteration(name)


def base_time() -> datetime:
    return datetime(2025, 1, 1, 9, 0, 0)


def scenario_timestamp(day_offset: int) -> datetime:
    return base_time() + timedelta(days=day_offset)
