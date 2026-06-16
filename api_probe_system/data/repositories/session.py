"""Repository 接口与 SQLite 实现（详细设计 §3.2）。

M1 实现 ProbeSessionRepository（会话管理），其他 Repository 在后续里程碑补齐。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional, Protocol

import aiosqlite


# ──────────────────────────────────────────────────────────────────────────
# Repository 接口（详细设计 §3.2）
# ──────────────────────────────────────────────────────────────────────────


class ProbeSessionRepository(Protocol):
    """探测会话 Repository 接口。"""

    async def create_session(self, platform_id: int, mode: str) -> int:
        """创建会话，返回 session_id。"""
        ...

    async def update_status(
        self, session_id: int, status: str, completed_at: Optional[datetime] = None
    ) -> None:
        """更新会话状态。"""
        ...

    async def get_session(self, session_id: int) -> Optional[dict]:
        """查询会话详情。"""
        ...


# ──────────────────────────────────────────────────────────────────────────
# SQLite 实现
# ──────────────────────────────────────────────────────────────────────────


class SQLiteProbeSessionRepository:
    """探测会话 Repository SQLite 实现。"""

    def __init__(self, conn: aiosqlite.Connection):
        """初始化 Repository。

        Args:
            conn: aiosqlite 连接对象
        """
        self._conn = conn

    async def create_session(self, platform_id: int, mode: str) -> int:
        """创建探测会话。

        Args:
            platform_id: 平台 ID
            mode: 探测模式（quick/standard/deep/custom）

        Returns:
            新创建的 session_id
        """
        cursor = await self._conn.execute(
            """
            INSERT INTO probe_sessions (platform_id, mode, status)
            VALUES (?, ?, 'running')
            """,
            (platform_id, mode),
        )
        await self._conn.commit()
        return cursor.lastrowid

    async def update_status(
        self, session_id: int, status: str, completed_at: Optional[datetime] = None
    ) -> None:
        """更新会话状态。

        Args:
            session_id: 会话 ID
            status: 新状态（running/completed/failed/stopped）
            completed_at: 完成时间（可选）
        """
        if completed_at:
            await self._conn.execute(
                """
                UPDATE probe_sessions
                SET status = ?, completed_at = ?
                WHERE id = ?
                """,
                (status, completed_at.isoformat(), session_id),
            )
        else:
            await self._conn.execute(
                """
                UPDATE probe_sessions
                SET status = ?
                WHERE id = ?
                """,
                (status, session_id),
            )
        await self._conn.commit()

    async def get_session(self, session_id: int) -> Optional[dict]:
        """查询会话详情。

        Args:
            session_id: 会话 ID

        Returns:
            会话字典，不存在返回 None
        """
        cursor = await self._conn.execute(
            """
            SELECT id, platform_id, mode, started_at, completed_at, status
            FROM probe_sessions
            WHERE id = ?
            """,
            (session_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None

        return {
            "id": row[0],
            "platform_id": row[1],
            "mode": row[2],
            "started_at": row[3],
            "completed_at": row[4],
            "status": row[5],
        }


class SQLiteStageResultRepository:
    """阶段结果 Repository SQLite 实现（M2 完善）。"""

    def __init__(self, conn: aiosqlite.Connection):
        self._conn = conn

    async def save_stage_result(
        self,
        session_id: int,
        stage: int,
        status: str,
        result_json: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """保存阶段结果。

        Args:
            session_id: 会话 ID
            stage: 阶段编号 0~5
            status: 阶段状态（success/failed/skipped）
            result_json: 阶段产出 JSON 字符串
            error_message: 错误信息（失败时）
        """
        await self._conn.execute(
            """
            INSERT INTO stage_results (session_id, stage, status, result_json, error_message)
            VALUES (?, ?, ?, ?, ?)
            """,
            (session_id, stage, status, result_json, error_message),
        )
        await self._conn.commit()
