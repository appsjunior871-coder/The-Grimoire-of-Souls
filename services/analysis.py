"""Analyse de la transcription par Gemma via Ollama (local)."""
import json, os
import httpx

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
MODEL = os.getenv("OLLAMA_MODEL", "gemma3")

SYSTEM = """Tu es un archiviste bienveillant qui préserve les histoires orales de famille.
On te donne la transcription d'un souvenir raconté à l'oral. Réponds UNIQUEMENT par un objet JSON
valide, sans texte autour, avec exactement ces clés :
{"titre": "...", "resume": "3 phrases maximum", "portrait": "court portrait chaleureux de la personne qui raconte",
 "personnes": [], "lieux": [], "dates": [], "proverbes": ["phrases marquantes à conserver mot pour mot"]}
Écris en français (sauf les citations, gardées dans la langue d'origine). N'invente rien : si une
information est absente, laisse la liste vide."""

LISTES = ("personnes", "lieux", "dates", "proverbes")


class OllamaIndisponible(Exception): pass
class AnalyseInvalide(Exception): pass


def _normaliser(d: dict) -> dict:
    if not isinstance(d, dict):
        raise ValueError("pas un objet")
    out = {k: str(d.get(k) or "").strip() for k in ("titre", "resume", "portrait")}
    for k in LISTES:
        v = d.get(k) or []
        out[k] = [str(x).strip() for x in (v if isinstance(v, list) else [v]) if str(x).strip()]
    if not out["titre"]:
        raise ValueError("titre manquant")
    return out


def parse_json(raw: str) -> dict:
    """Parse tolérant : accepte du texte/```json autour de l'objet."""
    try:
        return _normaliser(json.loads(raw))
    except (json.JSONDecodeError, ValueError):
        a, b = raw.find("{"), raw.rfind("}")
        if a < 0 or b <= a:
            raise AnalyseInvalide("Aucun JSON dans la réponse.")
        try:
            return _normaliser(json.loads(raw[a:b + 1]))
        except (json.JSONDecodeError, ValueError) as e:
            raise AnalyseInvalide(str(e)) from e


def _appeler(texte: str, contexte: str) -> str:
    try:
        r = httpx.post(f"{OLLAMA_URL}/api/chat", timeout=600, json={
            "model": MODEL, "stream": False, "format": "json",
            "messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": f"{contexte}\n\nTranscription :\n{texte}"}]})
    except (httpx.ConnectError, httpx.ConnectTimeout) as e:
        raise OllamaIndisponible("Ollama ne répond pas. Lancez-le (`ollama serve`) puis réessayez.") from e
    except httpx.HTTPError as e:
        raise OllamaIndisponible(f"Erreur de communication avec Ollama : {e}") from e
    if r.status_code == 404:
        raise OllamaIndisponible(f"Modèle « {MODEL} » introuvable. Lancez : ollama pull {MODEL}")
    if r.status_code != 200:
        raise OllamaIndisponible(f"Ollama a répondu avec le code {r.status_code}.")
    return r.json().get("message", {}).get("content", "")


def analyser(texte: str, conteur: str = "", parente: str = "", langue: str = "") -> dict:
    """Réessaie une fois si le JSON est invalide, sinon lève AnalyseInvalide."""
    ctx = f"Conteur : {conteur or 'inconnu'} ({parente or 'lien non précisé'}). Langue parlée : {langue or 'inconnue'}."
    dernier = None
    for _ in range(2):
        try:
            return parse_json(_appeler(texte, ctx))
        except AnalyseInvalide as e:
            dernier = e
    raise AnalyseInvalide(f"Gemma n'a pas renvoyé de JSON valide ({dernier}).")
