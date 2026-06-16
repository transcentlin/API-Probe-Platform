"""SQLite 数据库初始化与连接管理（详细设计 §3.1 ER 图）。

职责：
    1. 创建 4 张表：platforms / probe_sessions / stage_results / probe_requests
    2. 提供异步数据库连接管理
"""
from __future__ import annotations

from pathlib import Path

import aiosqlite

# ──────────────────────────────────────────────────────────────────────────
# 建表 SQL（详细设计 §3.1 ER 图）
# ──────────────────────────────────────────────────────────────────────────

SCHEMA_SQL = """
-- 平台基本信息
CREATE TABLE IF NOT EXISTS platforms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    base_url TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 探测会话
CREATE TABLE IF NOT EXISTS probe_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform_id INTEGER NOT NULL,
    mode TEXT NOT NULL,  -- quick/standard/deep/custom
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    status TEXT NOT NULL,  -- running/completed/failed/stopped
    FOREIGN KEY (platform_id) REFERENCES platforms(id)
);

-- 阶段结果
CREATE TABLE IF NOT EXISTS stage_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    stage INTEGER NOT NULL,  -- 0~5
    status TEXT NOT NULL,  -- success/failed/skipped
    result_json TEXT,  -- 阶段产出 JSON
    error_message TEXT,
    executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES probe_sessions(id)
);

-- 探针请求记录（支持断点续测与统计）
CREATE TABLE IF NOT EXISTS probe_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    model TEXT NOT NULL,
    probe_name TEXT NOT NULL,  -- tool_calling/vision/...
    request_body TEXT,  -- 脱敏后
    response_body TEXT,
    status_code INTEGER,
    latency_ms REAL,
    success BOOLEAN,
    executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(session_id, model, probe_name),  -- 幂等键
    FOREIGN KEY (session_id) REFERENCES probe_sessions(id)
);

-- 索引优化
CREATE INDEX IF NOT EXISTS idx_sessions_platform ON probe_sessions(platform_id);
CREATE INDEX IF NOT EXISTS idx_stage_results_session ON stage_results(session_id);
CREATE INDEX IF NOT EXISTS idx_probe_requests_session ON probe_requests(session_id);
"""


# ──────────────────────────────────────────────────────────────────────────
# 数据库管理
# ──────────────────────────────────────────────────────────────────────────


class Database:
    """SQLite 数据库管理器（异步）。"""

    def __init__(self, db_path: Path):
        """初始化数据库管理器。

        Args:
            db_path: SQLite 数据库文件路径
        """
        self.db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        """连接数据库并初始化表结构。"""
        self._conn = await aiosqlite.connect(self.db_path)
        # 启用外键约束
        await self._conn.execute("PRAGMA foreign_keys = ON")
        # 执行建表 SQL
        await self._conn.executescript(SCHEMA_SQL)
        await self._conn.commit()

    async def close(self) -> None:
        """关闭数据库连接。"""
        if self._conn:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        """获取数据库连接（供 Repository 使用）。

        Raises:
            RuntimeError: 未连接时抛出
        """
        if not self._conn:
            raise RuntimeError("数据库未连接，请先调用 connect()")
        return self._conn

    async def __aenter__(self):
        """异步上下文管理器入口。"""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口。"""
        await self.close()
