import os
import sys
from pathlib import Path

# Окружение задаётся до импорта модуля: режим чтения определяется при импорте.
os.environ.update(TRACKER_TOKEN="test-token", TRACKER_ORG_ID="42", TRACKER_ENV_FILE=os.devnull)
for name in ("TRACKER_CLOUD_ORG_ID", "TRACKER_AUTH_TYPE", "TRACKER_READ_ONLY", "TRACKER_API_URL"):
    os.environ.pop(name, None)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
