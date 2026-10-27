"""平台层测试：传感器取值、开关/选择器/按钮驱动 API、设备追踪状态。"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock

from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.ikuai_connect.button import IkuaiButton
from custom_components.ikuai_connect.const import DOMAIN
from tests import payloads
from tests.conftest import find_entity_id, state_of


async def test_system_sensors(hass, setup_integration):
    await setup_integration()

    assert state_of(hass, "sensor", f"{payloads.GWID}_cpu_load").state == "12.0"
    assert state_of(hass, "sensor", f"{payloads.GWID}_memory_usage").state == "45.0"
    assert state_of(hass, "sensor", f"{payloads.GWID}_uptime").state == "3725"
    assert state_of(hass, "sensor", f"{payloads.GWID}_online_users").state == "7"
    assert state_of(hass, "sensor", f"{payloads.GWID}_ap_online").state == "2"


async def test_wan_and_balance_sensors(hass, setup_integration):
    await setup_integration()

    wan_ip = state_of(hass, "sensor", f"{payloads.GWID}_iface_adsl0_ipv4_addr")
    assert wan_ip.state == "1.2.3.4"

    balance = state_of(hass, "sensor", f"{payloads.GWID}_wan_balance_balance_snapshot")
    assert balance.state == "2/3 在线"


async def test_maintenance_and_disk_sensors(hass, setup_integration):
    await setup_integration()

    upgrade = state_of(hass, "sensor", f"{payloads.GWID}_maint_upgrade_status")
    assert upgrade.state == "发现新版本: 4.0.308"

    usage = state_of(hass, "sensor", f"{payloads.GWID}_disk_sda_disk_usage_rate")
    assert usage.state == "25.0"


async def test_sensor_state_updates_after_refresh(
    hass, setup_integration, config_entry, api_stub
):
    """协调器数据变了，传感器必须跟着变（不是只在 setup 时取一次）。"""
    await setup_integration()
    entity_id = find_entity_id(hass, "sensor", f"{payloads.GWID}_cpu_load")
    assert hass.states.get(entity_id).state == "12.0"

    api_stub.results[0]["sysinfo"]["cpu"] = ["88%", "1%"]
    await config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(entity_id).state == "88.0"


async def test_switch_toggles_mac_rule(hass, setup_integration, api_stub):
    await setup_integration()
    entity_id = find_entity_id(hass, "switch", f"{payloads.GWID}_sec_macrule_3")

    assert hass.states.get(entity_id).state == "on"  # enabled == "yes"

    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": entity_id}, blocking=True
    )
    await hass.async_block_till_done()
    api_stub.toggle_mac_rule.assert_awaited_with(3, False)

    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": entity_id}, blocking=True
    )
    await hass.async_block_till_done()
    api_stub.toggle_mac_rule.assert_awaited_with(3, True)


async def test_switch_reports_rule_attributes(hass, setup_integration):
    await setup_integration()
    entity_id = find_entity_id(hass, "switch", f"{payloads.GWID}_sec_macrule_3")

    attributes = hass.states.get(entity_id).attributes
    assert attributes["rule_id"] == "3"
    assert attributes["mac_address"] == "aa"
    assert attributes["expires"] is not None


async def test_select_shows_and_changes_acl_mode(hass, setup_integration, api_stub):
    await setup_integration()
    entity_id = find_entity_id(hass, "select", f"{payloads.GWID}_mac_mode_mac_acl_mode")

    assert hass.states.get(entity_id).state == "whitelist"  # acl_mac == 1

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": entity_id, "option": "blacklist"},
        blocking=True,
    )
    await hass.async_block_till_done()

    api_stub.set_mac_mode.assert_awaited_with(0)

    # 状态以路由器回读为准：模拟路由器已切到黑名单后再刷新
    api_stub.results[11] = {"acl_mac": 0}
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=15))
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == "blacklist"


async def test_button_press_triggers_backup(
    hass, setup_integration, api_stub, monkeypatch
):
    # 通知与延迟刷新跟本次断言无关，替换掉以免留下后台任务
    monkeypatch.setattr(IkuaiButton, "_send_notification", AsyncMock())
    monkeypatch.setattr(IkuaiButton, "_delayed_refresh", AsyncMock())
    await setup_integration()
    entity_id = find_entity_id(hass, "button", f"{payloads.GWID}_ctrl_create_backup")

    await hass.services.async_call(
        "button", "press", {"entity_id": entity_id}, blocking=True
    )
    await hass.async_block_till_done()

    api_stub.trigger_backup.assert_awaited_once()


async def test_reboot_button_is_disabled_by_default(hass, setup_integration):
    """重启按钮默认禁用：误触的代价太大，用户要手动开。"""
    await setup_integration()
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "button", DOMAIN, f"{payloads.GWID}_ctrl_reboot"
    )

    assert entity_id is not None  # 注册表里有记录
    assert hass.states.get(entity_id) is None  # 但不进状态机
    assert registry.async_get(entity_id).disabled_by is not None


async def test_button_press_triggers_reboot(
    hass, setup_integration, config_entry, api_stub, monkeypatch
):
    monkeypatch.setattr(IkuaiButton, "_send_notification", AsyncMock())
    await setup_integration()
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "button", DOMAIN, f"{payloads.GWID}_ctrl_reboot"
    )

    # 用户手动启用后重载条目，按钮才真正建出来
    registry.async_update_entity(entity_id, disabled_by=None)
    await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()

    await hass.services.async_call(
        "button", "press", {"entity_id": entity_id}, blocking=True
    )
    await hass.async_block_till_done()

    api_stub.trigger_immediate_reboot.assert_awaited_once()


async def test_button_survives_api_error(
    hass, setup_integration, api_stub, monkeypatch
):
    """动作失败只记日志，不能把实体打挂。"""
    monkeypatch.setattr(IkuaiButton, "_send_notification", AsyncMock())
    await setup_integration()
    api_stub.fail("trigger_backup", RuntimeError("backup failed"))
    entity_id = find_entity_id(hass, "button", f"{payloads.GWID}_ctrl_create_backup")

    await hass.services.async_call(
        "button", "press", {"entity_id": entity_id}, blocking=True
    )
    await hass.async_block_till_done()

    assert hass.states.get(entity_id) is not None


async def test_device_tracker_reports_home(hass, setup_integration):
    await setup_integration()
    entity_id = find_entity_id(
        hass, "device_tracker", f"{payloads.GWID}_track_089b4b017e7c"
    )

    state = hass.states.get(entity_id)
    assert state.state == "home"
    assert state.attributes["source_type"] == "router"
    assert state.attributes["ip_address"] == "192.168.1.10"
    assert state.attributes["mac_address"] == payloads.MAC1


async def test_device_tracker_entity_removed_when_untracked(
    hass, setup_integration, config_entry
):
    """从选项里删掉终端后，设备追踪实体必须从注册表物理删除。"""
    await setup_integration()
    entity_id = find_entity_id(
        hass, "device_tracker", f"{payloads.GWID}_track_089b4b017e7c"
    )

    hass.config_entries.async_update_entry(
        config_entry,
        options={**config_entry.options, "tracker_config": {}},
    )
    await hass.async_block_till_done()

    assert hass.states.get(entity_id) is None
