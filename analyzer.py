from __future__ import annotations

import json
import os
from typing import Any

MODEL_NAME = "gemini-2.5-flash"


def _require_api_key() -> str:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is required. Gemini-only mode is enabled.")
    return api_key


def _model():
    try:
        import google.generativeai as genai
    except Exception as exc:
        raise RuntimeError(
            "google-generativeai package is required for Gemini-only mode."
        ) from exc

    api_key = _require_api_key()
    genai.configure(api_key=api_key)
    return genai.GenerativeModel(MODEL_NAME)


def _json_call(payload: dict[str, Any]) -> dict[str, Any]:
    model = _model()
    response = model.generate_content(
        json.dumps(payload, ensure_ascii=True),
        generation_config={"response_mime_type": "application/json"},
    )
    return json.loads(response.text)


def analyze_project(project: dict[str, Any]) -> dict[str, Any]:
    prompt = {
        "task": "Analyze a failed side project and output strict JSON only.",
        "requirements": [
            "Use realistic startup language.",
            "No hype. No generic advice.",
            "Ground claims in provided project details.",
        ],
        "schema": {
            "confidence": "low|medium|high",
            "failure_vector": ["string", "string", "string"],
            "risk_scores": {
                "market_risk": "0-10",
                "execution_risk": "0-10",
                "founder_risk": "0-10",
            },
            "common_pattern_summary": "string",
            "next_attempt_playbook": ["string", "string", "string"],
        },
        "project": project,
    }
    data = _json_call(prompt)
    data["model"] = MODEL_NAME
    return data


def analyze_portfolio(projects: list[dict[str, Any]]) -> dict[str, Any]:
    prompt = {
        "task": "Analyze this portfolio of failed side projects and return dashboard-ready JSON for a Failure Pattern Console.",
        "requirements": [
            "Use only the provided dataset.",
            "Produce realistic and concise insights.",
            "Cause wording must be clean, canonical, and human-readable.",
            "Sort common causes by impact descending.",
            "Use rounded numeric values where needed.",
        ],
        "schema": {
            "headline_stats": {
                "total_projects": "integer",
                "top_cause_name": "string",
                "top_cause_votes": "integer",
                "top_cause_coverage_pct": "number",
            },
            "signals": {
                "avg_burnout": "number",
                "avg_market_signal": "number",
                "avg_tech_debt": "number",
            },
            "common_causes": [
                {
                    "name": "string",
                    "total_votes": "integer",
                    "project_count": "integer",
                    "coverage_pct": "number",
                    "confidence": "low|medium|high",
                }
            ],
            "causes_chart_note": "string",
            "console_cards": [
                {
                    "label": "string",
                    "value": "string",
                    "note": "string",
                }
            ],
            "cause_leaderboard": ["string"],
            "category_story": ["string"],
        },
        "projects": projects,
    }
    data = _json_call(prompt)
    data["model"] = MODEL_NAME
    return data
