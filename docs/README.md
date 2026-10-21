# Documentation index

Read in order the first time:

| # | Doc | Read it when… |
|---|---|---|
| 01 | [OFFLINE_REQUIREMENTS](01_OFFLINE_REQUIREMENTS.md) | you want to know what's needed to run with no API key |
| 02 | [LOCAL_MODEL_SETUP](02_LOCAL_MODEL_SETUP.md) | you're installing Ollama/llama.cpp/LM Studio or picking a model |
| 03 | [ARCHITECTURE](03_ARCHITECTURE.md) | you want to understand or extend the code |
| 04 | [TOOLS](04_TOOLS.md) | you want the full tool list, the profiles, or to add a tool *(generated)* |
| 05 | [COUNCIL](05_COUNCIL.md) | you want several agents to deliberate together |
| 06 | [GUI_AND_PERSONAS](06_GUI_AND_PERSONAS.md) | you want the GUI, personas with faces, and the avatar roadmap |
| 07 | [SAFETY_AND_DIAGNOSTICS](07_SAFETY_AND_DIAGNOSTICS.md) | you want to know how your computer is protected, the drill results, and code health |
| ★ | [agent_builder_suite.html](agent_builder_suite.html) | **open in a browser**: interactive tool explorer, profile builder, council designer, faces *(generated)* |
| — | [FILE_MAP](FILE_MAP.md) | you're looking for which file does what *(generated)* |
| — | [../NOTES.md](../NOTES.md) | you want the build log: what changed, why, and what was tested |

Regenerate the generated docs after changing code:
```bash
python scripts/gen_tool_docs.py && python scripts/gen_file_map.py && python scripts/gen_knowledge_suite.py
```
