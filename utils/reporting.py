import logging
import datetime


def report_status(message: str, level: str = "INFO", context: dict = None):
    """
    Sends a status update to the logging system.
    """
    timestamp = datetime.datetime.now().isoformat()
    
    log_entry = {
        "timestamp": timestamp,
        "level": level,
        "message": message,
        "context": context or {}
    }
    
    # console logging
    logging.info(f"[{level}] {message} | {context if context else ''}")
        
    return log_entry

