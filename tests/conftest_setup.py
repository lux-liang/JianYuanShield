# Add project root to sys.path for unittest discovery
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
