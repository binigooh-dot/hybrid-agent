"""[TOOLS / builtin] The built-in tool modules. Each module has a `register(registry)`
function and a CATEGORY label. ALL_MODULES is the single list of what ships.

    module          category        what it covers
    files           files           read/write/edit/search/copy/move/delete/diff files
    shell           shell           run shell commands, run python, which
    code            code            code outline, syntax check, run tests, git
    data            data            CSV, JSON, SQLite, XML
    text            text            stats, regex, entities, encode/decode, hashing, ids
    math_time       math, time      calculator, statistics, units, bases, dates, timezones
    web             web             fetch pages, web search, links, downloads
    network         network         raw HTTP requests, URL/port checks, DNS
    knowledge       knowledge       Wikipedia, arXiv, weather, dictionary, RSS (all keyless)
    system          system          OS/CPU/RAM/disk info, env vars, python packages
    archives        archives        zip / tar create, list, extract
    memory          memory          long-term key/value memory
    documents       documents       local BM25 document search (RAG without embeddings)
    agent_ops       agent           plan, think, ask_user, delegate_to_local
    council_board   council         shared blackboard for council members
"""
from . import (
               agent_ops,
               archives,
               code,
               council_board,
               data,
               documents,
               files,
               knowledge,
               math_time,
               memory,
               network,
               shell,
               system,
               text,
               web,
)

ALL_MODULES = [files, shell, code, data, text, math_time, web, network, knowledge, system,
               archives, memory, documents, agent_ops, council_board]
