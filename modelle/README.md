# Modelle der Bildanalyse

Die Modelldateien liegen nicht im Git. Laden und prüfen: `.venv/bin/python werkzeuge/modelle_laden.py`
(Adressen und SHA-256 stehen dort).

| Datei | Zweck | Herkunft | Lizenz | Größe | geladen |
|---|---|---|---|---|---|
| `yolox_s.onnx` | F5 Personen auf Fotos (Vorschaubilder, 640 × 640, COCO-Klasse 0 „person“) | [YOLOX 0.1.1rc0, Megvii](https://github.com/Megvii-BaseDetection/YOLOX/releases/tag/0.1.1rc0) | Apache 2.0 | 36 MB | 30.10.2026 |
| `yunet.onnx` | F5 Gesichter auf Fotos (Vorschaubilder, 640 × 640), daraus der Bildtyp Porträt/Personen | [YuNet `face_detection_yunet_2023mar.onnx`, OpenCV Zoo](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet) | MIT | 0,2 MB | 03.11.2026 |
| `clip_bild.onnx` | V3 Sujet, Bildteil (224 × 224, Merkmale 512) | [OpenCLIP ViT-B-32 `laion2b_s34b_b79k`, ONNX-Export von Immich](https://huggingface.co/immich-app/ViT-B-32__laion2b-s34b-b79k) (`visual/model.onnx`) | MIT | 352 MB | 04.11.2026 |
| `clip_text.onnx` | V3 Sujet, Textteil (77 Zeichen-IDs, Merkmale 512) | dasselbe (`textual/model.onnx`) | MIT | 254 MB | 04.11.2026 |
| `clip_tokenizer.json` | V3 Sujet, Wortliste (BPE) des Textteils, gelesen ohne Zusatzpaket | dasselbe (`textual/tokenizer.json`) | MIT | 3,6 MB | 04.11.2026 |

Neue Modelle nur nach Rückfrage (CLAUDE.md, harte Regel 5); Entscheidungen in `docs/plan.md`.
