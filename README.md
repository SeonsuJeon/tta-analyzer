# TTA 사업계획서 분석 도구

한국정보통신기술협회(TTA)가 수행 가능한 과제를 AI로 자동 분석하는 Flask 웹 애플리케이션입니다.

## 주요 기능

- **기존 사업계획서** PDF 업로드 → TTA의 업무 역량 자동 파악
- **품목개요서(상세RFP)** PDF 업로드 → TTA 수행 가능 과제 자동 선별
- 과제별 **관리번호 / 과제명 / 개발내용(상세) / 수행가능 근거** 출력
- 분석 결과 `.txt` 파일 저장

## 기술 스택

| 구분 | 사용 기술 |
|------|----------|
| 백엔드 | Python 3.10+, Flask 3.x |
| AI 분석 | OpenAI GPT-4o |
| PDF 파싱 | pdfplumber |
| 프론트엔드 | HTML / CSS / Vanilla JS (드래그&드롭 지원) |

## 설치 및 실행

```bash
# 1. 저장소 클론
git clone https://github.com/SeonsuJeon/tta-analyzer.git
cd tta-analyzer

# 2. 패키지 설치
pip install flask openai pdfplumber

# 3. 서버 실행
python app.py
```

브라우저에서 `http://127.0.0.1:5000` 접속

## 사용 방법

1. **OpenAI API Key** 입력 (sk-로 시작하는 키)
2. **① 기존 사업계획서** — TTA가 과거 수행한 사업계획서 PDF 업로드
3. **② 품목개요서(상세RFP)** — 분석할 RFP PDF 업로드
4. **분석 시작** 버튼 클릭 → 실시간 진행 로그 확인
5. 결과 확인 후 필요 시 `.txt`로 저장

## 분석 흐름

```
기존 사업계획서 PDF
        ↓
  [1단계] GPT-4o → TTA 역량 분석
        ↓
품목개요서(상세RFP) PDF + TTA 역량
        ↓
  [2단계] GPT-4o → 수행 가능 과제 선별
        ↓
관리번호 / 과제명 / 개발내용 / 수행가능 근거 출력
```

## 디렉토리 구조

```
tta-analyzer/
├── app.py              # Flask 백엔드
├── templates/
│   └── index.html      # 웹 UI
├── uploads/            # 임시 업로드 폴더 (분석 후 자동 삭제)
├── .gitignore
└── README.md
```

## 주의사항

- OpenAI API 사용 요금이 발생합니다 (GPT-4o 기준)
- PDF 파일당 최대 60,000자까지 분석합니다
- 업로드된 PDF는 분석 완료 후 서버에서 자동 삭제됩니다
