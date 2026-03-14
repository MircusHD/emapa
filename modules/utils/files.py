import hashlib
import re
from typing import List
from modules.config import DG_DEPT


def sha256_bytes(b: bytes) -> str:
    h = hashlib.sha256()
    h.update(b)
    return h.hexdigest()


def normalize_dept(dept: str) -> str:
    d = (dept or "").strip().upper().replace(" ", "_").replace("-", "_")
    return d if d else DG_DEPT


def safe_filename(name: str) -> str:
    name = (name or "file").replace("\\", "_").replace("/", "_")
    for ch in [":", "*", "?", "\"", "<", ">", "|"]:
        name = name.replace(ch, "_")
    return name


def parse_tags(tags_str: str) -> List[str]:
    tags = [t.strip() for t in (tags_str or "").split(",")]
    tags = [t for t in tags if t]
    out = []
    seen = set()
    for t in tags:
        k = t.lower()
        if k not in seen:
            seen.add(k)
            out.append(t)
    return out
