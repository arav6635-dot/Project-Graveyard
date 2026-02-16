from __future__ import annotations

import json
import re
import sqlite3
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template, request

from analyzer import analyze_portfolio, analyze_project

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "graveyard.db"
SEED_SQL_PATH = BASE_DIR / "db" / "seed.sql"

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False

DEFAULT_CAUSES = [
    "No Market Need",
    "Scope Creep",
    "Burnout",
    "Ran Out of Time",
    "Poor Distribution",
    "Unclear Positioning",
    "Team Conflict",
    "Technical Complexity",
    "No Monetization Path",
    "Lost Motivation",
]

CAUSE_ALIASES = {
    "no market fit": "No Market Need",
    "no product market fit": "No Market Need",
    "market fit": "No Market Need",
    "scope creep": "Scope Creep",
    "burnt out": "Burnout",
    "burn out": "Burnout",
    "poor marketing": "Poor Distribution",
    "distribution": "Poor Distribution",
    "team issues": "Team Conflict",
    "team conflict": "Team Conflict",
    "complexity": "Technical Complexity",
    "tech complexity": "Technical Complexity",
    "no monetization": "No Monetization Path",
    "lost interest": "Lost Motivation",
    "lost motivation": "Lost Motivation",
}


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_default_causes(conn: sqlite3.Connection) -> None:
    for cause in DEFAULT_CAUSES:
        conn.execute(
            "INSERT OR IGNORE INTO failure_causes(name) VALUES(?)",
            (cause,),
        )


def normalize_cause_name(raw: Any) -> str | None:
    text = str(raw or "").strip().lower()
    if not text:
        return None

    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[^a-z0-9 &/+'-]", "", text).strip()
    if len(text) < 4:
        return None

    letters = re.sub(r"[^a-z]", "", text)
    if letters and not any(ch in "aeiou" for ch in letters):
        return None

    canonical = CAUSE_ALIASES.get(text, text)
    if canonical in DEFAULT_CAUSES:
        return canonical
    return canonical.title()[:56]


def cleanup_cause_data(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT id, name FROM failure_causes ORDER BY id ASC").fetchall()
    for row in rows:
        old_id = row["id"]
        normalized = normalize_cause_name(row["name"])
        if not normalized:
            conn.execute("DELETE FROM project_cause_votes WHERE cause_id = ?", (old_id,))
            conn.execute("DELETE FROM failure_causes WHERE id = ?", (old_id,))
            continue

        conn.execute("INSERT OR IGNORE INTO failure_causes(name) VALUES(?)", (normalized,))
        new_id = conn.execute(
            "SELECT id FROM failure_causes WHERE name = ?",
            (normalized,),
        ).fetchone()["id"]

        if new_id == old_id:
            continue

        votes = conn.execute(
            "SELECT project_id, votes FROM project_cause_votes WHERE cause_id = ?",
            (old_id,),
        ).fetchall()
        for vote in votes:
            conn.execute(
                """
                INSERT INTO project_cause_votes(project_id, cause_id, votes, source)
                VALUES(?, ?, ?, 'cleanup')
                ON CONFLICT(project_id, cause_id) DO UPDATE SET votes = votes + excluded.votes
                """,
                (vote["project_id"], new_id, vote["votes"]),
            )

        conn.execute("DELETE FROM project_cause_votes WHERE cause_id = ?", (old_id,))
        conn.execute("DELETE FROM failure_causes WHERE id = ?", (old_id,))


def init_db() -> None:
    conn = db()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            summary TEXT NOT NULL,
            category TEXT NOT NULL,
            status TEXT NOT NULL,
            idea_origin TEXT,
            problem_target TEXT,
            target_audience TEXT,
            stack TEXT,
            team_size INTEGER,
            duration_months INTEGER,
            budget_range TEXT,
            timeline TEXT,
            what_happened TEXT,
            why_failed TEXT,
            lessons_learned TEXT,
            burnout_level INTEGER DEFAULT 0,
            market_signal INTEGER DEFAULT 0,
            tech_debt_level INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS failure_causes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        );

        CREATE TABLE IF NOT EXISTS project_cause_votes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            cause_id INTEGER NOT NULL,
            votes INTEGER NOT NULL DEFAULT 1,
            source TEXT NOT NULL DEFAULT 'crowd',
            UNIQUE(project_id, cause_id),
            FOREIGN KEY(project_id) REFERENCES projects(id),
            FOREIGN KEY(cause_id) REFERENCES failure_causes(id)
        );

        CREATE TABLE IF NOT EXISTS project_tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            tag TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(project_id, tag),
            FOREIGN KEY(project_id) REFERENCES projects(id)
        );

        CREATE TABLE IF NOT EXISTS analysis_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            model TEXT NOT NULL,
            analysis_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(project_id) REFERENCES projects(id)
        );

        CREATE TABLE IF NOT EXISTS ai_analytics_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fingerprint TEXT UNIQUE NOT NULL,
            model TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )
    ensure_default_causes(conn)
    cleanup_cause_data(conn)

    existing = conn.execute("SELECT COUNT(*) AS c FROM projects").fetchone()["c"]
    if existing == 0:
        seed_projects_from_sql(conn)

    conn.commit()
    conn.close()


def seed_projects_from_sql(conn: sqlite3.Connection) -> None:
    if not SEED_SQL_PATH.exists():
        return
    conn.executescript(SEED_SQL_PATH.read_text(encoding="utf-8"))


def project_with_meta(conn: sqlite3.Connection, project_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not row:
        return None

    causes = conn.execute(
        """
        SELECT fc.name, pcv.votes
        FROM project_cause_votes pcv
        JOIN failure_causes fc ON fc.id = pcv.cause_id
        WHERE pcv.project_id = ?
        ORDER BY pcv.votes DESC, fc.name ASC
        """,
        (project_id,),
    ).fetchall()

    tags = conn.execute(
        "SELECT tag FROM project_tags WHERE project_id = ? ORDER BY tag ASC",
        (project_id,),
    ).fetchall()

    latest_analysis = conn.execute(
        """
        SELECT model, analysis_json, created_at
        FROM analysis_reports
        WHERE project_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (project_id,),
    ).fetchone()

    data = dict(row)
    data["causes"] = [dict(c) for c in causes]
    data["tags"] = [t["tag"] for t in tags]
    data["analysis"] = None
    if latest_analysis:
        data["analysis"] = {
            "model": latest_analysis["model"],
            "created_at": latest_analysis["created_at"],
            "report": json.loads(latest_analysis["analysis_json"]),
        }
    return data

def parse_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def build_portfolio_snapshot(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    ids = [r["id"] for r in conn.execute("SELECT id FROM projects ORDER BY id ASC").fetchall()]
    projects = [project_with_meta(conn, pid) for pid in ids]
    return [p for p in projects if p]


def portfolio_fingerprint(projects: list[dict[str, Any]]) -> str:
    cache_version = "analytics-v2"
    compact = json.dumps(
        {"version": cache_version, "projects": projects},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(compact.encode("utf-8")).hexdigest()


def regroup_causes_for_small_sample(
    causes: list[dict[str, Any]], total_projects: int
) -> list[dict[str, Any]]:
    themes = [
        ("Validation & Demand", ["market", "positioning", "audience", "need", "demand"]),
        ("Distribution & Growth", ["distribution", "marketing", "acquisition", "channel", "seo"]),
        ("Execution & Complexity", ["technical", "complex", "debt", "architecture", "scope"]),
        ("Team & Founder Bandwidth", ["burnout", "motivation", "team", "conflict", "time"]),
        ("Monetization & Business Model", ["monetization", "pricing", "revenue", "business model"]),
    ]

    grouped: dict[str, dict[str, Any]] = {}
    for cause in causes:
        label = cause["name"]
        low = label.lower()
        for theme, keywords in themes:
            if any(word in low for word in keywords):
                label = theme
                break

        bucket = grouped.setdefault(
            label,
            {
                "name": label,
                "total_votes": 0,
                "project_count": 0,
                "coverage_pct": 0.0,
                "confidence": "medium",
            },
        )
        bucket["total_votes"] += max(0, parse_int(cause.get("total_votes"), 0))
        bucket["project_count"] += max(0, parse_int(cause.get("project_count"), 0))

    merged = []
    for item in grouped.values():
        project_count = min(total_projects, item["project_count"])
        coverage = round((project_count / total_projects) * 100, 1) if total_projects else 0.0
        confidence = "high" if item["total_votes"] >= 5 else "medium" if item["total_votes"] >= 2 else "low"
        merged.append(
            {
                "name": item["name"],
                "total_votes": item["total_votes"],
                "project_count": project_count,
                "coverage_pct": coverage,
                "confidence": confidence,
            }
        )

    merged.sort(key=lambda x: (-x["total_votes"], -x["project_count"], x["name"]))
    return merged[:6]


def normalize_ai_analytics(data: dict[str, Any], total_projects: int) -> dict[str, Any]:
    common_causes_raw = data.get("common_causes") or []
    common_causes: list[dict[str, Any]] = []
    for item in common_causes_raw[:10]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        votes = max(0, parse_int(item.get("total_votes"), 0))
        project_count = max(0, parse_int(item.get("project_count"), 0))
        coverage = parse_float(item.get("coverage_pct"), 0.0)
        if total_projects > 0 and (coverage <= 0.0 or coverage > 100):
            coverage = round((project_count / total_projects) * 100, 1)
        common_causes.append(
            {
                "name": name[:60],
                "total_votes": votes,
                "project_count": project_count,
                "coverage_pct": max(0.0, min(100.0, coverage)),
                "confidence": str(item.get("confidence", "medium")).lower(),
            }
        )
    common_causes.sort(key=lambda x: (-x["total_votes"], -x["project_count"], x["name"]))

    # In tiny portfolios, Gemini may return many equally small causes.
    # Group them into clearer macro themes for a less noisy chart.
    is_fragmented = (
        len(common_causes) >= 5
        and total_projects <= 6
        and len({c["total_votes"] for c in common_causes[:6]}) == 1
    )
    if is_fragmented:
        common_causes = regroup_causes_for_small_sample(common_causes, total_projects)

    signals_raw = data.get("signals") or {}
    signals = {
        "avg_burnout": round(max(0.0, min(10.0, parse_float(signals_raw.get("avg_burnout"), 0.0))), 1),
        "avg_market_signal": round(max(0.0, min(10.0, parse_float(signals_raw.get("avg_market_signal"), 0.0))), 1),
        "avg_tech_debt": round(max(0.0, min(10.0, parse_float(signals_raw.get("avg_tech_debt"), 0.0))), 1),
    }

    cards: list[dict[str, str]] = []
    for card in (data.get("console_cards") or [])[:4]:
        if not isinstance(card, dict):
            continue
        cards.append(
            {
                "label": str(card.get("label", "")).strip()[:40],
                "value": str(card.get("value", "")).strip()[:40],
                "note": str(card.get("note", "")).strip()[:120],
            }
        )
    if not cards:
        cards = [
            {"label": "Dataset size", "value": str(total_projects), "note": "Active failed-project records analyzed by Gemini."},
            {"label": "Primary risk", "value": common_causes[0]["name"] if common_causes else "Insufficient signal", "note": "Most repeated failure theme in current submissions."},
        ]

    leaderboard = [str(x).strip()[:80] for x in (data.get("cause_leaderboard") or []) if str(x).strip()][:6]
    category_story = [str(x).strip()[:110] for x in (data.get("category_story") or []) if str(x).strip()][:6]

    chart_note = str(data.get("causes_chart_note", "")).strip() or "Gemini-derived cause clustering across current graveyard projects."
    if is_fragmented:
        chart_note = (
            "Small dataset detected. Causes are grouped into macro patterns for clearer signal."
        )
    top = (data.get("headline_stats") or {})
    if common_causes:
        top_default_name = common_causes[0]["name"]
        top_default_votes = common_causes[0]["total_votes"]
        top_default_coverage = common_causes[0]["coverage_pct"]
    else:
        top_default_name = "N/A"
        top_default_votes = 0
        top_default_coverage = 0.0

    top_name = str(top.get("top_cause_name", top_default_name)).strip()
    top_votes = max(0, parse_int(top.get("top_cause_votes"), top_default_votes))
    top_coverage = max(
        0.0,
        min(100.0, parse_float(top.get("top_cause_coverage_pct"), top_default_coverage)),
    )
    if is_fragmented:
        top_name = top_default_name
        top_votes = top_default_votes
        top_coverage = top_default_coverage

    return {
        "total_projects": max(0, parse_int(top.get("total_projects"), total_projects)),
        "top_cause_name": top_name[:60],
        "top_cause_votes": top_votes,
        "top_cause_coverage_pct": round(top_coverage, 1),
        "signals": signals,
        "common_causes": common_causes,
        "causes_chart_note": chart_note[:160],
        "console_cards": cards,
        "cause_leaderboard": leaderboard,
        "category_story": category_story,
    }


@app.get("/")
def index() -> str:
    return render_template("index.html")


@app.get("/api/causes")
def list_causes():
    conn = db()
    rows = conn.execute("SELECT id, name FROM failure_causes ORDER BY name ASC").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.get("/api/projects")
def list_projects():
    category = request.args.get("category")
    status = request.args.get("status")

    clauses = []
    params: list[Any] = []
    if category:
        clauses.append("category = ?")
        params.append(category)
    if status:
        clauses.append("status = ?")
        params.append(status)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    conn = db()
    rows = conn.execute(
        f"SELECT id FROM projects {where} ORDER BY datetime(created_at) DESC, id DESC", params
    ).fetchall()
    data = [project_with_meta(conn, r["id"]) for r in rows]
    conn.close()
    return jsonify(data)


@app.post("/api/projects")
def create_project():
    payload = request.get_json(force=True, silent=True) or {}

    required = ["title", "summary", "category", "status", "why_failed"]
    missing = [field for field in required if not str(payload.get(field, "")).strip()]
    if missing:
        return jsonify({"error": f"Missing required fields: {', '.join(missing)}"}), 400

    conn = db()
    now = datetime.utcnow().isoformat(timespec="seconds")
    cur = conn.execute(
        """
        INSERT INTO projects(
            title, summary, category, status,
            idea_origin, problem_target, target_audience,
            stack, team_size, duration_months, budget_range,
            timeline, what_happened, why_failed, lessons_learned,
            burnout_level, market_signal, tech_debt_level, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload.get("title", "").strip(),
            payload.get("summary", "").strip(),
            payload.get("category", "Unknown").strip(),
            payload.get("status", "Archived").strip(),
            payload.get("idea_origin", "").strip(),
            payload.get("problem_target", "").strip(),
            payload.get("target_audience", "").strip(),
            payload.get("stack", "").strip(),
            parse_int(payload.get("team_size"), 1),
            parse_int(payload.get("duration_months"), 0),
            payload.get("budget_range", "").strip(),
            payload.get("timeline", "").strip(),
            payload.get("what_happened", "").strip(),
            payload.get("why_failed", "").strip(),
            payload.get("lessons_learned", "").strip(),
            max(0, min(10, parse_int(payload.get("burnout_level"), 0))),
            max(0, min(10, parse_int(payload.get("market_signal"), 0))),
            max(0, min(10, parse_int(payload.get("tech_debt_level"), 0))),
            now,
        ),
    )
    project_id = cur.lastrowid

    for tag in payload.get("tags", []):
        clean = str(tag).strip().lower()
        if clean:
            conn.execute(
                "INSERT OR IGNORE INTO project_tags(project_id, tag, created_at) VALUES(?, ?, ?)",
                (project_id, clean, now),
            )

    for cause_name in payload.get("initial_causes", []):
        clean = normalize_cause_name(cause_name)
        if not clean:
            continue
        conn.execute("INSERT OR IGNORE INTO failure_causes(name) VALUES(?)", (clean,))
        cause_id = conn.execute(
            "SELECT id FROM failure_causes WHERE name = ?", (clean,)
        ).fetchone()["id"]
        conn.execute(
            """
            INSERT INTO project_cause_votes(project_id, cause_id, votes, source)
            VALUES(?, ?, 1, 'owner')
            ON CONFLICT(project_id, cause_id) DO UPDATE SET votes = votes + 1
            """,
            (project_id, cause_id),
        )

    conn.commit()
    project = project_with_meta(conn, project_id)
    conn.close()
    return jsonify(project), 201


@app.post("/api/projects/<int:project_id>/vote-cause")
def vote_cause(project_id: int):
    payload = request.get_json(force=True, silent=True) or {}
    cause_name = normalize_cause_name(payload.get("cause"))
    votes = max(1, parse_int(payload.get("votes"), 1))

    if not cause_name:
        return jsonify({"error": "cause is invalid or too noisy"}), 400

    conn = db()
    exists = conn.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not exists:
        conn.close()
        return jsonify({"error": "Project not found"}), 404

    conn.execute("INSERT OR IGNORE INTO failure_causes(name) VALUES(?)", (cause_name,))
    cause_id = conn.execute(
        "SELECT id FROM failure_causes WHERE name = ?", (cause_name,)
    ).fetchone()["id"]

    conn.execute(
        """
        INSERT INTO project_cause_votes(project_id, cause_id, votes, source)
        VALUES(?, ?, ?, 'crowd')
        ON CONFLICT(project_id, cause_id) DO UPDATE SET votes = votes + excluded.votes
        """,
        (project_id, cause_id, votes),
    )
    conn.commit()
    project = project_with_meta(conn, project_id)
    conn.close()
    return jsonify(project)


@app.post("/api/projects/<int:project_id>/tags")
def add_tag(project_id: int):
    payload = request.get_json(force=True, silent=True) or {}
    tag = str(payload.get("tag", "")).strip().lower()
    if not tag:
        return jsonify({"error": "tag is required"}), 400

    conn = db()
    exists = conn.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not exists:
        conn.close()
        return jsonify({"error": "Project not found"}), 404

    conn.execute(
        "INSERT OR IGNORE INTO project_tags(project_id, tag, created_at) VALUES(?, ?, ?)",
        (project_id, tag, datetime.utcnow().isoformat(timespec="seconds")),
    )
    conn.commit()
    project = project_with_meta(conn, project_id)
    conn.close()
    return jsonify(project)


@app.post("/api/projects/<int:project_id>/analyze")
def analyze(project_id: int):
    conn = db()
    project = project_with_meta(conn, project_id)
    if not project:
        conn.close()
        return jsonify({"error": "Project not found"}), 404

    try:
        report = analyze_project(project)
    except Exception as exc:
        conn.close()
        return jsonify({"error": f"Gemini analysis failed: {exc}"}), 502
    conn.execute(
        "INSERT INTO analysis_reports(project_id, model, analysis_json, created_at) VALUES(?, ?, ?, ?)",
        (
            project_id,
            report.get("model", "gemini-2.5-flash"),
            json.dumps(report, ensure_ascii=True),
            datetime.utcnow().isoformat(timespec="seconds"),
        ),
    )
    conn.commit()
    updated = project_with_meta(conn, project_id)
    conn.close()
    return jsonify(updated)


@app.get("/api/analytics/overview")
def analytics_overview():
    conn = db()
    projects = build_portfolio_snapshot(conn)
    total_projects = len(projects)
    if total_projects == 0:
        conn.close()
        return jsonify(
            {
                "total_projects": 0,
                "top_cause_name": "N/A",
                "top_cause_votes": 0,
                "top_cause_coverage_pct": 0.0,
                "signals": {"avg_burnout": 0.0, "avg_market_signal": 0.0, "avg_tech_debt": 0.0},
                "common_causes": [],
                "causes_chart_note": "No project data yet.",
                "console_cards": [],
                "cause_leaderboard": [],
                "category_story": [],
            }
        )

    fingerprint = portfolio_fingerprint(projects)
    cached = conn.execute(
        "SELECT payload_json FROM ai_analytics_cache WHERE fingerprint = ?",
        (fingerprint,),
    ).fetchone()

    if cached:
        payload = json.loads(cached["payload_json"])
        conn.close()
        return jsonify(payload)

    try:
        ai_result = analyze_portfolio(projects)
    except Exception as exc:
        conn.close()
        return jsonify({"error": f"Gemini analytics failed: {exc}"}), 502

    payload = normalize_ai_analytics(ai_result, total_projects)
    conn.execute(
        """
        INSERT INTO ai_analytics_cache(fingerprint, model, payload_json, created_at)
        VALUES(?, ?, ?, ?)
        ON CONFLICT(fingerprint) DO UPDATE
        SET model = excluded.model,
            payload_json = excluded.payload_json,
            created_at = excluded.created_at
        """,
        (
            fingerprint,
            ai_result.get("model", "gemini-2.5-flash"),
            json.dumps(payload, ensure_ascii=True),
            datetime.utcnow().isoformat(timespec="seconds"),
        ),
    )
    conn.commit()
    conn.close()
    return jsonify(payload)


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
