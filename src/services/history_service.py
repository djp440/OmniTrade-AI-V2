"""
历史记录管理服务
管理分析历史记录的存储和清理
"""

from collections import defaultdict

from src.infrastructure.logger import Logger


class HistoryService:
    """历史记录管理服务"""

    def __init__(self, max_history_length: int, logger: Logger):
        self.max_history_length = max_history_length
        self.logger = logger
        # 每个交易对维护独立的历史记录
        self._history: dict[str, list[str]] = defaultdict(list)

    def add_record(self, inst_id: str, compressed_analysis: str):
        """
        添加分析记录

        Args:
            inst_id: 交易对ID
            compressed_analysis: 压缩后的分析文本
        """
        self._history[inst_id].append(compressed_analysis)

        # 如果超出最大长度，删除最早的记录
        if len(self._history[inst_id]) > self.max_history_length:
            removed = self._history[inst_id].pop(0)
            self.logger.debug(f"Removed oldest history for {inst_id}: {removed}")

        self.logger.info(
            f"Added history for {inst_id}, current length: {len(self._history[inst_id])}"
        )

    def get_history(self, inst_id: str) -> list[str]:
        """
        获取交易对的历史记录

        Args:
            inst_id: 交易对ID

        Returns:
            历史记录列表
        """
        return self._history[inst_id].copy()

    def clear_history(self, inst_id: str):
        """
        清空交易对的历史记录

        Args:
            inst_id: 交易对ID
        """
        if inst_id in self._history:
            self._history[inst_id] = []
            self.logger.info(f"Cleared history for {inst_id}")

    def get_all_inst_ids(self) -> list[str]:
        """获取所有有历史记录的交易对ID"""
        return list(self._history.keys())
