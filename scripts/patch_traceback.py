"""
Patch research_agent to dump full traceback to /tmp/crash.log on next scan failure.
Run once inside container: python3 /tmp/patch_traceback.py
"""
import sys, os, time, traceback, logging
sys.path.insert(0, '/app')
logging.basicConfig(level=logging.WARNING)

# Read the current source
src_path = '/app/agents/research_agent.py'
with open(src_path) as f:
    src = f.read()

# Already patched?
if 'CRASH_DUMP' in src:
    print("Already patched")
    sys.exit(0)

# Inject full traceback dump into the except block
old = 'except Exception as e:\n            self.logger.error(f"Error during market scan: {e}")'
new = ('except Exception as e:\n'
       '            import traceback as _tb\n'
       '            _tb_str = _tb.format_exc()\n'
       '            self.logger.error(f"Error during market scan: {e}\\nCRASH_DUMP:\\n{_tb_str}")\n'
       '            try:\n'
       '                with open("/tmp/crash.log","w") as _f: _f.write(_tb_str)\n'
       '            except: pass\n'
       '            self.logger.error(f"Error during market scan: {e}")')

if old not in src:
    print("Pattern not found — source may have changed")
    # Just show what the except block looks like
    idx = src.find('except Exception as e:')
    if idx >= 0:
        print("Found except at:", src[idx:idx+200])
    sys.exit(1)

patched = src.replace(old, new, 1)
with open(src_path, 'w') as f:
    f.write(patched)
print("Patched. Next scan failure will write to /tmp/crash.log")
