"""测试隔离（2026-10-23）。

问题：`app.calllog` 在**导入时**按 `CALLLOG_DB` 决定库路径，默认落到 `data/calllog.db`
—— 也就是**生产库**。测试一跑就会往里写测试数据（还会污染 /metrics 的统计口径）。

conftest 在测试模块导入**之前**执行，所以在这里改环境变量最合适：
让所有测试写到临时目录，跑完即弃，生产库一个字节都不动。
"""

import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="gw-test-calllog-")
os.environ.setdefault("CALLLOG_DB", os.path.join(_TMP, "calllog-test.db"))
# 内容上限调小，避免测试里的大 prompt 把临时库撑大
os.environ.setdefault("CALLLOG_CONTENT_MAX", "200000")

import pytest


@pytest.fixture(scope="session", autouse=True)
def _calllog_ready():
    """测试会话内把调用日志库打开（TestClient 不走 lifespan，否则 flush() 写不进临时库）。"""
    from app import calllog

    calllog.store.open()
    yield
    try:
        calllog.store.flush()
    except Exception:  # noqa: BLE001
        pass
