"""Lädt die Modelle der Bildanalyse nach modelle/ neben dem Code (nicht im Git, docs/plan.md, Entscheidung 30.10.2026).

Jedes Modell wird nach dem Laden mit seiner SHA-256 geprüft; vorhandene, korrekte Dateien bleiben unberührt.
Neue Modelle hier nur nach Rückfrage eintragen (CLAUDE.md, harte Regel 5).

    .venv/bin/python werkzeuge/modelle_laden.py
"""
import hashlib
import sys
import urllib.request
from pathlib import Path

CODE = Path(__file__).resolve().parent.parent
MODELLE = CODE / "modelle"
CLIP = "https://huggingface.co/immich-app/ViT-B-32__laion2b-s34b-b79k/resolve/main/"

# Name: (Adresse, SHA-256, Zweck)
LISTE = {
    "yolox_s.onnx": ("https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_s.onnx",
                     "c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063",
                     "F5 Personen auf Fotos (YOLOX-s, Megvii, Apache 2.0, 36 MB)"),
    "yunet.onnx": ("https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/"
                   "face_detection_yunet_2023mar.onnx",
                   "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
                   "F5 Gesichter auf Fotos (YuNet 2023mar, OpenCV Zoo, MIT, 0,2 MB)"),
    # V3 Sujet (Entscheidung 04.11.2026): OpenCLIP ViT-B-32 laion2b_s34b_b79k als ONNX-Export von Immich, MIT
    "clip_bild.onnx": (CLIP + "visual/model.onnx",
                       "b9ce24b91a8c62ef8d40ea786051709c93140104cbf2b6b4a2cc270df3838f9c",
                       "V3 Sujet, Bildteil (OpenCLIP ViT-B/32, LAION-2B, MIT, 352 MB)"),
    "clip_text.onnx": (CLIP + "textual/model.onnx",
                       "48c25be37b352398f2533c9426dab6f9340535e14e46f884cc894236a5060722",
                       "V3 Sujet, Textteil (OpenCLIP ViT-B/32, LAION-2B, MIT, 254 MB)"),
    "clip_tokenizer.json": (CLIP + "textual/tokenizer.json",
                            "6d9109cc838977f3ca94a379eec36aecc7c807e1785cd729660ca2fc0171fb35",
                            "V3 Sujet, Wortliste des Textteils (BPE, 3,6 MB)"),
}


def pruefsumme(pfad):
    h = hashlib.sha256()
    with open(pfad, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main():
    MODELLE.mkdir(exist_ok=True)
    fehler = 0
    for name, (adresse, sha, zweck) in LISTE.items():
        ziel = MODELLE / name
        if ziel.exists() and pruefsumme(ziel) == sha:
            print(f"✓ {name} vorhanden ({zweck})")
            continue
        print(f"… {name} wird geladen ({zweck})")
        zwischen = ziel.with_suffix(".tmp")
        urllib.request.urlretrieve(adresse, zwischen)
        if pruefsumme(zwischen) != sha:
            zwischen.unlink()
            print(f"✗ {name}: Prüfsumme stimmt nicht, Datei verworfen")
            fehler += 1
            continue
        zwischen.replace(ziel)
        print(f"✓ {name} geladen")
    sys.exit(1 if fehler else 0)


if __name__ == "__main__":
    main()
