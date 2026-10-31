"""Tests sans modèles : transcription/Ollama simulés. Lancer : pytest -q"""
import time, wave, struct, math, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import pytest
from fastapi.testclient import TestClient
import main
from services import analysis, storage, transcription

GOOD = {"titre": "Le baobab", "resume": "a", "portrait": "b", "personnes": ["Ama"], "lieux": [], "dates": [], "proverbes": ["Qui sème récolte."]}


def sample_wav(path: Path, secs=1):
    """Audio d'exemple (La 440 Hz). Pour un vrai test vocal : voir README."""
    with wave.open(str(path), "w") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * t / 16000))) for t in range(16000 * secs)))


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA", tmp_path)
    monkeypatch.setattr(transcription, "transcribe", lambda p, l, cb=None: (cb and cb(1.0)) or {"texte": "Il était une fois.", "langue": "fr", "duree": 1.0})
    return TestClient(main.app), tmp_path


def envoyer(c, tmp, nom="a.wav"):
    sample_wav(tmp / "s.wav")
    r = c.post("/api/souvenirs", files={"audio": (nom, (tmp / "s.wav").read_bytes())}, data={"conteur": "Mama Ama", "parente": "grand-mère"})
    return r


def attendre(c, i):
    for _ in range(50):
        s = c.get(f"/api/souvenirs/{i}/statut").json()
        if s["etape"] in ("termine", "erreur"): return s
        time.sleep(0.1)


def test_parse_json_tolerant():
    assert analysis.parse_json("```json\n" + json.dumps(GOOD) + "\n```")["titre"] == "Le baobab"
    with pytest.raises(analysis.AnalyseInvalide): analysis.parse_json("pas de json")


def test_retry_une_fois(monkeypatch):
    rep = iter(["oups", json.dumps(GOOD)])
    monkeypatch.setattr(analysis, "_appeler", lambda *a: next(rep))
    assert analysis.analyser("x")["titre"] == "Le baobab"
    monkeypatch.setattr(analysis, "_appeler", lambda *a: "oups")
    with pytest.raises(analysis.AnalyseInvalide): analysis.analyser("x")


def test_flux_complet_et_export(client, monkeypatch):
    c, tmp = client
    monkeypatch.setattr(analysis, "_appeler", lambda *a: json.dumps(GOOD))
    i = envoyer(c, tmp).json()["id"]
    assert attendre(c, i)["etape"] == "termine"
    assert c.get(f"/api/souvenirs/{i}").json()["analyse"]["titre"] == "Le baobab"
    assert c.get(f"/api/souvenirs/{i}/audio").status_code == 200
    assert "# Le baobab" in c.get(f"/api/souvenirs/{i}/export").text
    assert len(c.get("/api/souvenirs").json()) == 1


def test_ollama_absent_garde_transcription(client, monkeypatch):
    c, tmp = client
    def boom(*a): raise analysis.OllamaIndisponible("Ollama ne répond pas.")
    monkeypatch.setattr(analysis, "_appeler", boom)
    i = envoyer(c, tmp).json()["id"]
    attendre(c, i)
    m = c.get(f"/api/souvenirs/{i}").json()
    assert m["transcription"] and "Ollama" in m["avertissement"] and "analyse" not in m


def test_fichier_invalide(client):
    c, tmp = client
    assert envoyer(c, tmp, "a.exe").status_code == 400
    assert c.post("/api/souvenirs", files={"audio": ("a.wav", b"")}).status_code == 400
    assert c.get("/api/souvenirs/../etc").status_code in (404, 422)


def test_statut_persiste_et_relancer(client, monkeypatch):
    c, tmp = client
    # Simuler une panne
    def boom(*a): raise analysis.OllamaIndisponible("Ollama éteint.")
    monkeypatch.setattr(analysis, "_appeler", boom)
    i = envoyer(c, tmp).json()["id"]
    attendre(c, i)
    # Effacer JOBS pour tester la persistance depuis le disque
    main.JOBS.clear()
    s = c.get(f"/api/souvenirs/{i}/statut").json()
    assert s["etape"] == "termine" or s["erreur"] is None
    # Relancer après remise en marche d'Ollama
    monkeypatch.setattr(analysis, "_appeler", lambda *a: json.dumps(GOOD))
    r = c.post(f"/api/souvenirs/{i}/relancer")
    assert r.status_code == 200
    assert attendre(c, i)["etape"] == "termine"
    assert c.get(f"/api/souvenirs/{i}").json()["analyse"]["titre"] == "Le baobab"


def test_en_markdown_resilience():
    m = {"id": "123", "conteur": "Jean", "statut": "termine"}
    md = main.en_markdown(m)
    assert "# Souvenir de Jean" in md
    assert "_(indisponible)_" in md
