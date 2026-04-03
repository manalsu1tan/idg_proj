from __future__ import annotations

import random
from dataclasses import dataclass, replace
from datetime import datetime, timedelta


DEFAULT_SCENARIO_SEEDS: tuple[int, ...] = (11, 23, 37, 53)
QUERY_PARAPHRASE_STYLES: tuple[str, ...] = ("concise", "indirect", "colloquial")
QUERY_PERTURBATION_STYLES: tuple[str, ...] = (
    *QUERY_PARAPHRASE_STYLES,
    "typo_noise",
    "word_order",
    "entity_swap_distractor",
)


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
            text=f"Met {person} and promised I would bring it for their upcoming request.",
            day_offset=1,
            importance=0.95,
        ),
        ScenarioEvent(
            text=f"Follow-up note: for the {event}, the item to bring is the {item}.",
            day_offset=1,
            importance=0.9,
        ),
        ScenarioEvent(
            text=f"Draft rehearsal checklist mentioned a placeholder kit for internal dry run, not the external meeting.",
            day_offset=4,
            importance=0.3,
        ),
        ScenarioEvent(
            text=f"Packed presentation notes for the {event} but did not restate the promise terms.",
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
        query=f"For the {event}, which item did I commit to bringing for {person}?",
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
            text=f"Had a tense argument with {person} about a {conflict_issue}.",
            day_offset=3,
            importance=0.92,
        ),
        ScenarioEvent(
            text="After cooling down, wrote a note to repair trust tomorrow.",
            day_offset=3,
            importance=0.88,
        ),
        ScenarioEvent(
            text="Minor disagreement about lunch timing came up in a separate team chat.",
            day_offset=4,
            importance=0.22,
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


def temporal_override_chain_scenario(seed: int) -> Scenario:
    rng = random.Random(seed)
    artifact = rng.choice(["prototype", "demo build", "briefing deck", "release candidate"])
    d1, d2, d3 = rng.choice(
        [("Tuesday", "Wednesday", "Friday"), ("Monday", "Thursday", "Friday"), ("Wednesday", "Thursday", "Saturday")]
    )
    reason = rng.choice(["after final QA", "after partner sign-off", "after validation passes"])
    events = [
        ScenarioEvent(text=f"Initial plan: ship the {artifact} on {d1}.", day_offset=1, importance=0.72),
        ScenarioEvent(text=f"Revision: move the {artifact} to {d2} due to blocker triage.", day_offset=3, importance=0.78),
        ScenarioEvent(text=f"Final decision: ship the {artifact} on {d3} {reason}.", day_offset=6, importance=0.95),
        ScenarioEvent(text=f"Shared with the team that {d3} is now the canonical launch date.", day_offset=7, importance=0.88),
        ScenarioEvent(text="Routine work: standup, docs cleanup, and inbox triage.", day_offset=8, importance=0.2),
    ]
    expected_slots = {
        "artifact": [artifact.lower()],
        "ship_day": [d3.lower()],
        "reason": [reason.lower()],
    }
    return Scenario(
        name=_scenario_id("temporal_override_chain", seed),
        family_name="temporal_override_chain",
        agent_id=_agent_id("temporal_override_chain", seed),
        seed=seed,
        events=events,
        query=f"What is the latest committed ship day for the {artifact}?",
        query_day_offset=9,
        expected_keywords=_flatten_keywords(expected_slots, ["final", "latest"]),
        expected_slots=expected_slots,
        notes=["Multiple revisions require selecting the final override over earlier plans."],
    )


def cross_event_composition_scenario(seed: int) -> Scenario:
    rng = random.Random(seed)
    person = rng.choice(["Avery", "Mina", "Theo", "Sasha"])
    preference = rng.choice(["direct feedback", "short written updates", "explicit agendas", "blunt status notes"])
    avoid = rng.choice(["surprise meetings", "last-minute changes", "rambling calls", "vague requests"])
    tactic = rng.choice(["send bullet points in advance", "confirm goals in writing", "summarize decisions immediately"])
    events = [
        ScenarioEvent(text=f"In 1:1, {person} said they prefer {preference}.", day_offset=1, importance=0.83),
        ScenarioEvent(text=f"Later, learned {person} dislikes {avoid}.", day_offset=2, importance=0.82),
        ScenarioEvent(text=f"Reflection: with {person}, I should {tactic}.", day_offset=4, importance=0.9),
        ScenarioEvent(text=f"Routine note: chatted with another teammate about lunch plans.", day_offset=5, importance=0.2),
    ]
    expected_slots = {
        "person": [person.lower()],
        "preference": [preference.lower()],
        "avoid": [avoid.lower()],
        "tactic": [tactic.lower()],
    }
    return Scenario(
        name=_scenario_id("cross_event_composition", seed),
        family_name="cross_event_composition",
        agent_id=_agent_id("cross_event_composition", seed),
        seed=seed,
        events=events,
        query=f"How should I communicate with {person} given their preferences and dislikes?",
        query_day_offset=7,
        expected_keywords=_flatten_keywords(expected_slots, ["communicate"]),
        expected_slots=expected_slots,
        notes=["Answer requires composing guidance spread across multiple events."],
    )


def contradictory_near_duplicates_scenario(seed: int) -> Scenario:
    rng = random.Random(seed)
    person = rng.choice(["Maria", "Nadia", "Leah", "Priya"])
    item_old, item_new = rng.choice(
        [
            ("draft deck", "final launch deck"),
            ("prototype v1", "finished prototype"),
            ("brief summary", "full research brief"),
            ("demo shell", "demo kit"),
        ]
    )
    event = rng.choice(["Friday demo", "partner review", "investor showcase"])
    events = [
        ScenarioEvent(text=f"Told {person} I might bring the {item_old} to the {event}.", day_offset=1, importance=0.74),
        ScenarioEvent(text=f"Correction sent to {person}: bring the {item_new} to the {event}.", day_offset=3, importance=0.93),
        ScenarioEvent(text=f"Internal draft still mentions the {item_old}, marked outdated.", day_offset=4, importance=0.35),
        ScenarioEvent(text="Routine work: backlog grooming and code review.", day_offset=5, importance=0.2),
    ]
    expected_slots = {
        "person": [person.lower()],
        "item": [item_new.lower()],
        "event": [event.lower()],
    }
    return Scenario(
        name=_scenario_id("contradictory_near_duplicates", seed),
        family_name="contradictory_near_duplicates",
        agent_id=_agent_id("contradictory_near_duplicates", seed),
        seed=seed,
        events=events,
        query=f"What should I bring for {person} at the {event} now?",
        query_day_offset=6,
        expected_keywords=_flatten_keywords(expected_slots, ["correction", "now"]),
        expected_slots=expected_slots,
        notes=["Near-duplicate facts conflict; retriever should prefer corrected evidence."],
    )


def pronoun_alias_ambiguity_scenario(seed: int) -> Scenario:
    rng = random.Random(seed)
    canonical, alias = rng.choice([("Samantha", "Sam"), ("Alexander", "Alex"), ("Catherine", "Cat"), ("Nicholas", "Nick")])
    preference = rng.choice(["written agendas", "direct feedback", "concise updates", "clear action items"])
    events = [
        ScenarioEvent(text=f"Met {canonical} today; she asked for {preference}.", day_offset=1, importance=0.85),
        ScenarioEvent(text=f"Later note: {alias} said she dislikes vague status calls.", day_offset=2, importance=0.82),
        ScenarioEvent(text=f"Reminder: Sam from finance is a different person and not this contact.", day_offset=3, importance=0.45),
        ScenarioEvent(text="Routine standup and inbox cleanup.", day_offset=4, importance=0.2),
    ]
    expected_slots = {
        "person": [canonical.lower(), alias.lower()],
        "preference": [preference.lower()],
        "avoid": ["vague status calls"],
    }
    return Scenario(
        name=_scenario_id("pronoun_alias_ambiguity", seed),
        family_name="pronoun_alias_ambiguity",
        agent_id=_agent_id("pronoun_alias_ambiguity", seed),
        seed=seed,
        events=events,
        query=f"How should I communicate with {alias} based on what she asked for?",
        query_day_offset=6,
        expected_keywords=_flatten_keywords(expected_slots, []),
        expected_slots=expected_slots,
        notes=["Pronouns and aliases require entity resolution across events."],
    )


def multi_person_interference_scenario(seed: int) -> Scenario:
    rng = random.Random(seed)
    target = rng.choice(["Avery", "Mina", "Theo", "Sasha"])
    other = rng.choice([name for name in ["Jordan", "Noah", "Priya", "Leah"] if name != target])
    target_pref = rng.choice(["direct feedback", "written agendas", "short updates"])
    other_pref = rng.choice(["brainstorm calls", "long verbal context", "informal check-ins"])
    events = [
        ScenarioEvent(text=f"{target} prefers {target_pref} and dislikes surprises.", day_offset=1, importance=0.86),
        ScenarioEvent(text=f"{other} prefers {other_pref} and casual syncs.", day_offset=2, importance=0.82),
        ScenarioEvent(text=f"Follow-up: with {target}, send expectations in writing first.", day_offset=3, importance=0.88),
        ScenarioEvent(text=f"Follow-up: with {other}, improv sessions are fine.", day_offset=4, importance=0.76),
    ]
    expected_slots = {
        "person": [target.lower()],
        "preference": [target_pref.lower()],
        "strategy": ["in writing"],
    }
    return Scenario(
        name=_scenario_id("multi_person_interference", seed),
        family_name="multi_person_interference",
        agent_id=_agent_id("multi_person_interference", seed),
        seed=seed,
        events=events,
        query=f"What communication strategy should I use with {target}?",
        query_day_offset=6,
        expected_keywords=_flatten_keywords(expected_slots, []),
        expected_slots=expected_slots,
        notes=["Two similar relationship threads compete; retrieval must isolate the target person."],
    )


def negation_traps_scenario(seed: int) -> Scenario:
    rng = random.Random(seed)
    person = rng.choice(["Maria", "Nadia", "Leah", "Priya"])
    wrong_item, right_item = rng.choice(
        [("demo kit", "finished prototype"), ("draft deck", "launch deck"), ("summary memo", "full brief")]
    )
    event = rng.choice(["Friday demo", "partner review", "investor showcase"])
    events = [
        ScenarioEvent(text=f"I did not agree to bring the {wrong_item} for {person}.", day_offset=1, importance=0.86),
        ScenarioEvent(text=f"I agreed to bring the {right_item} for the {event}.", day_offset=2, importance=0.92),
        ScenarioEvent(text=f"Checklist: do not pack the {wrong_item}; pack the {right_item}.", day_offset=3, importance=0.88),
        ScenarioEvent(text="Routine standup, code review, and inbox cleanup.", day_offset=4, importance=0.2),
    ]
    expected_slots = {
        "person": [person.lower()],
        "item": [right_item.lower()],
        "event": [event.lower()],
    }
    return Scenario(
        name=_scenario_id("negation_traps", seed),
        family_name="negation_traps",
        agent_id=_agent_id("negation_traps", seed),
        seed=seed,
        events=events,
        query=f"What did I agree to bring for {person} at the {event}?",
        query_day_offset=6,
        expected_keywords=_flatten_keywords(expected_slots, ["agreed"]),
        expected_slots=expected_slots,
        notes=["Negation and corrections test resistance to lexical traps."],
    )


def time_window_pressure_scenario(seed: int) -> Scenario:
    rng = random.Random(seed)
    person = rng.choice(["Avery", "Mina", "Theo", "Sasha"])
    stable_preference = rng.choice(["written agendas", "direct feedback", "short updates"])
    recent_noise = rng.choice(["lunch preference", "calendar color theme", "office snack request"])
    events = [
        ScenarioEvent(text=f"Important: {person} consistently prefers {stable_preference} for serious work updates.", day_offset=1, importance=0.9),
        ScenarioEvent(text=f"Repeated reminder: for decisions, communicate with {person} via {stable_preference}.", day_offset=2, importance=0.88),
        ScenarioEvent(text=f"Recent note: {person} changed {recent_noise} today.", day_offset=9, importance=0.4),
        ScenarioEvent(text="Routine status: standup, triage, and ticket cleanup.", day_offset=10, importance=0.2),
    ]
    expected_slots = {
        "person": [person.lower()],
        "preference": [stable_preference.lower()],
    }
    return Scenario(
        name=_scenario_id("time_window_pressure", seed),
        family_name="time_window_pressure",
        agent_id=_agent_id("time_window_pressure", seed),
        seed=seed,
        events=events,
        query=f"For important decisions, how should I communicate with {person}?",
        query_day_offset=11,
        expected_keywords=_flatten_keywords(expected_slots, ["important decisions"]),
        expected_slots=expected_slots,
        notes=["Older but durable facts should beat newer irrelevant updates."],
    )


SCENARIO_BUILDERS = {
    "delayed_commitment": delayed_commitment_scenario,
    "routine_interruption": routine_interruption_scenario,
    "relationship_context": relationship_context_scenario,
    "commitment_revision": commitment_revision_scenario,
    "identity_shift": identity_shift_scenario,
    "temporal_override_chain": temporal_override_chain_scenario,
    "cross_event_composition": cross_event_composition_scenario,
    "contradictory_near_duplicates": contradictory_near_duplicates_scenario,
    "pronoun_alias_ambiguity": pronoun_alias_ambiguity_scenario,
    "multi_person_interference": multi_person_interference_scenario,
    "negation_traps": negation_traps_scenario,
    "time_window_pressure": time_window_pressure_scenario,
}

QUICK_SCENARIO_FAMILIES: tuple[str, ...] = (
    "cross_event_composition",
    "temporal_override_chain",
    "multi_person_interference",
    "time_window_pressure",
)


def all_scenarios(seeds: tuple[int, ...] = DEFAULT_SCENARIO_SEEDS) -> list[Scenario]:
    scenarios: list[Scenario] = []
    for family_name, builder in SCENARIO_BUILDERS.items():
        for seed in seeds:
            scenarios.append(builder(seed))
    return scenarios


def quick_scenarios(
    seeds: tuple[int, ...] = (DEFAULT_SCENARIO_SEEDS[0],),
    families: tuple[str, ...] = QUICK_SCENARIO_FAMILIES,
) -> list[Scenario]:
    scenarios: list[Scenario] = []
    for family_name in families:
        builder = SCENARIO_BUILDERS[family_name]
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


def paraphrase_query(query: str, style: str) -> str:
    if style not in QUERY_PARAPHRASE_STYLES:
        raise ValueError(f"Unsupported paraphrase style: {style}")

    replacements_by_style: dict[str, list[tuple[str, str]]] = {
        "concise": [
            ("How should I communicate with", "What communication approach should I use with"),
            ("based on what I know about them", "using what I already know"),
            ("given their preferences and dislikes", "given their likes and dislikes"),
            ("What major conflict happened recently and with whom?", "Who was my recent major conflict with?"),
            ("When is the", "What's the current ship timing for the"),
            ("actually supposed to ship now?", "right now?"),
            ("What is the latest committed ship day for the", "Which day is currently planned for the"),
            ("What did I agree to bring for", "Which item am I bringing for"),
            ("For the", "For"),
            ("which item did I commit to bringing for", "what am I bringing for"),
            ("What should I bring for", "Which item should I bring for"),
            ("How do I describe my current relationship to presenting or facilitation?", "How would I describe myself with presenting now?"),
            ("For important decisions, how should I communicate with", "For important decisions, what's the best way to message"),
        ],
        "indirect": [
            ("How should I communicate with", "Based on my notes, how do I best communicate with"),
            ("What major conflict happened recently and with whom?", "From recent notes, what conflict happened and who was involved?"),
            ("When is the", "From the latest updates, when is the"),
            ("What is the latest committed ship day for the", "Looking at revisions, what is the current ship day for the"),
            ("What did I agree to bring for", "From my commitments, what did I agree to bring for"),
            ("What should I bring for", "From the corrected plan, what should I bring for"),
            ("How do I describe my current relationship to presenting or facilitation?", "From my recent reflections, how should I describe my current stance on presenting?"),
            ("For important decisions, how should I communicate with", "Given durable preferences, how should I communicate with"),
            ("For the", "For the"),
        ],
        "colloquial": [
            ("How should I communicate with", "What's the best way to talk with"),
            ("What major conflict happened recently and with whom?", "Who did I recently clash with, and over what?"),
            ("When is the", "So when is the"),
            ("actually supposed to ship now?", "supposed to ship now, exactly?"),
            ("What is the latest committed ship day for the", "When's the"),
            ("What did I agree to bring for", "What am I bringing for"),
            ("For the", "For"),
            ("which item did I commit to bringing for", "what did I say I'd bring for"),
            ("What should I bring for", "What am I supposed to bring for"),
            ("How do I describe my current relationship to presenting or facilitation?", "How would I describe where I'm at with presenting these days?"),
            ("For important decisions, how should I communicate with", "For important calls, how should I reach out to"),
        ],
    }

    paraphrased = query
    for source, target in replacements_by_style[style]:
        if source in paraphrased:
            paraphrased = paraphrased.replace(source, target)
    if paraphrased == query:
        # Ensure every style still yields a distinct surface form.
        prefix = {
            "concise": "Quickly:",
            "indirect": "Based on prior notes,",
            "colloquial": "In plain terms,",
        }[style]
        paraphrased = f"{prefix} {query}"
    return paraphrased


def _typo_noise_query(query: str) -> str:
    replacements = {
        "communicate": "comunicate",
        "important": "importnt",
        "latest": "latset",
        "commit": "comit",
        "bringing": "bringng",
        "relationship": "relatoinship",
        "preferences": "preferneces",
        "dislikes": "dislkes",
    }
    noisy = query
    for source, target in replacements.items():
        noisy = noisy.replace(source, target)
        noisy = noisy.replace(source.capitalize(), target.capitalize())
    return noisy


def _word_order_query(query: str) -> str:
    if "," in query:
        parts = [part.strip() for part in query.split(",") if part.strip()]
        if len(parts) >= 2:
            return ", ".join(parts[1:] + parts[:1])
    words = query.split()
    if len(words) < 6:
        return f"Please answer: {query}"
    pivot = len(words) // 2
    return " ".join(words[pivot:] + words[:pivot])


def _entity_swap_distractor(scenario: Scenario) -> Scenario:
    query_entities = [value for value in scenario.expected_slots.get("person", []) if value]
    target = query_entities[0] if query_entities else "the target contact"
    alternates = ["maria", "nadia", "leah", "priya", "avery", "mina", "theo", "sasha", "jordan", "noah"]
    distractor = next((name for name in alternates if name != target.lower()), "another contact")
    distractor_event = ScenarioEvent(
        text=(
            f"Distractor update: {distractor.title()} has a separate thread with opposite preferences; "
            f"this note is not about {target}."
        ),
        day_offset=max(1, scenario.query_day_offset - 1),
        importance=0.55,
    )
    return replace(
        scenario,
        events=sorted([*scenario.events, distractor_event], key=lambda item: item.day_offset),
    )


def scenario_with_perturbation(scenario: Scenario, style: str) -> Scenario:
    if style not in QUERY_PERTURBATION_STYLES:
        raise ValueError(f"Unsupported perturbation style: {style}")
    query = scenario.query
    events = scenario.events
    if style in QUERY_PARAPHRASE_STYLES:
        query = paraphrase_query(query, style)
    elif style == "typo_noise":
        query = _typo_noise_query(query)
    elif style == "word_order":
        query = _word_order_query(query)
    elif style == "entity_swap_distractor":
        scenario = _entity_swap_distractor(scenario)
        events = scenario.events
    suffix = f"__qp_{style}"
    return replace(
        scenario,
        name=f"{scenario.name}{suffix}",
        agent_id=f"{scenario.agent_id}-qp-{style}",
        query=query,
        events=events,
    )


def scenario_with_paraphrase(scenario: Scenario, style: str) -> Scenario:
    return scenario_with_perturbation(scenario, style)
