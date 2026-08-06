import sys
from pathlib import Path

tests = Path(__file__).parent
sys.path[:0] = [str(tests / "lib"), str(tests)]
