"""[COUNCIL] A council of agents that deliberate together.

    blackboard.py  shared, thread-safe board members post findings to
    roles.py       the chair (sums up) and members
    member.py      MemberSpec (config) and CouncilMember (live agent)
    ballots.py     parse VOTE/CONFIDENCE lines, weighted/majority tally
    protocols.py   roundtable, debate, vote, critique procedures
    council.py     Council orchestrator, Session, CouncilResult (+ transcript save)
"""
from .ballots import Ballot, Tally, parse_ballot, tally
from .blackboard import Blackboard
from .council import Council, CouncilError, CouncilResult
from .member import CouncilMember, MemberSpec
from .protocols import PROTOCOLS, Protocol
from .roles import ROLES, Role

__all__ = [
           "PROTOCOLS",
           "ROLES",
           "Ballot",
           "Blackboard",
           "Council",
           "CouncilError",
           "CouncilMember",
           "CouncilResult",
           "MemberSpec",
           "Protocol",
           "Role",
           "Tally",
           "parse_ballot",
           "tally",
]
