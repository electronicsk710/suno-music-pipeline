import logging
import logging.handlers
import os
from datetime import datetime

# Create logs directory if it doesn't exist
os.makedirs("logs", exist_ok=True)

def setup_logger(name, log_level=logging.INFO):
    """
    Configure logging for the application.
    Logs to both console and file.
    """
    logger = logging.getLogger(name)
    logger.setLevel(log_level)
    
    # Log file path
    log_filename = f"logs/{datetime.now().strftime('%Y%m%d')}.log"
    
    # Create formatters
    file_formatter = logging.Formatter(
        '[%(asctime)s] %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_formatter = logging.Formatter(
        '%(levelname)s: %(message)s'
    )
    
    # File handler (rotating)
    file_handler = logging.handlers.RotatingFileHandler(
        log_filename,
        maxBytes=10485760,  # 10MB
        backupCount=5
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(file_formatter)
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(console_formatter)
    
    # Add handlers to logger
    if not logger.handlers:
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
    
    return logger

# Create logger for app
logger = setup_logger("music_pipeline")
