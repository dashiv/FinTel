import sys, os
from loguru import logger

def setup_logger(log_level="INFO", log_file="logs/fintel.log"):
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    logger.remove()
    logger.add(
        sys.stdout,
        level=log_level,
        format="<green>{time:HH:mm:ss}</green> | <level>{level:<8}</level> | <level>{message}</level>",
        colorize=True,
    )
    logger.add(
        log_file,
        level=log_level,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {name}:{line} | {message}",
        rotation="1 day",
        retention="7 days",
    )
    return logger

setup_logger()
