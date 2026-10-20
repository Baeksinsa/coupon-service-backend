import os
import sys
from pathlib import Path

# backend/ 를 import 경로에 올린다
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# 테스트는 외부 의존성 없이 import 가능해야 한다
os.environ.setdefault("CACHE_ENABLED", "false")
os.environ.setdefault("ADMIN_TOKEN", "test-token")
