"""Mémoire des Anciens — API FastAPI (100 % local)."""
import threading, datetime as dt
from pathlib import Path
from fastapi import FastAPI, File, Form, UploadFile, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from services import storage, transcription, analysis

BASE = Path(__file__).parent
EXTS = {".mp3", ".wav", ".m4a", ".webm", ".ogg"}
MAX_MO = 200
app = FastAPI(title="Mémoire des Anciens")
JOBS: dict[str, dict] = {}  # id -> {etape, progression, erreur}


def _job(i, **kw):
    JOBS.setdefault(i, {"etape": "attente", "progression": 0, "erreur": None}).update(kw)


def traiter(m: dict, chemin: Path):
    i = m["id"]
    try:
        _job(i, etape="transcription", progression=1)
        r = transcription.transcribe(str(chemin), m["langue"], lambda f: _job(i, progression=int(f * 80)))
        m.update(transcription=r["texte"], langue_detectee=r["langue"], duree=r["duree"])
        storage.save(m)  # la transcription est sauvegardée même si l'analyse échoue
        _job(i, etape="analyse", progression=85)
        try:
            m["analyse"] = analysis.analyser(r["texte"], m["conteur"], m["parente"], m["langue"])
        except (analysis.OllamaIndisponible, analysis.AnalyseInvalide) as e:
            m["avertissement"] = f"{e} Transcription brute conservée."
        m["statut"] = "termine"
        storage.save(m)
        _job(i, etape="termine", progression=100)
    except transcription.TranscriptionError as e:
        m.update(statut="erreur", avertissement=str(e)); storage.save(m)
        _job(i, etape="erreur", erreur=str(e))
    except Exception as e:  # filet de sécurité
        m.update(statut="erreur", avertissement=f"Erreur inattendue : {e}"); storage.save(m)
        _job(i, etape="erreur", erreur=f"Erreur inattendue : {e}")


@app.post("/api/souvenirs")
async def creer(audio: UploadFile = File(...), conteur: str = Form(""), parente: str = Form(""), langue: str = Form("fr")):
    ext = Path(audio.filename or "").suffix.lower() or ".webm"
    if ext not in EXTS:
        raise HTTPException(400, f"Format « {ext} » non pris en charge. Utilisez mp3, wav, m4a ou webm.")
    data = await audio.read()
    if not data:
        raise HTTPException(400, "Le fichier audio est vide.")
    if len(data) > MAX_MO * 1024 * 1024:
        raise HTTPException(413, f"Fichier trop volumineux (maximum {MAX_MO} Mo).")
    i = storage.new_id()
    storage.DATA.mkdir(exist_ok=True)
    chemin = storage.DATA / f"{i}{ext}"
    chemin.write_bytes(data)
    m = {"id": i, "cree_le": dt.datetime.now().isoformat(timespec="seconds"), "conteur": conteur.strip() or "Un proche",
         "parente": parente.strip(), "langue": langue, "audio": chemin.name, "statut": "en_cours"}
    storage.save(m)
    _job(i)
    threading.Thread(target=traiter, args=(m, chemin), daemon=True).start()
    return {"id": i}


@app.get("/api/souvenirs/{i}/statut")
def statut(i: str):
    if i in JOBS:
        return JOBS[i]
    m = storage.load(i)
    if not m:
        raise HTTPException(404, "Souvenir introuvable.")
    st = m.get("statut")
    if st == "erreur":
        return {"etape": "erreur", "progression": 0, "erreur": m.get("avertissement") or "Une erreur est survenue."}
    if st == "en_cours":
        return {"etape": "attente", "progression": 50, "erreur": None}
    return {"etape": "termine", "progression": 100, "erreur": None}


@app.post("/api/souvenirs/{i}/relancer")
def relancer(i: str):
    m = storage.load(i)
    if not m:
        raise HTTPException(404, "Souvenir introuvable.")
    p = storage.audio_path(m)
    if not p:
        raise HTTPException(400, "Fichier audio introuvable pour ce souvenir.")
    m["statut"] = "en_cours"
    m.pop("avertissement", None)
    storage.save(m)
    _job(i, etape="attente", progression=0, erreur=None)
    threading.Thread(target=traiter, args=(m, p), daemon=True).start()
    return {"id": i, "message": "Traitement relancé."}


@app.get("/api/souvenirs")
def liste():
    return storage.list_all()


@app.get("/api/souvenirs/{i}")
def detail(i: str):
    m = storage.load(i)
    if not m:
        raise HTTPException(404, "Souvenir introuvable.")
    return m


@app.get("/api/souvenirs/{i}/audio")
def audio(i: str):
    m = storage.load(i)
    p = m and storage.audio_path(m)
    if not p:
        raise HTTPException(404, "Audio introuvable.")
    return FileResponse(p)


def en_markdown(m: dict) -> str:
    a = m.get("analyse") or {}
    conteur = m.get("conteur") or "Un proche"
    parente = m.get("parente") or ""
    date_cree = (m.get("cree_le") or "")[:10]
    titre = a.get("titre") or f"Souvenir de {conteur}"
    L = [f"# {titre}", "",
         f"*Raconté par **{conteur}**" + (f" ({parente})" if parente else "") + (f" — {date_cree}*" if date_cree else "*"), ""]
    if a:
        if a.get("resume"):
            L += ["## Résumé", a["resume"], ""]
        if a.get("portrait"):
            L += ["## Portrait", a["portrait"], ""]
        for cle, nom in (("personnes", "Personnes"), ("lieux", "Lieux"), ("dates", "Dates")):
            val = a.get(cle) or []
            if val:
                L += [f"**{nom} :** " + ", ".join(val), ""]
        if a.get("proverbes"):
            L += ["## Paroles à garder", *[f"> {p}" for p in a["proverbes"]], ""]
    if m.get("avertissement"):
        L += [f"> ⚠️ {m['avertissement']}", ""]
    L += ["## Transcription", m.get("transcription", "_(indisponible)_"), ""]
    return "\n".join(L)


@app.get("/api/souvenirs/{i}/export")
def exporter(i: str):
    m = storage.load(i)
    if not m:
        raise HTTPException(404, "Souvenir introuvable.")
    return Response(en_markdown(m), media_type="text/markdown; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="souvenir-{i}.md"'})


@app.get("/")
def accueil():
    return FileResponse(BASE / "static" / "index.html")


app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")


if __name__ == "__main__":  # permet `python main.py` (utilisé par lancer.bat)
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000)
