"""Path constants for the criticas subsystem."""

from __future__ import annotations

from pathlib import Path

from ..rag.paths import PROJECT_ROOT

# processos-criticas lives as a sibling of this project's root
_PROCESSOS_CRITICAS = PROJECT_ROOT.parent.parent.parent / "processos-criticas"

CRITICAS_DIR = _PROCESSOS_CRITICAS / "src" / "criticas"
CRITICAS_TS = _PROCESSOS_CRITICAS / "src" / "constants" / "criticas.ts"
PROJETO_DIR = _PROCESSOS_CRITICAS
