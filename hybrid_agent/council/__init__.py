"""[COUNCIL] Groundwork for a council of agents that deliberate together.

    blackboard.py  shared, thread-safe board members post findings to
    roles.py       preset roles (persona + default tool profile)
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

__all__ = ["Ballot", "Blackboard", "Council", "CouncilError", "CouncilMember", "CouncilResult",
           "MemberSpec", "PROTOCOLS", "Protocol", "ROLES", "Role", "Tally", "parse_ballot", "tally"]
