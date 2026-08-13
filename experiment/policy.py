"""The shared decision policy. SELECTION STAGE.

This module imports NOTHING. Not the world, not the perception store, not
sqlite3, not even the character-facing recall API -- it is handed a plain list
of memories and returns a plain list of proposals.

That is the whole anti-cheating argument: there is no name in this file's
namespace through which canonical state could be reached, so the policy cannot
consult the world even by accident. It is the same capability discipline
`one_world.minds` uses, applied one layer further out.

The policy is deliberately trivial. The experiment tests whether the causal
chain geometry -> sensing -> stored history -> action is connected, not whether
the decision procedure is any good.
"""

#: What the inhabitant is looking for, as they would remember it. This is a
#: DESCRIPTION, the only form an object takes in a character's history. No
#: canonical object id appears anywhere in this module.
TARGET_DESCRIPTION = "red lighter"

#: Fixed, and identical for every inhabitant, so orientation cannot differ
#: between them for any reason traceable to the policy.
FACING = (1, 0)


def last_known_position(history):
    """Go to the last place you personally saw the thing, and take it.

    `history` is a list of memories, each {seq, kind, grade, source, content},
    exactly as CharacterHistory.recall returns them for ONE inhabitant.

    NOTE what is absent from the signature: there is no character id, no pose,
    no world, no object id. The policy cannot tell WHO it is deciding for, which
    is what makes an identity-keyed shortcut impossible rather than merely
    absent.

    Returns a list of (verb, params) proposals, or [] to abstain.
    """
    for memory in sorted(history, key=lambda m: m["seq"], reverse=True):
        content = memory.get("content", {})
        if "at" in content and content.get("object") == TARGET_DESCRIPTION:
            return [
                ("MOVE", {"to": tuple(content["at"]), "facing": FACING}),
                ("TAKE", {"description": TARGET_DESCRIPTION}),
            ]
    return []
