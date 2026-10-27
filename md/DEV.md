# 二次开发记录 (Dev Notes)

本文件用于记录对 `ha_ikuai_connect` 的二次开发内容。

## 环境信息

- 上游仓库 (upstream)：https://github.com/PraxiGEN/ha_ikuai_connect
- 本仓库 (origin/fork)：https://github.com/dtapps/ha_ikuai_connect

## 同步上游

```bash
git fetch upstream
git merge upstream/main
# 或 git rebase upstream/main
```

## 测试

测试栈用 `pytest-homeassistant-custom-component`，跑在**真实 Home Assistant** 上： 集成入口、平台加载、配置流、服务全部走 HA 的真实接线，不做任何 mock 替身。 唯一被替换的是 `IkuaiAPI` 的网络方法（HTTP 细节由 `tests/test_api.py` 用假会话单独覆盖）， 这样失败信息只会指向「集成逻辑错了」，不会混进「网络抖动」。

依赖见 `requirements_test.txt`（`pytest-homeassistant-custom-component` 会带入匹配版本的 `homeassistant`，所以锁它的版本等于锁被测的 HA 版本）。本地和 CI 跑的是同一个文件、同一条命令。

```bash
make test                                                   # 跑全部（缺 .venv 会自动装依赖）
make test PYTEST_ARGS="tests/test_config_flow.py -k scan"   # 只跑一部分
```

覆盖率不在本地跑，交给 CI（`.github/workflows/codecov.yml` 上传 `coverage.xml` + `junit.xml`）。

首次 `make test` 会建 `.venv` 并拉 Home Assistant（约 300MB，实测 3~10 分钟，取决于 pip 缓存）， 之后每次跑约 8 秒。CI 里对应 `.github/workflows/codecov.yml` 和 `coveralls.yml`。

覆盖范围（当前 93%）：

| 模块                | 覆盖 | 说明                                                         |
|---------------------|------|--------------------------------------------------------------|
| `__init__.py`       | 100% | setup / unload / 选项重载 / 服务生命周期 / 多 entry 共享服务 |
| `api.py`            | 99%  | 请求封装、TTL 缓存、404 负缓存、5xx 重试、通用调用、动作方法 |
| `coordinator.py`    | 99%  | 17 槽位清洗流水线、离线缓冲、WAN 聚合、事件游标、磁盘        |
| `config_flow.py`    | 99%  | 初次安装、重配置、选项流（扫描 / 增删终端）                  |
| `services.py`       | 99%  | 5 个服务 + device_id 路由 + 错误兜底                         |
| `sensor.py`         | 92%  | 状态取值、单位、刷新联动、禁用默认值的实体                   |
| `event.py`          | 94%  | 实体创建与事件属性                                           |
| `switch.py`         | 88%  | MAC 规则开关、属性、动态增删                                 |
| `device_tracker.py` | 94%  | 在线判定、属性、取消追踪后物理删除实体                       |
| `button.py`         | 84%  | 动作分发、通知、失败不炸实体、重启按钮默认禁用               |
| `select.py`         | 100% | ACL 模式读值与切换                                           |
| `helpers.py`        | 100% | 终端名解码、标签提取、MAC 归一化                             |
| `diagnostics.py`    | 0%   | 未接入（纯字典组装，收益低）                                 |

## 开发记录

| 日期       | 模块                                                  | 改动说明                                                                                                                                                                                                                                                                           | 备注                                                                          |
|------------|-------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------|
| 2026-10-07 | helpers/config_flow/coordinator/event/services/switch | 修复 issue #42：终端名称未做 URL 编码解码。新增 `decode_term_name()` 辅助函数（对 `termname`/`client_model` 做 `unquote` 反解码，还原 `%20`→空格），并在设备发现、display_name、在线/离线事件、WiFi 事件、流量统计服务、离线历史服务、MAC 规则属性等所有读取终端名的位置统一应用。 | 上游作者认为 3.0→4.0 升级后被爱快强行填充的编码名不是问题，故自行 fork 修复。 |

---

<!-- 在此追加二次开发条目 -->
