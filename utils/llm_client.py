import json
import logging
import os
import time

_LLM_USAGE_FILE = "llm_usage.json"

# Module-level usage accumulator shared across all LLMClient instances
# Tracks token counts per agent for cost monitoring
_usage_accumulator = {}  # agent_name -> {"input": int, "output": int, "thinking": int, "calls": int}
_day_reset_ts = time.time()
_hour_reset_ts = time.time()

# Restore today's counts from disk if the saved data is from the same calendar day
try:
    with open(_LLM_USAGE_FILE, "r") as _f:
        _saved = json.load(_f)
    import datetime as _dt
    _saved_date = _dt.date.fromtimestamp(_saved.get("day_reset_ts", 0))
    if _saved_date == _dt.date.today():
        _usage_accumulator = _saved.get("accumulator", {})
        _day_reset_ts = _saved.get("day_reset_ts", _day_reset_ts)
        _hour_reset_ts = _saved.get("hour_reset_ts", _hour_reset_ts)
except Exception:
    pass  # No file yet or parse error — start fresh

def _get_or_init_agent(agent_name: str) -> dict:
    if agent_name not in _usage_accumulator:
        _usage_accumulator[agent_name] = {
            "today_input": 0, "today_output": 0, "today_thinking": 0, "today_calls": 0,
            "hour_input": 0, "hour_output": 0, "hour_thinking": 0, "hour_calls": 0,
        }
    return _usage_accumulator[agent_name]

def get_llm_usage_stats() -> dict:
    """Returns a snapshot of token usage per agent for dashboard reporting."""
    global _day_reset_ts, _hour_reset_ts
    now = time.time()

    # Reset hourly counters every 3600s
    if now - _hour_reset_ts > 3600:
        for agent in _usage_accumulator.values():
            agent["hour_input"] = 0
            agent["hour_output"] = 0
            agent["hour_thinking"] = 0
            agent["hour_calls"] = 0
        _hour_reset_ts = now

    # Reset daily counters every 86400s
    if now - _day_reset_ts > 86400:
        for agent in _usage_accumulator.values():
            agent["today_input"] = 0
            agent["today_output"] = 0
            agent["today_thinking"] = 0
            agent["today_calls"] = 0
        _day_reset_ts = now

    by_agent = {}
    total_today = 0
    total_hour = 0
    for name, stats in _usage_accumulator.items():
        today_total = stats["today_input"] + stats["today_output"] + stats["today_thinking"]
        hour_total = stats["hour_input"] + stats["hour_output"] + stats["hour_thinking"]
        # Approximate cost: $0.125 per 1M tokens blended (gemini-2.0-flash-ish)
        today_cost_eur = round(today_total * 0.000000125 * 0.92, 4)  # USD to EUR ~0.92
        by_agent[name] = {
            "today": today_total,
            "hour": hour_total,
            "calls_today": stats["today_calls"],
            "cost_eur_today": today_cost_eur,
        }
        total_today += today_total
        total_hour += hour_total

    result = {
        "today_total": total_today,
        "hourly_total": total_hour,
        "by_agent": by_agent,
        "last_updated": int(now),
    }

    # Persist accumulator to disk so restarts don't lose today's counts
    try:
        with open(_LLM_USAGE_FILE, "w") as _f:
            json.dump({
                "accumulator": _usage_accumulator,
                "day_reset_ts": _day_reset_ts,
                "hour_reset_ts": _hour_reset_ts,
            }, _f)
    except Exception:
        pass

    return result


class LLMClient:
    def __init__(self, model_name: str = None):
        self.logger = logging.getLogger("LLMClient")
        self.available = False
        self.model = None

        # Initialize Google GenAI
        try:
            import google.generativeai as genai

            # Use GCP Secret Manager (with local fallback)
            try:
                from utils.gcp_secrets import get_google_api_key
                api_key = get_google_api_key()
            except ImportError:
                api_key = os.getenv("GOOGLE_API_KEY")
                if not api_key:
                    from dotenv import load_dotenv
                    load_dotenv(".env.adk")
                    api_key = os.getenv("GOOGLE_API_KEY")

            if api_key:
                genai.configure(api_key=api_key)
                # model_name param takes priority; fall back to env var; then default
                self.model_name = model_name or os.getenv("GEMINI_MODEL", "gemini-3-flash-preview")

                self.model = genai.GenerativeModel(self.model_name)
                self.available = True
                self.logger.info(f"LLMClient initialized with google.generativeai ({self.model_name})")
            else:
                 self.logger.error("GOOGLE_API_KEY not found in environment.")
        except ImportError:
            self.logger.warning("google.generativeai not found. Trying vertexai...")
            try:
                import vertexai
                from vertexai.generative_models import GenerativeModel
                self.model_name = model_name or os.getenv("GEMINI_MODEL", "gemini-3-flash-preview")
                self.model = GenerativeModel(self.model_name)
                self.available = True
                self.logger.info(f"LLMClient initialized with vertexai ({self.model_name})")
            except Exception as e:
                self.logger.critical(f"LLM initialization failed: {e}")
                self.available = False
        except Exception as e:
             self.logger.error(f"Error initializing Google GenAI: {e}")
             self.available = False

    def analyze_text(self, prompt: str, agent_name: str = "Unknown") -> str:
        if not self.available or not self.model:
            error_msg = "CRITICAL: LLM Service unavailable. Cannot proceed with probabilistic reasoning."
            self.logger.error(error_msg)
            raise RuntimeError(error_msg)

        try:
            self.logger.info(f"Generating content with model: {self.model.model_name}")

            # Wrap in timeout to prevent hangs
            import concurrent.futures
            print(f"[DEBUG] Starting LLM generation (Model: {self.model_name}, Agent: {agent_name})...")
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(self.model.generate_content, prompt)
                response = future.result(timeout=120)  # 120s timeout for thinking models
            print(f"[DEBUG] LLM generation complete.")

            # --- Token usage tracking ---
            try:
                meta = getattr(response, 'usage_metadata', None)
                if meta:
                    input_tokens    = getattr(meta, 'prompt_token_count', 0) or 0
                    output_tokens   = getattr(meta, 'candidates_token_count', 0) or 0
                    thinking_tokens = getattr(meta, 'thoughts_token_count', 0) or 0
                    stats = _get_or_init_agent(agent_name)
                    stats["today_input"]    += input_tokens
                    stats["today_output"]   += output_tokens
                    stats["today_thinking"] += thinking_tokens
                    stats["today_calls"]    += 1
                    stats["hour_input"]     += input_tokens
                    stats["hour_output"]    += output_tokens
                    stats["hour_thinking"]  += thinking_tokens
                    stats["hour_calls"]     += 1
                    self.logger.info(
                        f"[TOKENS] {agent_name} ({self.model_name}): "
                        f"in={input_tokens} out={output_tokens} think={thinking_tokens}"
                    )
            except Exception as te:
                self.logger.debug(f"Token tracking failed (non-critical): {te}")
            # ----------------------------

            if response and response.text:
                return response.text
            else:
                raise ValueError("Empty response from LLM")
        except concurrent.futures.TimeoutError:
            self.logger.error("LLM Generation Timed Out (120s)")
            raise RuntimeError("LLM Timed Out")
        except Exception as e:
            self.logger.error(f"LLM generation failed with model {self.model.model_name}: {e}")
            raise RuntimeError(f"LLM Call Failed: {e}")
