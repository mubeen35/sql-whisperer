"""Root conftest — adds src/ to sys.path so pytest can find db_mcp."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
