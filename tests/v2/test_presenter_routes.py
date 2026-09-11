from fastapi.testclient import TestClient

from v2.main import app


def test_presenter_has_separate_chat_and_tasks_routes(monkeypatch) -> None:
    monkeypatch.delenv("FOUNDRY_V2_COMMANDER_ENDPOINT", raising=False)

    with TestClient(app) as client:
        redirect = client.get("/v2", follow_redirects=False)
        chat = client.get("/v2/chat")
        tasks = client.get("/v2/tasks")

    assert redirect.status_code == 307
    assert redirect.headers["location"] == "/v2/chat"
    assert chat.status_code == 200
    assert tasks.status_code == 200
    assert 'id="panel-chat"' in chat.text
    assert 'id="panel-tasks"' in tasks.text
