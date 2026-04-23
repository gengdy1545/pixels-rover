import pytest

from tests.conftest import auth_header, make_access_token

pytestmark = pytest.mark.asyncio


async def create_thread(async_client, token: str, *, title: str = "Conversation A") -> dict:
    resp = await async_client.post(
        "/api/v1/conversations",
        json={"backendId": "mock-backend", "schemaName": "test_schema", "title": title},
        headers=auth_header(token),
    )
    assert resp.status_code == 200
    return resp.json()["data"]


async def test_create_and_list_conversations(async_client):
    token = make_access_token(user_id=1, email="user1@example.com")
    created = await create_thread(async_client, token)

    resp = await async_client.get("/api/v1/conversations", headers=auth_header(token))
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["data"]) == 1
    assert body["data"][0]["threadId"] == created["threadId"]
    assert body["data"][0]["backendId"] == "mock-backend"


async def test_get_conversation_is_user_scoped(async_client):
    token_user_1 = make_access_token(user_id=1, email="user1@example.com")
    token_user_2 = make_access_token(user_id=2, email="user2@example.com")

    created = await create_thread(async_client, token_user_1)

    resp = await async_client.get(
        f"/api/v1/conversations/{created['threadId']}",
        headers=auth_header(token_user_2),
    )
    assert resp.status_code == 404


async def test_patch_conversation_title_and_status(async_client):
    token = make_access_token(user_id=1, email="user1@example.com")
    created = await create_thread(async_client, token)

    resp = await async_client.patch(
        f"/api/v1/conversations/{created['threadId']}",
        json={"title": "Renamed Thread", "status": "archived"},
        headers=auth_header(token),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["title"] == "Renamed Thread"
    assert body["data"]["status"] == "archived"


async def test_archived_thread_rejects_new_analysis(async_client):
    token = make_access_token(user_id=1, email="user1@example.com")
    created = await create_thread(async_client, token)

    archive_resp = await async_client.patch(
        f"/api/v1/conversations/{created['threadId']}",
        json={"status": "archived"},
        headers=auth_header(token),
    )
    assert archive_resp.status_code == 200

    resp = await async_client.post(
        "/api/v1/analysis",
        json={"question": "What is the total revenue?", "threadId": created["threadId"]},
        headers=auth_header(token),
    )
    assert resp.status_code == 409


async def test_analysis_requires_thread_id(async_client):
    token = make_access_token(user_id=1, email="user1@example.com")
    resp = await async_client.post(
        "/api/v1/analysis",
        json={"question": "What is the total revenue?"},
        headers=auth_header(token),
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["details"]["errorCode"] == "ANALYSIS_INVALID_ARGUMENT"
    assert body["details"]["category"] == "USER_INPUT"
