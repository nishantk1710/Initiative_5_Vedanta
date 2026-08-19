import os

# Anchored to this file's location (python/), not the process cwd — so
# results/ always resolves to the same place regardless of where uvicorn
# (or a one-off script) was launched from.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS_DIR = os.path.join(REPO_ROOT, "results")


def document_dir(document_id: str) -> str:
    return os.path.join(RESULTS_DIR, document_id)
