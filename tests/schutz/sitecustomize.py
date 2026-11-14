"""Lädt Python bei jedem Start automatisch, wenn dieser Ordner in PYTHONPATH steht (nur in den Tests, tests/conftest.py).
Schaltet die Schutzwache auch in Unterprozessen ein: Server und Hintergrundläufe dürfen /Volumes nicht berühren."""
import os

if os.environ.get("BALDUIN_SCHUTZ_PROTOKOLL"):        # nur in Prozessen, die die Tests gestartet haben
    import schutzwache

    schutzwache.einschalten()
