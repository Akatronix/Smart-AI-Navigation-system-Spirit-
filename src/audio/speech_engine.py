import asyncio
import threading
import queue
import logging
import tempfile
import os
import re
import time
import hashlib
import shutil
import subprocess
import wave



# Suppress pygame welcome message

os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = '1'



try:

    import edge_tts

    EDGE_TTS_AVAILABLE = True

except ImportError:

    EDGE_TTS_AVAILABLE = False



try:

    from piper import PiperVoice

    PIPER_LIB_AVAILABLE = True

except ImportError:

    PIPER_LIB_AVAILABLE = False



logger = logging.getLogger("spirit.audio")



# ---------------------------------------------------------------------------

# Configuration

# ---------------------------------------------------------------------------

VOICE_NAME = "en-US-AvaMultilingualNeural"                      # edge-tts voice

PIPER_MODEL = os.path.expanduser("~/piper-voices/en_US-amy-medium.onnx")

EDGE_TTS_TIMEOUT = 10.0                                         # s before giving up on network



# Priority order: offline natural voice first, cloud as fallback, robot last.

TTS_CHAIN = ["piper", "edge", "espeak"]



# ---------------------------------------------------------------------------

# Speech sanitization: LLM output -> TTS-safe text.

# Spirit's words are NEVER shown as text, so markdown, emoji, and exotic

# unicode must be stripped before they reach the TTS engine.

# ---------------------------------------------------------------------------

_MARKDOWN_RULES = [

    (re.compile(r"```.*?```", re.DOTALL), " "),            # code blocks

    (re.compile(r"`([^`]*)`"), r"\1"),                     # inline code

    (re.compile(r"!\[[^\]]*\]\([^)]*\)"), " "),            # images

    (re.compile(r"\[([^\]]+)\]\([^)]*\)"), r"\1"),         # [text](url) -> text

    (re.compile(r"(\*\*\*|___)(.+?)\1"), r"\2"),           # bold-italic

    (re.compile(r"(\*\*|__)(.+?)\1"), r"\2"),              # bold

    (re.compile(r"(\*|_)(.+?)\1"), r"\2"),                 # italic

    (re.compile(r"^#{1,6}\s*", re.MULTILINE), ""),         # # headers

    (re.compile(r"^\s*[-*+]\s+", re.MULTILINE), ""),       # bullet markers

    (re.compile(r"^\s*\d{1,2}[.)]\s+", re.MULTILINE), ""), # list numbers

    (re.compile(r"^>\s?", re.MULTILINE), ""),              # blockquotes

    (re.compile(r"\|"), " "),                              # table pipes

]



_UNICODE_MAP = {

    "\u2019": "'", "\u2018": "'",       # curly quotes -> straight

    "\u201c": '"', "\u201d": '"',

    "\u2014": ", ", "\u2013": "-",      # em dash, en dash

    "\u2026": "...",                     # ellipsis

    "\u202f": " ", "\u00a0": " ",       # narrow no-break space, nbsp

    "\u200b": "", "\u200c": "",         # zero-width chars

}



_EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F]+")





def _fix_mojibake(text: str) -> str:

    """Repair double-encoded UTF-8 (e.g. the bus ' instead of an apostrophe)."""

    if "bus" in text or "�" in text:

        try:

            repaired = text.encode("cp1252", errors="ignore").decode("utf-8", errors="ignore")

            if repaired:

                return repaired

        except (UnicodeEncodeError, UnicodeDecodeError):

            pass

    return text





def clean_for_speech(text: str) -> str:

    if not text:

        return text

    text = _fix_mojibake(text)

    for pattern, repl in _MARKDOWN_RULES:

        text = pattern.sub(repl, text)

    for src, dst in _UNICODE_MAP.items():

        text = text.replace(src, dst)

    text = _EMOJI_RE.sub(" ", text)

    text = re.sub(r"\*+", "", text)              # stray/unpaired asterisks (truncated bold)

    text = re.sub(r"\s*\n+\s*", " ", text)       # newlines -> spaces

    text = re.sub(r"[ \t]{2,}", " ", text)

    return text.strip()


class SpiritAudio:

    def __init__(self):

        self.speaking_event = threading.Event()

        self.speech_queue = queue.Queue()



        self._edge_loop = None

        self._piper_voice = None

        self._piper_checked = False



        # Startup diagnostics

        piper_ok = PIPER_LIB_AVAILABLE and os.path.exists(PIPER_MODEL)

        edge_ok = EDGE_TTS_AVAILABLE

        espeak_ok = bool(shutil.which("espeak-ng") or shutil.which("espeak"))

        logger.info(

            f"SpiritAudio chain={TTS_CHAIN} | "

            f"piper={'OK' if piper_ok else 'missing'} | "

            f"edge-tts={'OK' if edge_ok else 'missing'} | "

            f"espeak={'OK' if espeak_ok else 'missing'}"

        )

        if not piper_ok:

            logger.warning("Piper unavailable: pip install piper-tts and run "

                           "python3 -m piper.download_voices en_US-amy-medium")



        self.tts_thread = threading.Thread(target=self._tts_worker, daemon=True, name="spirit-tts")

        self.tts_thread.start()



    # ------------------------------------------------------------------

    # Backend 1: Piper (offline, natural) - PRIMARY

    # ------------------------------------------------------------------

    def _get_piper(self):

        """Lazy-load Piper on first utterance so app startup stays fast."""

        if not self._piper_checked:

            self._piper_checked = True

            if not PIPER_LIB_AVAILABLE:

                logger.warning("piper-tts not installed")

            elif not os.path.exists(PIPER_MODEL):

                logger.warning(f"Piper model not found: {PIPER_MODEL}")

            else:

                try:

                    self._piper_voice = PiperVoice.load(PIPER_MODEL)

                    logger.info("Piper voice loaded (offline natural TTS)")

                except Exception as e:

                    logger.warning(f"Piper load failed: {e}")

        return self._piper_voice



    def _speak_piper(self, text: str) -> bool:

        voice = self._get_piper()

        if voice is None:

            return False

        try:

            # Cache repeated phrases (nav commands repeat a lot)

            key = hashlib.md5(text.encode()).hexdigest()[:10]

            wav_path = os.path.join(tempfile.gettempdir(), f"spirit_tts_{key}.wav")

            if not os.path.exists(wav_path):

                part_path = wav_path + ".part"

                with wave.open(part_path, "wb") as wf:

                    voice.synthesize_wav(text, wf)

                os.replace(part_path, wav_path)   # atomic: never cache a partial file

            self._play_file(wav_path)

            return True

        except Exception as e:

            logger.warning(f"Piper TTS failed: {e}")

            return False


# ------------------------------------------------------------------

    # Backend 2: edge-tts (cloud) - FALLBACK

    # ------------------------------------------------------------------

    def _speak_edge(self, text: str) -> bool:

        if not EDGE_TTS_AVAILABLE:

            return False

        tmp_path = None

        try:

            communicate = edge_tts.Communicate(text, VOICE_NAME)

            tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)

            tmp_path = tmp.name

            tmp.close()



            if self._edge_loop is None or self._edge_loop.is_closed():

                self._edge_loop = asyncio.new_event_loop()



            self._edge_loop.run_until_complete(

                asyncio.wait_for(communicate.save(tmp_path), timeout=EDGE_TTS_TIMEOUT)

            )

            self._play_file(tmp_path)

            return True

        except Exception as e:

            logger.warning(f"Edge TTS failed: {e}")

            return False

        finally:

            if tmp_path:

                try:

                    os.unlink(tmp_path)

                except OSError:

                    pass



    # ------------------------------------------------------------------

    # Backend 3: espeak-ng (offline, robotic) - LAST RESORT

    # ------------------------------------------------------------------

    def _speak_espeak(self, text: str) -> bool:

        espeak = shutil.which("espeak-ng") or shutil.which("espeak")

        if not espeak:

            return False

        try:

            wav_path = os.path.join(tempfile.gettempdir(), "spirit_espeak.wav")

            subprocess.run(

                [espeak, "-v", "en-us", "-s", "170", "-w", wav_path, text],

                check=True, timeout=30,

            )

            self._play_file(wav_path)

            return True

        except Exception as e:

            logger.warning(f"espeak fallback failed: {e}")

            return False



    # ------------------------------------------------------------------

    # Playback (pygame first - proven working; CLI players as backup)

    # ------------------------------------------------------------------

    def _play_file(self, filepath):

        try:

            import pygame

            pygame.mixer.init()

            pygame.mixer.music.load(filepath)

            pygame.mixer.music.play()

            while pygame.mixer.music.get_busy():

                time.sleep(0.05)

            pygame.mixer.quit()

            return

        except Exception as e:

            logger.warning(f"pygame playback failed: {e}")

            try:

                pygame.mixer.quit()

            except Exception:

                pass



        for cmd in (

            ["mpg123", "-q"],

            ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"],

            ["aplay", "-q"],   # last: currently broken on this Pi (error 524)

        ):

            if shutil.which(cmd[0]):

                try:

                    subprocess.run(cmd + [filepath], check=True, timeout=120)

                    return

                except Exception as e:

                    logger.warning(f"{cmd[0]} playback failed: {e}")



        logger.error(f"No audio backend could play {filepath}")




# ------------------------------------------------------------------

    # Worker + public API

    # ------------------------------------------------------------------

    def _tts_worker(self):

        while True:

            text = self.speech_queue.get()

            try:

                for backend in TTS_CHAIN:

                    if backend == "piper":

                        ok = self._speak_piper(text)

                    elif backend == "edge":

                        ok = self._speak_edge(text)

                    elif backend == "espeak":

                        ok = self._speak_espeak(text)

                    else:

                        ok = False

                    if ok:

                        break

                else:

                    logger.error(f"All TTS backends failed - no audio for: {text[:60]!r}")

            except Exception as e:

                logger.error(f"TTS worker error: {e}")

            finally:

                self.speech_queue.task_done()

                if self.speech_queue.empty():

                    self.speaking_event.clear()



    def speak_async(self, text):

        if text:

            self.speaking_event.set()   # set BEFORE enqueue - no race in wait_until_done

            self.speech_queue.put(clean_for_speech(text))



    def wait_until_done(self, timeout=30.0):

        waited = 0.0

        while waited < timeout:

            if self.speech_queue.empty() and not self.speaking_event.is_set():

                return True

            time.sleep(0.1)

            waited += 0.1

        return False