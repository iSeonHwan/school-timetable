# 학교 시간표 관리 시스템

PyQt6 + SQLAlchemy 기반의 **학교 시간표 자동 생성 및 관리 데스크톱 애플리케이션**입니다. 학년·반 편제 입력부터 시간표 자동 생성, 셀 단위 수정, 변경 신청 및 결재, 학사일정 관리, PDF·NEIS 출력까지 학교 시간표 운영에 필요한 전체 워크플로우를 단일 앱에서 제공합니다.

---

## 목차

1. [프로그램 개요](#1-프로그램-개요)
2. [주요 기능 상세](#2-주요-기능-상세)
   - 2.1 [기초 데이터 설정](#21-기초-데이터-설정)
   - 2.2 [시간표 자동 생성](#22-시간표-자동-생성)
   - 2.3 [시간표 조회](#23-시간표-조회)
   - 2.4 [시간표 수정 및 변경 관리](#24-시간표-수정-및-변경-관리)
   - 2.5 [학사일정 관리](#25-학사일정-관리)
   - 2.6 [변경 이력 추적](#26-변경-이력-추적)
   - 2.7 [내보내기 (PDF / NEIS)](#27-내보내기-pdf--neis)
   - 2.8 [프로젝트 저장 및 불러오기](#28-프로젝트-저장-및-불러오기)
3. [데이터 연결성 설계](#3-데이터-연결성-설계)
4. [설치 및 실행 방법](#4-설치-및-실행-방법)
5. [상세 사용 설명](#5-상세-사용-설명)
6. [프로젝트 구조](#6-프로젝트-구조)
7. [데이터베이스 구조 (ERD)](#7-데이터베이스-구조-erd)
8. [시간표 자동 생성 알고리즘](#8-시간표-자동-생성-알고리즘)
9. [테스트 실행](#9-테스트-실행)
10. [설치 프로그램 빌드](#10-설치-프로그램-빌드)
11. [기술 스택](#11-기술-스택)
12. [장점과 한계](#12-장점과-한계)

---

## 1. 프로그램 개요

학교 시간표 관리는 수십 명의 교사, 수백 개의 수업 시수, 그리고 교실 배정이라는 복잡한 제약조건을 동시에 만족시켜야 하는 어려운 문제입니다. 기존에는 Excel 스프레드시트나 종이 대장을 활용하는 경우가 많았으나, 이는 변경 이력 관리가 어렵고, 교사 간 중복 배정 오류가 발생하기 쉬우며, NEIS(나이스 국가교육정보시스템) 입력 작업을 별도로 반복해야 하는 불편함이 있었습니다.

이 프로그램은 위와 같은 문제를 해결하기 위해 설계되었습니다. 핵심 설계 원칙은 세 가지입니다. 첫째, **데이터 일관성**입니다. 모든 수업 배정은 SQLAlchemy ORM을 통해 관계형 데이터베이스에 저장되므로, 교사 중복·교실 중복 같은 기본적인 충돌은 자동 생성 단계에서 알고리즘이 원천 차단합니다. 둘째, **워크플로우 완결성**입니다. 시간표 생성 이후의 수정 과정에서도 '직접 수정'과 '변경 신청→결재' 두 가지 경로를 지원하여, 단순 오류 정정은 즉시 반영하고 실질적인 시간표 변경은 결재 흔적을 남기도록 합니다. 셋째, **감사 추적성**입니다. 모든 생성·수정·삭제 이벤트는 TimetableChangeLog 테이블에 변경 전후 상태를 JSON으로 기록하므로, 언제 누가 무엇을 바꿨는지를 언제든지 조회할 수 있습니다.

운영 환경에 따라 SQLite(개인 PC 단독 사용)와 PostgreSQL(교무실 서버 공유) 두 가지 데이터베이스를 지원합니다. 앱 내 설정 화면에서 전환할 수 있으며, 설정은 프로젝트 루트의 `db_config.json`에 저장됩니다.

---

## 2. 주요 기능 상세

### 2.1 기초 데이터 설정

시간표를 생성하기 전에 반드시 설정해야 하는 네 가지 기초 데이터가 있습니다.

**학년/반 편제**는 학교의 기본 단위인 학년과 학급을 등록하는 화면입니다. 학년 번호(1·2·3 등)를 먼저 등록하고, 그 아래 학급 번호(1반·2반 등)를 추가합니다. 학급을 삭제할 때는 해당 학급에 배정된 모든 시간표 항목과 수업 시수 배정 정보가 연쇄적으로 삭제(cascade)되므로 주의가 필요합니다.

**교사 관리**는 시간표 생성에서 핵심이 되는 교사 데이터를 관리합니다. 교사 등록 시 이름과 일 최대 수업 수(기본 5교시)를 입력하며, 담임 학급을 배정할 수 있습니다. 특히 주목할 기능은 **불가 시간 설정**입니다. 교사별 편집 화면에는 요일(월~금) × 교시(1~7)로 구성된 35칸의 체크박스 그리드가 표시되며, 체크된 슬롯은 자동 생성 시 해당 교사에게 수업을 배정하지 않습니다. 예를 들어, 매주 수요일 6교시에 교직원 회의가 있다면 해당 칸을 체크함으로써 회의 시간에 수업이 잡히는 상황을 사전에 방지할 수 있습니다.

**교과목/시수 배정**은 개별 과목을 정의하고, 각 학반마다 해당 과목의 주당 시수와 담당 교사를 지정하는 화면입니다. 과목에는 색상을 지정할 수 있어서, 시간표 그리드에서 과목을 시각적으로 구분하기가 쉽습니다. 시수 배정 테이블은 가로축이 과목, 세로축이 학반으로 구성되며, 각 셀에 주당 시수(숫자)와 담당 교사를 입력합니다.

**교실 관리**에서는 일반 교실뿐 아니라 과학실·음악실·체육관·도서관 등의 특별실을 등록할 수 있습니다. 수업 배정 시 특정 교실을 지정하면, 자동 생성 과정에서 해당 교실의 중복 사용을 방지합니다.

### 2.2 시간표 자동 생성

사이드바의 "▶ 자동 생성" 버튼을 누르면 학기를 선택하고 생성을 시작할 수 있습니다. 생성은 **Greedy + Random Restart** 알고리즘으로 이루어지며, 백그라운드 스레드(QThread)에서 실행되기 때문에 생성 중에도 UI가 멈추지 않습니다. 생성이 시작되면 다이얼로그에 진행 상황이 표시되고, 완료 또는 실패 시 결과 메시지가 나타납니다. 생성이 완료되면 기존 시간표 데이터는 삭제되고 새로운 배정으로 교체됩니다.

알고리즘의 자세한 동작 방식은 [8장 시간표 자동 생성 알고리즘](#8-시간표-자동-생성-알고리즘)에서 설명합니다.

### 2.3 시간표 조회

생성된 시간표는 두 가지 뷰에서 확인할 수 있습니다.

**반별 시간표** 뷰에서는 상단 콤보박스로 학반을 선택하고 두 가지 표시 모드를 탭으로 전환할 수 있습니다. **Mode A(주간 보기)**는 가로축이 요일(월~금), 세로축이 교시(1~7)인 전통적인 시간표 형태입니다. **Mode B(1일 전체 보기)**는 가로축이 학반 전체, 세로축이 교시인 형태로, 특정 요일에 각 학반이 어떤 수업을 듣는지 한눈에 비교할 수 있습니다. 시간표 셀을 더블클릭하면 해당 슬롯을 편집하는 다이얼로그가 열립니다.

**교사별 시간표** 뷰에서는 교사를 선택하면 해당 교사가 어느 학반에 언제 수업을 하는지를 요일×교시 그리드로 보여줍니다. 이때 각 셀에는 교사 이름 대신 담당 학반 이름이 표시되어, 교사 입장에서 자신의 수업 분포를 한눈에 파악할 수 있습니다.

### 2.4 시간표 수정 및 변경 관리

시간표 셀을 더블클릭하면 수정 다이얼로그가 열립니다. 이 다이얼로그에서는 **과목, 교사, 교실**을 콤보박스로 변경할 수 있으며, 수정 방식으로 두 가지 중 하나를 선택합니다.

**직접 수정**을 선택하면 변경 내용이 즉시 시간표에 반영되고, 변경 이력(TimetableChangeLog)에도 자동으로 기록됩니다. 오탈자 수정이나 담당 교사 조정 같은 단순한 정정 작업에 적합합니다.

**변경 신청**을 선택하면 변경 사유를 입력한 후 신청 레코드(TimetableChangeRequest)가 생성됩니다. 변경 신청은 즉시 시간표에 반영되지 않으며, 사이드바의 "변경 신청/결재" 페이지에서 관리자가 내용을 검토하고 **승인** 또는 **거절**을 처리합니다. 승인 시에는 해당 변경 내용이 실제 시간표에 적용되고, 거절 시에는 신청 레코드만 거절 상태로 표시됩니다.

이처럼 두 가지 경로를 두는 이유는 운영 현장의 현실을 반영하기 위해서입니다. 부장교사나 교무주임은 직접 수정 권한을 가지고, 일반 교사는 변경 신청 후 결재를 받는 방식으로 역할을 분리할 수 있습니다.

### 2.5 학사일정 관리

학사일정 페이지는 월별 캘린더와 일정 목록을 나란히 표시합니다. 캘린더에서 날짜를 클릭하면 해당 날짜의 일정이 우측 목록에 표시됩니다. "추가" 버튼을 눌러 새 일정을 등록할 수 있으며, 다음 일곱 가지 유형 중 하나를 선택합니다.

| 유형 | 대표 사례 |
|------|-----------|
| 개교기념일 | 학교 창립 기념일 |
| 시험 | 중간·기말고사, 모의고사 |
| 축제 | 체육대회, 학교 축제 |
| 방학 | 여름방학, 겨울방학, 봄방학 |
| 공휴일 | 국경일, 법정 공휴일 |
| 행사 | 입학식, 졸업식, 현장학습 |
| 기타 | 위에 해당하지 않는 학교 행사 |

각 유형마다 다른 색상으로 캘린더에 마커가 표시되므로, 학사 일정의 분포를 시각적으로 파악할 수 있습니다. 등록된 일정을 선택하면 목록 아래에 상세 내용(이름, 날짜, 유형, 설명)이 표시되며, 수정 및 삭제가 가능합니다.

### 2.6 변경 이력 추적

변경 이력 페이지는 시간표에 일어난 모든 변화를 감사 로그 형태로 조회하는 화면입니다. 상단 필터 바에서 **날짜 범위**, **학반**, **변경 유형**(생성/수정/삭제)을 조합하여 검색할 수 있으며, 최신순으로 최대 200건이 표시됩니다.

각 이력 항목은 다음 정보를 포함합니다.

- **일시**: 변경이 일어난 정확한 시각 (연-월-일 시:분)
- **학반**: 해당 수업이 배정된 학반 이름
- **변경 유형**: 생성(초록), 수정(주황), 삭제(빨강)으로 색상 구분
- **요일/교시**: 해당 수업 슬롯 (예: "화 3교시")
- **상세 내용**: 수정의 경우 변경 전→후 과목ID·교사ID·교실ID 비교 표시

목록에서 행을 클릭하면 하단 상세 영역에 더 자세한 내용이 펼쳐집니다. 이 기능을 통해 "지난주에 누가 3학년 2반 목요일 4교시를 바꿨는가?"와 같은 질문에 답할 수 있습니다.

### 2.7 내보내기 (PDF / NEIS)

**PDF 출력**은 ReportLab 라이브러리를 사용하여 A4 가로 방향으로 시간표 PDF를 생성합니다. 학기와 출력 범위(전체 학반 / 전체 교사 / 모두)를 선택하면, 학반별 또는 교사별로 한 페이지씩 구성된 PDF가 저장됩니다. 한국어 폰트는 운영체제별로 자동 탐색합니다. macOS에서는 Apple SD Gothic Neo를, Windows에서는 맑은 고딕(malgun.ttf)을, Linux에서는 나눔고딕 또는 Noto Sans CJK를 자동으로 감지하여 사용합니다. 시스템에 한글 폰트가 전혀 없는 경우 Helvetica로 대체됩니다.

**NEIS 내보내기**는 openpyxl 라이브러리를 사용하여 Excel(.xlsx) 파일을 생성합니다. 이 기능은 NEIS에 직접 API 업로드를 하는 것이 아니라, NEIS 시간표 입력 템플릿에 복사·붙여넣기할 수 있도록 정리된 형식의 Excel을 제공합니다. 반별 또는 교사별 시트가 각각 생성되며, 각 시트는 타이틀 행, 헤더(요일) 행, 교시별 데이터 행으로 구성됩니다. 셀에는 나이스 시스템과 유사한 파란색 헤더 서식이 적용됩니다.

### 2.8 프로젝트 저장 및 불러오기

**프로젝트 저장(Export)** 기능은 현재 데이터베이스에 저장된 모든 데이터를 하나의 JSON 파일(`.json`)로 직렬화하여 내보냅니다. 파일은 사람이 읽고 편집할 수 있는 UTF-8 텍스트 형식이며, 운영체제에 상관없이 공유할 수 있습니다.

**프로젝트 불러오기(Import)** 기능은 이전에 저장한 JSON 파일을 읽어 데이터베이스를 완전히 대체합니다. 불러오기 과정에서 자동으로 처리되는 핵심 사항은 다음과 같습니다.

**ID 재매핑**. JSON 파일에는 각 레코드의 원본 ID가 포함되어 있지만, 가져오기 시 데이터베이스는 새로운 auto-increment 기본키를 할당합니다. `import_project()` 함수는 12개 테이블을 의존성 순서(Tier 0→4)대로 처리하면서 `old_id → new_id` 매핑을 유지하고, 모든 외래키 컬럼을 자동으로 변환합니다. 예를 들어, 원본 파일에서 `Teacher.homeroom_class_id=5`였던 값을 가져오기 후에는 새롭게 할당된 `homeroom_class_id`로 올바르게 연결합니다.

**트랜잭션 안전성**. 불러오기는 다음 세 단계로 진행됩니다.
1. 파일 검증 — JSON 구조, `metadata`·`data` 키 존재 여부, 파일 버전 호환성 확인
2. 기존 데이터 전량 삭제 — FK 제약 위반을 피하기 위해 역방향 의존성 순서(Tier 4→0)로 DELETE 실행
3. 새 데이터 삽입 — 정방향 순서(Tier 0→4)로 INSERT, ID 재매핑 적용

이 세 단계는 모두 하나의 데이터베이스 트랜잭션으로 묶여 있습니다. 3단계에서라도 오류(예: 손상된 FK 참조, JSON 파싱 오류)가 발생하면 전체 작업이 롤백되고 **기존 데이터는 그대로 보존**됩니다. 불러오기 전에는 반드시 경고 다이얼로그("기존 모든 데이터가 삭제됩니다")로 사용자 확인을 거칩니다.

**파일 구조**. 저장되는 JSON 파일은 다음과 같은 구조를 가집니다.

```json
{
  "metadata": {
    "app_name": "학교 시간표 관리 시스템",
    "file_version": "1.0",
    "exported_at": "2026-05-10T15:30:00"
  },
  "data": {
    "academic_terms": [
      {"id": 1, "year": 2025, "semester": 1, "start_date": "2025-03-02", ...}
    ],
    "grades": [{"id": 1, "grade_number": 1, "name": "1학년"}],
    "rooms": [...], "subjects": [...], "school_classes": [...],
    "teachers": [...], "subject_class_assignments": [...],
    "teacher_constraints": [...], "timetable_entries": [...],
    "school_events": [...], "timetable_change_logs": [...],
    "timetable_change_requests": [...]
  }
}
```

날짜 컬럼은 ISO 8601 문자열(`"2025-03-02"`)로, datetime 컬럼은 `"2026-05-10T15:30:00"` 형식으로, Boolean은 JSON `true`/`false`로, NULL은 `null`로 직렬화됩니다. 한글·특수문자 등 Unicode 텍스트도 `ensure_ascii=False`로 온전히 보존됩니다.

**활용 사례**.
- **백업**: 학기 말마다 프로젝트 파일을 저장해 두면, PC 고장이나 DB 손상 시에도 복원 가능
- **학년도 전환**: 작년 시간표를 파일로 저장한 뒤, 새 DB에서 불러와 올해 시간표의 기초 템플릿으로 활용
- **공동 작업**: 한 교사가 기초 데이터 입력 후 파일로 저장 → 다른 교사에게 전달 → 불러와서 시간표 생성 계속 진행
- **여러 학교 관리**: 학교마다 별도 프로젝트 파일을 관리하며 필요할 때마다 전환

---

## 3. 데이터 연결성 설계

이 프로그램의 가장 중요한 아키텍처 설계 중 하나는 **페이지 간 데이터 연결성**입니다. 기초 데이터 입력 페이지(0~3번)에서 입력한 내용이 후속 페이지의 콤보박스와 테이블에 실시간으로 반영되도록 설계되어 있습니다.

### 3.1 데이터 흐름

```
편제 설정(0): 학년·반 등록
    ↓ (페이지 전환 시 refresh)
교사 관리(1): 담임 학반 콤보박스에 등록된 반 목록 표시
    ↓
교과목/시수(2): 학반·교과·교사 콤보박스에 등록된 모든 목록 표시
    ↓
교실 관리(3): 독립적 (등록된 교실은 시간표 생성·편집 시 사용)
    ↓ (시수 배정 완료 후)
자동 생성 → 반별 시간표(4)·교사별 시간표(5) 조회
```

### 3.2 Refresh 메커니즘

모든 페이지 전환은 `MainWindow._switch_page(idx)` 메서드를 통해 이루어집니다. 이 메서드는 단순히 `QStackedWidget.setCurrentIndex()`만 호출하는 것이 아니라, **전환 대상 페이지의 `refresh()` 메서드를 반드시 호출**합니다.

```python
# main_window.py — _switch_page() 내부
refresh_map = {
    0: self.page_class.refresh,       # 편제 설정
    1: self.page_teacher.refresh,     # 교사 관리
    2: self.page_subject.refresh,     # 교과목/시수
    3: self.page_room.refresh,        # 교실 관리
    4: self.page_class_view.refresh,  # 반별 시간표
    5: self.page_teacher_view.refresh,# 교사별 시간표
    6: self.page_request_list.refresh,# 변경 신청/결재
    7: self.page_calendar.refresh,    # 학사일정
    8: self.page_history.refresh,     # 변경 이력
}
```

각 페이지의 `refresh()`는 내부적으로 `_load_data()` 또는 `_populate_combos()`를 호출하여 데이터베이스에서 최신 데이터를 다시 읽어옵니다. 따라서 다음과 같은 시나리오가 자연스럽게 동작합니다.

- 편제 설정(0)에서 "1-1" 학반 추가 → 교사 관리(1)로 이동 → 담임 학반 콤보박스에 "1-1"이 나타남
- 교사 관리(1)에서 "홍길동" 교사 추가 → 교과목/시수(2)로 이동 → 담당 교사 콤보박스에 "홍길동"이 나타남
- 교과목/시수(2)에서 시수 배정 완료 → 시간표 생성 후 → 반별 시간표(4)에서 즉시 확인 가능

### 3.3 데이터 입력 권장 순서

FK 제약조건과 데이터 의존성을 고려한 권장 입력 순서입니다.

| 순서 | 작업 | 선행 필요 데이터 |
|------|------|------------------|
| 1 | 학기 추가 (TermDialog) | 없음 |
| 2 | 학년 등록 (ClassSetupWidget) | 없음 |
| 3 | 반 등록 (ClassSetupWidget) | 학년 |
| 4 | 교실 등록 (RoomSetupWidget) | 없음 |
| 5 | 교과목 등록 (SubjectSetupWidget) | 없음 |
| 6 | 교사 등록 (TeacherSetupWidget) | 반 (담임 지정 시) |
| 7 | 교사 불가 시간 설정 (TeacherSetupWidget) | 교사 |
| 8 | 시수 배정 (SubjectSetupWidget) | 반, 교과목, 교사 |
| 9 | 시간표 자동 생성 | 시수 배정 |
| 10 | 시간표 조회·수정·변경 신청 | 생성된 시간표 |

이 순서를 지키면 "학반이 없어서 콤보박스가 비어 있음"과 같은 불편을 겪지 않습니다. 단, 2~6단계는 순서가 바뀌더라도 페이지 간 refresh 덕분에 후속 페이지에서 최신 데이터를 확인할 수 있습니다.

---

## 4. 설치 및 실행 방법

### 사전 요구사항

- Python 3.10 이상 (3.12 권장)
- macOS / Windows / Linux 모두 지원

### 소스코드로 직접 실행하는 방법

먼저 프로젝트 루트 디렉터리에 Python 가상환경을 만들고 의존성을 설치합니다.

```bash
# 가상환경 생성
python3 -m venv .venv

# 가상환경 활성화
source .venv/bin/activate        # macOS / Linux
# .venv\Scripts\activate.bat     # Windows (명령 프롬프트)
# .venv\Scripts\Activate.ps1     # Windows (PowerShell)

# 의존성 설치
pip install -r requirements.txt

# 앱 실행
python3 main.py
```

앱을 처음 실행하면 프로젝트 루트에 `timetable.db`(SQLite 파일)가 자동으로 생성되고, 필요한 테이블이 모두 만들어집니다. 별도의 초기 설정 없이 바로 기초 데이터 입력부터 시작할 수 있습니다.

### PostgreSQL로 전환하는 방법

교무실 내 여러 PC가 동일한 시간표 데이터를 공유해야 하는 경우, PostgreSQL 서버를 구성한 후 앱 내에서 연결 정보를 입력할 수 있습니다. 메인 윈도우 사이드바 하단의 "DB 설정" 버튼을 클릭하면 연결 설정 다이얼로그가 열립니다. 호스트, 포트(기본 5432), 데이터베이스명, 사용자명, 비밀번호를 입력하고 저장하면 `db_config.json`에 기록됩니다. 이후 앱을 재시작하면 PostgreSQL에 연결됩니다.

---

## 5. 상세 사용 설명

이 장에서는 처음 사용하는 분이 시간표를 완성하기까지의 전체 과정을 순서대로 설명합니다.

### 5.1 학년/반 편제 등록

앱을 처음 실행한 후 사이드바에서 **"학년/반 편제"**를 선택합니다. 화면 상단에 학년 목록이, 하단에 선택된 학년에 속한 학급 목록이 표시됩니다. "학년 추가" 버튼을 클릭하여 학년 번호를 입력하고 학년을 등록합니다. 그런 다음 등록된 학년을 클릭하여 선택하고, "학급 추가" 버튼으로 해당 학년 아래 학급을 추가합니다. 예를 들어, 3개 학년 각 5학급의 학교라면 학년 3개를 먼저 등록한 후 각 학년에 학급 5개씩 추가합니다.

### 5.2 교사 등록 및 불가 시간 설정

사이드바에서 **"교사 관리"**를 선택합니다. "교사 추가" 버튼으로 교사 이름과 일 최대 수업 수를 입력합니다. 일 최대 수업 수는 자동 생성 시 소프트 제약조건으로 사용됩니다. 기본값은 5교시입니다.

교사를 등록한 후, 목록에서 교사를 선택하고 "불가 시간 편집" 버튼을 클릭하면 5×7 체크박스 그리드가 나타납니다. 해당 교사가 수업을 받을 수 없는 슬롯(예: 수요일 7교시, 금요일 6~7교시 등)에 체크합니다. 체크된 슬롯은 시간표 자동 생성 시 하드 제약조건으로 처리되어 해당 교사에게 수업이 배정되지 않습니다.

### 5.3 교과목 및 주당 시수 배정

사이드바에서 **"교과목/시수 배정"**을 선택합니다. "과목 추가" 버튼으로 과목 이름과 약어, 색상을 입력합니다. 색상은 시간표 그리드에서 과목을 구분하는 데 사용됩니다. 과목이 여럿 등록되면 자동으로 서로 다른 색상이 순환 배정됩니다.

하단 시수 배정 테이블에서 각 학반(행)과 과목(열)이 교차하는 셀에 주당 시수 숫자를 입력하고, 담당 교사를 드롭다운으로 선택합니다. 이 정보가 자동 생성 알고리즘의 기본 입력 데이터가 됩니다.

### 5.4 교실 등록

사이드바에서 **"교실 관리"**를 선택합니다. "교실 추가" 버튼으로 교실 이름(예: "과학실 1", "음악실", "체육관")과 유형을 입력합니다. 교실 유형으로는 일반교실, 과학실, 음악실, 미술실, 컴퓨터실, 체육관, 도서관, 기타 중에서 선택합니다.

### 5.5 학기 등록 및 시간표 자동 생성

사이드바 하단의 **"+ 학기 추가"** 버튼을 클릭하여 연도와 학기(1학기/2학기)를 입력합니다. 학기가 등록되면 사이드바에 표시됩니다.

이제 **"▶ 자동 생성"** 버튼을 클릭합니다. 다이얼로그에서 대상 학기를 선택하고 "생성" 버튼을 누르면 알고리즘이 백그라운드에서 실행됩니다. 몇 초에서 수십 초 안에 결과가 표시됩니다. 성공하면 기존 시간표가 교체되고, 실패하면 재시도를 제안하는 메시지가 나타납니다. 실패 시 교사 불가 시간을 줄이거나 일 최대 수업 수를 늘린 후 다시 시도하는 것이 좋습니다.

### 5.6 시간표 조회 및 수정

사이드바에서 **"반별 시간표"** 또는 **"교사별 시간표"**를 선택하여 생성된 결과를 확인합니다. 원하는 학반이나 교사를 상단 콤보박스에서 선택하면 해당 시간표가 그리드로 표시됩니다.

수정이 필요한 셀을 **더블클릭**하면 편집 다이얼로그가 열립니다. 과목, 교사, 교실을 변경한 후 수정 방식을 선택합니다. 간단한 오류 수정은 "직접 수정"으로 즉시 반영하고, 실질적인 시간표 변경은 변경 사유를 입력하여 "변경 신청"으로 제출합니다.

### 5.7 변경 신청 결재

사이드바에서 **"변경 신청/결재"**를 선택하면 대기 중인 변경 신청 목록이 표시됩니다. 목록에서 신청 항목을 클릭하면 하단에 신청 내용(대상 슬롯, 변경 내용, 사유)이 표시됩니다. "승인" 또는 "거절" 버튼을 클릭하여 처리합니다. 승인된 항목은 즉시 시간표에 반영됩니다.

---

## 6. 프로젝트 구조

```
school_timetable/
├── main.py                       # 앱 진입점: Qt 초기화 → DB 초기화 → 메인 윈도우
├── config.py                     # db_config.json 읽기/쓰기, SQLAlchemy URL 생성
├── requirements.txt              # Python 의존성 목록
├── build_installer.py            # PyInstaller 기반 설치 프로그램 빌드 스크립트
├── db_config.json                # DB 연결 설정 (자동 생성, git 제외 권장)
├── timetable.db                  # SQLite DB 파일 (자동 생성, SQLite 모드 시)
├── feedback.json                 # 사용자 피드백 저장 파일 (자동 생성)
│
├── database/
│   ├── models.py                 # SQLAlchemy ORM 모델 12개
│   └── connection.py             # 모듈 레벨 싱글턴 엔진 및 세션 팩토리
│
├── core/
│   ├── generator.py              # Greedy + Random Restart 시간표 생성 알고리즘
│   ├── change_logger.py          # TimetableChangeLog 기록 헬퍼 함수
│   └── project_manager.py        # 프로젝트 저장(JSON export) / 불러오기(import + ID 재매핑)
│
├── ui/
│   ├── main_window.py            # QMainWindow: 사이드바 네비게이션 + GenerateWorker
│   ├── feedback.py               # 피드백 수집 다이얼로그 → feedback.json 저장
│   ├── setup/
│   │   ├── class_setup.py        # 학년/반 CRUD 화면
│   │   ├── teacher_setup.py      # 교사 CRUD + 불가 시간 체크박스 그리드
│   │   ├── subject_setup.py      # 교과목 CRUD + 반별 시수/교사 배정 테이블
│   │   └── room_setup.py         # 교실 CRUD (일반교실·특별실)
│   ├── timetable/
│   │   ├── class_view.py         # 반별 시간표 조회 (Mode A: 주간 / Mode B: 1일 전체)
│   │   ├── teacher_view.py       # 교사별 시간표 조회
│   │   ├── neis_grid.py          # TimetableGridA / TimetableGridB 공통 그리드 위젯
│   │   ├── edit_dialog.py        # 시간표 셀 수정 다이얼로그 (직접 수정 / 변경 신청)
│   │   └── request_list.py       # 변경 신청 목록 조회 및 승인/거절 처리
│   ├── calendar/
│   │   └── calendar_widget.py    # 학사일정 관리 (월별 캘린더 + 일정 CRUD)
│   ├── history/
│   │   └── history_view.py       # 변경 이력 조회 (필터링, 상세 보기)
│   └── export/
│       ├── pdf_export.py         # ReportLab 기반 PDF 출력
│       └── neis_export.py        # openpyxl 기반 NEIS Excel 출력
│
├── installer/
│   ├── generate_icon.py          # PIL로 앱 아이콘 생성
│   ├── icon.png                  # 256×256 PNG 아이콘
│   ├── icon.icns                 # macOS 전용 아이콘
│   └── icon.ico                  # Windows 전용 아이콘
│
└── tests/
    ├── conftest.py               # pytest-qt 공용 픽스처
    ├── test_feedback.py          # FeedbackDialog 단위 테스트
    └── test_project_manager.py   # 프로젝트 저장/불러오기 단위 테스트 (16개)
```

---

## 7. 데이터베이스 구조 (ERD)

이 프로그램은 12개의 ORM 모델을 사용합니다. 각 모델의 관계와 역할을 이해하면 데이터가 어떻게 연결되는지 파악하기 쉽습니다.

```
AcademicTerm (학기)
  └──< SchoolEvent (학사일정, cascade)

Grade (학년)
  └──< SchoolClass (학반)
         ├── homeroom_room_id → Room (담임 교실)
         └──< SubjectClassAssignment (주당 시수 배정)
                  ├── subject_id  → Subject (교과목)
                  ├── teacher_id  → Teacher (담당 교사)
                  └── preferred_room_id → Room (선호 교실)

Teacher (교사)
  ├── homeroom_class_id → SchoolClass (담임 학반)
  └──< TeacherConstraint (불가/선호/회피 슬롯, cascade)

TimetableEntry (시간표 배정 1행 = 1수업 슬롯)
  ├── term_id          → AcademicTerm
  ├── school_class_id  → SchoolClass
  ├── subject_id       → Subject
  ├── teacher_id       → Teacher
  └── room_id          → Room (nullable)
       └──< TimetableChangeRequest (변경 신청/결재)
       └──< TimetableChangeLog    (변경 이력, 감사 로그)
```

**모델별 핵심 컬럼 요약**

| 모델 | 핵심 컬럼 |
|------|-----------|
| `AcademicTerm` | year, semester |
| `Grade` | grade_number |
| `SchoolClass` | grade_id, class_number, homeroom_teacher_id |
| `Subject` | name, short_name, color |
| `Teacher` | name, max_daily_classes |
| `SubjectClassAssignment` | school_class_id, subject_id, teacher_id, weekly_hours |
| `TimetableEntry` | term_id, school_class_id, subject_id, teacher_id, room_id, day_of_week, period |
| `TeacherConstraint` | teacher_id, day_of_week, period, constraint_type (unavailable/preferred/avoid) |
| `SchoolEvent` | term_id, name, event_date, event_type, description |
| `TimetableChangeLog` | entry_id, school_class_id, change_type, details(JSON), changed_at |
| `TimetableChangeRequest` | entry_id, requester, reason, status, new_subject_id, new_teacher_id, new_room_id |
| `Room` | name, room_type |

### FK 의존성 계층 (Tier)

테이블 간 외래키 의존성에 따라 데이터를 처리해야 하는 순서입니다. 프로젝트 불러오기(import)와 데이터 삭제 시 이 순서가 사용됩니다.

| Tier | 방향 | 테이블 | 의존 대상 |
|------|------|--------|-----------|
| 0 | 독립 | `academic_terms` | 없음 |
| 0 | 독립 | `grades` | 없음 |
| 0 | 독립 | `rooms` | 없음 |
| 0 | 독립 | `subjects` | 없음 |
| 1 | ↓ | `school_classes` | grades, rooms |
| 2 | ↓ | `teachers` | school_classes |
| 3 | ↓ | `subject_class_assignments` | school_classes, subjects, teachers, rooms |
| 3 | ↓ | `teacher_constraints` | teachers |
| 3 | ↓ | `timetable_entries` | academic_terms, school_classes, subjects, teachers, rooms |
| 3 | ↓ | `school_events` | academic_terms |
| 4 | 최하위 | `timetable_change_logs` | timetable_entries, academic_terms, school_classes |
| 4 | 최하위 | `timetable_change_requests` | timetable_entries, subjects, teachers, rooms |

- **INSERT(Import)**: Tier 0 → 4 순서로 처리 (상위 데이터가 먼저 존재해야 FK 생성 가능)
- **DELETE(초기화)**: Tier 4 → 0 순서로 처리 (하위 데이터를 먼저 삭제해야 FK 위반 방지)
- **Cascade 삭제**: Grade 삭제 → SchoolClass 삭제 → SubjectClassAssignment·TimetableEntry 삭제

---

## 8. 시간표 자동 생성 알고리즘

시간표 자동 생성은 `core/generator.py`의 `generate_timetable(session, term_id)` 함수가 담당합니다. 이 함수는 UI에서 `GenerateWorker`(QThread 서브클래스)를 통해 백그라운드로 실행됩니다.

### 알고리즘 개요: Greedy + Random Restart

이 알고리즘은 NP-hard 수준의 제약 만족 문제를 실용적인 시간 안에 풀기 위해 그리디(탐욕적) 접근과 무작위 재시작을 결합한 방식입니다.

**1단계: 수업 인스턴스 확장**

데이터베이스에서 `SubjectClassAssignment`를 읽어, 주당 시수만큼 개별 수업 인스턴스를 생성합니다. 예를 들어 "3학년 1반 수학, 주 4시간"이라는 배정이 있으면, 4개의 독립적인 수업 인스턴스가 만들어집니다.

**2단계: 무작위 셔플 (매 시도마다)**

수업 인스턴스 목록과 사용 가능한 슬롯(요일 1~5 × 교시 1~7 = 최대 35슬롯)을 무작위로 섞습니다. 이 셔플이 Random Restart의 핵심입니다. 매 시도마다 다른 순서로 시도하기 때문에, 한 순서로 풀리지 않는 문제가 다른 순서에서는 풀릴 수 있습니다.

**3단계: Greedy 배치**

셔플된 수업 인스턴스를 순서대로 꺼내, 셔플된 슬롯 목록을 처음부터 순회하면서 제약조건을 모두 통과하는 첫 번째 슬롯에 배치합니다. 이 과정에서 확인하는 제약조건은 다음과 같습니다.

| 유형 | 조건 | 처리 방식 |
|------|------|-----------|
| Hard | 해당 학반이 이미 그 슬롯에 다른 수업 배정됨 | 슬롯 건너뜀 |
| Hard | 해당 교사가 이미 그 슬롯에 다른 수업 배정됨 | 슬롯 건너뜀 |
| Hard | 지정 교실이 이미 그 슬롯에 다른 수업 배정됨 | 슬롯 건너뜀 |
| Hard | 교사의 불가 시간(TeacherConstraint.unavailable)으로 지정된 슬롯 | 슬롯 건너뜀 |
| Soft | 해당 교사가 해당 요일에 이미 일 최대 수업 수에 도달 | 슬롯 건너뜀 |

**4단계: Fail-Fast와 재시도**

특정 수업 인스턴스를 배치할 수 있는 슬롯이 한 개도 없으면, 현재 시도를 즉시 중단(Fail-Fast)하고 처음부터 다시 셔플 후 재시도합니다. 최대 30회 재시도 후에도 완전한 배치가 불가능하면 실패 메시지를 반환합니다.

**5단계: 커밋**

모든 수업 인스턴스가 배치되면 기존 시간표 데이터를 삭제하고 새 배정을 데이터베이스에 저장합니다.

### 알고리즘의 특성과 한계

이 알고리즘은 대부분의 일반적인 학교 규모(학급 15개 이하, 교사 40명 이하)에서 1~3회 시도 만에 성공합니다. 다만 교사 불가 시간이 많거나 교사 수 대비 학급 수가 매우 많은 특수한 환경에서는 30회 내에 해를 찾지 못할 수 있습니다. 이 경우 교사 불가 시간을 줄이거나, 주당 시수를 조정하거나, 일 최대 수업 수를 늘려서 재시도하는 것을 권장합니다.

현재 `TeacherConstraint`의 `preferred`(선호)와 `avoid`(회피) 유형은 데이터 모델에는 정의되어 있으나, 생성 알고리즘에서 아직 반영되지 않습니다. 향후 개선 대상입니다.

---

## 9. 테스트 실행

테스트는 `pytest`와 `pytest-qt`를 사용합니다. GUI 테스트이므로 디스플레이가 필요하며, 디스플레이가 없는 CI 환경에서는 `QT_QPA_PLATFORM=offscreen` 환경변수를 설정합니다.

```bash
# 일반 환경 (디스플레이 있음)
.venv/bin/python -m pytest tests/ -v

# headless 환경 (CI/CD 등 디스플레이 없음)
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ -v
```

### 테스트 파일 구성 (총 24개 테스트)

**`tests/test_feedback.py`** — 피드백 다이얼로그 테스트 (8개)
- 다이얼로그 제목, 카테고리 옵션, 빈 메시지 경고, 저장 동작, 파일 누적, 손상된 파일 처리, 공백 메시지 경고

**`tests/test_project_manager.py`** — 프로젝트 저장/불러오기 테스트 (16개)

| 카테고리 | 테스트 케이스 | 검증 내용 |
|----------|--------------|-----------|
| Export | `test_export_empty_db_creates_valid_file` | 빈 DB도 유효한 JSON 생성 |
| Export | `test_export_with_data` | 모든 테이블의 모든 행이 저장됨 |
| Export | `test_export_preserves_dates_and_nulls` | 날짜→ISO 문자열, None→null 직렬화 |
| Roundtrip | `test_roundtrip_preserves_all_data` | Export→Import 왕복 후 모든 데이터 복원 |
| Roundtrip | `test_roundtrip_preserves_relationships` | FK 관계(담임 학반, 교실 등) 정상 유지 |
| Roundtrip | `test_roundtrip_twice_is_idempotent` | 두 번 왕복해도 데이터 무결성 유지 |
| ID 재매핑 | `test_import_with_non_contiguous_ids` | 원본 ID 비연속적이어도 FK 올바르게 연결 |
| Overwrite | `test_import_replaces_all_existing_data` | Import 시 기존 데이터 완전 대체 |
| Rollback | `test_import_rollback_preserves_original_data` | 손상된 파일 import 시 기존 데이터 보존 |
| Rollback | `test_import_corrupted_json_raises` | 깨진 JSON 파일 감지 및 예외 발생 |
| Validation | `test_validate_rejects_missing_metadata` | metadata 키 누락 검출 |
| Validation | `test_validate_rejects_missing_data` | data 키 누락 검출 |
| Validation | `test_validate_rejects_wrong_version` | 버전 불일치 파일 차단 |
| Validation | `test_validate_accepts_valid_file` | 유효한 파일은 검증 통과 |
| Validation | `test_validate_rejects_nonexistent_file` | 존재하지 않는 파일 경로 감지 |
| Unicode | `test_export_preserves_unicode_text` | 한글·특수문자(🔬)·중간점(·) 보존 |

모든 `test_project_manager.py` 테스트는 인메모리 SQLite(`sqlite:///:memory:`)에서 실행되며 파일 입출력은 `tempfile`을 사용하여 실제 디스크 파일 동작을 검증합니다. 이 테스트들은 Qt 위젯을 사용하지 않으므로 `QT_QPA_PLATFORM=offscreen` 없이도 실행 가능합니다.

---

## 10. 설치 프로그램 빌드

`build_installer.py` 스크립트가 PyInstaller를 사용하여 독립 실행 가능한 설치 프로그램을 생성합니다.

```bash
# macOS: .app 번들 생성 (dist/학교시간표관리.app)
python3 build_installer.py

# macOS: .dmg 설치 이미지 생성 (installer_output/학교시간표관리.dmg)
python3 build_installer.py --dmg

# Windows: .exe 실행 파일 + ZIP 패키지 생성
python3 build_installer.py --win
```

빌드 전에 `installer/` 디렉터리에 아이콘 파일이 있어야 합니다. 아이콘이 없으면 `installer/generate_icon.py`를 먼저 실행하여 생성할 수 있습니다.

```bash
python3 installer/generate_icon.py
```

빌드 결과물은 두 곳에 생성됩니다.

- `dist/` — PyInstaller가 생성한 원시 결과물 (앱 번들 또는 EXE)
- `installer_output/` — 최종 배포용 설치 이미지 (DMG 또는 ZIP)

---

## 11. 기술 스택

| 계층 | 기술 | 버전 | 용도 |
|------|------|------|------|
| **UI 프레임워크** | PyQt6 | 6.x | 데스크톱 GUI (QMainWindow, QDialog, QThread 등) |
| **ORM** | SQLAlchemy | 2.0+ | 데이터베이스 추상화, 모델 정의, 세션 관리 |
| **알고리즘** | Python 표준 라이브러리 | — | random.shuffle, 제약조건 검사 |
| **PDF 생성** | ReportLab | 4.x | A4 가로 PDF, 한글 TTF 폰트 등록, 테이블 스타일 |
| **Excel 생성** | OpenPyXL | 3.x | xlsx 파일 생성, 셀 서식, 시트 관리 |
| **기본 DB** | SQLite | 내장 | 로컬 단일 파일 데이터베이스 |
| **공유 DB** | PostgreSQL (psycopg2) | 선택적 | 네트워크 공유 데이터베이스 |
| **테스트** | pytest + pytest-qt | — | GUI 단위 테스트 |
| **패키징** | PyInstaller | 6.x | 단일 실행 파일 / 설치 프로그램 생성 |

---

## 12. 장점과 한계

### 장점

이 프로그램의 가장 큰 강점은 **워크플로우 완결성**입니다. 시간표 관련 작업이 한 앱 안에서 처음부터 끝까지 처리됩니다. 기초 데이터를 입력하고, 자동으로 시간표를 생성하고, 필요한 부분을 수정하고, 결재 과정을 거쳐 확정한 뒤, PDF나 NEIS 형식으로 출력하는 일련의 과정이 앱 전환 없이 가능합니다.

두 번째 강점은 **자동화된 감사 추적**입니다. 모든 변경 이벤트가 자동으로 기록되므로 별도로 변경 내역을 관리할 필요가 없습니다. 변경 이력 페이지에서 날짜·학반·유형을 필터링하여 특정 변경 사항을 신속하게 찾을 수 있습니다.

세 번째 강점은 **UI 응답성**입니다. 시간표 자동 생성은 연산 부하가 큰 작업이지만, QThread를 사용하여 백그라운드에서 실행하기 때문에 생성 중에도 앱이 멈추거나 응답 없음 상태가 되지 않습니다.

### 한계

**동시 편집 미지원**이 가장 큰 한계입니다. 여러 명이 PostgreSQL에 동시 접속하여 같은 시간표를 편집할 경우, 충돌 감지나 잠금 메커니즘 없이 마지막 저장이 덮어씁니다. 복수의 교무 담당자가 동시에 작업해야 하는 환경에서는 주의가 필요합니다.

**사용자 인증 부재**도 고려해야 합니다. 현재는 누가 변경을 신청했는지를 이름 문자열로만 기록하며, 별도의 계정 시스템이 없습니다. 변경 신청자와 승인자 구분이 신뢰 수준에서 처리됩니다.

**DB 스키마 마이그레이션 미지원**도 알려진 한계입니다. 앱은 `create_all()`로 테이블을 초기 생성하지만, 기존에 운영 중인 DB에 새 컬럼이나 테이블이 추가된 경우 자동으로 반영되지 않습니다. 스키마 변경 시 Alembic 같은 마이그레이션 도구를 별도로 사용해야 합니다.

**교사 선호/회피 제약조건 미반영**도 개선이 필요한 부분입니다. `TeacherConstraint` 모델에는 `preferred`(선호)와 `avoid`(회피) 타입이 정의되어 있지만, 자동 생성 알고리즘은 현재 `unavailable`(불가) 타입만 참조합니다.

---

## 라이선스

이 프로젝트는 MIT 라이선스를 따릅니다. 자유롭게 사용·수정·배포하실 수 있습니다.

---

## 문의 및 기여

버그 신고, 기능 제안, 기여는 앱 내 "피드백 보내기" 메뉴 또는 GitHub Issues를 통해 부탁드립니다.
