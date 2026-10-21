"""Rozbor detailu jídla ze Strava.cz (endpoint /api/orderModalDetails).

Pole "AlergenyPopis" má tvar:
  "07 -Mléko|09 -Celer||Receptury a suroviny s alergeny|-----|Chod  (A: 09)|   Surovina  (A: 09)|-----|Salát  (A: 07)|   Sýr cihla  (A: 07)|"
Řádek bez odsazení je chod, řádek odsazený je jeho surovina.
"""
from __future__ import annotations

import re

BLOCKING = ("03", "04", "07")          # vejce, ryby, mléko
_A = re.compile(r"\(\s*A:\s*([^)]*)\)")
_LEGEND = re.compile(r"^\s*(\w+)\s*-\s*(.+?)\s*$")


def _codes(text: str) -> list[str]:
    m = _A.search(text)
    if not m:
        return []
    return [c.strip() for c in re.split(r"[,\s]+", m.group(1)) if c.strip()]


def _name(text: str) -> str:
    return _A.sub("", text).strip()


def build_payload(user, language: str, veta, datum: str, druh: str, cislo_jidelnicku: str = "1") -> dict:
    """Tělo dotazu přesně podle webu (sid, cislo a url bere z přihlášení knihovna)."""
    return {
        "sid": user.sid,
        "cislo": user.canteen_number,
        "url": user.s5url,
        "lang": language,
        "ignoreCert": "false",
        "cisloJidelnicku": str(cislo_jidelnicku),
        "datum": datum,            # YYYY-MM-DD
        "druh": druh,              # např. "O2"
        "veta": str(veta),
        "fetchGramaze": True,
        "fetchHodnoceni": False,
    }


def parse_detail(response: dict) -> dict:
    """Vrátí {"legend": {kód: název}, "courses": [{name, allergens, ingredients:[{name, allergens}]}]}."""
    g = (response or {}).get("gramaze") or {}
    raw = str(g.get("AlergenyPopis") or "")
    legend: dict[str, str] = {}
    courses: list[dict] = []
    in_recipes = False
    for part in raw.split("|"):
        if not part.strip():
            continue
        if part.strip().lower().startswith("receptury"):
            in_recipes = True
            continue
        if set(part.strip()) == {"-"}:
            continue
        if not in_recipes:
            m = _LEGEND.match(part)
            if m:
                legend[m.group(1)] = m.group(2)
            continue
        item = {"name": _name(part), "allergens": _codes(part)}
        if part[:1].isspace() and courses:
            courses[-1]["ingredients"].append(item)
        else:
            courses.append({**item, "ingredients": []})
    return {"legend": legend, "courses": courses, "all": [c.strip() for c in str(g.get("Alergeny") or "").split(",") if c.strip()]}


_NAMES = {"03": "vejce", "04": "ryby", "07": "mléko"}
_TOPPING = ("sýr", "syr", "parmaz", "posyp", "strouhan")


def is_side(course_name: str) -> bool:
    """Salát a podobné přílohy."""
    return "salát" in course_name.lower()


def _is_topping(ingredient: str) -> bool:
    n = ingredient.lower()
    return any(w in n for w in _TOPPING)


def _what(codes) -> str:
    return ", ".join(f"{_NAMES.get(c, c)} ({c})" for c in codes)


def vegan_summary(detail: dict, soup_allergens=(), blocking=BLOCKING) -> dict:
    """Vyhodnocení pro rozhodování a pro přehled.

    ok     = hlavní jídlo nemá blokující alergen (salát, sýr jako posyp a polévka
             rozhodnutí NEOVLIVNÍ, jen se vypíšou v poznámkách)
    blockers = co hlavní jídlo blokuje (prázdné, pokud ok)
    notes  = poznámky pro přehled (salát, posyp, polévka)
    label  = jedna věta pro dashboard
    """
    blockers, notes = [], []
    for c in detail["courses"]:
        bad = [a for a in c["allergens"] if a in blocking]
        if not bad:
            continue
        bad_ings = [i for i in c["ingredients"] if any(a in blocking for a in i["allergens"])]
        if is_side(c["name"]):
            ing = ", ".join(i["name"] for i in bad_ings)
            notes.append(f"salát s {ing.lower() if ing else _what(bad)} ({', '.join(bad)})".replace("s sýr cihla", "se sýrem"))
        elif bad_ings and all(_is_topping(i["name"]) for i in bad_ings):
            notes.append(f"{', '.join(i['name'] for i in bad_ings)} jako posyp/přísada ({', '.join(bad)}), lze vynechat")
        else:
            blockers.append({"course": c["name"], "ingredients": [i["name"] for i in bad_ings], "codes": bad})
    sb = [a for a in soup_allergens if a in blocking]
    if sb:
        notes.append(f"polévka není vegan: {_what(sb)}")
    ok = not blockers
    if ok:
        label = "vegan" + (", ale " + "; ".join(notes) if notes else "")
    else:
        label = "NEVEGAN: " + "; ".join(
            f"{b['course']} – {_what(b['codes'])}" + (f" [{', '.join(b['ingredients'])}]" if b["ingredients"] else "")
            for b in blockers) + (" | " + "; ".join(notes) if notes else "")
    return {"ok": ok, "blockers": blockers, "notes": notes, "label": label}
