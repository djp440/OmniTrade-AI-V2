"""历史记录管理服务

每个交易对维护独立的分析历史列表（内存存储），支持长度限制和清空操作。
"""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING

from src.domain.events import PositionCloseEvent
from src.infrastructure.logger import Logger

if TYPE_CHECKING:
    pass


class HistoryService:
    """历史记录管理服务

    为每个交易对维护独立的分析历史记录列表，仅存储在内存中。
    新增记录时检查长度，超出限制自动删除最早记录。
    平仓完成后自动清空对应交易对历史。
    """

    def __init__(self, max_history_length: int = 10) -> None:
        """初始化历史记录服务

        Args:
            max_history_length: 分析历史最大保留条数
        """
        self._max_history_length = max_history_length
        self._logger = Logger()
        self._histories: dict[str, deque[str]] = {}

    def add_analysis_record(self, inst_id: str, compressed_analysis: str) -> None:
        """添加分析记录

        Args:
            inst_id: 交易对ID
            compressed_analysis: 压缩后的分析结果
        """
        if inst_id not in self._histories:
            self._histories[inst_id] = deque(maxlen=self._max_history_length)

        history = self._histories[inst_id]
        history.append(compressed_analysis)

        self._logger.debug(
            f"分析记录已添加: {inst_id}, "
            f"当前记录数: {len(history)}/{self._max_history_length}"
        )

    def get_history(self, inst_id: str) -> list[str]:
        """获取指定交易对的分析历史

        Args:
            inst_id: 交易对ID

        Returns:
            分析历史记录列表（按时间顺序，从早到晚）
        """
        if inst_id not in self._histories:
            return []
        return list(self._histories[inst_id])

    def get_history_text(self, inst_id: str) -> str:
        """获取格式化的历史记录文本

        Args:
            inst_id: 交易对ID

        Returns:
            格式化的历史记录文本，如果没有记录返回"无"
        """
        history = self.get_history(inst_id)
        if not history:
            return "无"

        lines = []
        for i, record in enumerate(history, 1):
            lines.append(f"{i}. {record}")
        return "\n".join(lines)

    def clear_history(self, inst_id: str) -> None:
        """清空指定交易对的分析历史

        Args:
            inst_id: 交易对ID
        """
        if inst_id in self._histories:
            self._histories[inst_id].clear()
            self._logger.info(f"分析历史已清空: {inst_id}")

    def clear_all_history(self) -> None:
        """清空所有交易对的分析历史"""
        for inst_id in self._histories:
            self._histories[inst_id].clear()
        self._logger.info("所有交易对的分析历史已清空")

    async def on_position_close(self, event: PositionCloseEvent) -> None:
        """处理平仓完成事件

        收到平仓完成事件后，立即清空对应交易对的所有分析历史记录。

        Args:
            event: 平仓完成事件
        """
        self._logger.info(f"收到平仓完成事件: {event.inst_id}")
        self.clear_history(event.inst_id)

    def get_history_count(self, inst_id: str) -> int:
        """获取指定交易对的历史记录数量

        Args:
            inst_id: 交易对ID

        Returns:
            历史记录数量
        """
        if inst_id not in self._histories:
            return 0
        return len(self._histories[inst_id])

    def is_history_full(self, inst_id: str) -> bool:
        """检查指定交易对的历史记录是否已满

        Args:
            inst_id: 交易对ID

        Returns:
            是否已满
        """
        if inst_id not in self._histories:
            return False
        return len(self._histories[inst_id]) >= self._max_history_length
