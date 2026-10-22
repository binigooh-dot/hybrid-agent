"""[AGENTS] Your agents: generic ASCII smiley faces with small differences, and which model each uses.

    store.py   AgentProfile (id, name, face, model), built-in Blue/Green/Orange, load/save/delete
    faces.py   the smiley faces: 7 lines x 16 columns of plain ASCII, with simple animations
"""
from .faces import EXPRESSIONS, face_for, random_face, render_all, render_face
from .store import AgentProfile, builtin_agents, delete_agent, load_agents, new_agent_id, save_agent

__all__ = ["EXPRESSIONS", "AgentProfile", "builtin_agents", "delete_agent", "face_for", "load_agents", "new_agent_id",
           "random_face", "render_all", "render_face", "save_agent"]
