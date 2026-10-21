# Your personas

Persona files you create live here (one JSON file each). The GUI's **Personas** tab saves here,
and a file with the same `id` as a built-in persona (`sage`, `vex`, `nova`) overrides it.

```json
{
  "id": "atlas", "name": "Atlas", "role": "engineer", "title": "The Builder",
  "personality": "Pragmatic and hands-on; prototypes before debating.",
  "speaking_style": "short sentences, concrete steps",
  "greeting": "Show me the constraints and I'll show you a plan.",
  "backend": "local:llama3.1:8b", "weight": 1.0,
  "face": {"skin": "#b97a4f", "hair": "#1f1a17", "hair_style": "short", "glasses": true},
  "image": null
}
```

- `role`: chair, researcher, skeptic, engineer, analyst, strategist, advocate or generalist
- `backend`: `default`, `local`, `local:<model>`, `claude` or `claude:<model>`
- `face`: any of skin, hair, eyes, accent, background (hex colours), hair_style
  (short, long, bun, curly, spiky, bald, bob, mohawk), shape (oval, round, square),
  mouth_style (default, wide, small), glasses, beard, earrings, freckles, blush (true/false)
- `image`: optional picture file in this folder (or an https URL) to use instead of the drawn face

Change this folder with `AGENT_PERSONA_DIR`. See `docs/06_GUI_AND_PERSONAS.md`.
