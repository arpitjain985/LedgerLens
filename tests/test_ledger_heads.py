from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_ledger_heads_returns_full_taxonomy_no_auth_needed():
    """This is a static reference list, not firm data -- no token required."""
    resp = client.get("/ledger-heads")
    assert resp.status_code == 200
    heads = resp.json()
    assert len(heads) == 20
    codes = {h["code"] for h in heads}
    assert "RENT" in codes
    assert "SALARY" in codes
    assert all("label" in h for h in heads)
