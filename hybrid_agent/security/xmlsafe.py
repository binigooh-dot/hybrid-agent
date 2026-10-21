"""[SECURITY / xmlsafe] Parse untrusted XML without entity tricks.

XML can declare entities that expand exponentially ("billion laughs") or pull
in local files (external entities). The stdlib parser doesn't fetch external
entities and modern expat limits expansion, but we go one step further and
refuse any document that declares a DTD or entities at all - real-world feeds
and data files almost never need them.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

from ..core.errors import ToolError

_DTD = re.compile(rb"<!DOCTYPE|<!ENTITY", re.IGNORECASE)


def _check(data: bytes) -> None:
    if _DTD.search(data[:200_000]) or (len(data) > 200_000 and _DTD.search(data)):
        raise ToolError("XML with a DOCTYPE/ENTITY declaration was refused (entity-expansion protection).")


def safe_xml_fromstring(text: str | bytes) -> ET.Element:
    data = text.encode() if isinstance(text, str) else text
    _check(data)
    try:
        # Reviewed (B314): DTD/entities rejected above
        return ET.fromstring(data)  # noqa: S314  # nosec B314
    except ET.ParseError as e:
        raise ToolError(f"XML error: {e}") from None


def safe_xml_parse(path: Path) -> ET.Element:
    return safe_xml_fromstring(path.read_bytes())
