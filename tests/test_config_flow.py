"""配置流测试：初次安装、重配置、选项流（扫描 / 增删终端）。

选项流全部走 HA 的公开接口（async_init → async_configure），
不碰 flow 内部状态，这样重构 flow 时用例才有意义。
"""

from __future__ import annotations

from homeassistant.const import (
    CONF_HOST,
    CONF_NAME,
    CONF_SCAN_INTERVAL,
    CONF_TOKEN,
)
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.selector import SelectSelector

from custom_components.ikuai_connect.const import (
    CONF_OFFLINE_GRACE_PERIOD,
    CONF_TRACKER_CONFIG,
    DOMAIN,
)
from tests import payloads

USER_INPUT = {
    CONF_NAME: "家里的路由器",
    CONF_HOST: "https://10.10.10.1/",  # 故意带尾斜杠，验证归一化
    CONF_TOKEN: "test-token",
}


# ---------------------------------------------------------------- 初次安装


async def test_user_flow_creates_entry(hass, api_stub):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=USER_INPUT
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "家里的路由器"
    assert result["data"][CONF_HOST] == "https://10.10.10.1"  # 尾斜杠被去掉
    assert result["data"][CONF_TOKEN] == "test-token"
    assert result["data"][CONF_TRACKER_CONFIG] == {}
    api_stub.get_system_info.assert_awaited_once()


async def test_user_flow_reports_cannot_connect(hass, api_stub):
    api_stub.fail("get_system_info", RuntimeError("connection refused"))

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=USER_INPUT
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_rejects_duplicate_name(hass, config_entry, api_stub):
    """同名会撞 entity_id（出现 _2），所以在建条目前就拦住。"""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={**USER_INPUT, CONF_NAME: config_entry.title},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_NAME: "name_exists"}
    # 名称冲突不该去打路由器
    api_stub.get_system_info.assert_not_awaited()


async def test_user_flow_aborts_on_same_host(hass, config_entry, api_stub):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={**USER_INPUT, CONF_NAME: "另一台设备"},
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


# ---------------------------------------------------------------- 重新配置


async def test_reconfigure_updates_host_and_token(
    hass, config_entry, api_stub, setup_integration
):
    await setup_integration()

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "reconfigure", "entry_id": config_entry.entry_id},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_HOST: "https://10.10.10.9/", CONF_TOKEN: "new-token"},
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert config_entry.data[CONF_HOST] == "https://10.10.10.9"
    assert config_entry.data[CONF_TOKEN] == "new-token"
    # 没填的字段必须保留，不能被清空
    assert config_entry.data[CONF_TRACKER_CONFIG] == {}


async def test_reconfigure_reports_cannot_connect(hass, config_entry, api_stub):
    api_stub.fail("get_system_info", RuntimeError("nope"))

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "reconfigure", "entry_id": config_entry.entry_id},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_HOST: "https://10.10.10.9", CONF_TOKEN: "new-token"},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
    assert config_entry.data[CONF_HOST] == payloads.HOST  # 原值不动


# ---------------------------------------------------------------- 选项流


async def _options_start(hass, entry):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    return result


async def _options_base_submit(hass, result, action: str = "none"):
    return await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_SCAN_INTERVAL: 45,
            CONF_OFFLINE_GRACE_PERIOD: 3,
            "manage_action": action,
        },
    )


async def test_options_flow_saves_basic_settings(hass, config_entry, setup_integration):
    await setup_integration()
    result = await _options_start(hass, config_entry)

    result = await _options_base_submit(hass, result, action="none")

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_SCAN_INTERVAL] == 45
    assert result["data"][CONF_OFFLINE_GRACE_PERIOD] == 3
    # 已有追踪配置必须被带过来，不能被清掉
    assert payloads.MAC1 in result["data"][CONF_TRACKER_CONFIG]


async def test_options_flow_scan_lists_only_untracked_devices(
    hass, config_entry, setup_integration, api_stub
):
    await setup_integration()
    result = await _options_start(hass, config_entry)

    result = await _options_base_submit(hass, result, action="add")

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "scan"
    options = _scan_options(result["data_schema"])

    # MAC1 已在追踪列表里，不该再出现
    assert payloads.MAC1 not in options
    # 在线终端出现，且标签里是「名称优先级」的最高项
    assert "iPhone 15" in options[payloads.MAC2]
    assert "电视盒子" in options[payloads.MAC3]
    # 离线列表里那台从未在线的终端也要冒出来
    assert "aa:bb:cc:dd:ee:99" in options


async def test_options_flow_scan_reports_no_selection(
    hass, config_entry, setup_integration
):
    await setup_integration()
    result = await _options_start(hass, config_entry)
    result = await _options_base_submit(hass, result, action="add")

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"devices": []}
    )

    assert result["step_id"] == "scan"
    assert result["errors"] == {"base": "no_devices_selected"}


async def test_options_flow_scan_reports_unreachable_router(
    hass, config_entry, setup_integration, api_stub
):
    await setup_integration()
    api_stub.fail("get_lan_devices", RuntimeError("offline"))
    result = await _options_start(hass, config_entry)

    result = await _options_base_submit(hass, result, action="add")

    assert result["step_id"] == "scan"
    assert result["errors"] == {"base": "cannot_connect"}


async def test_options_flow_scan_tolerates_offline_api_failure(
    hass, config_entry, setup_integration, api_stub
):
    """离线历史是补充数据源，它挂了不能阻断整个扫描。"""
    await setup_integration()
    api_stub.fail("get_offline_history", RuntimeError("timeout"))
    result = await _options_start(hass, config_entry)

    result = await _options_base_submit(hass, result, action="add")

    options = _scan_options(result["data_schema"])
    assert payloads.MAC2 in options  # 在线列表照常返回


async def test_options_flow_adds_tracked_device(hass, config_entry, setup_integration):
    await setup_integration()
    result = await _options_start(hass, config_entry)
    result = await _options_base_submit(hass, result, action="add")

    # 选一台新终端 → 进入逐个配置
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"devices": [payloads.MAC2]}
    )
    assert result["step_id"] == "configure_devices"
    # 默认名称从标签括号里提取
    assert result["description_placeholders"]["device"].startswith("iPhone 15")
    assert result["description_placeholders"]["remaining"] == "1"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={CONF_NAME: "爸爸的手机", CONF_OFFLINE_GRACE_PERIOD: 10},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    tracker_config = result["data"][CONF_TRACKER_CONFIG]
    assert tracker_config[payloads.MAC2] == {"name": "爸爸的手机", "buffer": 10}
    # 原有的追踪项不受影响
    assert payloads.MAC1 in tracker_config


async def test_options_flow_configures_multiple_devices_in_sequence(
    hass, config_entry, setup_integration
):
    await setup_integration()
    result = await _options_start(hass, config_entry)
    result = await _options_base_submit(hass, result, action="add")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"devices": [payloads.MAC2, payloads.MAC3]}
    )

    assert result["step_id"] == "configure_devices"
    assert result["description_placeholders"]["remaining"] == "2"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={CONF_NAME: "爸爸的手机", CONF_OFFLINE_GRACE_PERIOD: 10},
    )
    # 还有第二台，不能提前收工
    assert result["step_id"] == "configure_devices"
    assert result["description_placeholders"]["remaining"] == "1"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={CONF_NAME: "电视盒子", CONF_OFFLINE_GRACE_PERIOD: 5},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    tracker_config = result["data"][CONF_TRACKER_CONFIG]
    assert tracker_config[payloads.MAC2]["name"] == "爸爸的手机"
    assert tracker_config[payloads.MAC3]["name"] == "电视盒子"


async def test_options_flow_removes_tracked_device(
    hass, config_entry, setup_integration
):
    await setup_integration()
    result = await _options_start(hass, config_entry)
    result = await _options_base_submit(hass, result, action="remove")

    assert result["step_id"] == "remove"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"devices_to_remove": [payloads.MAC1]}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert payloads.MAC1 not in result["data"][CONF_TRACKER_CONFIG]


def _scan_options(schema) -> dict[str, str]:
    """从窗体 schema 里取出 SelectSelector 的 value → label 映射。"""
    for value in schema.schema.values():
        if isinstance(value, SelectSelector):
            return {
                option["value"]: option["label"] for option in value.config["options"]
            }
    raise AssertionError("schema 里没有 SelectSelector")
