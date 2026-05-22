"""
Multi-agent system with smart fail-over across Google AI models.

Features:
- Hierarchical orchestrator + specialist sub-agents
- Capability-aware routing (text vs. multimodal)
- Resilient fail-over across multiple models per agent
- Handles transient errors (5xx), rate limits (429), and capability mismatches (400)
- Exponential backoff retry before falling over
"""

import asyncio
import os
from io import BytesIO
from typing import AsyncGenerator

from dotenv import load_dotenv

from faster_whisper import WhisperModel

from google import genai
from google.adk.agents import Agent
from google.adk.models import BaseLlm, Gemini
from google.adk.tools import FunctionTool, AgentTool, google_search
from google.api_core import exceptions as gcp_exceptions
from google.genai import errors as genai_errors


# ───────────────────────────────────────────────────────────────────────────
# 🛡️  Whisper - STT
# ───────────────────────────────────────────────────────────────────────────

from faster_whisper import WhisperModel

# Recomendação para manter a estabilidade nos 1.5GB de VRAM
model = WhisperModel(
    "deepdml/faster-whisper-large-v3-turbo-ct2", # Versão otimizada para CTranslate2
    device="cuda",
    compute_type="int8_float16"
)

def transcribe_audio(path):
    """ O Turbo performa muito bem com beam_size baixo, economizando memória"""
    segments, info = model.transcribe(path, beam_size=1, language="pt")
    print(info)
    return " ".join([s.text.strip() for s in segments])

# ───────────────────────────────────────────────────────────────────────────
# 🛡️  Fail-over infrastructure
# ───────────────────────────────────────────────────────────────────────────

# Patterns indicating "this model can't do what we asked" → safe to fail over
CAPABILITY_ERROR_PATTERNS = (
    "function calling is not enabled",
    "developer instruction is not enabled",
    "system instruction",
    "does not support",
    "not supported for model",
    "tools are not supported",
    "thought_signature",  # 🆕 treat as capability mismatch → fail over
)

# Transient errors from EITHER SDK family — always safe to retry/fail over
TRANSIENT_ERRORS = (
    genai_errors.ServerError,                # google-genai 5xx (500, 503, 504)
    gcp_exceptions.ServiceUnavailable,       # google-api-core 503
    gcp_exceptions.InternalServerError,      # google-api-core 500
    gcp_exceptions.DeadlineExceeded,         # google-api-core timeout
    gcp_exceptions.GatewayTimeout,           # google-api-core 504
)

# Rate-limit errors from google-api-core (genai uses ClientError with code 429)
RATE_LIMIT_ERRORS = (
    gcp_exceptions.ResourceExhausted,        # google-api-core 429
)


def _is_capability_error(err: Exception) -> bool:
    """Check if a 400 error is a capability limitation (safe to fail over)."""
    msg = str(err).lower()
    return any(pattern in msg for pattern in CAPABILITY_ERROR_PATTERNS)


def _classify_error(err: Exception) -> str:
    """
    Returns one of:
      'transient'  → retry/fail over (5xx, network)
      'rate_limit' → fail over (429)
      'capability' → fail over (400 + capability message)
      'fatal'      → re-raise (real bug, auth, etc.)
    """
    if isinstance(err, TRANSIENT_ERRORS):
        return "transient"
    if isinstance(err, RATE_LIMIT_ERRORS):
        return "rate_limit"
    if isinstance(err, genai_errors.ClientError):
        if err.code == 429:
            return "rate_limit"
        if err.code in (500, 502, 503, 504):
            return "transient"
        if err.code == 400 and _is_capability_error(err):
            return "capability"
        return "fatal"
    if isinstance(err, gcp_exceptions.InvalidArgument):
        return "capability" if _is_capability_error(err) else "fatal"
    return "fatal"


async def _run_chain(
    models: list[Gemini],
    names: list[str],
    llm_request,
    stream: bool,
    max_quick_retries: int = 1,
    backoff_base: float = 1.5,
) -> AsyncGenerator:
    """
    Iterate through models, trying each one (with quick retry on transient errors)
    before falling over to the next. Yields responses on success.
    """
    last_error = None

    for model, name in zip(models, names):
        # 🔑 CRITICAL: ADK's Gemini.generate_content_async reads llm_request.model
        #              (NOT self.model) — so we MUST override it here.
        llm_request.model = name

        for attempt in range(max_quick_retries + 1):
            try:
                if attempt > 0:
                    delay = backoff_base ** attempt
                    print(f"   🔄 Retry {attempt}/{max_quick_retries} after {delay:.1f}s...")
                    await asyncio.sleep(delay)

                print(f"🤖 Trying {name} (attempt {attempt + 1})...")
                async for response in model.generate_content_async(
                    llm_request, stream=stream
                ):
                    yield response
                print(f"✅ {name} succeeded")
                return

            except Exception as e:
                kind = _classify_error(e)
                last_error = e

                if kind == "fatal":
                    print(f"❌ {name}: fatal error — not retrying ({type(e).__name__})")
                    raise

                if kind == "transient" and attempt < max_quick_retries:
                    print(f"   ⏳ {name}: transient error ({type(e).__name__}), retrying...")
                    continue

                emoji = {"transient": "⚠️", "rate_limit": "🚦", "capability": "🧩"}[kind]
                print(f"{emoji}  {name}: {kind} ({type(e).__name__}) — falling back...")
                break  # exit retry loop, move to next model

    raise RuntimeError(
        f"All {len(names)} models failed. Last error: {last_error}"
    )


# ───────────────────────────────────────────────────────────────────────────
# 🔁  Basic fail-over: tries each model in the chain in order
# ───────────────────────────────────────────────────────────────────────────

class FailoverModel(BaseLlm):
    """Tries each model in the chain on failure."""

    def __init__(self, model_chain: list[str]):
        super().__init__(model=model_chain[0])
        self._models = [Gemini(model=m) for m in model_chain]
        self._chain = model_chain

    async def generate_content_async(
        self, llm_request, stream: bool = False
    ) -> AsyncGenerator:
        async for response in _run_chain(
            self._models, self._chain, llm_request, stream
        ):
            yield response


# ───────────────────────────────────────────────────────────────────────────
# 🧠  Smart fail-over: text vs. multimodal
# ───────────────────────────────────────────────────────────────────────────

class SmartFailoverModel(BaseLlm):
    """Picks text-chain or multimodal-chain based on the input contents."""

    def __init__(self, text_chain: list[str], multimodal_chain: list[str]):
        super().__init__(model=text_chain[0])
        self._text_models = [Gemini(model=m) for m in text_chain]
        self._mm_models = [Gemini(model=m) for m in multimodal_chain]
        self._text_names = text_chain
        self._mm_names = multimodal_chain

    @staticmethod
    def _has_media(llm_request) -> bool:
        """Detect if request contains images/audio/video/PDF parts.
           Convert audio to text
        """
        has_other = False
        has_audio = False
        for content in llm_request.contents or []:
            for part in content.parts or []:
                if getattr(part, "inline_data", None) or getattr(part, "file_data", None):
                    part_type = "inline" if getattr(part, "inline_data", None) else "file"
                    part_body = part.inline_data if part_type == "inline" else part.file_data
                    has_audio = has_audio or part_body.mime_type.startswith('audio/')
                    if (not part_body.mime_type.startswith('audio/') and
                                not part_body.mime_type.startswith('text/')):
                        has_other = True
                elif (getattr(part, "text", None) is None and
                            not getattr(part, "function_call", None) and
                            not getattr(part, "function_response", None)):
                    has_other = True

        if not has_audio:
            return has_other

        for content in llm_request.contents or []:
            for part in content.parts or []:
                if getattr(part, "inline_data", None) or getattr(part, "file_data", None):
                    part_type = "inline" if getattr(part, "inline_data", None) else "file"
                    part_body = part.inline_data if part_type == "inline" else part.file_data
                    if part_body.mime_type.startswith('audio/'):
                        audio_file = BytesIO(part_body.data)
                        transcription = transcribe_audio(audio_file)
                        part.text = f"User said: {transcription}"
                        setattr(part, part_type + "_data", None)

        return has_other

    async def generate_content_async(
        self, llm_request, stream: bool = False
    ) -> AsyncGenerator:
        if self._has_media(llm_request):
            models, names = self._mm_models, self._mm_names
            print("🎨 Multimodal input detected — using vision chain")
        else:
            models, names = self._text_models, self._text_names
            print("📝 Text-only input — using text chain")

        async for response in _run_chain(models, names, llm_request, stream):
            yield response


# ───────────────────────────────────────────────────────────────────────────
# 🛠️  Functions tools
# ───────────────────────────────────────────────────────────────────────────

def list_google_models() -> str:
    """List all Google AI models supported by the user's API key."""
    load_dotenv()
    client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
    return "\n".join(model.name for model in client.models.list())

def transcribe_audio(audio_path: str) -> str:
    """Use this tool when you need to understand, read
       or transcribe the contents of an audio file."""
    print(f"🎵 Audio file: '{audio_path}'")
    model = WhisperModel(
        "large-v3-turbo",
        device="cuda",
        compute_type="int8_float16"
    )
    segments, info = model.transcribe(
        audio_path,
        beam_size=8,
        vad_filter=True,
        task="transcribe"
    )
    print(f"🎵 Detected language '{info.language}' with probability {info.language_probability * 100:.2f}%")
    return " ".join([segment.text for segment in segments])

# ───────────────────────────────────────────────────────────────────────────
# 🤖  Specialist sub-agents
# ───────────────────────────────────────────────────────────────────────────

# 🔍 Search specialist — needs grounding tool, so Gemini-only
search_agent = Agent(
    name="search_agent",
    model=FailoverModel([
        "gemini-2.5-flash-lite",          # primary: 20 RPD
        "gemini-2.5-flash",               # backup: 20 RPD
    ]),
    instruction="Search the web and return relevant results with sources.",
    tools=[google_search],
)

# 💬 Chat specialist — casual conversation, no tools
chat_agent = Agent(
    name="chat_agent",
    model=FailoverModel([
        "gemma-4-31b-it",                 # primary: 1.5K RPD 💰
        "gemini-3.1-flash-lite-preview",  # backup: 500 RPD
        "gemini-2.5-flash-lite",          # backup: 20 RPD
        "gemini-2.5-flash",               # last resort: 20 RPD
    ]),
    instruction="Handle casual conversation, explanations, and writing tasks.",
)

# 🧠 Thinking specialist — complex reasoning, may receive media via AgentTool
thinking_agent = Agent(
    name="thinking_agent",
    model=FailoverModel([
        "gemma-4-31b-it",                 # primary: 1.5K RPD 💰
        "gemini-3.1-flash-lite-preview",  # primary: 500 RPD (unstable, multimodal)
        "gemini-2.5-flash-lite",          # backup: 20 RPD (stable, multimodal)
        "gemini-2.5-flash",               # backup: 20 RPD (stable, multimodal)
    ]),
    instruction=(
        "Handle complex tasks: coding, technical guides, math, "
        "step-by-step reasoning, image analysis, and structured analysis. "
        "Always format code in fenced markdown blocks with the language tag."
    ),
)

# 🖼️🎵 Multimodal specialist — images, audio, video, PDFs
vision_agent = Agent(
    name="vision_agent",
    model=FailoverModel([
        "gemma-4-31b-it",                 # primary: 1.5K RPD 💰
        "gemini-3.1-flash-lite-preview",  # primary: 500 RPD
        "gemini-2.5-flash-lite",          # primary: 20 RPD
        "gemini-2.5-flash",               # backup: 20 RPD
    ]),
    instruction=(
        "You are a multimodal analysis specialist. "
        "When the user provides images, audio, video, or documents, "
        "analyze them carefully and describe what you observe.\n\n"
        "- 🖼️ Images: describe content, objects, text (OCR), colors, mood.\n"
        "- 🎵 Audio: transcribe speech and describe background sounds.\n"
        "- 🎬 Video: describe scenes, actions, and any spoken dialogue.\n"
        "- 📄 Documents: extract and summarize key information.\n"
        "⚠️ IMPORTANT: If the task requires deep technical expertise "
        "(network configs, code analysis, math problems, system design), "
        "respond with: 'This task needs the thinking_agent — please re-route.' "
        "Do NOT attempt to solve it yourself."
   ),
)

# 🎭 Orchestrator — uses tools, so MUST avoid Gemini 3.x
root_agent = Agent(
    name="root_agent",
    model=SmartFailoverModel(
        text_chain=[
            "gemma-4-31b-it",                 # primary: 1.5K RPD 💰
            "gemini-3.1-flash-lite-preview",  # backup: 500 RPD
            "gemini-2.5-flash-lite",          # backup: 20 RPD
            "gemini-2.5-flash",               # last resort: 20 RPD
        ],
        multimodal_chain=[
            "gemma-4-31b-it",                 # primary: 1.5K RPD 💰
            "gemini-3.1-flash-lite-preview",  # primary: 500 RPD (Gemma can't see)
            "gemini-2.5-flash-lite",          # backup: 20 RPD
            "gemini-2.5-flash",               # backup: 20 RPD
        ],
    ),
    instruction=(
        "You are the main assistant. Your ONLY job is to delegate tasks "
        "to the right specialist. When a sub-agent returns a result, "
        "present it to the user AS-IS without rephrasing.\n\n"
        "When present the result, put your thought in a THOUGHT-BOX "
        "and the result AS-IS in a separeted response box."
        "🎯 Routing rules (decide by the TASK, not just by media presence):\n\n"
        "- 🧠 `thinking_agent` → for ANY complex task: coding, technical guides, "
        "math, BGP/network configs, system design, step-by-step reasoning, "
        "diagram interpretation. **Use this even if the task includes images** "
        "(e.g. analyzing a network diagram, reading a code screenshot, "
        "explaining a chart, debugging from a screenshot).\n\n"
        "- 🎵 `transcribe_audio` → Use this tool when you need to understand, read "
        "or transcribe the contents of an audio, passing the path as argument.\n\n"
        "- 🖼️ `vision_agent` → ONLY for pure description/recognition tasks "
        "with no deeper reasoning needed: 'what's in this photo?', "
        "'not for transcribe audio', 'describe this video', 'OCR this document'.\n\n"
        "- 💬 `chat_agent` → casual chat, explanations, writing, brainstorming "
        "(text-only).\n\n"
        "- 🔍 `search_agent` → current info, news, web lookups, recent events.\n\n"
        "- 📋 `list_google_models` → user asks which AI models are available.\n\n"
        "💡 Tie-breaker: if a task involves an image AND requires expertise "
        "(networking, code, math, etc.), prefer `thinking_agent`."
    ),
    tools=[
        AgentTool(agent=chat_agent),
        AgentTool(agent=thinking_agent),
        AgentTool(agent=search_agent),
        AgentTool(agent=vision_agent),
        list_google_models,
        FunctionTool(transcribe_audio),
    ],
)
