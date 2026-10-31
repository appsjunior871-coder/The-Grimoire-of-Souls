"""Stockage local : un JSON + un fichier audio par souvenir dans ./data/."""
import json, re, uuid
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
_ID = re.compile(r"[0-9a-f]{12}")


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def valid_id(i: str) -> bool:
    return bool(_ID.fullmatch(i or ""))


def save(m: dict) -> None:
    DATA.mkdir(exist_ok=True)
    (DATA / f"{m['id']}.json").write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")


def load(i: str) -> dict | None:
    if not valid_id(i) or not (DATA / f"{i}.json").exists():
        return None
    return json.loads((DATA / f"{i}.json").read_text(encoding="utf-8"))


def list_all() -> list[dict]:
    out = []
    for p in DATA.glob("*.json"):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    return sorted(out, key=lambda m: m.get("cree_le") or "", reverse=True)


def audio_path(m: dict) -> Path | None:
    p = DATA / m.get("audio", "")
    return p if m.get("audio") and p.exists() else None
