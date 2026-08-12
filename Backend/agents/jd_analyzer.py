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
  "experience_level": "junior|mid|senior|null",
  "ambiguous_requirements": ["..."]
}}

Weights should reflect relative importance and sum to approximately 1.0 within each list.

HOW TO DECIDE WHAT IS A SKILL VS. WHAT IS AMBIGUOUS:
A requirement only belongs in must_have_skills or nice_to_have_skills if it names a
SPECIFIC, VERIFIABLE technology, tool, language, framework, certification, or
measurable qualification (e.g. "Python", "AWS", "PMP certification", "5 years of
Java experience"). A resume can be checked against it directly.

Everything else goes in ambiguous_requirements instead -- do NOT convert it into a
skill with an invented weight. This includes:
- Soft traits and personality descriptors: "team player", "self-starter",
  "great communicator", "rockstar", "ninja", "wear many hats"
- Vague domain references with no named technology: "some backend stuff",
  "modern tech stack", "familiar with cloud tools", "knows a bit of coding"
- Environment/culture descriptions: "fast-paced environment", "hit the ground
  running", "startup mentality"
Do not silently drop vague phrases either -- every vague phrase from the JD must
appear in ambiguous_requirements, worded close to the original text.

EXPERIENCE_LEVEL RULE:
Only set experience_level to "junior", "mid", or "senior" if the JD gives an
actual basis for it (explicit years of experience, or an explicit seniority
title like "Senior Engineer" or "entry-level"). If the JD gives no such basis,
return null. Never guess a level just because none was stated.

EXAMPLE (for calibration only, do not copy its content into your output):
JD snippet: "Need a rockstar dev, must know some backend stuff, 3+ years with
Python and Django required."
Correct output for that snippet:
  must_have_skills: [{{"skill": "Python", "weight": ...}}, {{"skill": "Django", "weight": ...}}]
  ambiguous_requirements: ["rockstar dev", "some backend stuff"]
  experience_level: "mid"   (justified by "3+ years" explicitly stated)
Incorrect: turning "some backend stuff" into a must-have skill called
"backend development", or turning "rockstar dev" into a "communication" skill.

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