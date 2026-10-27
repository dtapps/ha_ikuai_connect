"""集成服务测试：流量排行、协议分布、离线历史、MAC 规则、万能调用。"""

from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.const import CONF_HOST, CONF_TOKEN
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.ikuai_connect.const import CONF_TRACKER_CONFIG, DOMAIN
from tests import payloads


async def _call(hass, service: str, data: dict):
    return await hass.services.async_call(
        DOMAIN, service, data, blocking=True, return_response=True
    )


async def test_get_traffic_ranking(hass, setup_integration):
    await setup_integration()

    response = await _call(hass, "get_traffic_ranking", {})

    assert response["total_flow_mb"] == 3.0
    first, second = response["devices"]
    assert first["name"] == "小米 Pad"  # termname 被 URL 解码
    assert first["total_mb"] == 2.0
    assert first["up_mb"] == 0.5
    assert second["name"] == "爸爸的手机"  # comment 优先级最高


async def test_get_protocol_stats_uses_tracked_ip(hass, setup_integration, api_stub):
    await setup_integration()

    # 大写 + 横杠的 MAC 也要能命中协调器里的数据
    response = await _call(hass, "get_protocol_stats", {"mac": "08-9B-4B-01-7E-7C"})

    assert response["mac"] == payloads.MAC1
    assert response["ip"] == "192.168.1.10"
    api_stub.get_client_protocol_stats.assert_awaited_once_with(
        payloads.MAC1, "192.168.1.10"
    )
    # 零流量协议被过滤，其余按流量降序
    assert [item["name"] for item in response["protocols"]] == ["P2P", "HTTP"]
    assert response["protocols"][0]["total_mb"] == 3.0


async def test_get_protocol_stats_without_ip_returns_error(
    hass, setup_integration, api_stub
):
    await setup_integration()

    response = await _call(hass, "get_protocol_stats", {"mac": "11:22:33:44:55:66"})

    assert "error" in response
    api_stub.get_client_protocol_stats.assert_not_awaited()


async def test_get_offline_history_formats_entries(hass, setup_integration):
    await setup_integration()

    response = await _call(hass, "get_offline_history", {})

    first, second = response["history"]
    assert first["name"] == "旧平板"
    assert first["total_usage_mb"] == 2.0  # up + down 各 1 MiB
    assert first["offline_at"] != "Unknown"
    assert first["vendor"] == "Apple"
    assert second["offline_at"] == "Unknown"  # 没有 logout_time
    assert second["name"] == "Client ee:99"  # 兜底名称（取 mac 末 5 位）


async def test_add_mac_rule_normalizes_mac_and_refreshes(
    hass, setup_integration, api_stub
):
    await setup_integration()
    refreshes_before = api_stub.get_all_data.await_count

    await hass.services.async_call(
        DOMAIN, "add_mac_rule", {"mac": "AA-BB-CC-DD-EE-FF"}, blocking=True
    )
    await hass.async_block_till_done()

    payload = api_stub.add_mac_rule.await_args.args[0]
    assert payload["mac"] == "aa:bb:cc:dd:ee:ff"
    assert payload["enabled"] == "yes"
    assert payload["tagname"] == "HA_ee:ff"
    assert payload["comment"] == "Added by HA"
    assert payload["time"] == "00:00-23:59"
    # 改完规则要重拉数据：async_request_refresh 有 10 秒防抖，拨快时钟验证
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=15))
    await hass.async_block_till_done()
    assert api_stub.get_all_data.await_count > refreshes_before


async def test_add_mac_rule_honours_overrides(hass, setup_integration, api_stub):
    await setup_integration()

    await hass.services.async_call(
        DOMAIN,
        "add_mac_rule",
        {
            "mac": "aa:bb:cc:dd:ee:ff",
            "tagname": "访客",
            "comment": "临时放行",
            "expires": 3600,
        },
        blocking=True,
    )

    payload = api_stub.add_mac_rule.await_args.args[0]
    assert payload["tagname"] == "访客"
    assert payload["comment"] == "临时放行"
    assert payload["expires"] == 3600


async def test_delete_mac_rule(hass, setup_integration, api_stub):
    await setup_integration()

    await hass.services.async_call(
        DOMAIN, "delete_mac_rule", {"rule_id": 3}, blocking=True
    )
    await hass.async_block_till_done()

    api_stub.delete_mac_rule.assert_awaited_once_with(3)


async def test_call_api_service_passes_through(hass, setup_integration, api_stub):
    await setup_integration()

    response = await _call(
        hass,
        "call_api_service",
        {"path": "/api/v4.0/monitoring/system", "method": "GET"},
    )

    assert response == {"success": True, "data": {}}
    kwargs = api_stub.call_custom_api.await_args.kwargs
    assert kwargs["method"] == "GET"
    assert kwargs["path"] == "/api/v4.0/monitoring/system"


async def test_call_api_service_rejects_lowercase_method(
    hass, setup_integration, api_stub
):
    """service schema 只收大写动词，小写会在进 handler 之前被拒。

    这是当前的对外行为：调用方必须写 GET/POST/...，写 get 会拿到 schema 校验错误。
    """
    await setup_integration()

    with pytest.raises(Exception) as err:
        await _call(
            hass,
            "call_api_service",
            {"path": "/api/v4.0/monitoring/system", "method": "get"},
        )

    assert "method" in str(err.value)
    api_stub.call_custom_api.assert_not_awaited()


async def test_call_api_service_swallows_errors(hass, setup_integration, api_stub):
    """探索性调用失败不能把 HA 服务打挂，要返回结构化失败。"""
    await setup_integration()
    api_stub.fail("call_custom_api", ValueError("path 必须以 /api/ 开头"))

    response = await _call(hass, "call_api_service", {"path": "/etc/passwd"})

    assert response["success"] is False
    assert "path 必须以 /api/ 开头" in response["message"]
    assert response["data"] is None


async def test_services_require_device_id_when_multiple_routers(
    hass, setup_integration, config_entry, api_stub
):
    await setup_integration()
    second = MockConfigEntry(
        domain=DOMAIN,
        title="第二台路由器",
        data={
            CONF_HOST: "https://10.10.10.2",
            CONF_TOKEN: "token-2",
            CONF_TRACKER_CONFIG: {},
        },
        options={},
        entry_id="ikuai_second_entry",
    )
    second.add_to_hass(hass)
    assert await hass.config_entries.async_setup(second.entry_id)
    await hass.async_block_till_done()

    with pytest.raises(ValueError, match="请通过 device_id 指定目标设备"):
        await hass.services.async_call(
            DOMAIN, "get_traffic_ranking", {}, blocking=True, return_response=True
        )

    # 指定 device_id 后能正确路由到对应 entry
    registry = dr.async_get(hass)
    devices = dr.async_entries_for_config_entry(registry, config_entry.entry_id)
    response = await hass.services.async_call(
        DOMAIN,
        "get_traffic_ranking",
        {"device_id": devices[0].id},
        blocking=True,
        return_response=True,
    )
    assert response["devices"][0]["mac"] == payloads.MAC1


async def test_service_rejects_unknown_device_id(hass, setup_integration):
    await setup_integration()

    with pytest.raises(ValueError, match="找不到设备 ID 对应的路由器"):
        await hass.services.async_call(
            DOMAIN,
            "get_traffic_ranking",
            {"device_id": "not-a-real-device"},
            blocking=True,
            return_response=True,
        )
