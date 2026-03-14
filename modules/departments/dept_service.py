from typing import List
from sqlalchemy import select
from modules.database.session import SessionLocal
from modules.database.models import Department
from modules.utils.files import normalize_dept


def get_dept_children_map() -> dict:
    with SessionLocal() as db:
        deps = db.execute(select(Department)).scalars().all()
    m = {}
    for d in deps:
        if d.parent_department:
            p = normalize_dept(d.parent_department)
            c = normalize_dept(d.name)
            m.setdefault(p, []).append(c)
    return m


def get_descendant_departments(root_dept: str) -> List[str]:
    root = normalize_dept(root_dept)
    m = get_dept_children_map()
    out = [root]
    seen = {root}
    stack = [root]
    while stack:
        cur = stack.pop()
        for child in m.get(cur, []):
            if child not in seen:
                seen.add(child)
                out.append(child)
                stack.append(child)
    return out
