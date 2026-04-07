"""PageFly 入口 — 初始化 + 手动测试入口。"""

from src.shared.logger import get_logger
from src.storage.db import init_db

logger = get_logger("main")


def setup() -> None:
    """初始化系统。"""
    init_db()
    logger.info("PageFly initialized")


if __name__ == "__main__":
    setup()
    logger.info("PageFly is ready. Use ingest/pipeline.py to add documents.")
