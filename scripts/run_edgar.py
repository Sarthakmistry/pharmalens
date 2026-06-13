"""
One-shot script: run the compiler on all local EDGAR files not yet in wiki sources.
Bypasses the full GCS file scan so only local raw/edgar/ files are processed.
"""
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv
load_dotenv()

from agents.orchestrator import run_daily_pipeline
from agents import state as state_mod

# --- patch get_unprocessed_files to return only local edgar files not in state ---
import agents.state as _state

_original = _state.get_unprocessed_files

def _edgar_only():
    all_files = _original()
    edgar = [f for f in all_files if "edgar" in f.parts]
    print(f"[run_edgar] {len(all_files)} total unprocessed → {len(edgar)} edgar files queued")
    for f in sorted(edgar):
        print(f"  {f.relative_to(BASE_DIR)}")
    return edgar

_state.get_unprocessed_files = _edgar_only

# also patch in orchestrator module's imported reference
import agents.orchestrator as _orch
_orch.get_unprocessed_files = _edgar_only

run_daily_pipeline()
