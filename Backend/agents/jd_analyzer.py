"""
agents/jd_analyzer.py

Turns a raw, human-written job description into structured JSON that the
Resume Screener can compare candidates against.

Uses Groq's free API (Llama 3.3 70B) instead of Anthropic. Groq's SDK is
OpenAI-compatible, and its JSON mode (response_format={"type": "json_object"})
guarantees valid JSON back, so parsing is more reliable than pure prompt
instruction alone.
"""

import os
import json
import logging
from groq import Groq

logger = logging.getLogger("autohire.jd_analyzer")

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

MODEL = "llama-3.3-70b-versatile"

JD_ANALYZER_PROMPT = """You are a job description analysis assistant.
Given a raw job description, extract structured requirements.

Return ONLY valid JSON, no other text, in this exact format:
{{
  "must_have_skills": [{{"skill": "...", "weight": 0.0-1.0}}],
  "nice_to_have_skills": [{{"skill": "...", "weight": 0.0-1.0}}],
  "experience_level": "junior|mid|senior",
  "ambiguous_requirements": ["..."]
}}

Weights should reflect relative importance and sum to approximately 1.0 within each list.
Flag anything vague (e.g., "team player", "fast-paced environment") in ambiguous_requirements.

Job Description:
{jd_text}
"""


def _parse_json_response(raw_output: str) -> dict:
    """
    Groq's JSON mode should return clean JSON, but we still guard against
    stray markdown fences the way we did for the Anthropic version -- cheap
    insurance, and keeps behavior consistent if you ever swap providers again.
    """
    try:
        return json.loads(raw_output)
    except json.JSONDecodeError:
        cleaned = raw_output.replace("```json", "").replace("```", "").strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            logger.error("JD Analyzer returned unparseable output: %r", raw_output)
            raise


def analyze_jd(jd_text: str) -> dict:
    if not jd_text or not jd_text.strip():
        raise ValueError("jd_text must be non-empty")

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "user", "content": JD_ANALYZER_PROMPT.format(jd_text=jd_text)}
        ],
        response_format={"type": "json_object"},
        temperature=0.2,
        max_completion_tokens=1000,
    )
    raw_output = response.choices[0].message.content
    return _parse_json_response(raw_output)