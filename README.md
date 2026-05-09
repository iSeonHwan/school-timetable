# 학교 시간표 관리 시스템

PyQt6 + SQLAlchemy 기반의 **학교 시간표 자동 생성 및 관리 데스크톱 애플리케이션**입니다.  
학년/반 편제 입력부터 시간표 자동 생성, 수정/결재, PDF 출력, NEIS 내보내기까지 전체 시간표 관리 워크플로우를 지원합니다.

---

## 주요 기능

### 기초 데이터 입력
- **학년/반 편제** — 학년(1~3학년) 및 학급 등록·관리
- **교사 관리** — 교사 등록, 담임 배정, 일 최대 수업 수 설정, 요일×교시별 불가 시간 지정
- **교과목/시수 배정** — 과목 등록 (색상 지정), 반별 주당 시수 및 담당 교사 배정
- **교실 관리** — 일반교실·특별실 등록 (과학실, 음악실, 체육관 등)

### 시간표 자동 생성
- **Greedy + Random Restart** 알고리즘 (최대 30회 재시도)
- **Hard 제약조건**: 학반 중복 불가, 교사 중복 불가, 교실 중복 불가, 교사 불가 시간
- **Soft 제약조건**: 교사 일 최대 수업 수 제한
- 백그라운드 스레드(QThread)에서 실행 → UI 멈춤 없이 생성

### 시간표 조회
- **Mode A (반별 주간)** — 요일(월~금) × 교시(1~7) 그리드, 학반별 조회
- **Mode B (전체 1일)** — 교시 × 학반 그리드, 특정 요일 전체 학급 동시 조회
- **교사별 시간표** — 교사별 배정 현황 조회

### 시간표 수정 및 변경 관리
- **셀 더블클릭 편집** — 시간표 그리드에서 직접 더블클릭하여 수정
- **직접 수정** — 즉시 시간표에 반영 (변경 이력 자동 기록)
- **변경 신청/결재** — 변경 사유를 포함한 신청 → 승인/거절 워크플로우
- **승인 시 자동 반영** — 승인된 변경사항은 시간표에 자동 적용

### 학사일정 관리
- 월별 캘린더 + 일정 목록 동시 표시
- 7가지 일정 유형 (개교기념일, 시험, 축제, 방학, 공휴일, 행사, 기타)
- 유형별 색상 구분, 일정 추가·수정·삭제

### 변경 이력 추적
- 시간표 생성·수정·삭제 내역 자동 기록
- 날짜 범위, 학반, 변경 유형별 필터 검색
- 변경 전/후 상세 비교 조회

### 내보내기
- **PDF 출력** — 전체 학반·교사 시간표를 PDF로 출력 (한글 폰트 지원)
- **NEIS 내보내기** — 나이스(NEIS) 템플릿에 복사 가능한 Excel(.xlsx) 형식 출력

### 데이터베이스
- **SQLite** (로컬 단일 파일, 기본) 및 **PostgreSQL** (네트워크 공유) 지원
- 앱 내에서 DB 연결 설정 변경 가능 (설정 즉시 반영)

---

## 기술 스택

| 계층 | 기술 |
|------|------|
| **UI** | PyQt6 (Qt 6.x), Fusion 스타일 |
| **ORM** | SQLAlchemy 2.0 (Declarative) |
| **생성 알고리즘** | Greedy + Random Restart (Python) |
| **PDF 출력** | ReportLab 4.x (platypus, 한글 TTF) |
| **Excel 출력** | OpenPyXL 3.x (NEIS 스타일 서식) |
| **DB 지원** | SQLite (내장), PostgreSQL (psycopg2) |
| **병렬 처리** | QThread (UI 논블로킹) |
| **설치 프로그램** | PyInstaller 6.x (macOS .app/.dmg, Windows .exe) |
| **테스트** | pytest + pytest-qt |

---

## 프로젝트 구조

```
school_timetable/
├── main.py                       # 앱 진입점
├── config.py                     # DB 설정 읽기/쓰기 (db_config.json)
├── requirements.txt              # Python 의존성
├── build_installer.py            # 설치 프로그램 빌드 스크립트
├── README.md
│
├── database/
│   ├── models.py                 # SQLAlchemy ORM 모델 (11개)
│   └── connection.py             # DB 엔진 / 세션 팩토리
│
├── core/
│   ├── generator.py              # 시간표 자동 생성 알고리즘
│   └── change_logger.py          # 변경 이력 기록 헬퍼
│
├── ui/
│   ├── main_window.py            # 메인 윈도우 + 사이드바 + GenerateWorker
│   ├── feedback.py               # 피드백 다이얼로그
│   ├── setup/                    # 설정 페이지들
│   │   ├── class_setup.py        # 학년/반 편제
│   │   ├── teacher_setup.py      # 교사 관리 + 불가 시간
│   │   ├── subject_setup.py      # 교과목/시수 배정
│   │   └── room_setup.py         # 교실 관리
│   ├── timetable/                # 시간표 조회/편집
│   │   ├── class_view.py         # 반별 시간표 (Mode A/B)
│   │   ├── teacher_view.py       # 교사별 시간표
│   │   ├── neis_grid.py          # 공통 그리드 위젯 (TimetableGridA/B)
│   │   ├── edit_dialog.py        # 시간표 셀 수정 다이얼로그
│   │   └── request_list.py       # 변경 신청 목록/승인
│   ├── calendar/
│   │   └── calendar_widget.py    # 학사일정 관리
│   ├── history/
│   │   └── history_view.py       # 변경 이력 조회
│   └── export/
│       ├── pdf_export.py         # PDF 출력
│       └── neis_export.py        # NEIS Excel 출력
│
├── installer/
│   ├── generate_icon.py          # 앱 아이콘 생성기
│   ├── icon.png / icon.icns / icon.ico
│
└── tests/
    ├── conftest.py
    └── test_feedback.py
```

---

## ERD (데이터베이스 관계도)

```
Grade (1) ──< (N) SchoolClass (1) ──< (N) SubjectClassAssignment (N) >── (1) Subject
                      │                            │
                      │ (homeroom)                 │ (teacher)
                      ▼                            ▼
                     Room                       Teacher (1) ──< (N) TeacherConstraint
                      ▲                            ▲
                      │ (room)                     │ (teacher)
                      │                            │
                      └── (N) TimetableEntry ──────┘
                                 │
                                 │ (term)       (cascade)
                                 ▼
                            AcademicTerm ──< (N) SchoolEvent

TimetableEntry ──< (N) TimetableChangeRequest  (변경 신청/결재)
TimetableEntry ──< (N) TimetableChangeLog       (변경 이력)
```

**11개 모델**: `AcademicTerm`, `Grade`, `SchoolClass`, `Subject`, `Teacher`, `SubjectClassAssignment`, `Room`, `TeacherConstraint`, `TimetableEntry`, `SchoolEvent`, `TimetableChangeLog`, `TimetableChangeRequest`

---

## 설치 및 실행 방법

### 1. 사전 요구사항
- Python 3.10 이상
- macOS / Windows / Linux

### 2. 소스코드 실행

```bash
# 가상환경 생성
python3 -m venv .venv
source .venv/bin/activate  # macOS/Linux
# .venv\Scripts\activate   # Windows

# 의존성 설치
pip install -r requirements.txt

# 앱 실행
python3 main.py
```

### 3. 설치 프로그램 빌드

```bash
# macOS
python3 build_installer.py          # .app 번들 생성
python3 build_installer.py --dmg    # .dmg 설치 이미지 생성

# Windows
python3 build_installer.py --win    # .exe + ZIP 패키지 생성
```

결과물은 `dist/` (실행 파일) 및 `installer_output/` (설치 이미지) 디렉터리에 생성됩니다.

### 4. 테스트 실행

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ -v
```

---

## 사용 순서

1. **편제 설정** → 학년/반 등록
2. **교사 관리** → 교사 추가 + 불가 시간 설정 (체크박스 그리드)
3. **교과목/시수** → 과목 추가 + 반별 주당 시수 및 교사 배정
4. **교실 관리** → 교실·특별실 등록
5. **학기 추가** → 좌측 사이드바 "+ 학기 추가"
6. **자동 생성** → 좌측 사이드바 "▶ 자동 생성" (학기 선택 후 실행)
7. **시간표 조회** → 반별·교사별 탭에서 확인
8. **시간표 수정** → 셀 더블클릭 → 직접 수정 또는 변경 신청
9. **변경 승인** → 변경 신청/결재 페이지에서 승인/거절 처리
10. **내보내기** → PDF 출력 또는 NEIS Excel 내보내기

---

## 시간표 생성 알고리즘 상세

### Greedy + Random Restart

1. **수업 인스턴스 확장**: 각 `SubjectClassAssignment`(주당 시수) → 개별 수업 단위로 분해
2. **무작위 셔플**: 수업 목록과 슬롯(요일×교시)을 매 시도마다 무작위 배열
3. **Greedy 배치**: 각 수업을 순회하며 제약조건을 통과하는 첫 번째 슬롯에 배치
4. **Fail-Fast**: 하나라도 배치 불가능한 수업이 발생하면 해당 시도 폐기 → 재시도
5. **최대 30회** 시도 후 실패 시 사용자에게 안내

### 제약조건 우선순위

| 우선순위 | 유형 | 조건 |
|----------|------|------|
| Hard | 학반 중복 방지 | 동일 학반이 같은 시간에 2개 이상 수업 불가 |
| Hard | 교사 중복 방지 | 동일 교사가 같은 시간에 2개 이상 수업 불가 |
| Hard | 교실 중복 방지 | 동일 교실에 같은 시간 2개 이상 수업 불가 |
| Hard | 교사 불가 시간 | 교사가 불가로 지정한 슬롯에는 배치 불가 |
| Soft | 교사 일 최대 수업 | 교사별 일 최대 수업 수 초과 시 다른 요일 우선 |

---

## 장점

- **완전한 워크플로우** — 편제 입력부터 생성, 수정, 결재, 출력까지 하나의 앱에서 처리
- **빠른 생성** — Greedy + Random Restart로 대부분의 케이스에서 1~3회 만에 생성 완료
- **UI 논블로킹** — QThread 기반 백그라운드 생성으로 앱이 멈추지 않음
- **NEIS 연계** — 나이스 템플릿에 바로 복사 가능한 Excel 출력
- **변경 이력 감사** — 모든 생성·수정·삭제가 JSON 상세 내역과 함께 자동 기록
- **결재 워크플로우** — 변경 신청 → 승인/거절로 책임 소재 분리
- **다중 DB 지원** — SQLite(단독 사용)부터 PostgreSQL(전교 공유)까지 유연한 구성
- **크로스 플랫폼** — macOS, Windows 모두 네이티브 설치 프로그램 지원
- **직관적인 UI** — 사이드바 네비게이션 + NEIS 스타일 시간표 그리드

## 단점 및 한계

- **단일 사용자 가정** — 동시 편집 충돌 해결 기능 없음 (DB 레벨 트랜잭션만 의존)
- **사용자 인증 없음** — 변경 신청자/승인자 구분이 이름 문자열 기반 (계정 시스템 없음)
- **수동 NEIS 업로드** — NEIS 템플릿에 직접 업로드하는 기능이 아닌 복사·붙여넣기 방식
- **DB 마이그레이션 없음** — `create_all()`만 사용하므로 기존 DB 스키마 자동 변경 안 됨
- **한글 폰트 의존성** — PDF 출력 시 시스템에 한글 폰트가 없으면 한글 깨짐 발생 가능
- **교사 선호/회피 미구현** — 생성기에서 `preferred`/`avoid` 제약조건 타입을 학습에 반영하지 않음
- **대규모 시간표 한계** — Random Restart 방식이므로 학급·교사 수가 매우 많을 경우 생성 실패 확률 증가

---

## 향후 개선 계획

아래 기능들은 README.txt의 "다음 단계 예정 기능" 목록에서 **이미 구현 완료**되었습니다:

- ✅ 당일 시간표 수정 + 변경 신청/결재
- ✅ 학사일정 관리
- ✅ PDF 출력
- ✅ 변경 이력 관리
- ✅ NEIS 내보내기

추가로 고려할 수 있는 개선 사항:

- 사용자 인증 (교사/관리자 역할 구분)
- NEIS API 직접 연동 (SIS/XML 형식)
- 마이그레이션 시스템 도입 (Alembic)
- 생성 알고리즘에 선호/회피 제약조건 반영
- 웹 버전 (Flask/FastAPI + React)
- 모바일 알림 (시간표 변경 시 카카오톡/이메일 알림)

---

## 라이선스

이 프로젝트는 MIT 라이선스를 따릅니다. 자유롭게 사용·수정·배포하실 수 있습니다.

---

## 문의 및 기여

버그 신고, 기능 제안, 기여는 GitHub Issues를 통해 부탁드립니다.

**GitHub**: [https://github.com/iSeonHwan/school-timetable](https://github.com/iSeonHwan/school-timetable)
