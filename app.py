"""
TTA 사업계획서 분석 도구 - Flask 웹앱 (Vercel 서버리스 호환)
"""

import io
import os
import json
import re

from flask import Flask, render_template, request, jsonify
import pdfplumber
from openai import OpenAI

# ─── 설정 ────────────────────────────────────────────────────────────────────
MODEL = "gpt-4o"
MAX_TOKENS = 8000
PDF_CHAR_LIMIT = 60000

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024  # 100 MB


# ─── PDF 파싱 (메모리 기반) ───────────────────────────────────────────────────
def extract_text_from_bytes(data: bytes) -> str:
    parts = []
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    parts.append(t)
    except Exception as e:
        return f"[PDF 파싱 오류: {e}]"
    return "\n".join(parts)[:PDF_CHAR_LIMIT]


# ─── OpenAI 호출 ──────────────────────────────────────────────────────────────
def chat(client: OpenAI, prompt: str, max_tokens: int = 4000) -> str:
    resp = client.chat.completions.create(
        model=MODEL,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.choices[0].message.content.strip()


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

    try:
        client = OpenAI(api_key=api_key)

        # ── PDF 텍스트 추출 ──
        existing_parts = []
        for f in existing_files:
            if f.filename:
                text = extract_text_from_bytes(f.read())
                existing_parts.append(f"=== 파일: {f.filename} ===\n{text}")

        rfp_parts = []
        for f in rfp_files:
            if f.filename:
                text = extract_text_from_bytes(f.read())
                rfp_parts.append(f"=== 파일: {f.filename} ===\n{text}")

        existing_combined = "\n\n".join(existing_parts)
        rfp_combined = "\n\n".join(rfp_parts)

        # ── 1단계: TTA 역량 분석 ──
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

        # ── 2단계: RFP 매칭 ──
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

        # ── JSON 파싱 ──
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

        return jsonify({
            "tasks": tasks,
            "capability_summary": capability_summary,
            "raw": raw_json if tasks is None else None,
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
