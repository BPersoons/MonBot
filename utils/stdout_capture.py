import sys
import io
from collections import deque

class StdoutCapture:
    def __init__(self, max_lines=5):
        self.max_lines = max_lines
        self.buffer = deque(maxlen=max_lines)
        self.original_stdout = sys.stdout

    def write(self, message):
        # Extremely robust write method to prevent ANY logging crashes
        text_to_buffer = ""
        try:
            # Try writing to original stdout first
            if hasattr(self.original_stdout, 'buffer'):
                 # Write bytes directly if possible to avoid encoding issues
                 if isinstance(message, str):
                      self.original_stdout.buffer.write(message.encode('utf-8', 'replace'))
                 else:
                      self.original_stdout.buffer.write(message)
                 self.original_stdout.flush()
            else:
                 # Fallback for IDLE or other environments
                 self.original_stdout.write(message)
            
            # Now process for buffer
            if isinstance(message, bytes):
                text_to_buffer = message.decode('utf-8', 'replace')
            else:
                text_to_buffer = str(message)
                
        except Exception:
            try: text_to_buffer = str(message)
            except: text_to_buffer = "<Encoding Error>"

        if text_to_buffer.strip():
            self.buffer.append(text_to_buffer.strip())

    def flush(self):
        self.original_stdout.flush()

    def get_latest(self):
        return list(self.buffer)

# Global instance
capture = StdoutCapture()

def start_capture():
    sys.stdout = capture

def stop_capture():
    sys.stdout = capture.original_stdout

def get_logs():
    return capture.get_latest()
