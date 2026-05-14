import json

from aisbf.coderai_broker import CoderAIBroker


def test_coderai_broker_send_request_falls_back_to_client_id_named_provider_snapshot(tmp_path):
    broker = CoderAIBroker()
    broker._state_path = tmp_path / "coderai_broker_sessions.json"
    session_key = broker._session_meta_key("zeiss-nvidia", "zeiss-nvidia")
    broker._cache.broker_set(
        session_key,
        {
            "session_id": "sess-1",
            "provider_id": "actual-coderai-provider",
            "client_id": "zeiss-nvidia",
            "closed": False,
            "metadata": {"owner_user_id": None},
        },
        ttl=120,
    )

    import asyncio

    async def _run():
        task = asyncio.create_task(
            broker.send_request("zeiss-nvidia", "models.list", {}, client_id="zeiss-nvidia", owner_user_id=None, timeout=0.01)
        )
        await asyncio.sleep(0)
        pending = next(iter(broker._pending.values()))
        assert pending.request_snapshot["provider_id"] == "actual-coderai-provider"
        task.cancel()
        try:
            await task
        except BaseException:
            pass

    asyncio.run(_run())


def test_studio_sidebar_search_input_declares_stable_search_key():
    studio_js = open("/working/aisbf/static/dashboard/studio.js", "r", encoding="utf-8").read()
    assert "data-search-key" in studio_js
    assert "setSelectionRange" in studio_js
