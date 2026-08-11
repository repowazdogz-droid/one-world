"""The v0.1 behavioural contract, as named checks over ANY history object.

A "history" here is anything with `.recall(character_id) -> list[dict]`, where
each memory is {"seq": int, "kind": str, "content": dict}. That interface is
what makes the safe and unsafe implementations comparable: the same checks run
against both, and the negative control asserts which ones flip.

Every check is evaluated independently and recorded pass/fail; nothing aborts
the run. Purely behavioural -- no structural or import assertions live here,
because those do not change when the implementation is swapped.
"""

from __future__ import annotations

import json
from typing import Any

CANONICAL_EVENT_COUNT = 4

FORBIDDEN_FOR_NOAH = ["lighter", "red", "leaving tomorrow", "jacket", "pocket"]


def _blob(memories: list[dict]) -> str:
    return json.dumps(memories, sort_keys=True).lower()


def run_contract(history: Any) -> dict[str, bool]:
    """Run every behavioural check. Returns {check_name: passed}."""
    warren = history.recall("warren")
    ava = history.recall("ava")
    noah = history.recall("noah")

    r: dict[str, bool] = {}

    def check(name: str, fn) -> None:
        try:
            r[name] = bool(fn())
        except Exception:
            r[name] = False

    # -- Ava: perceived everything, at full fidelity --------------------
    check("ava_memory_count_is_4", lambda: len(ava) == 4)
    check(
        "ava_seq_strictly_ascending",
        lambda: all(a["seq"] < b["seq"] for a, b in zip(ava, ava[1:])),
    )
    check(
        "ava_kind_order_is_attempt_give_speech_stow",
        lambda: [m["kind"] for m in ava]
        == ["GIVE_ATTEMPT", "GIVE", "SPEECH", "STOW"],
    )
    check("ava_knows_red_lighter", lambda: ava[1]["content"]["object"] == "red lighter")
    check(
        "ava_knows_the_offer_was_of_the_lighter",
        lambda: ava[0]["content"]["object"] == "red lighter",
    )
    check(
        "ava_knows_private_sentence",
        lambda: ava[2]["content"]["utterance"] == "I'm leaving tomorrow",
    )

    # -- Noah: present throughout, perceived almost none of it ----------
    check("noah_memory_count_is_2", lambda: len(noah) == 2)
    check(
        "noah_objects_are_all_something",
        lambda: [m["content"]["object"] for m in noah] == ["something", "something"],
    )
    check("noah_no_red_lighter", lambda: "lighter" not in _blob(noah) and "red" not in _blob(noah))
    check("noah_no_private_sentence", lambda: "leaving tomorrow" not in _blob(noah))
    check("noah_no_utterance_field", lambda: "utterance" not in _blob(noah))
    check(
        "noah_no_stow_detail",
        lambda: "jacket" not in _blob(noah) and "pocket" not in _blob(noah),
    )
    check(
        "noah_no_forbidden_substring",
        lambda: all(s not in _blob(noah) for s in FORBIDDEN_FOR_NOAH),
    )

    # -- Warren: a human player, and still just an inhabitant -----------
    check("warren_memory_count_is_3", lambda: len(warren) == 3)
    check(
        "warren_no_stow_detail",
        lambda: "jacket" not in _blob(warren) and "pocket" not in _blob(warren),
    )
    check("warren_not_omniscient", lambda: len(warren) < CANONICAL_EVENT_COUNT)

    # -- ordering holds for every inhabitant ----------------------------
    check(
        "all_seqs_ascending",
        lambda: all(
            all(a["seq"] < b["seq"] for a, b in zip(ms, ms[1:]))
            for ms in (warren, ava, noah)
        ),
    )
    return r


#: Checks that MUST flip to failing when recall is served from canonical
#: history filtered by presence. Asserted in test_negative_control.py.
MUST_FAIL_AGAINST_UNSAFE = {
    "noah_memory_count_is_2",
    "noah_objects_are_all_something",
    "noah_no_red_lighter",
    "noah_no_private_sentence",
    "noah_no_utterance_field",
    "noah_no_stow_detail",
    "noah_no_forbidden_substring",
    "warren_memory_count_is_3",
    "warren_no_stow_detail",
    "warren_not_omniscient",
}
