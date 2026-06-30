"""
TTA 사업계획서 분석 도구 - Flask 웹앱
"""

import os
import json
import re
import uuid
import threading
from pathlib import Path

from flask import Flask, render_template, request, jsonify, session
import pdfplumber
from openai import OpenAI

# ─── 설정 ────────────────────────────────────────────────────────────────────
MODEL = "gpt-4o"
MAX_TOKENS = 8000
PDF_CHAR_LIMIT = 60000

UPLOAD_FOLDER = Path("uploads")
UPLOAD_FOLDER.mkdir(exist_ok=True)

app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024  # 100MB

# 분석 작업 상태 저장 {job_id: {"status": ..., "log": [], "result": ...}}
jobs: dict[str, dict] = {}
jobs_lock = threading.Lock()


# ─── PDF 파싱 ─────────────────────────────────────────────────────────────────
def extract_text_from_pdf(path: Path) -> str:
    parts = []
    try:
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    parts.append(t)
    except Exception as e:
        return f"[PDF 파싱 오류: {e}]"
    return "\n".join(parts)[:PDF_CHAR_LIMIT]


# ─── OpenAI 분석 ──────────────────────────────────────────────────────────────
def chat(client: OpenAI, prompt: str, max_tokens: int = 4000) -> str:
    resp = client.chat.completions.create(
        model=MODEL,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.choices[0].message.content.strip()


def run_analysis(job_id: str, existing_paths: list, rfp_paths: list, api_key: str):
    def log(msg: str):
        with jobs_lock:
            jobs[job_id]["log"].append(msg)

    def set_status(s: str):
        with jobs_lock:
            jobs[job_id]["status"] = s

    try:
        set_status("running")
        log("PDF 파일 파싱 시작...")

        # ── PDF 텍스트 추출 ──
        existing_docs = {}
        for p in existing_paths:
            log(f"  기존 사업계획서 파싱: {Path(p).name}")
            existing_docs[Path(p).name] = extract_text_from_pdf(Path(p))

        rfp_docs = {}
        for p in rfp_paths:
            log(f"  품목개요서 파싱: {Path(p).name}")
            rfp_docs[Path(p).name] = extract_text_from_pdf(Path(p))

        client = OpenAI(api_key=api_key)

        # ── 1단계 ──
        log("1단계: 기존 사업계획서 분석 중 (GPT-4o)...")
        existing_combined = "\n\n".join(
            f"=== 파일: {name} ===\n{text}" for name, text in existing_docs.items()
        )
        step1_prompt = f"""아래는 한국정보통신기술협회(TTA)가 과거에 수행한 사업계획서들입니다.
이 문서들을 분석하여 TTA가 수행해 온 주요 업무 영역, 역량, 전문 분야를 구체적으로 파악해 주세요.

[기존 사업계획서]
{existing_combined}

분석 결과를 다음 형식으로 정리해 주세요:
1. TTA의 주요 업무 영역 (구체적으로)
2. TTA의 핵심 역량 및 전문성
3. TTA가 수행 가능한 업무 유형
"""
        capability_summary = chat(client, step1_prompt, max_tokens=4000)
        log("1단계 완료.")

        # ── 2단계 ──
        log("2단계: 품목개요서(상세RFP) 분석 및 매칭 중 (GPT-4o)...")
        rfp_combined = "\n\n".join(
            f"=== 파일: {name} ===\n{text}" for name, text in rfp_docs.items()
        )
        step2_prompt = f"""당신은 한국정보통신기술협회(TTA)의 사업 전략 전문가입니다.

아래 [TTA 역량 분석]을 바탕으로, [품목개요서(상세RFP)] 에 포함된 과제들 중
TTA가 수행할 수 있는 과제를 선별하고 상세히 분석해 주세요.

[TTA 역량 분석]
{capability_summary}

[품목개요서(상세RFP)]
{rfp_combined}

─────────────────────────────────────────────────
출력 형식 (JSON 배열, 마크다운 코드블록 없이 순수 JSON만 출력):
[
  {{
    "관리번호": "과제의 관리번호 또는 식별번호",
    "과제명": "과제 전체 명칭",
    "개발내용": "TTA가 수행 가능한 구체적인 개발/수행 내용. 다음을 포함하여 500자 이상 상세히 기술: ① 과제 배경 및 목적, ② 주요 개발/연구 내용, ③ TTA가 담당할 수 있는 세부 업무, ④ 기대 성과 및 활용 방안",
    "수행가능_근거": "TTA의 어떤 역량/경험이 이 과제 수행에 적합한지 설명"
  }}
]

JSON 배열만 출력하세요. 설명 텍스트 없이.
"""
        raw_json = chat(client, step2_prompt, max_tokens=MAX_TOKENS)
        log("2단계 완료. 결과 파싱 중...")

        # JSON 파싱
        tasks = None
        try:
            tasks = json.loads(raw_json)
        except json.JSONDecodeError:
            m = re.search(r"\[.*\]", raw_json, re.DOTALL)
            if m:
                try:
                    tasks = json.loads(m.group())
                except Exception:
                    pass

        with jobs_lock:
            jobs[job_id]["capability_summary"] = capability_summary
            jobs[job_id]["tasks"] = tasks
            jobs[job_id]["raw"] = raw_json if tasks is None else None
            jobs[job_id]["status"] = "done"
        log("✔ 분석 완료!")

    except Exception as e:
        with jobs_lock:
            jobs[job_id]["status"] = "error"
            jobs[job_id]["error"] = str(e)
        log(f"오류 발생: {e}")
    finally:
        # 업로드 파일 정리
        for p in existing_paths + rfp_paths:
            try:
                Path(p).unlink()
            except Exception:
                pass


# ─── 라우트 ───────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/analyze", methods=["POST"])
def analyze():
    api_key = request.form.get("api_key", "").strip()
    if not api_key:
        return jsonify({"error": "OpenAI API Key를 입력하세요."}), 400

    existing_files = request.files.getlist("existing_files")
    rfp_files = request.files.getlist("rfp_files")

    if not existing_files or all(f.filename == "" for f in existing_files):
        return jsonify({"error": "기존 사업계획서 PDF를 1개 이상 업로드하세요."}), 400
    if not rfp_files or all(f.filename == "" for f in rfp_files):
        return jsonify({"error": "품목개요서(상세RFP) PDF를 1개 이상 업로드하세요."}), 400

    job_id = uuid.uuid4().hex
    job_dir = UPLOAD_FOLDER / job_id
    job_dir.mkdir()

    existing_paths, rfp_paths = [], []

    for f in existing_files:
        if f.filename:
            p = job_dir / f"e_{f.filename}"
            f.save(p)
            existing_paths.append(str(p))

    for f in rfp_files:
        if f.filename:
            p = job_dir / f"r_{f.filename}"
            f.save(p)
            rfp_paths.append(str(p))

    with jobs_lock:
        jobs[job_id] = {"status": "pending", "log": [], "tasks": None, "error": None}

    thread = threading.Thread(
        target=run_analysis,
        args=(job_id, existing_paths, rfp_paths, api_key),
        daemon=True,
    )
    thread.start()

    return jsonify({"job_id": job_id})


@app.route("/status/<job_id>")
def status(job_id: str):
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "없는 작업입니다."}), 404
    return jsonify({
        "status": job["status"],
        "log": job["log"],
        "error": job.get("error"),
    })


@app.route("/result/<job_id>")
def result(job_id: str):
    with jobs_lock:
        job = jobs.get(job_id)
    if not job or job["status"] != "done":
        return jsonify({"error": "아직 완료되지 않았습니다."}), 400
    return jsonify({
        "tasks": job.get("tasks"),
        "capability_summary": job.get("capability_summary"),
        "raw": job.get("raw"),
    })


if __name__ == "__main__":
    app.run(debug=True, port=5000)
