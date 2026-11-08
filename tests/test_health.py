from unittest.mock import patch


def test_health_database_available(client, db):
    response = client.get("/health/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_database_down_hides_details(client):
    with patch("apps.core.views.connection.cursor", side_effect=RuntimeError("private database address")):
        response = client.get("/health/")
    assert response.status_code == 503
    assert b"private" not in response.content


def test_health_rejects_post(client):
    assert client.post("/health/").status_code == 405
