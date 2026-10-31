"""Transcription locale avec faster-whisper (modèle « tiny », CPU, int8)."""
import os, threading

# Compatibilité PyAV >= 14 (suppression de metadata_errors dans av.open)
try:
    import av
    _orig_av_open = av.open
    def _safe_av_open(*args, **kwargs):
        kwargs.pop("metadata_errors", None)
        return _orig_av_open(*args, **kwargs)
    av.open = _safe_av_open
except Exception:
    pass

MODEL_SIZE = os.getenv("WHISPER_MODEL", "tiny")
_model, _lock = None, threading.Lock()
# Langues connues de Whisper ; les autres (éwé, kabiyè…) -> détection automatique.
LANGS = {"fr": "fr", "en": "en", "es": "es", "ar": "ar", "pt": "pt"}


class TranscriptionError(Exception):
    pass


def _get_model():
    global _model
    with _lock:
        if _model is None:
            try:
                from faster_whisper import WhisperModel
                _model = WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8")
            except ImportError as e:
                raise TranscriptionError("faster-whisper n'est pas installé (pip install -r requirements.txt).") from e
            except Exception as e:
                raise TranscriptionError(
                    f"Impossible de charger le modèle Whisper « {MODEL_SIZE} ». "
                    "Au premier lancement, il doit être téléchargé une fois (connexion requise)."
                ) from e
    return _model


def transcribe(path: str, langue: str | None = "fr", on_progress=None) -> dict:
    """Retourne {texte, langue, duree}. on_progress(fraction 0..1)."""
    model = _get_model()
    try:
        segments, info = model.transcribe(path, language=LANGS.get((langue or "").lower()), vad_filter=True)
        parts = []
        for seg in segments:
            parts.append(seg.text.strip())
            if on_progress and info.duration:
                on_progress(min(seg.end / info.duration, 1.0))
    except Exception as e:
        raise TranscriptionError("Fichier audio illisible ou corrompu. Essayez mp3, wav, m4a ou webm.") from e
    texte = " ".join(p for p in parts if p).strip()
    if not texte:
        raise TranscriptionError("Aucune parole détectée dans l'audio.")
    return {"texte": texte, "langue": info.language, "duree": round(info.duration, 1)}


if __name__ == "__main__":  # CLI : python -m services.transcription fichier.mp3 [fr]
    import sys
    if len(sys.argv) < 2:
        sys.exit("Usage : python -m services.transcription <audio> [langue]")
    try:
        r = transcribe(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "fr",
                       lambda f: print(f"\r{f:.0%}", end="", flush=True))
    except TranscriptionError as e:
        sys.exit(f"Erreur : {e}")
    print(f"\n[{r['langue']}, {r['duree']} s]\n{r['texte']}")
