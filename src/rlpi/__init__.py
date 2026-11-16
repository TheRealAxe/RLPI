# Console Windows : forcer l'UTF-8 pour que les messages (→, accents) ne fassent pas planter les scripts.
import sys as _sys

for _s in (_sys.stdout, _sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
