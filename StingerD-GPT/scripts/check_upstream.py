#!/usr/bin/env python3
"""One-shot read-only upstream check; the web server checks automatically."""
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.upstream import check
print(json.dumps(check(), indent=2))
