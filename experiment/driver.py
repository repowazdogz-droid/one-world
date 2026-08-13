"""The inhabitant driver. SELECTION STAGE.

Constructed with a perception-store connection and nothing else, exactly like
`one_world.minds.CharacterHistory`. It imports no canonical storage module and
has no helper that opens one, so an inhabitant's decision cannot be informed by
anything the inhabitant did not physically perceive.

Selection happens here. EXECUTION happens in `runner`, which is allowed
canonical state and may judge whether a chosen action is physically possible --
but by then the choice has already been made and recorded.
"""

from one_world.minds import CharacterHistory

from experiment.policy import last_known_position


class Inhabitant:
    """One inhabitant's decision-making. Subjective input only."""

    #: The single shared policy. Every Inhabitant uses THIS object; the tests
    #: assert identity, not equality, so two inhabitants cannot silently run
    #: different implementations.
    POLICY = staticmethod(last_known_position)

    def __init__(self, minds_conn):
        self._history = CharacterHistory(minds_conn)

    def evidence(self, character_id):
        """Exactly what this inhabitant has to go on."""
        return self._history.recall(character_id)

    def propose(self, character_id):
        """Choose, from stored history alone.

        `character_id` selects WHOSE memories to read. It is not passed to the
        policy, so it cannot influence WHAT is chosen given those memories.
        """
        return Inhabitant.POLICY(self.evidence(character_id))
