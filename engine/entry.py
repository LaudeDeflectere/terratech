"""PyInstaller entry point (the packaged engine executable is built from this file)."""
import sys

from dgm_engine.cli import main

if __name__ == '__main__':
    sys.exit(main())
