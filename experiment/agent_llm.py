"""The language-model inhabitant. SELECTION STAGE.

Like `experiment.policy`, this module imports NOTHING from the world. Not the
world store, not the perception store, not sqlite3, not the character-facing
recall API. It is handed a plain list of memories -- and, under the ON
condition, a plain list of last turn's action outcomes -- and returns a plain
list of proposals.

That is the anti-cheating argument, unchanged from Experiment 1: there is no
name in this file's namespace through which canonical state could be reached.

It is also not told WHICH character it is deciding for, so an identity-keyed
shortcut is impossible rather than merely absent.
"""

from __future__ import annotations

import json
import re

from experiment.providers import TransportError, complete

TARGET_DESCRIPTION = "red lighter"

#: Tokens that would indicate canonical state reached the prompt. Asserted
#: against every prompt before it is sent (NC1).
FORBIDDEN = ("world.db", "minds.db", "object_location", "sqlite3",
             "WorldStore", "PerceptionRouter", "lighter-1", "world_event",
             "world_pose", "world_observation")

PROMPT = """You are a person in a room. You are looking for a {target}.

You know only what you remember. Your memories are listed below, oldest first.
Nothing else is available to you: there is no map, no narrator, and no way to
ask the world a question.

YOUR MEMORIES
{memories}
{feedback}
HOW PERCEPTION WORKS HERE
- You see only what is in front of you, within a limited arc, and only nearby
  things are seen in detail. Things behind you or to your side are not seen.
- Turning changes what you will perceive next. Turning is an action.
- Distances are in centimetres. Positions are [x, y]. Facing is a direction
  vector such as [1, 0] or [0, -1].

ACTIONS YOU MAY PROPOSE, this turn, as a JSON list
  ["MOVE", {{"to": [x, y], "facing": [fx, fy]}}]   move and/or turn. Changing
      only facing, keeping the same position, is a legal move.
  ["LOOK", {{}}]                                    observe from where you
      stand, facing as you are. Changes nothing physical.
  ["TAKE", {{"description": "{target}"}}]           pick it up. Only succeeds
      if you are close enough to it.

Reply with ONLY a JSON list of actions for this turn, for example:
  [["MOVE", {{"to": [0, 0], "facing": [1, 0]}}], ["TAKE", {{"description": "{target}"}}]]
An empty list [] means you do nothing this turn.
"""

FEEDBACK_BLOCK = """
WHAT HAPPENED WHEN YOU ACTED LAST TURN
{lines}
"""


def render_memories(history):
    """Exactly what the inhabitant has to go on, as text."""
    if not history:
        return "  (you remember nothing)"
    out = []
    for m in sorted(history, key=lambda m: m["seq"]):
        out.append(f"  {m['seq']}. [{m['kind']}/{m['grade']}] "
                   f"{json.dumps(m.get('content', {}), sort_keys=True)}")
    return "\n".join(out)


def render_feedback(outcomes):
    """Last turn's per-action results. Empty string under the OFF condition."""
    if outcomes is None:
        return ""
    if not outcomes:
        return FEEDBACK_BLOCK.format(lines="  (you have not acted yet)")
    lines = []
    for o in outcomes:
        verd = "ACCEPTED" if o["accepted"] else f"REJECTED ({o['reason']})"
        lines.append(f"  {o['verb']} {json.dumps(o['params'], sort_keys=True)}"
                     f" -> {verd}")
    return FEEDBACK_BLOCK.format(lines="\n".join(lines))


def build_prompt(history, outcomes=None):
    p = PROMPT.format(target=TARGET_DESCRIPTION,
                      memories=render_memories(history),
                      feedback=render_feedback(outcomes))
    for tok in FORBIDDEN:
        assert tok not in p, f"canonical token {tok!r} reached the prompt"
    return p


def parse(text):
    """Model text -> proposals. Unparseable is MALFORMED, never an abstention."""
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        return None
    try:
        raw = json.loads(m.group(0))
    except Exception:
        return None
    if not isinstance(raw, list):
        return None
    out = []
    for item in raw:
        if not (isinstance(item, list) and len(item) == 2
                and isinstance(item[0], str) and isinstance(item[1], dict)):
            return None
        verb, params = item[0].upper(), item[1]
        if verb not in ("MOVE", "LOOK", "TAKE"):
            return None
        out.append((verb, params))
    return out


def propose(model, history, outcomes=None):
    """Returns (proposals | None, prompt, raw_text, status)."""
    prompt = build_prompt(history, outcomes)
    try:
        text = complete(model, prompt)
    except TransportError as e:
        return None, prompt, "", f"transport_error: {e}"
    parsed = parse(text)
    return parsed, prompt, text, ("ok" if parsed is not None else "malformed")
