"""python -m prancha_ok_autocad            -> servidor MCP (stdio), o que o assistente roda
python -m prancha_ok_autocad instalar   -> pasta do LISP entre as confiáveis do AutoCAD
python -m prancha_ok_autocad desinstalar"""
from __future__ import annotations

import sys


def main() -> None:
    comando = sys.argv[1] if len(sys.argv) > 1 else "servir"
    if comando == "instalar":
        from .instalar import instalar

        sys.exit(instalar())
    if comando == "desinstalar":
        from .instalar import desinstalar

        sys.exit(desinstalar())
    if comando == "servir":
        from .servidor import rodar

        rodar()
        return
    print(__doc__)
    sys.exit(1)


if __name__ == "__main__":
    main()
