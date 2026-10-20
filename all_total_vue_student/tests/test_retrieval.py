import pytest
from agent.retrieval import RunbookIndex


@pytest.fixture(scope="module")
def index():
    x = RunbookIndex()
    x.build()
    return x


@pytest.mark.parametrize(
    "query,expected",
    [
        ("CPU saturation high processor usage", "cpu-spike"),
        ("메모리를 반환하지 않아 힙이 계속 커지고 있어요", "memory-leak"),
        ("no space left on device disk space low", "disk-full"),
        ("upstream timeout 504 network packet loss", "network-timeout"),
        ("p95 latency connection pool exhausted", "high-latency"),
        ("데이터베이스에 접속할 수 없고 복제도 중단되었습니다", "db-down"),
    ],
)
def test_real_multilingual_dense_retrieval(index, query, expected):
    hits = index.search(query)
    assert hits and hits[0]["incident_type"] == expected
    assert hits[0]["uri"].endswith(expected)


def test_threshold_can_abstain(index):
    assert index.search("CPU saturation", min_score=1.1) == []
