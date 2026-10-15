import json
import logging
import os
import re
import time
from datetime import datetime
from pathlib import Path

import groq
from groq import Groq

from src.nlp.model_manager import ModelManager, NoModelAvailableError, is_model_gone

logger = logging.getLogger("spirit.spirit_agent")

# ---------------------------------------------------------------------------
# Intent classification - local, zero latency, no API cost. Decides which
# model tier, how much reasoning, and how much history each turn deserves.
# ---------------------------------------------------------------------------
_GREETING_RE = re.compile(
    r"^(hi|hello|hey|good (morning|afternoon|evening)|how are you|what'?s up|thank(s| you))\b"
)

_INTENT_RULES = [
    ("urgent", re.compile(
        r"\b(help me|danger|emergency|i'?m scared|watch out|something'?s wrong)\b", re.I)),
    ("nav", re.compile(
        r"\b(where is|how do i (get|go|walk)|directions?|take me|navigate|route|"
        r"nearest|closest|walk to|go to (?!sleep\b))\b", re.I)),
    ("question", re.compile(
        r"\b(what|why|when|who|which|where|can you|do you|is there|are there|"
        r"tell me|explain|how)\b", re.I)),
]

# intent: (tier, reasoning_effort, max_tokens, history_turns, temperature)
_INTENT_CONFIG = {
    "urgent":   ("fast",  "low",    150, 2, 0.3),
    "nav":      ("smart", "medium", 800, 8, 0.4),
    "question": ("smart", "medium", 700, 8, 0.5),
    "chat":     ("fast",  "low",    250, 6, 0.8),
}

_WORD_RE = re.compile(r"[a-z0-9']+")
_LOCATION_RE = re.compile(r"current location:\s*([^;.]+)", re.I)

SYSTEM_PROMPT = """You are Spirit, the intelligence inside a wearable navigation assistant for a visually impaired user you address as "Master". You are sharp, warm and resourceful - a trusted guide with eyes, ears and a sense of direction.

## OUTPUT FORMAT (CRITICAL)
Your words are converted to speech by a TTS engine and are NEVER shown as text.
- Plain spoken sentences only. No markdown: no **bold**, *italics*, `code`, #headers, bullets, numbered lists, tables, or emoji.
- Directions are flowing sentences with distances, turns and landmarks: "Head south on Airport Road for about two kilometers, then turn left at the fuel station."
- Say numbers the way people speak: "fifteen kilometers", "in about five minutes".

## HOW TO THINK
- Safety first: if live sensor data shows a hazard or vehicle, mention it before answering, even if the user asked something else. If it is immediately dangerous, use the fewest possible words.
- Think spatially: prefer landmarks over street names, estimate distances and walking times, and describe what Master will see or hear along the way.
- Infer intent: "I want to go to the airport" means give a route or next steps, not a definition. "Can you play music" means answer honestly, then offer what you can do.
- Never claim abilities you don't have: you cannot play music, make calls, send messages, or set alarms.
- Use the context you are given: weave in live sensor data, the time, the last known location and relevant facts naturally. Never read raw data aloud.
- If something is missing (no GPS fix, no sensor data), say so in one short sentence and suggest the fastest way forward.
- Small talk stays short and warm - one or two sentences - then offer help. Never lecture, never repeat the user's question back.

## WHAT YOU CAN DO
- See through a live camera: people, vehicles, obstacles and hazards in front of Master
- Track Master's GPS location and work out routes and nearby places
- Read temperature and humidity when the sensor module is active
- Hear everything Master says and answer by voice, instantly

## STYLE
- Confident, concise, human. Contractions, varied phrasing, a light touch of warmth.
- Address the user as "Master" occasionally, not in every sentence.
- One to three sentences normally; go longer only for genuine step-by-step directions.

## EXAMPLES
User: what can you do
Spirit: I'm your eyes and guide, Master. I can spot people, vehicles and obstacles through the camera, track where we are, give walking directions, and read the temperature. What do you need?

User: I want to go to the airport
Spirit: From Oshodi the quickest is a ride along Airport Road, about forty minutes right now, Master. Want turn-by-turn guidance or the nearest pickup point?

User: tell me a joke
Spirit: Why did the scarecrow win an award? He was outstanding in his field. Where to next, Master?
"""


class SpiritAgent:
    """
    Spirit's brain. Talks to Groq with intent-aware routing:

    - URGENT turns go to the fast tier with minimal reasoning.
    - Navigation and questions go to the smart tier with reasoning enabled.
    - Small talk stays cheap and quick on the fast tier.

    MODEL RESILIENCE: model names are never hard-coded. ModelManager asks Groq
    which models exist, picks the best for each tier, and this class fails over
    to the next best model mid-request if one is removed or rate-limited.

    PRODUCTION NOTE: this class must NEVER crash the app on init. Hazard
    alerts are deterministic and don't depend on it.
    """

    REQUEST_TIMEOUT_SEC = 12.0   # per attempt: a stalled request must not hang the voice UX
    TOTAL_BUDGET_SEC = 20.0      # stop trying more fallback models after this long
    MAX_ATTEMPTS = 4

    def __init__(self):
        api_key = os.environ.get("GROQ_API_KEY", "").strip()
        self.client = None
        self.models = None

        if not api_key:
            logger.error("GROQ_API_KEY not set - Spirit will report this out loud until it's fixed.")
        else:
            try:
                self.client = Groq(api_key=api_key, timeout=self.REQUEST_TIMEOUT_SEC)
                self.models = ModelManager(self.client)
                self.models.refresh_async(force=True)   # background: never delays startup
            except Exception as e:
                logger.error("Failed to construct Groq client: %s", e)
                self.client = None
                self.models = None

        self.permanent_facts = self._load_facts()
        self.history = []
        self.last_known_location = None

        logger.info("Spirit AI initialized. Model selection is automatic.")
        logger.info("Permanent facts loaded: %d", len(self.permanent_facts))

    # ------------------------------------------------------------------
    # Persistent facts
    # ------------------------------------------------------------------
    def _load_facts(self):
        facts_file = Path("data/permanent_facts.json")
        if facts_file.exists():
            try:
                with open(facts_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error("Failed to load permanent facts: %s", e)
                return []
        return []


    def _save_facts(self):
        facts_file = Path("data/permanent_facts.json")
        facts_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(facts_file, "w", encoding="utf-8") as f:
                json.dump(self.permanent_facts, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error("Failed to save permanent facts: %s", e)

    def add_permanent_fact(self, fact: str):
        self.permanent_facts.append(fact)
        self._save_facts()

    def remove_permanent_fact(self, fact: str):
        if fact in self.permanent_facts:
            self.permanent_facts.remove(fact)
            self._save_facts()

    def _relevant_facts(self, message: str, limit: int = 6):
        """Only send facts relevant to this turn - keyword overlap scoring.
        Falls back to the first few facts when nothing matches, since early
        facts (home address, routines) tend to matter most."""
        if not self.permanent_facts:
            return []
        msg_words = set(_WORD_RE.findall(message.lower()))
        scored = []
        for fact in self.permanent_facts:
            words = set(_WORD_RE.findall(str(fact).lower()))
            scored.append((len(msg_words & words), fact))
        scored.sort(key=lambda pair: -pair[0])
        top = [fact for score, fact in scored[:limit] if score > 0]
        return top or list(self.permanent_facts[:limit])

    
    # ------------------------------------------------------------------
    # Intent + context
    # ------------------------------------------------------------------
    def _classify(self, message: str) -> str:
        text = message.strip().lower()
        # Short greetings/phatics stay cheap - "hello" doesn't need reasoning
        if len(text.split()) <= 4 and _GREETING_RE.match(text):
            return "chat"
        for name, pattern in _INTENT_RULES:
            if pattern.search(text):
                return name
        return "chat"

    def _remember_location(self, sensor_summary: str):
        if not sensor_summary:
            return
        m = _LOCATION_RE.search(sensor_summary)
        if m:
            loc = m.group(1).strip()
            if loc and loc.lower() not in ("unknown", "none", "n/a", "not available"):
                self.last_known_location = loc

    def set_location(self, location: str):
        """Optional hook: let main.py's GPS thread push fixes directly."""
        if location:
            self.last_known_location = str(location).strip()

    def _build_context(self, user_message: str, sensor_summary: str) -> str:
        parts = []
        now = datetime.now().strftime("%A, %d %B %Y, %H:%M")
        parts.append(f"Current time: {now}")
        if self.last_known_location:
            parts.append(f"Last known location: {self.last_known_location}")
        if sensor_summary:
            parts.append(f"Live sensor data: {sensor_summary}")
        facts = self._relevant_facts(user_message)
        if facts:
            parts.append("Relevant facts about Master:")
            parts.extend(f"  - {f}" for f in facts)
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Model plumbing
    # ------------------------------------------------------------------
    def _trim_to_sentence(self, text: str) -> str:
        """If the answer was cut off by the token cap, end at the last
        complete sentence instead of mid-word."""
        m = re.match(r"^(.+[.!?])", text, re.DOTALL)
        return m.group(1).strip() if m else text.strip()

    def _call_model(self, model, messages, effort, max_tokens, temperature):
        """One request to one specific model."""
        kwargs = dict(model=model, messages=messages,
                      temperature=temperature, max_tokens=max_tokens)
        if effort and self.models.supports_reasoning(model):
            kwargs["reasoning_effort"] = effort
        try:
            return self.client.chat.completions.create(**kwargs)
        except groq.APIStatusError as e:
            if (kwargs.get("reasoning_effort") and e.status_code == 400
                    and "reasoning" in str(e).lower()):
                self.models.mark_no_reasoning(model)
                kwargs.pop("reasoning_effort")
                return self.client.chat.completions.create(**kwargs)
            raise
        except TypeError:
            if kwargs.get("reasoning_effort"):
                self.models.mark_no_reasoning(model)
                kwargs.pop("reasoning_effort")
                return self.client.chat.completions.create(**kwargs)
            raise

    def _complete(self, tier, messages, effort, max_tokens, temperature):
        """
        Try this tier's best model; if it is gone, rate-limited or timing out,
        move to the next best. Returns (response, model_used).
        """
        deadline = time.monotonic() + self.TOTAL_BUDGET_SEC
        tried = set()
        last_error = None

        for _ in range(self.MAX_ATTEMPTS):
            candidates = [m for m in self.models.candidates(tier) if m not in tried]
            if not candidates and not tried:
                self.models.refresh()      # nothing known yet: fetch the list now
                candidates = [m for m in self.models.candidates(tier) if m not in tried]
            if not candidates:
                break
            if tried and time.monotonic() > deadline:
                break

            model = candidates[0]
            tried.add(model)
            try:
                response = self._call_model(model, messages, effort, max_tokens, temperature)
                self.models.note_success(tier, model)
                return response, model
            except groq.AuthenticationError:
                raise                                   # no other model can fix a bad key
            except Exception as e:
                last_error = e
                if is_model_gone(e):
                    self.models.mark_dead(model)
                elif isinstance(e, groq.APITimeoutError):
                    logger.warning("%s timed out; trying another model.", model)
                elif isinstance(e, groq.APIConnectionError):
                    raise                               # offline: fallbacks would fail too
                elif isinstance(e, groq.APIStatusError):
                    logger.warning("%s failed (%s); trying another model.", model, e)
                else:
                    raise

        if last_error is not None and not is_model_gone(last_error):
            raise last_error
        raise NoModelAvailableError("No usable Groq chat model is available.")

    # ------------------------------------------------------------------
    # Main entry point (same signature as before - main.py unchanged)
    # ------------------------------------------------------------------
    def chat(self, user_message: str, sensor_summary: str = "", urgent: bool = False) -> str:
        if self.client is None:
            return "My AI service isn't connected right now, Master - check the API key."
        if not user_message or not user_message.strip():
            return "I didn't catch that, Master. Say it again?"

        intent = "urgent" if urgent else self._classify(user_message)
        tier, effort, max_tokens, history_n, temperature = _INTENT_CONFIG[intent]

        self._remember_location(sensor_summary)
        context = self._build_context(user_message, sensor_summary)

        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        if context:
            messages.append({"role": "system", "content": f"[ENVIRONMENT]\n{context}"})
        messages.extend(self.history[-history_n * 2:])
        shown = f"[URGENT] {user_message}" if intent == "urgent" else user_message
        messages.append({"role": "user", "content": shown})

        start = time.monotonic()
        try:
            response, model_used = self._complete(tier, messages, effort, max_tokens, temperature)
            content = (response.choices[0].message.content or "").strip()

            if not content:
                # reasoning tokens can swallow a small budget - retry with headroom
                response, model_used = self._complete(tier, messages, "low",
                                                      max_tokens + 400, temperature)
                content = (response.choices[0].message.content or "").strip()
            if not content:
                content = "I'm still thinking that through, Master. Ask me again in a moment."

            content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
            if getattr(response.choices[0], "finish_reason", None) == "length":
                content = self._trim_to_sentence(content)

            elapsed_ms = (time.monotonic() - start) * 1000
            logger.info("chat intent=%s model=%s effort=%s in %.0fms",
                        intent, model_used, effort, elapsed_ms)

            self.history.append({"role": "user", "content": user_message})
            self.history.append({"role": "assistant", "content": content})
            if len(self.history) > 30:
                self.history = self.history[-16:]
            return content

        except Exception as e:
            return self._friendly_error(e)

    def _friendly_error(self, e) -> str:
        if isinstance(e, NoModelAvailableError):
            logger.error("No usable Groq chat model found: %s", e)
            return "I can't find an available AI model right now, Master. Try again in a minute."
        if isinstance(e, groq.AuthenticationError):
            logger.error("Groq authentication failed - API key is invalid.")
            return "My AI service isn't authorized right now, Master - the API key needs checking."
        if isinstance(e, groq.RateLimitError):
            logger.error("Groq rate limit hit.")
            return "I'm being rate-limited right now, Master. Give it a moment."
        if isinstance(e, groq.APIConnectionError):
            logger.error("Groq connection failed: %s", e)
            return "I can't reach my AI service right now, Master - check the connection."
        logger.error("AI request failed: %s", e)
        return "Sorry Master, something went wrong. Try again."

    def clear_history(self):
        self.history = []