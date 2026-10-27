"""api 模块单元测试：请求封装、缓存、负缓存、重试、通用调用、动作方法。

不依赖 Home Assistant：`async_get_clientsession` 被换成 FakeSession。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import pytest

from tests.doubles import FakeResponse, FakeSession


def _body(results=None, code: int = 0) -> str:
    return json.dumps({"code": code, "results": results if results is not None else {}})


def _ok_session() -> FakeSession:
    """一个立刻返回 200 空 results 的会话。"""
    return FakeSession(FakeResponse(200, _body({})))


# ---------------------------------------------------------------- 请求基础行为


@pytest.mark.asyncio
async def test_request_returns_results_and_sends_bearer(make_api):
    api, session = make_api(FakeSession(FakeResponse(200, _body({"data": [1]}))))
    result = await api.get_lan_devices()

    assert result == {"data": [1]}
    call = session.calls[0]
    assert call["method"] == "GET"
    assert (
        call["url"] == "https://10.0.0.1/api/v4.0/monitoring/clients-online?limit=500"
    )
    assert call["headers"]["Authorization"] == "Bearer test-token"
    assert call["ssl"] is False


@pytest.mark.asyncio
async def test_host_trailing_slash_normalized(make_api):
    api, session = make_api(FakeSession(), host="https://10.0.0.1/")
    await api.get_system_info()
    assert session.calls[0]["url"] == "https://10.0.0.1/api/v4.0/monitoring/system"


@pytest.mark.asyncio
async def test_invalid_json_timeout_marker_is_patched(make_api):
    """iKuai 偶发返回 "data":timeout 非法 JSON，必须被修补成空列表。"""
    raw = '{"code":0,"results":{"data":timeout}}'
    api, _ = make_api(FakeSession(FakeResponse(200, raw)))

    assert await api.get_system_info() == {"data": []}


# ---------------------------------------------------------------- 缓存与负缓存


@pytest.mark.asyncio
async def test_ttl_cache_hit_skips_second_request(make_api):
    api, session = make_api(
        FakeSession(
            FakeResponse(200, _body({"data": ["a"]})), FakeResponse(200, _body())
        )
    )
    first = await api.get_lan_devices()
    second = await api.get_lan_devices()

    assert first == second == {"data": ["a"]}
    assert len(session.calls) == 1


@pytest.mark.asyncio
async def test_zero_ttl_endpoint_always_refetches(make_api):
    api, session = make_api(
        FakeSession(
            FakeResponse(200, _body({"n": 1})), FakeResponse(200, _body({"n": 2}))
        )
    )
    await api.get_system_info()
    second = await api.get_system_info()

    assert second == {"n": 2}
    assert len(session.calls) == 2


@pytest.mark.asyncio
async def test_expired_cache_refetches(make_api):
    api, session = make_api(FakeSession(FakeResponse(200, _body({"data": ["new"]}))))
    api._cache["/api/v4.0/monitoring/clients-online?limit=500"] = (
        0.0,  # 时间戳远古 → TTL 15 秒已过期
        {"data": ["stale"]},
    )

    assert await api.get_lan_devices() == {"data": ["new"]}
    assert len(session.calls) == 1


@pytest.mark.asyncio
async def test_404_enters_negative_cache_and_skips_http(make_api):
    api, session = make_api(FakeSession(FakeResponse(404, "")))

    assert await api.get_mac_mode() == {}
    assert api._failed_until["/api/v4.0/security/mac-mode"] > 0

    # 第二次直接命中负缓存，不再发起请求
    assert await api.get_mac_mode() == {}
    assert len(session.calls) == 1


@pytest.mark.asyncio
async def test_5xx_retries_once_via_raw_request(make_api):
    api, session = make_api(
        FakeSession(FakeResponse(500, ""), FakeResponse(200, _body({"ok": True})))
    )

    assert await api.get_system_info() == {"ok": True}
    assert len(session.calls) == 2


@pytest.mark.asyncio
async def test_exception_falls_back_to_cached_value(make_api):
    api, session = make_api(
        FakeSession(
            FakeResponse(200, _body({"data": ["cached"]})), RuntimeError("boom")
        )
    )
    endpoint = "/api/v4.0/monitoring/clients-online?limit=500"
    assert await api.get_lan_devices() == {"data": ["cached"]}

    api._cache[endpoint] = (0.0, {"data": ["cached"]})  # 让缓存过期，逼迫重新请求
    assert await api.get_lan_devices() == {"data": ["cached"]}
    assert len(session.calls) == 2


@pytest.mark.asyncio
async def test_exception_without_cache_propagates(make_api):
    api, _ = make_api(FakeSession(RuntimeError("connection reset")))

    with pytest.raises(RuntimeError, match="connection reset"):
        await api.get_system_info()


# ---------------------------------------------------------------- 通用调用


@pytest.mark.asyncio
async def test_call_custom_api_rejects_non_api_path(make_api):
    api, _ = make_api()

    with pytest.raises(ValueError, match=r"path 必须以 /api/ 开头"):
        await api.call_custom_api("GET", "/etc/passwd")


@pytest.mark.asyncio
async def test_call_custom_api_get_builds_query_string(make_api):
    api, session = make_api(_ok_session())
    await api.call_custom_api("GET", "/api/v4.0/custom", params={"a": 1, "b": "x y"})

    url = session.calls[0]["url"]
    assert session.calls[0]["method"] == "GET"
    assert session.calls[0]["json"] is None
    assert parse_qs(urlparse(url).query) == {"a": ["1"], "b": ["x y"]}


@pytest.mark.asyncio
async def test_call_custom_api_get_appends_with_ampersand(make_api):
    api, session = make_api(_ok_session())
    await api.call_custom_api("GET", "/api/v4.0/custom?fixed=1", params={"a": 1})

    assert session.calls[0]["url"] == "https://10.0.0.1/api/v4.0/custom?fixed=1&a=1"


@pytest.mark.asyncio
async def test_call_custom_api_parses_string_params_as_json(make_api):
    api, session = make_api(_ok_session())
    await api.call_custom_api("GET", "/api/v4.0/custom", params='{"a": 2}')

    assert session.calls[0]["url"].endswith("?a=2")


@pytest.mark.asyncio
async def test_call_custom_api_ignores_blank_string_params(make_api):
    api, session = make_api(_ok_session())
    await api.call_custom_api("GET", "/api/v4.0/custom", params="   ")

    assert session.calls[0]["url"] == "https://10.0.0.1/api/v4.0/custom"


@pytest.mark.asyncio
async def test_call_custom_api_post_sends_json_body(make_api):
    api, session = make_api(_ok_session())
    await api.call_custom_api("POST", "/api/v4.0/custom", params={"a": 1})

    assert session.calls[0]["json"] == {"a": 1}


@pytest.mark.asyncio
async def test_call_custom_api_strips_results_envelope(make_api):
    api, _ = make_api(
        FakeSession(
            FakeResponse(200, json.dumps({"code": 0, "results": {"data": [1]}}))
        )
    )
    result = await api.call_custom_api("GET", "/api/v4.0/custom")

    assert result == {
        "success": True,
        "status": 200,
        "code": 0,
        "message": None,
        "data": {"data": [1]},
    }


@pytest.mark.asyncio
async def test_call_custom_api_raw_keeps_envelope(make_api):
    api, _ = make_api(
        FakeSession(
            FakeResponse(200, json.dumps({"code": 0, "results": {"data": [1]}}))
        )
    )
    result = await api.call_custom_api("GET", "/api/v4.0/custom", raw=True)

    assert result["data"] == {"code": 0, "results": {"data": [1]}}


@pytest.mark.asyncio
async def test_call_custom_api_tolerates_invalid_json(make_api):
    api, _ = make_api(FakeSession(FakeResponse(200, "not json at all")))
    result = await api.call_custom_api("GET", "/api/v4.0/custom")

    assert result["success"] is True
    assert result["data"] == {"_raw_text": "not json at all"}


@pytest.mark.asyncio
async def test_call_custom_api_wraps_non_dict_payload(make_api):
    """接口返回 JSON 数组 / 标量时用 _raw 包一层，不让调用方拿到非 dict。"""
    api, _ = make_api(FakeSession(FakeResponse(200, "[1, 2, 3]")))
    result = await api.call_custom_api("GET", "/api/v4.0/custom")

    assert result["data"] == {"_raw": [1, 2, 3]}


@pytest.mark.asyncio
async def test_call_custom_api_reports_http_failure(make_api):
    api, _ = make_api(
        FakeSession(FakeResponse(503, json.dumps({"code": 1, "message": "busy"})))
    )
    result = await api.call_custom_api("GET", "/api/v4.0/custom")

    assert result["success"] is False
    assert result["status"] == 503
    assert result["message"] == "busy"


# ---------------------------------------------------------------- 动作方法


@pytest.mark.parametrize(
    ("invoke", "method", "endpoint", "payload"),
    [
        (lambda api: api.trigger_backup(), "POST", "/api/v4.0/system/backup", None),
        (
            lambda api: api.check_upgrade(),
            "POST",
            "/api/v4.0/system/upgrade:check",
            None,
        ),
        (
            lambda api: api.start_upgrade(),
            "POST",
            "/api/v4.0/system/upgrade:start",
            {"type": "system"},
        ),
        (
            lambda api: api.set_mac_mode(1),
            "PUT",
            "/api/v4.0/security/mac-mode",
            {"acl_mac": 1},
        ),
        (
            lambda api: api.toggle_mac_rule(7, True),
            "PATCH",
            "/api/v4.0/security/mac-rules/7",
            {"enabled": "yes"},
        ),
        (
            lambda api: api.toggle_mac_rule(7, False),
            "PATCH",
            "/api/v4.0/security/mac-rules/7",
            {"enabled": "no"},
        ),
        (
            lambda api: api.delete_mac_rule(9),
            "DELETE",
            "/api/v4.0/security/mac-rules/9",
            None,
        ),
    ],
)
@pytest.mark.asyncio
async def test_action_methods_use_correct_verb_path_payload(
    make_api, invoke, method, endpoint, payload
):
    api, session = make_api(FakeSession(FakeResponse(200, _body({}))))
    await invoke(api)

    call = session.calls[0]
    assert call["method"] == method
    assert call["url"] == f"https://10.0.0.1{endpoint}"
    assert call["json"] == payload


@pytest.mark.asyncio
async def test_add_mac_rule_returns_results_and_invalidates_cache(make_api):
    api, session = make_api(FakeSession(FakeResponse(200, _body({"id": 11}))))
    api._cache["/api/v4.0/security/mac-rules?limit=100"] = (9e9, {"data": []})

    result = await api.add_mac_rule({"mac": "aa:bb"})

    assert result == {"id": 11}
    assert session.calls[0]["json"] == {"mac": "aa:bb"}
    assert "/api/v4.0/security/mac-rules?limit=100" not in api._cache


@pytest.mark.asyncio
async def test_trigger_backup_invalidates_backup_cache(make_api):
    api, _ = make_api(FakeSession(FakeResponse(200, _body({}))))
    api._cache["/api/v4.0/system/backup"] = (9e9, {"backup_info": []})

    assert await api.trigger_backup() is True
    assert "/api/v4.0/system/backup" not in api._cache


@pytest.mark.asyncio
async def test_check_upgrade_invalidates_upgrade_info_cache(make_api):
    api, _ = make_api(FakeSession(FakeResponse(200, _body({}))))
    api._cache["/api/v4.0/system/upgrade"] = (9e9, {"data": {}})

    assert await api.check_upgrade() is True
    assert "/api/v4.0/system/upgrade" not in api._cache


@pytest.mark.asyncio
async def test_trigger_immediate_reboot_schedules_one_minute_ahead(
    make_api, monkeypatch
):
    api, session = make_api(FakeSession(FakeResponse(200, _body({}))))

    before = datetime.now(ZoneInfo("Asia/Shanghai")) + timedelta(minutes=1)
    assert await api.trigger_immediate_reboot() is True
    after = datetime.now(ZoneInfo("Asia/Shanghai")) + timedelta(minutes=1)

    payload = session.calls[0]["json"]
    assert (
        session.calls[0]["url"] == "https://10.0.0.1/api/v4.0/system/reboot-schedules"
    )
    assert payload["event"] == "reboot"
    assert payload["strategy"] == "one"
    assert payload["enabled"] == "yes"
    assert payload["tagname"] == "HA_Reboot"
    assert {before.strftime("%H:%M"), after.strftime("%H:%M")} >= {payload["time"]}
    assert payload["cycle_time"] in {
        before.strftime("%Y-%m-%d"),
        after.strftime("%Y-%m-%d"),
    }


# ---------------------------------------------------------------- 批量拉取与端点拼装


@pytest.mark.asyncio
async def test_get_all_data_preserves_documented_order(make_api):
    api, _ = make_api()
    order = [
        "get_system_info",
        "get_lan_devices",
        "get_wifi_stats",
        "get_wifi_score",
        "get_v6_traffic",
        "get_iface_status",
        "get_message_center",
        "get_presence_logs",
        "get_ddns_logs",
        "get_wireless_logs",
        "get_system_logs",
        "get_mac_mode",
        "get_mac_rules",
        "get_backup_list",
        "get_upgrade_info",
        "get_upgrade_status",
        "get_disks",
    ]

    def make_stub(name):
        async def _stub():
            return {name: True}

        return _stub

    for name in order:
        api.__dict__[name] = make_stub(name)

    results = await api.get_all_data()

    assert results == [{name: True} for name in order]


@pytest.mark.asyncio
async def test_get_all_data_keeps_exceptions_in_slot(make_api):
    api, _ = make_api()

    async def boom():
        raise RuntimeError("endpoint down")

    api.__dict__["get_system_info"] = boom
    results = await api.get_all_data()

    # 协调器靠这个位置拿到异常对象做降级，顺序不能错
    assert isinstance(results[0], RuntimeError)
    assert len(results) == 17


@pytest.mark.parametrize(
    ("invoke", "endpoint"),
    [
        (
            lambda api: api.get_offline_history(5),
            "/api/v4.0/monitoring/clients-offline?limit=5&order=desc&order_by=logout_time&page=1",
        ),
        (
            lambda api: api.get_client_traffic_summary(),
            "/api/v4.0/monitoring/clients-traffic-summary?limit=100",
        ),
        (
            lambda api: api.get_client_protocol_stats("aa:bb", "1.2.3.4"),
            "/api/v4.0/monitoring/clients/protocols?mac=aa:bb&ip=1.2.3.4",
        ),
        (
            lambda api: api.get_system_logs(),
            "/api/v4.0/log/system?limit=10&order=desc&order_by=id",
        ),
        (lambda api: api.get_upgrade_status(), "/api/v4.0/system/upgrade:status"),
        (lambda api: api.get_disks(), "/api/v4.0/system/disks"),
    ],
)
@pytest.mark.asyncio
async def test_endpoint_paths(make_api, invoke, endpoint):
    api, session = make_api(FakeSession(FakeResponse(200, _body({}))))
    await invoke(api)

    assert session.calls[0]["url"] == f"https://10.0.0.1{endpoint}"
