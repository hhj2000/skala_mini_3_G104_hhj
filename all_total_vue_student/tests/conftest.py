import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["MONITORING_FIXED"] = "1"
os.environ["LLM_BACKEND"] = "fake"
os.environ["AGENT_MODE"] = "improved"
# Unit tests must not inherit real-runtime options from the developer's .env.
# Tests exercising the model guard or vectors explicitly override these values.
os.environ["CONTENT_FILTER_MODE"] = "rules"
os.environ["SPELL_VECTOR_ENABLED"] = "0"
# The TestClient uses HTTP. Do not inherit HTTPS-only cookies from deployment .env.
os.environ['KHARAKTERES_COOKIE_SECURE'] = '0'
os.environ['REQUIRE_SESSION_SECRET'] = '0'
