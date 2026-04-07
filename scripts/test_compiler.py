"""Quick test: run the compiler agent."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agents.compiler import main

if __name__ == "__main__":
    main()
