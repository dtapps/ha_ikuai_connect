"""集成入口测试：setup、unload、选项重载、服务生命周期。"""

from __future__ import annotations

from datetime import timedelta

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_SCAN_INTERVAL, CONF_TOKEN
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ikuai_connect.const import (
    CONF_TRACKER_CONFIG,
    DOMAIN,
    PLATFORMS,
)
from tests import payloads


def _unique_ids_by_domain(hass, entry) -> dict[str, set[str]]:
    registry = er.async_get(hass)
    grouped: dict[str, set[str]] = {}
    for item in er.async_entries_for_config_entry(registry, entry.entry_id):
        grouped.setdefault(item.domain, set()).add(item.unique_id)
    return grouped


async def test_setup_creates_entities_for_every_platform(hass, setup_integration):
    entry = await setup_integration()
    grouped = _unique_ids_by_domain(hass, entry)

    assert {platform.value for platform in PLATFORMS} <= set(grouped)

    assert f"{payloads.GWID}_cpu_load" in grouped["sensor"]
    assert f"{payloads.GWID}_maint_upgrade_status" in grouped["sensor"]
    assert f"{payloads.GWID}_disk_sda_disk_usage_rate" in grouped["sensor"]
    assert f"{payloads.GWID}_mac_mode_mac_acl_mode" in grouped["select"]
    assert f"{payloads.GWID}_ctrl_create_backup" in grouped["button"]
    assert f"{payloads.GWID}_sec_macrule_3" in grouped["switch"]
    assert f"{payloads.GWID}_track_089b4b017e7c" in grouped["device_tracker"]
    assert f"{payloads.GWID}_event_terminal_presence_log" in grouped["event"]


async def test_setup_registers_all_services(hass, setup_integration):
    await setup_integration()

    for service in (
        "get_traffic_ranking",
        "get_protocol_stats",
        "get_offline_history",
        "add_mac_rule",
        "delete_mac_rule",
        "call_api_service",
    ):
        assert hass.services.has_service(DOMAIN, service), service


async def test_update_interval_comes_from_options(
    hass, setup_integration, config_entry
):
    await setup_integration()

    assert config_entry.runtime_data.update_interval == timedelta(seconds=30)


async def test_options_update_triggers_reload(
    hass, setup_integration, config_entry, api_stub
):
    await setup_integration()
    calls_before = api_stub.get_all_data.await_count

    hass.config_entries.async_update_entry(
        config_entry,
        options={**config_entry.options, CONF_SCAN_INTERVAL: 60},
    )
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.LOADED
    assert config_entry.runtime_data.update_interval == timedelta(seconds=60)
    # 重载 = 重新拉一遍数据
    assert api_stub.get_all_data.await_count > calls_before


async def test_unload_clears_entities_and_services(
    hass, setup_integration, config_entry
):
    await setup_integration()

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.NOT_LOADED
    assert not hass.services.has_service(DOMAIN, "call_api_service")
    # HA 的语义：注册表里仍有记录的实体，条目卸载后状态变 unavailable，
    # 状态对象本身留在状态机里（不是消失）。这条钉住这个语义，别按「清空」去写。
    sensor_ids = hass.states.async_entity_ids("sensor")
    assert sensor_ids
    assert all(hass.states.get(eid).state == "unavailable" for eid in sensor_ids)


async def test_services_survive_until_last_entry_unloads(
    hass, setup_integration, config_entry, api_stub
):
    """多路由器场景：卸载其中一台不能把服务摘掉，否则另一台的服务全废。"""
    await setup_integration()
    second = MockConfigEntry(
        domain=DOMAIN,
        title="第二台路由器",
        data={
            CONF_HOST: "https://10.10.10.2",
            CONF_TOKEN: "token-2",
            CONF_TRACKER_CONFIG: {},
        },
        options={CONF_SCAN_INTERVAL: 15},
        entry_id="ikuai_second_entry",
    )
    second.add_to_hass(hass)
    assert await hass.config_entries.async_setup(second.entry_id)
    await hass.async_block_till_done()
    assert second.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.services.has_service(DOMAIN, "call_api_service")

    assert await hass.config_entries.async_unload(second.entry_id)
    await hass.async_block_till_done()
    assert not hass.services.has_service(DOMAIN, "call_api_service")


async def test_setup_retries_when_router_unreachable(hass, config_entry, api_stub):
    api_stub.fail("get_all_data", RuntimeError("router offline"))

    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.SETUP_RETRY
    # 第一次刷新失败就不能注册服务，否则服务指向一个没有协调器的集成
    assert not hass.services.has_service(DOMAIN, "call_api_service")
