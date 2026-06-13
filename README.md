# 학교 시간표 관리 시스템

**FastAPI 서버 + PyQt6 관리자 프로그램 + PyQt6 교사 프로그램**으로 구성된 3-프로그램 분산 아키텍처입니다. 서버 컴퓨터에서 FastAPI 백엔드가 24시간 데이터를 관리하고, 교감·일과계는 관리자 프로그램으로 시간표를 생성·편집·승인하며, 일반 교사는 교사 프로그램으로 시간표를 조회하고 교체 신청을 제출합니다. 실시간 공동 채팅창이 두 프로그램 모두에 내장되어 있으며, 변경 신청 과정에서 피교사의 사전 동의를 받는 워크플로우를 지원합니다.

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
   - 2.9 [채팅 및 공지](#29-채팅-및-공지)
   - 2.10 [피교사 동의 및 알림 시스템](#210-피교사-동의-및-알림-시스템)
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
13. [코드 품질 개선 이력](#13-코드-품질-개선-이력-2026-06-13)

---

## 1. 프로그램 개요

학교 시간표 관리는 수십 명의 교사, 수백 개의 수업 시수, 그리고 교실 배정이라는 복잡한 제약조건을 동시에 만족시켜야 하는 어려운 문제입니다. 기존에는 Excel 스프레드시트나 종이 대장을 활용하는 경우가 많았으나, 이는 변경 이력 관리가 어렵고, 교사 간 중복 배정 오류가 발생하기 쉬우며, NEIS(나이스 국가교육정보시스템) 입력 작업을 별도로 반복해야 하는 불편함이 있었습니다.

### 3-프로그램 구조

이 시스템은 역할과 보안을 고려해 세 개의 독립 프로그램으로 구성됩니다.

| 프로그램 | 실행 위치 | 주요 역할 |
|---|---|---|
| **① FastAPI 서버** | 서버 컴퓨터 (24시간 상시 가동) | DB 관리, API 제공, 실시간 채팅 허브, 알림 중계 |
| **② 관리자 프로그램** | 일과계·교감 PC | **일과계(admin)**: 편제·교사·교과 등록, 시간표 생성·직접 수정, 결재 라인 설정, 변경 신청 승인 (워크플로우 설정에 따라 단계별) |
| | | **교감(vice_principal)**: 시간표 열람(읽기 전용), 변경 신청 승인/거절 (워크플로우 설정에 따름) |
| **③ 교사 프로그램** | 교사 PC | 시간표 조회, 교체 신청 제출·결과 확인, 피교사 동의/거절, 알림 수신 |

서버 컴퓨터를 분리하는 이유는 업무용 PC를 24시간 켜놓기 어렵고, 다른 작업 중에 시간표 데이터가 의도치 않게 영향을 받을 수 있기 때문입니다. 모든 데이터는 서버의 PostgreSQL에서 중앙 관리됩니다.

### 사용자 역할 체계

이 시스템은 네 가지 사용자 역할을 정의합니다.

| 역할 | 코드상 role 값 | 권한 요약 |
|---|---|---|
| **일과계 선생님** | `admin` | **전체 관리**: 편제(학년·반·교실)·교사·교과목 CRUD, 계정 관리, 시간표 생성·직접 수정, 결재 라인 설정, 변경 신청 승인 (워크플로우 설정에 따라 단계별) |
| **교감 선생님** | `vice_principal` | **읽기 전용 + 승인 권한**: 시간표 열람(편집 불가), 변경 신청 승인/거절 (워크플로우 설정에 따름). 편제·계정·일정 수정 불가 |
| **교무부장** | `department_head` | **읽기 전용 + 승인 권한**: 시간표 열람(편집 불가), 변경 신청 승인/거절 (워크플로우 설정에 따름). 3단계 이상 결재 라인에서 중간 승인자로 참여 가능 |
| **교사** | `teacher` | 시간표 조회, 변경 신청 제출, 피교사 동의/거절. 편집·승인 권한 없음 |

서버 컴퓨터를 분리하는 이유는 업무용 PC를 24시간 켜놓기 어렵고, 다른 작업 중에 시간표 데이터가 의도치 않게 영향을 받을 수 있기 때문입니다. 모든 데이터는 서버의 PostgreSQL에서 중앙 관리됩니다.

### 핵심 설계 원칙

핵심 설계 원칙은 세 가지입니다. 첫째, **역할 기반 접근 제어**입니다. JWT 토큰 인증으로 일과계(admin)·교감(vice_principal)·교무부장(department_head)·교사(teacher) 네 가지 계정을 구분하며, 시간표 생성·편집은 일과계만, 변경 신청 승인은 워크플로우 설정에 따라 역할별로 단계적 처리됩니다. 둘째, **데이터 일관성**입니다. 모든 수업 배정은 SQLAlchemy ORM을 통해 관계형 DB에 저장되므로, 교사 중복·교실 중복 같은 충돌은 자동 생성 단계에서 원천 차단합니다. 셋째, **감사 추적성**입니다. 모든 생성·수정·삭제 이벤트는 TimetableChangeLog 테이블에 변경 전후 상태를 JSON으로 기록하며, 변경 신청의 결재 이력도 approval_history JSON 배열로 완전히 추적됩니다.

서버는 SQLite(개발/단독 운용)와 PostgreSQL(운영 환경) 두 가지 데이터베이스를 지원합니다. `DB_URL` 환경 변수로 전환합니다.

---

## 2. 주요 기능 상세

### 2.1 기초 데이터 설정

시간표를 생성하기 전에 반드시 설정해야 하는 네 가지 기초 데이터가 있습니다.

**학년/반 편제**는 학교의 기본 단위인 학년과 학급을 등록하는 화면입니다. 학년 번호(1·2·3 등)를 먼저 등록하고, 그 아래 학급 번호(1반·2반 등)를 추가합니다. 학급을 삭제할 때는 해당 학급에 배정된 모든 시간표 항목과 수업 시수 배정 정보가 연쇄적으로 삭제(cascade)되므로 주의가 필요합니다.

**교사 관리**는 시간표 생성에서 핵심이 되는 교사 데이터를 관리합니다. 교사 등록 시 이름과 일 최대 수업 수(기본 5교시)를 입력하며, 담임 학급을 배정할 수 있습니다. 특히 주목할 기능은 **불가 시간 설정**입니다. 교사별 편집 화면에는 요일(월~금) × 교시(1~7)로 구성된 35칸의 체크박스 그리드가 표시되며, 체크된 슬롯은 자동 생성 시 해당 교사에게 수업을 배정하지 않습니다. 예를 들어, 매주 수요일 6교시에 교직원 회의가 있다면 해당 칸을 체크함으로써 회의 시간에 수업이 잡히는 상황을 사전에 방지할 수 있습니다.

**교과목/시수 배정**은 개별 과목을 정의하고, 각 학반마다 해당 과목의 주당 시수와 담당 교사를 지정하는 화면입니다. 과목에는 색상을 지정할 수 있어서, 시간표 그리드에서 과목을 시각적으로 구분하기가 쉽습니다. 시수 배정 테이블은 가로축이 과목, 세로축이 학반으로 구성되며, 각 셀에 주당 시수(숫자)와 담당 교사를 입력합니다. **2025년 6월 업데이트부터는 시수 배정에 학기(`term_id`)가 추가되어**, 같은 학반·과목이라도 학기별로 별도의 시수와 담당 교사를 지정할 수 있습니다. 이를 통해 생성기는 지정한 학기의 시수 배정만 사용하여 학기 간 데이터가 섞이는 문제를 방지합니다.

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

**직접 수정**을 선택하면 변경 내용이 즉시 시간표에 반영되고, 변경 이력(TimetableChangeLog)에도 자동으로 기록됩니다. 오탈자 수정이나 담당 교사 조정 같은 단순한 정정 작업에 적합합니다. 직접 수정은 **일과계 선생님(admin)**만 가능합니다.

**변경 신청**을 선택하면 변경 사유를 입력한 후 신청 레코드(TimetableChangeRequest)가 생성됩니다. 변경 신청은 즉시 시간표에 반영되지 않으며, 아래의 **결재 워크플로우**를 거쳐 최종 확정됩니다.

### 변경 신청 동적 결재 승인 절차

변경 신청은 실제 학교 운영 방식을 반영하여 관리자가 **자유롭게 설정할 수 있는 결재 워크플로우**로 처리됩니다. 학교 사정에 따라 1단계(일과계 단독 승인), 2단계(일과계 검토 → 교감 결재), 3단계 이상(일과계 → 교무부장 → 교감) 등으로 구성할 수 있습니다.

**결재 라인 설정** (일과계 전용):
- 사이드바 "결재 라인 설정" 페이지에서 워크플로우를 생성·수정·활성화
- 각 단계마다 승인 역할(admin / vice_principal / department_head)과 단계 이름을 지정
- 한 번에 하나의 워크플로우만 활성화되어 실제 결재에 사용됨
- 단계 순서는 1부터 연속되어야 하며, 최소 1단계 이상 필요

```
교사가 변경 신청 제출
  → 상태: pending (대기 중), current_step = 1
  → "변경 신청/결재" 페이지에 표시

[동적 결재 워크플로우에 따른 단계별 승인]

각 단계:
  → 해당 단계의 role_required 와 일치하는 사용자만 승인·거절 가능
  → 승인 시: approval_history JSON 배열에 기록 추가
     - 마지막 단계가 아니면 current_step += 1 (다음 단계로 진행)
     - 마지막 단계면 status = "approved", 실제 TimetableEntry 에 변경 적용 + 이력 기록
  → 거절 시: status = "rejected", TimetableEntry 는 변경되지 않음

예시: 3단계 결재 (일과계 → 교무부장 → 교감)
  1단계 — 일과계(admin) 승인 → approval_history: [1단계 승인 기록]
  2단계 — 교무부장(department_head) 승인 → approval_history: [1단계, 2단계]
  3단계 — 교감(vice_principal) 최종 승인 → status = "approved", 시간표 반영
```

**핵심 특징**:
- **설정 가능한 결재 라인**: 학교마다 다른 결재 구조를 자유롭게 구성할 수 있습니다
- **역할 기반 승인**: 각 단계는 개별 사용자가 아닌 역할(role) 단위로 승인자를 지정합니다
- **단계별 진행 추적**: `current_step` / `total_steps` 로 현재 승인 진행 상황을 실시간 확인 가능
- **완전한 감사 추적**: `approval_history` JSON 배열에 모든 단계의 승인·거절 기록(누가, 언제, 어떤 역할로, 어떤 결정을)이 저장됩니다
- **권한 검증**: 각 단계에서 지정된 role과 일치하지 않는 사용자는 승인·거절을 시도해도 서버에서 403 Forbidden으로 차단됩니다
- 교사는 교사 프로그램의 "교체 신청" 페이지에서 자신의 신청 상태(대기 중 (1/3단계) → 대기 중 (2/3단계) → 승인 완료/거절)를 실시간으로 확인할 수 있습니다

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

### 2.9 채팅 및 공지

세 프로그램(서버·관리자·교사) 모두에 내장된 공동 채팅창은 교무실 전체 메신저 역할을 합니다. WebSocket 으로 실시간 연결되며, 서버가 모든 접속자에게 메시지를 브로드캐스트합니다.

**공지 메시지**. 일과계 선생님(admin)과 교감 선생님(vice_principal)은 일반 메시지와 함께 공지 메시지를 전송할 수 있습니다. 공지 메시지는 노란색 배경과 왼쪽 주황색 세로줄로 강조 표시되어 일반 대화와 시각적으로 구분됩니다.

**메시지 관리 (일과계 전용)**. 일과계 선생님은 다음 두 가지 방법으로 채팅 메시지를 관리할 수 있습니다.

| 기능 | 방법 | 설명 |
|------|------|------|
| **개별 메시지 삭제** | 각 메시지 우측 상단의 ✕ 버튼 클릭 | 부적절한 메시지나 오류 메시지를 즉시 제거합니다. WebSocket 으로 모든 접속자에게 삭제가 전파되어 UI 가 실시간 갱신됩니다. |
| **오래된 메시지 일괄 정리** | 채팅 헤더의 "🗑 정리" 버튼 클릭 | `CHAT_RETENTION_DAYS`(기본 60일)보다 오래된 모든 메시지를 한 번에 삭제합니다. 서버의 백그라운드 태스크와 동일한 기준을 사용합니다. |

**자동 정리**. 서버는 12시간 간격으로 `CHAT_RETENTION_DAYS` 환경 변수에 설정된 기간(기본값 60일)보다 오래된 메시지를 자동으로 삭제합니다. `CHAT_RETENTION_DAYS=0` 으로 설정하면 자동 정리를 비활성화하고 메시지를 무기한 보관할 수 있습니다. 삭제된 메시지는 모든 접속 클라이언트의 UI 에서 자동으로 제거됩니다.

**연결 복원력**. WebSocket 연결이 끊기면 5초 간격으로 자동 재연결을 시도하며, 재연결 성공 시 최근 100개의 메시지 이력을 다시 불러옵니다.

### 2.10 피교사 동의 및 알림 시스템

#### 2.10.1 배경과 필요성

기존 변경 신청 흐름은 교사가 "이 시간을 바꾸고 싶다"고만 요청할 수 있었고, 실제로 어떤 대안이 있는지 프로그램이 안내하지 않았습니다. 또한 교사 간 수업 교체가 필요할 때 피교사의 사전 동의를 얻는 과정이 메신저나 전화로 분리되어 있어 불편하고 추적이 어려웠습니다. 이번 업데이트에서는 이 문제를 해결하기 위해 다음과 같은 기능을 추가했습니다.

1. **교체 가능한 대안 제시**: 시간표 슬롯을 클릭하면 프로그램이 "누구의 어떤 과목/교실과 바꿀 수 있는지" 또는 "이 슬롯에 누구를 배치할 수 있는지"를 충돌 검증 후 제안합니다.
2. **교사 간 동의(consent)**: 교체/대리 수업에 피교사가 있을 경우, 해당 교사에게 알림이 가고 승인/거절할 수 있습니다. 승인 후에만 일과계 → 교감(또는 워크플로우에 따른 결재 라인)이 진행됩니다.
3. **알림 시스템**: WebSocket 기반 실시간 알림과 DB 영속성을 결합하여, 교사가 오프라인이었더라도 재접속 시 확인할 수 있습니다.

#### 2.10.2 변경 신청의 세 가지 유형

변경 신청은 대상 슬롯의 어떤 속성을 바꾸느냐에 따라 동의 필요 여부가 달라집니다.

| 유형 | 동의 필요 여부 | 설명 |
|------|---------------|------|
| **교실 변경** | 불필요 (`not_required`) | 동일 교사·과목에서 교실만 이동하는 경우 |
| **교사 변경** | 필요 (`pending`) | `new_teacher_id`를 지정하여 담당 교사를 바꾸는 경우 |
| **교환(swap)** | 필요 (`pending`) | 다른 시간표 슬롯과 교사·과목을 맞바꾸는 경우 |

교사 변경이나 교환 신청이 접수되면, 해당 신청은 일시적으로 `current_step = 0` 상태가 되어 관리자가 먼저 승인할 수 없습니다. 피교사가 동의를 완료해야만 `current_step = 1`로 전환되어 정식 결재 라인이 시작됩니다.

#### 2.10.3 시간표 제안 API

교사 프로그램에서 시간표 슬롯을 더블클릭하면, 클라이언트는 `GET /timetable/suggestions?entry_id=<id>`를 호출합니다. 서버는 다음 정보를 포함한 제안 응답을 반환합니다.

```json
{
  "current": { "entry_id": 1, "day_of_week": 1, "period": 1, ... },
  "subjects": [...],
  "teachers": [...],
  "rooms": [...],
  "swaps": [...]
}
```

각 제안은 다음 제약조건을 모두 통과해야 합니다.

- **반 중복**: 동일 반의 동일 교시에 이미 수업이 있는 경우 제외
- **교사 중복**: 동일 교사의 동일 교시에 이미 수업이 있는 경우 제외
- **교실 중복**: 동일 교실의 동일 교시에 이미 수업이 있는 경우 제외
- **교사 불가 시간**: `TeacherConstraint.unavailable`로 지정된 슬롯 제외
- **일일 최대 수업 초과**: `Teacher.max_daily_classes`를 초과하는 경우 제외

**과목 대체 제안**은 현재 슬롯의 반·학기에 배정된 `SubjectClassAssignment` 중에서, 동일 교시에 배치 가능한 (과목, 교사) 조합을 찾아 제시합니다. **교사 대체 제안**은 현재 과목을 가르칠 수 있고 해당 교시에 갈 수 있는 다른 교사를 제시합니다. **교실 대체 제안**은 현재 슬롯의 교시에 비어 있는 교실을 제시하며, 특별실이 필요한 과목의 경우 일반 교실은 제외합니다.

**교환(swap) 제안**은 서로 다른 두 슬롯의 교사·과목을 맞바꾸는 경우입니다. 교환은 양쪽 교사 모두 상대 슬롯에 수업이 없고, 반·교실 충돌이 없어야 하며, 양쪽 교사의 불가 시간과 일일 최대 수업 제약을 모두 통과해야 제안됩니다.

#### 2.10.4 피교사 동의 워크플로우

```
교사 A가 교사 변경/교환 신청 제출
  → consent_status = "pending"
  → current_step = 0 (관리자 승인 불가)
  → 피교사 B에게 실시간 알림 + DB 알림 저장

피교사 B가 교사 프로그램에서 알림 확인
  → "승인" 선택:
       consent_status = "approved"
       current_step = 1 (일과계 결재 라인 시작)
       신청자 A에게 동의 완료 알림 전송
  → "거절" 선택:
       consent_status = "rejected"
       status = "rejected" (최종 거절)
       신청자 A에게 거절 알림 전송

consent_status = "approved" 이후:
  → 기존 동적 결재 워크플로우(일과계 → 교감 → ...)가 진행됨
  → 최종 승인 시 TimetableEntry 에 변경(또는 교환) 반영
```

동의 권한은 로그인한 사용자의 `teacher_id`가 변경 신청의 `affected_teacher_id`와 일치할 때만 부여됩니다. 즉, 변경 신청에 명시된 피교사 본인만 동의하거나 거절할 수 있습니다.

#### 2.10.5 알림 시스템

**알림 모델**. `Notification` 테이블은 다음 정보를 저장합니다.

| 컬럼 | 설명 |
|------|------|
| `user_id` | 수신자 (FK users.id) |
| `type` | `consent_request`, `consent_approved`, `consent_rejected`, `status_update`, `approved`, `rejected` 등 |
| `change_request_id` | 관련 변경 신청 ID (nullable) |
| `message` | 사용자에게 표시할 메시지 본문 |
| `is_read` | 읽음 여부 (기본값 false) |
| `created_at` | 생성 시각 |

**알림 전달 경로**.
1. 피교사 동의가 필요한 변경 신청이 생성되면, 서버는 `Notification` 레코드를 생성합니다.
2. 동일한 내용을 WebSocket `notification` 이벤트로 수신자에게 실시간 전송합니다.
3. 수신자가 오프라인이었다면, 다음 로그인 시 `GET /notifications` 엔드포인트로 누적된 알림을 조회할 수 있습니다.
4. 알림을 확인하면 `PATCH /notifications/{id}`로 읽음 처리하거나, `DELETE /notifications/{id}`로 삭제할 수 있습니다.

**교사 프로그램 UI**. 교사 프로그램 상단에는 알림 벨 아이콘이 표시되며, 읽지 않은 알림 개수가 배지로 나타납니다. 벨 아이콘을 클릭하면 알림 패널이 열리고, `consent_request` 유형의 알림에는 직접 "승인"과 "거절" 버튼이 표시되어 즉시 동의를 처리할 수 있습니다.

#### 2.10.6 변경 내용의 최종 반영

피교사 동의를 거쳐 관리자 승인까지 완료되면, 변경 내용은 실제 `TimetableEntry`에 반영됩니다.

- **단순 변경**(`new_subject_id`, `new_teacher_id`, `new_room_id`): 해당 슬롯의 속성을 업데이트하고 변경 이력을 남깁니다.
- **교환**(`swap_partner_entry_id`): 두 슬롯의 교사·과목·교실을 서로 맞바꿉니다. 이 과정에서 각 슬롯의 변경 전후 상태가 `TimetableChangeLog`에 기록됩니다.

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
| 8 | 시수 배정 (SubjectSetupWidget) | 반, 교과목, 교사, 학기 |
| 9 | 시간표 자동 생성 | 시수 배정 |
| 10 | 시간표 조회·수정·변경 신청 | 생성된 시간표 |

이 순서를 지키면 "학반이 없어서 콤보박스가 비어 있음"과 같은 불편을 겪지 않습니다. 단, 2~6단계는 순서가 바뀌더라도 페이지 간 refresh 덕분에 후속 페이지에서 최신 데이터를 확인할 수 있습니다.

---

## 4. 설치 및 실행 방법

### 사전 요구사항

- Python 3.10 이상 (3.12 권장)
- macOS / Windows / Linux 모두 지원
- 서버 프로그램은 네트워크에서 접근 가능한 별도 컴퓨터(또는 동일 PC의 별도 터미널)에서 실행

### 1단계: 의존성 설치 (공통)

```bash
# 가상환경 생성
python3 -m venv .venv

# 가상환경 활성화
source .venv/bin/activate        # macOS / Linux
# .venv\Scripts\activate.bat     # Windows (명령 프롬프트)
# .venv\Scripts\Activate.ps1     # Windows (PowerShell)

# 의존성 설치
pip install -r requirements.txt
```

### 2단계: FastAPI 서버 실행 (서버 컴퓨터에서)

```bash
# SQLite 사용 시 (개발·소규모 환경)
uvicorn server.main:app --host 0.0.0.0 --port 8000

# PostgreSQL 사용 시 (운영 환경 권장)
export DB_URL="postgresql+psycopg2://사용자:비밀번호@호스트/DB명"
export JWT_SECRET_KEY="반드시-운영환경에서-변경할-비밀키"
export ADMIN_PASSWORD="안전한-초기-비밀번호"
export VP_PASSWORD="안전한-초기-비밀번호"
export DH_PASSWORD="안전한-초기-비밀번호"
export CORS_ORIGINS="http://실제서버IP:8000,http://실제도메인:8000"
export WS_ALLOWED_ORIGINS="http://실제서버IP:8000,http://실제도메인:8000"
uvicorn server.main:app --host 0.0.0.0 --port 8000
```

서버를 처음 실행하면 두 종류의 관리자 계정이 자동 생성됩니다.

| 계정 유형 | 기본 아이디 | 기본 비밀번호 | 역할 |
|---|---|---|---|
| **일과계 선생님** | `admin` | 랜덤 생성 (서버 시작 시 콘솔에 1회 출력) | 전체 관리 (편제·계정·시간표 생성·승인) |
| **교감 선생님** | `vice_principal` | 랜덤 생성 (서버 시작 시 콘솔에 1회 출력) | 시간표 열람 + 변경 신청 승인 (워크플로우 설정에 따름) |
| **교무부장** | `department_head` | 랜덤 생성 (서버 시작 시 콘솔에 1회 출력) | 시간표 열람 + 변경 신청 승인 (워크플로우 설정에 따름) |

> **중요**: 서버 최초 실행 시 `ADMIN_PASSWORD` / `VP_PASSWORD` / `DH_PASSWORD` 환경 변수를 설정하지 않으면
> 비밀번호가 `secrets.token_urlsafe(12)` 로 무작위 생성됩니다. 생성된 비밀번호는 서버 콘솔에
> 한 번만 출력되므로 반드시 기록해 두세요. 환경 변수로 미리 설정하면 이 절차를 건너뛸 수 있습니다.
>
> **모든 계정은 첫 로그인 후 즉시 비밀번호를 변경하세요.**

환경 변수를 통해 기본값을 바꿀 수 있습니다.

| 환경 변수 | 기본값 | 설명 |
|---|---|---|
| `DB_URL` | SQLite (timetable.db) | SQLAlchemy DB 연결 URL |
| `JWT_SECRET_KEY` | `uuid4().hex` (서버 시작 시 자동 생성) | JWT 서명 키. **운영 환경에서는 반드시 고정된 값을 설정하세요.** 미설정 시 서버 재시작마다 새로운 키가 생성되어 기존 토큰이 모두 무효화됩니다. |
| `JWT_EXPIRE_HOURS` | `24` | 토큰 유효 시간 (시간 단위) |
| `ADMIN_USERNAME` | `admin` | 일과계 선생님 기본 아이디 |
| `ADMIN_PASSWORD` | `secrets.token_urlsafe(12)` (랜덤 생성) | 일과계 선생님 초기 비밀번호. 미설정 시 서버 콘솔에 1회 출력됩니다. |
| `VP_USERNAME` | `vice_principal` | 교감 선생님 기본 아이디 |
| `VP_PASSWORD` | `secrets.token_urlsafe(12)` (랜덤 생성) | 교감 선생님 초기 비밀번호. 미설정 시 서버 콘솔에 1회 출력됩니다. |
| `DH_USERNAME` | `department_head` | 교무부장 기본 아이디 |
| `DH_PASSWORD` | `secrets.token_urlsafe(12)` (랜덤 생성) | 교무부장 초기 비밀번호. 미설정 시 서버 콘솔에 1회 출력됩니다. |
| `CHAT_RETENTION_DAYS` | `60` | 채팅 메시지 보관 기간(일). 0=무기한 보관, 자동 정리 비활성화 |
| `CORS_ORIGINS` | `http://localhost:8000,http://127.0.0.1:8000` | CORS 허용 출처 (쉼표 구분, 운영 환경에서는 실제 서버 IP/도메인으로 설정) |
| `WS_ALLOWED_ORIGINS` | `http://localhost:8000,http://127.0.0.1:8000` | WebSocket 허용 출처 (CSWSH 방지, 쉼표 구분). "" (빈 문자열)로 설정 시 Origin 검증 비활성화 (개발 환경용) |
| `SSL_CERT_FILE` | (미설정) | TLS 인증서 경로. 설정 시 TLS 경고가 표시되지 않습니다. 운영 환경에서는 nginx 리버스 프록시 또는 uvicorn --ssl 옵션으로 TLS 활성화를 권장합니다. |

### 3단계: 관리자 프로그램 실행 (일과계·교감 PC에서)

```bash
export SERVER_URL="http://서버IP:8000"   # 서버 주소 지정
python -m admin_app.main
```

- **일과계 선생님**은 `admin` 계정으로 로그인합니다. 편제·교사·교과 등록 → 시간표 자동 생성 → 결재 라인 설정 → 변경 신청 승인 등 관리 기능 전체를 사용할 수 있습니다. 사이드바에는 9개 페이지가 표시됩니다.
- **교감 선생님**은 `vice_principal` 계정으로 로그인합니다. 사이드바에는 시간표 열람(읽기 전용)과 변경 신청 승인 페이지만 표시됩니다(3개 페이지). 편제나 계정 관리 기능은 접근할 수 없습니다.

### 4단계: 교사 프로그램 실행 (교사 PC에서)

```bash
export SERVER_URL="http://서버IP:8000"
python -m teacher_app.main
```

관리자가 생성해준 `teacher` 계정으로 로그인합니다. 시간표 조회, 교체 신청, 공동 채팅창, 알림 수신, 피교사 동의 처리를 할 수 있습니다.

> **참고:** `SERVER_URL` 환경 변수를 설정하지 않으면 기본값 `http://localhost:8000`을 사용합니다. 서버와 앱을 같은 PC에서 실행하는 경우에는 별도 설정이 불필요합니다.

---

## 5. 상세 사용 설명

이 장에서는 처음 사용하는 분이 시간표를 완성하기까지의 전체 과정을 순서대로 설명합니다.

### 5.1 학년/반 편제 등록

앱을 처음 실행한 후 사이드바에서 **"학년/반 편제"**를 선택합니다. 화면 상단에 학년 목록이, 하단에 선택된 학년에 속한 학급 목록이 표시됩니다. "학년 추가" 버튼을 클릭하여 학년 번호를 입력하고 학년을 등록합니다. 그런 다음 등록된 학년을 클릭하여 선택하고, "학급 추가" 버튼으로 해당 학년 아래 학급을 추가합니다. 예를 들어, 3개 학년 각 5학급의 학교라면 학년 3개를 먼저 등록한 후 각 학년에 학급 5개씩 추가합니다.

### 5.2 교사 등록 및 불가 시간 설정

사이드바에서 **"교사 관리"**를 선택합니다. "교사 추가" 버튼으로 교사 이름과 일 최대 수업 수를 입력합니다. 일 최대 수업 수는 자동 생성 시 소프트 제약조건으로 사용됩니다. 기본값은 5교시입니다. **교사 등록 시 `max_daily_classes`는 1 이상의 값이어야 합니다.**

교사를 등록한 후, 목록에서 교사를 선택하고 "불가 시간 편집" 버튼을 클릭하면 5×7 체크박스 그리드가 나타납니다. 해당 교사가 수업을 받을 수 없는 슬롯(예: 수요일 7교시, 금요일 6~7교시 등)에 체크합니다. 체크된 슬롯은 시간표 자동 생성 시 하드 제약조건으로 처리되어 해당 교사에게 수업이 배정되지 않습니다.

### 5.3 교과목 및 주당 시수 배정

사이드바에서 **"교과목/시수 배정"**을 선택합니다. "과목 추가" 버튼으로 과목 이름과 약어, 색상을 입력합니다. 색상은 시간표 그리드에서 과목을 구분하는 데 사용됩니다. 과목이 여럿 등록되면 자동으로 서로 다른 색상이 순환 배정됩니다.

하단 시수 배정 테이블에서 각 학반(행)과 과목(열)이 교차하는 셀에 주당 시수 숫자를 입력하고, 담당 교사를 드롭다운으로 선택합니다. **이때 상단의 학기 콤보박스에서 대상 학기를 반드시 선택해야 합니다.** 동일 학년·반·과목이라도 학기별로 별도의 시수와 담당 교사를 지정할 수 있습니다. 이 정보가 자동 생성 알고리즘의 기본 입력 데이터가 됩니다.

### 5.4 교실 등록

사이드바에서 **"교실 관리"**를 선택합니다. "교실 추가" 버튼으로 교실 이름(예: "과학실 1", "음악실", "체육관")과 유형을 입력합니다. 교실 유형으로는 일반교실, 과학실, 음악실, 미술실, 컴퓨터실, 체육관, 도서관, 기타 중에서 선택합니다.

### 5.5 학기 등록 및 시간표 자동 생성

사이드바 하단의 **"+ 학기 추가"** 버튼을 클릭하여 연도와 학기(1학기/2학기)를 입력합니다. 학기가 등록되면 사이드바에 표시됩니다.

이제 **"▶ 자동 생성"** 버튼을 클릭합니다. 다이얼로그에서 대상 학기를 선택하고 "생성" 버튼을 누르면 알고리즘이 백그라운드에서 실행됩니다. 몇 초에서 수십 초 안에 결과가 표시됩니다. 성공하면 기존 시간표가 교체되고, 실패하면 재시도를 제안하는 메시지가 나타납니다. 실패 시 교사 불가 시간을 줄이거나 일 최대 수업 수를 늘린 후 다시 시도하는 것이 좋습니다.

### 5.6 시간표 조회 및 수정

사이드바에서 **"반별 시간표"** 또는 **"교사별 시간표"**를 선택하여 생성된 결과를 확인합니다. 원하는 학반이나 교사를 상단 콤보박스에서 선택하면 해당 시간표가 그리드로 표시됩니다.

수정이 필요한 셀을 **더블클릭**하면 편집 다이얼로그가 열립니다. 과목, 교사, 교실을 변경한 후 수정 방식을 선택합니다. 간단한 오류 수정은 "직접 수정"으로 즉시 반영하고, 실질적인 시간표 변경은 변경 사유를 입력하여 "변경 신청"으로 제출합니다.

### 5.7 변경 신청 및 피교사 동의

교사 프로그램에서 수정이 필요한 시간표 슬롯을 더블클릭하면 **제안 다이얼로그**가 열립니다. 이 다이얼로그에서는 다음과 같은 대안을 확인할 수 있습니다.

- **과목 대체**: 현재 슬롯의 반·학기에 배정된 다른 과목/교사 조합
- **교사 대체**: 현재 과목을 가르칠 수 있고 해당 교시에 수업이 없는 다른 교사
- **교실 대체**: 현재 교시에 비어 있는 다른 교실
- **교환 제안**: 현재 슬롯과 교사·과목을 맞바꿀 수 있는 다른 슬롯

원하는 대안을 선택하고 사유를 입력한 뒤 "변경 신청" 버튼을 누릅니다. 변경 내용에 따라 다음과 같이 처리됩니다.

- **교실 변경**: 즉시 결재 라인으로 이동 (동의 불필요)
- **교사 변경**: 피교사 동의 대기 상태로 전환
- **교환**: 상대 슬롯 교사의 동의 대기 상태로 전환

피교사 동의가 필요한 경우, 상대 교사에게 실시간 알림과 DB 알림이 전송됩니다. 상대 교사는 교사 프로그램 상단의 알림 벨 아이콘을 클릭하여 알림 목록을 확인하고, "승인" 또는 "거절"을 선택할 수 있습니다.

### 5.8 변경 신청 결재

사이드바에서 **"변경 신청/결재"**를 선택하면 대기 중인 변경 신청 목록이 표시됩니다. 상태 컬럼에는 "대기 중 (1/3단계)"와 같이 현재 결재 진행 상황이 표시되며, **동의 상태** 컬럼에서는 피교사 동의 진행 상황을 확인할 수 있습니다. 동의 대기 중인 신청은 승인 버튼이 비활성화됩니다.

승인자는 자신의 역할(role)에 해당하는 단계의 신청만 처리할 수 있습니다. 예를 들어, 2단계 결재(일과계 → 교감)인 경우 일과계는 1단계 신청만 승인할 수 있고, 교감은 1단계를 통과한 2단계 신청만 최종 승인할 수 있습니다. 목록에서 신청 항목을 선택한 후 "승인" 또는 "거절" 버튼을 클릭하여 처리합니다. 마지막 단계에서 승인되면 변경 내용이 즉시 시간표에 반영되고 변경 이력에 자동 기록됩니다.

**결재 라인 설정** 페이지에서는 학교의 결재 구조에 맞게 워크플로우를 설정할 수 있습니다. 새 워크플로우 생성 다이얼로그에서 단계 수와 각 단계의 승인 역할·이름을 지정하고, 목록에서 원하는 워크플로우를 선택하여 "활성화" 버튼을 누르면 해당 워크플로우가 변경 신청 결재에 적용됩니다. 활성화된 워크플로우는 삭제할 수 없으므로, 먼저 다른 워크플로우를 활성화한 후 삭제해야 합니다.

---

## 6. 프로젝트 구조

```
school_timetable/
├── config.py                     # db_config.json 읽기/쓰기, SQLAlchemy URL 생성 (PostgreSQL 비밀번호 URL 인코딩 포함)
├── requirements.txt              # Python 의존성 목록 (서버·관리자·교사 앱 공통)
├── build_installer.py            # PyInstaller 기반 설치 프로그램 빌드 스크립트
│
├── shared/                       # 서버·관리자 앱·교사 앱이 함께 사용하는 공통 모듈
│   ├── models.py                 # SQLAlchemy ORM 모델 16개 (정식 정의 위치)
│   │                             #   기존 12개 + User(로그인 계정) + ChatMessage(채팅 메시지)
│   │                             #   + ApprovalWorkflow(결재 워크플로우) + ApprovalStep(결재 단계)
│   │                             #   + Notification(알림)
│   ├── schemas.py                # Pydantic v2 요청/응답 스키마 (API 계약 정의)
│   └── api_client.py             # 동기 HTTP + WebSocket 클라이언트 (ApiClient 클래스)
│                                 #   ※ 블로킹 호출 — PyQt6에서는 반드시 QThread 안에서 사용
│
├── server/                       # FastAPI 서버 (24시간 상시 운영)
│   ├── main.py                   # FastAPI 앱 진입점. lifespan으로 DB 초기화 및 최초 관리자 계정 생성
│   ├── auth_utils.py             # JWT 토큰 생성·검증, bcrypt 비밀번호 해싱
│   ├── deps.py                   # FastAPI 의존성: DB 세션 주입, JWT 인증·role 검사 가드
│   └── api/
│       ├── auth.py               # /auth/* 엔드포인트: 로그인, 현재 사용자 조회, 계정 CRUD (admin 전용)
│       ├── setup.py              # /setup/* 엔드포인트: 학년·반·교사·교과목·교실 CRUD (admin 전용)
│       ├── timetable.py          # /timetable/* 엔드포인트: 학기·시간표 조회·생성, 변경 신청·승인·이력, 제안, 동의
│       ├── chat.py               # /chat/* 엔드포인트: REST 메시지 조회 + WebSocket 실시간 채팅
│       │                         #   ConnectionManager 싱글턴이 접속 목록을 관리하며 브로드캐스트 처리
│       ├── notifications.py    # /notifications/* 엔드포인트: 알림 조회·읽음·삭제
│       └── workflow.py           # /workflows/* 엔드포인트: 결재 워크플로우 CRUD + 활성화 (일과계 전용)
│                                 #   ApprovalWorkflow + ApprovalStep 테이블 관리
│
├── admin_app/                    # 관리자(교감·일과계) 전용 데스크톱 앱
│   ├── main.py                   # 앱 진입점: Qt 초기화 → 로그인 창
│   └── ui/
│       ├── login_window.py       # 로그인 창 (role=admin 계정만 허용)
│       ├── admin_main_window.py  # 메인 창: 역할별 사이드바 (일과계 9페이지 / 교감 3페이지) + 우측 채팅 패널(280px)
│       └── chat_panel.py         # 채팅 패널. _WsThread(QThread)로 WebSocket 수신, 공지 체크박스 포함
│
├── teacher_app/                  # 일반 교사 전용 데스크톱 앱
│   ├── main.py                   # 앱 진입점: Qt 초기화 → 로그인 창
│   └── ui/
│       ├── login_window.py       # 로그인 창 (role 무관 허용; admin 계정도 로그인 가능하나 교사 기능만 제공)
│       ├── teacher_main_window.py# 메인 창: 3-페이지 네비게이션 + 우측 채팅 패널 + 알림 벨 아이콘
│       ├── my_timetable.py       # 내 시간표: 로그인한 교사의 주간 시간표 그리드
│       ├── class_timetable.py    # 학반별 시간표: 학반 선택 → 주간 그리드 조회
│       ├── request_widget.py     # 교체 신청: 내 시간표 슬롯 선택 + 사유 입력 → 신청 제출·목록 조회
│       ├── suggest_dialog.py     # 제안 다이얼로그: 교체/교환 대안 제시 및 변경 신청 제출
│       └── notification_panel.py # 알림 패널: 알림 목록, 동의/거절 버튼, 읽음 처리
│
├── database/                     # 하위 호환 레이어 (기존 코드의 import 경로 유지)
│   ├── models.py                 # shared/models.py 에서 전체 재수출 (ORM 모델 14개)
│   └── connection.py             # 모듈 레벨 싱글턴 엔진·세션 팩토리. init_db(url) 1회 → get_session() 반복 사용
│
├── core/
│   ├── generator.py              # Greedy + Random Restart 시간표 생성 알고리즘 (최대 30회 재시도)
│   ├── change_logger.py          # TimetableChangeLog 기록 헬퍼 함수
│   └── project_manager.py        # 프로젝트 저장(JSON export) / 불러오기(import + ID 재매핑, 14개 테이블)
│
├── ui/                           # 관리자 앱이 재사용하는 공통 PyQt6 위젯
│   ├── setup/
│   │   ├── class_setup.py        # 학년/반 CRUD 화면
│   │   ├── teacher_setup.py      # 교사 CRUD + 불가 시간 체크박스 그리드
│   │   ├── subject_setup.py      # 교과목 CRUD + 반별 시수/교사 배정 테이블 + 학기 선택
│   │   ├── room_setup.py         # 교실 CRUD (일반교실·특별실)
│   │   └── workflow_setup.py   # 결재 라인 설정 (워크플로우 CRUD + 활성화, 일과계 전용)
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
    ├── conftest.py               # pytest 공용 픽스처 (임시 파일 SQLite + TestClient + 인증 헤더)
    ├── test_feedback.py          # FeedbackDialog 단위 테스트
    ├── test_project_manager.py   # 프로젝트 저장/불러오기 단위 테스트 (16개)
    ├── test_generator.py         # 시간표 생성기 단위 테스트
    ├── test_chat.py              # 채팅 API 단위 테스트
    └── test_change_request.py    # 변경 신청·동의·제안 단위 테스트
```

---

## 7. 데이터베이스 구조 (ERD)

이 프로그램은 17개의 ORM 모델을 사용합니다(`shared/models.py` 기준). 각 모델의 관계와 역할을 이해하면 데이터가 어떻게 연결되는지 파악하기 쉽습니다.

```
AcademicTerm (학기)
  └──< SchoolEvent (학사일정, cascade)

Grade (학년)
  └──< SchoolClass (학반)
         └──< SubjectClassAssignment (주당 시수 배정)
                  ├── term_id            → AcademicTerm (학기)
                  ├── subject_id         → Subject (교과목)
                  ├── teacher_id         → Teacher (담당 교사)
                  └── preferred_room_id  → Room (선호 교실, nullable)

Teacher (교사)
  ├── homeroom_class_id → SchoolClass (담임 학반, nullable)
  ├──< TeacherConstraint (불가/선호/회피 슬롯, cascade)
  └── user              → User (1:1, 로그인 계정)

User (로그인 계정)
  ├── teacher_id → Teacher (nullable; admin 계정은 NULL)
  ├──< ChatMessage (발송한 채팅 메시지)
  └──< Notification (수신한 알림)

ChatMessage (채팅 메시지)
  └── user_id → User

Notification (알림)
  ├── user_id → User
  └── change_request_id → TimetableChangeRequest (nullable)

TimetableEntry (시간표 배정 1행 = 1수업 슬롯)
  ├── term_id          → AcademicTerm
  ├── school_class_id  → SchoolClass
  ├── subject_id       → Subject
  ├── teacher_id       → Teacher
  └── room_id          → Room (nullable)
       └──< TimetableChangeRequest (변경 신청/결재)
       └──< TimetableChangeLog    (변경 이력, 감사 로그)

ApprovalWorkflow (결재 워크플로우 정의)
  └──< ApprovalStep (cascade delete-orphan, step_order 기준 정렬)
         └── role_required → role 값 참조 (User.role 과 매칭, FK 아님)
```

**모델별 핵심 컬럼 요약**

| 모델 | 핵심 컬럼 |
|------|-----------|
| `AcademicTerm` | year, semester, start_date, end_date, is_current |
| `Grade` | grade_number |
| `SchoolClass` | grade_id, class_number, display_name |
| `Subject` | name, short_name, color |
| `Teacher` | name, max_daily_classes, homeroom_class_id |
| `SubjectClassAssignment` | term_id, school_class_id, subject_id, teacher_id, weekly_hours, preferred_room_id |
| `TimetableEntry` | term_id, school_class_id, subject_id, teacher_id, room_id, day_of_week, period |
| `TeacherConstraint` | teacher_id, day_of_week, period, constraint_type (unavailable/preferred/avoid) |
| `SchoolEvent` | term_id, title, start_date, end_date, event_type, description |
| `TimetableChangeLog` | timetable_entry_id, school_class_id, change_type, details(JSON), changed_at |
| `TimetableChangeRequest` | timetable_entry_id, requester_id, reason, status, approved_by, new_subject_id, new_teacher_id, new_room_id, swap_partner_entry_id, affected_teacher_id, consent_status, consent_by_user_id, consent_at |
| `Room` | name, room_type |
| `User` | username, password_hash, role (admin/teacher), teacher_id, is_active |
| `ChatMessage` | user_id, content, is_announcement, created_at |
| `Notification` | user_id, type, change_request_id, message, is_read, created_at |
| `ApprovalWorkflow` | name, description, is_active, created_at |
| `ApprovalStep` | workflow_id, step_order, role_required, step_name |

### FK 의존성 계층 (Tier)

테이블 간 외래키 의존성에 따라 데이터를 처리해야 하는 순서입니다. 프로젝트 불러오기(import)와 데이터 삭제 시 이 순서가 사용됩니다.

| Tier | 방향 | 테이블 | 의존 대상 |
|------|------|--------|-----------|
| 0 | 독립 | `academic_terms` | 없음 |
| 0 | 독립 | `grades` | 없음 |
| 0 | 독립 | `rooms` | 없음 |
| 0 | 독립 | `subjects` | 없음 |
| 1 | ↓ | `school_classes` | grades |
| 2 | ↓ | `teachers` | school_classes |
| 2 | ↓ | `users` | teachers (nullable) |
| 3 | ↓ | `subject_class_assignments` | academic_terms, school_classes, subjects, teachers, rooms |
| 3 | ↓ | `teacher_constraints` | teachers |
| 3 | ↓ | `timetable_entries` | academic_terms, school_classes, subjects, teachers, rooms |
| 3 | ↓ | `school_events` | academic_terms |
| 3 | ↓ | `chat_messages` | users |
| 3 | ↓ | `notifications` | users, timetable_change_requests |
| 4 | 최하위 | `timetable_change_logs` | timetable_entries, school_classes |
| 4 | 최하위 | `timetable_change_requests` | timetable_entries, subjects, teachers, rooms |
| 5 | 독립 | `approval_workflows` | 없음 |
| 5 | 하위 | `approval_steps` | approval_workflows |

- **INSERT(Import)**: Tier 0 → 4 순서로 처리 (상위 데이터가 먼저 존재해야 FK 생성 가능)
- **DELETE(초기화)**: Tier 4 → 0 순서로 처리 (하위 데이터를 먼저 삭제해야 FK 위반 방지)
- **Cascade 삭제**: Grade 삭제 → SchoolClass 삭제 → SubjectClassAssignment·TimetableEntry 삭제

---

## 8. 시간표 자동 생성 알고리즘

시간표 자동 생성은 `core/generator.py`의 `generate_timetable(session, term_id)` 함수가 담당합니다. 이 함수는 UI에서 `GenerateWorker`(QThread 서브클래스)를 통해 백그라운드로 실행됩니다.

### 알고리즘 개요: Greedy + Random Restart

이 알고리즘은 NP-hard 수준의 제약 만족 문제를 실용적인 시간 안에 풀기 위해 그리디(탐욕적) 접근과 무작위 재시작을 결합한 방식입니다.

**1단계: 수업 인스턴스 확장**

데이터베이스에서 `SubjectClassAssignment`를 읽어, 주당 시수만큼 개별 수업 인스턴스를 생성합니다. 예를 들어 "3학년 1반 수학, 주 4시간"이라는 배정이 있으면, 4개의 독립적인 수업 인스턴스가 만들어집니다. **이때 `term_id`에 해당하는 학기의 배정만 사용하므로, 다른 학기 데이터와 섞이지 않습니다.**

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

### 테스트 파일 구성 (총 37개 테스트)

**`tests/test_feedback.py`** — 피드백 다이얼로그 테스트 (8개)
- 다이얼로그 제목, 카테고리 옵션, 빈 메시지 경고, 저장 동작, 파일 누적, 손상된 파일 처리, 공백 메시지 경고

**`tests/test_project_manager.py`** — 프로젝트 저장/불러오기 테스트 (16개)
- 빈 DB export, 전체 테이블 export, 날짜/NULL 직렬화, 왕복 복원, 관계 유지, 멱등성, 비연속 ID 재매핑, 기존 데이터 대체, 롤백, 검증, Unicode 보존

**`tests/test_generator.py`** — 시간표 생성기 테스트 (4개)
- 학기별 필터링, 교사 불가 시간 준수, `max_daily_classes=1` 준수, 과배정 시 실패

**`tests/test_chat.py`** — 채팅 API 테스트 (3개)
- 메시지 작성/조회, `joinedload`에 의한 N+1 쿼리 방지, 공지 작성 권한 검증

**`tests/test_change_request.py`** — 변경 신청·동의·제안 테스트 (6개)
- 교실 변경은 동의 불필요
- 교사 변경은 동의 필요
- 동의 완료 전 관리자 승인 불가
- 피교사 동의 → 일과계 승인 → 교감 최종 승인
- 피교사 거절 시 최종 거절
- 교환 제안 및 교환 신청 동의

모든 `test_project_manager.py` 테스트는 인메모리 SQLite(`sqlite:///:memory:`)에서 실행되며 파일 입출력은 `tempfile`을 사용하여 실제 디스크 파일 동작을 검증합니다. API 테스트(`test_chat.py`, `test_change_request.py`)는 임시 파일 SQLite를 사용하며, FastAPI `TestClient`의 lifespan과 fixture가 동일한 DB를 공유하도록 구성되어 있습니다.

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
| **API 서버** | FastAPI | 0.111+ | REST API 및 WebSocket 엔드포인트 정의 |
| **ASGI 런타임** | uvicorn[standard] | 0.29+ | FastAPI 실행 서버. WebSocket 지원 포함 |
| **인증** | python-jose[cryptography] | 3.3+ | JWT 토큰 생성·서명·검증 (HS256 알고리즘) |
| **비밀번호 해싱** | bcrypt | 4.0+ | bcrypt로 비밀번호 단방향 해싱 및 검증 |
| **HTTP 클라이언트** | httpx | 0.27+ | 관리자·교사 앱에서 서버 REST API 동기 호출 |
| **WebSocket 클라이언트** | websocket-client | 1.8+ | 관리자·교사 앱에서 채팅 WebSocket 연결 |
| **데이터 검증** | Pydantic v2 | 2.0+ | API 요청/응답 스키마 정의 및 자동 검증 |
| **UI 프레임워크** | PyQt6 | 6.x | 데스크톱 GUI (QMainWindow, QDialog, QThread 등) |
| **ORM** | SQLAlchemy | 2.0+ | 데이터베이스 추상화, 모델 정의, 세션 관리 |
| **알고리즘** | Python 표준 라이브러리 | — | random.shuffle, 제약조건 검사 |
| **PDF 생성** | ReportLab | 4.x | A4 가로 PDF, 한글 TTF 폰트 등록, 테이블 스타일 |
| **Excel 생성** | OpenPyXL | 3.x | xlsx 파일 생성, 셀 서식, 시트 관리 |
| **기본 DB** | SQLite | 내장 | 개발 및 단독 운용 시 로컬 파일 데이터베이스 |
| **운영 DB** | PostgreSQL (psycopg2) | 선택적 | 운영 환경 권장. `DB_URL` 환경변수로 전환 |
| **테스트** | pytest + pytest-qt | — | GUI 단위 테스트 |
| **패키징** | PyInstaller | 6.x | 단일 실행 파일 / 설치 프로그램 생성 |

---

## 12. 장점과 한계

### 장점

이 프로그램의 가장 큰 강점은 **워크플로우 완결성**입니다. 시간표 관련 작업이 한 앱 안에서 처음부터 끝까지 처리됩니다. 기초 데이터를 입력하고, 자동으로 시간표를 생성하고, 필요한 부분을 수정하고, 결재 과정을 거쳐 확정한 뒤, PDF나 NEIS 형식으로 출력하는 일련의 과정이 앱 전환 없이 가능합니다.

두 번째 강점은 **자동화된 감사 추적**입니다. 모든 변경 이벤트가 자동으로 기록되므로 별도로 변경 내역을 관리할 필요가 없습니다. 변경 이력 페이지에서 날짜·학반·유형을 필터링하여 특정 변경 사항을 신속하게 찾을 수 있습니다.

세 번째 강점은 **UI 응답성**입니다. 시간표 자동 생성은 연산 부하가 큰 작업이지만, QThread를 사용하여 백그라운드에서 실행하기 때문에 생성 중에도 앱이 멈추거나 응답 없음 상태가 되지 않습니다.

네 번째 강점은 **피교사 동의 및 알림 시스템**입니다. 교사 간 수업 교체가 필요할 때 별도 메신저를 거치지 않고 시스템 내에서 동의를 받고, 그 과정이 DB에 남아 추적 가능합니다. 실시간 알림과 영속성을 모두 지원하여 오프라인이었던 교사도 재접속 시 놓친 소식을 확인할 수 있습니다.

### 한계

**동시 편집 충돌**이 주요 한계입니다. 두 관리자가 동시에 같은 시간표 슬롯을 수정할 경우 충돌 감지나 잠금 메커낌없이 마지막 저장이 덮어씁니다. 복수의 교무 담당자가 동시에 편집해야 하는 환경에서는 주의가 필요합니다.

**DB 스키마 마이그레이션 미지원**도 알려진 한계입니다. 서버는 `create_all()`로 테이블을 최초 생성하지만, 기존에 운영 중인 DB에 새 컬럼이나 테이블이 추가된 경우 자동으로 반영되지 않습니다. 다만 `SubjectClassAssignment.term_id` 같은 신규 컬럼은 서버 시작 시 `_ensure_assignment_terms()`를 통해 NULL 값을 현재/첫 학기로 백필하므로, 운영 중인 DB에서도 비교적 안전하게 마이그레이션됩니다. 그러나 그 외의 스키마 변경 시에는 Alembic 같은 마이그레이션 도구를 별도로 사용해야 합니다.

**교사 선호/회피 제약조건 미반영**도 개선이 필요한 부분입니다. `TeacherConstraint` 모델에는 `preferred`(선호)와 `avoid`(회피) 타입이 정의되어 있지만, 자동 생성 알고리즘은 현재 `unavailable`(불가) 타입만 참조합니다.

**채팅 메시지 자동 정리**도 지원합니다. 오래된 메시지는 `CHAT_RETENTION_DAYS`(기본 60일) 기준으로 서버가 12시간 간격으로 자동 삭제하며, 일과계 선생님은 필요시 수동으로 일괄 정리하거나 개별 메시지를 삭제할 수 있습니다. WebSocket 브로드캐스트로 모든 접속자의 UI 가 실시간 갱신됩니다.

---

## 13. 코드 품질 개선 이력 (2026-06-13)

코드 리뷰를 통해 발견된 문제를 우선순위 순서로 개선했습니다.

### 🔴 높음 — 즉시 수정

#### 1. N+1 쿼리 문제 해소 (`server/api/timetable.py`)

**문제**: `list_entries` (시간표 조회)와 `_build_suggestions` (대체 제안) 함수에서 시간표 항목이 N개일 때 교사·과목·교실을 가져오기 위해 최대 3N+α번 추가 SELECT 쿼리가 발생했습니다. 이를 **N+1 쿼리 문제**라 합니다.

**원인**: `for` 루프 안에서 `db.get(Subject, id)` / `db.get(Teacher, id)` / `db.get(Room, id)`를 반복 호출하면, SQLAlchemy가 매 호출마다 개별 SELECT를 실행합니다.

**해결 방법**: SQLAlchemy의 `joinedload()` 옵션을 사용합니다. 이 옵션을 지정하면 첫 번째 쿼리에 `LEFT OUTER JOIN`을 추가하여 연관 테이블의 데이터를 한 번에 가져옵니다.

```python
# 개선 전 (N+1 문제)
entries = q.all()   # SELECT * FROM timetable_entries
for e in entries:
    subj = db.get(Subject, e.subject_id)   # +1 query 반복
    tchr = db.get(Teacher, e.teacher_id)   # +1 query 반복
    room = db.get(Room, e.room_id)         # +1 query 반복

# 개선 후 (1+0 쿼리)
entries = q.options(
    joinedload(TimetableEntry.subject),    # JOIN subjects
    joinedload(TimetableEntry.teacher),    # JOIN teachers
    joinedload(TimetableEntry.room),       # JOIN rooms (LEFT OUTER)
).all()   # SELECT ... FROM timetable_entries JOIN subjects JOIN teachers LEFT JOIN rooms
for e in entries:
    e.subject.name   # 이미 메모리에 있음 — 추가 쿼리 없음
    e.teacher.name   # 이미 메모리에 있음 — 추가 쿼리 없음
    e.room.name      # 이미 메모리에 있음 — 추가 쿼리 없음
```

`_build_suggestions`는 추가로 마스터 데이터(전체 교사·과목·교실)를 `dict`로 미리 로드하고, 교환(swap) 제안 루프에서 `_build_conflict_maps_from_list()`(DB 접근 없는 메모리 연산)를 사용하도록 개선했습니다. 이를 통해 기존 O(N²) DB 쿼리가 O(N²) 인-메모리 연산으로 대체되었습니다.

#### 2. 교환(swap) 신청 타이밍 충돌(Race Condition) 감지 (`shared/models.py`, `server/api/timetable.py`)

**문제**: 교환 신청(swap)은 두 슬롯 A와 B의 교사를 서로 맞바꾸는 작업입니다. 결재 기간이 길어지는 경우(예: 며칠 뒤 최종 승인), 그 사이에 다른 변경 신청이 슬롯 B를 수정했을 수 있습니다. 이 상태에서 교환을 적용하면 의도하지 않은 데이터로 시간표가 덮어써집니다.

**해결 방법**:
1. `TimetableChangeRequest` 모델에 `change_snapshot` (TEXT, nullable) 컬럼 추가
2. 변경 신청 접수 시(`submit_request`) 대상 슬롯과 상대 슬롯의 현재 상태를 JSON으로 저장
3. 최종 승인 시(`_apply_request_changes`) 스냅샷과 현재 DB 상태를 비교
4. 불일치하면 `409 Conflict`를 반환하고 적용 중단

```python
# 신청 시 스냅샷 저장
change_snapshot = json.dumps({
    "entry":   {"subject_id": 1, "teacher_id": 2, "room_id": 3},
    "partner": {"subject_id": 4, "teacher_id": 5, "room_id": 6},
})

# 승인 시 비교
if current_partner_state != partner_snap:
    raise HTTPException(409, "교환 상대 슬롯이 결재 기간 중 수정되었습니다.")
```

`change_snapshot` 컬럼은 서버 시작 시 `ALTER TABLE ... ADD COLUMN`으로 자동 추가되며, 기존 레코드의 `NULL` 값은 건너뜁니다(하위 호환성 유지).

#### 3. `_apply_request_changes` 조용한 실패에 로그 추가 (`server/api/timetable.py`)

**문제**: 최종 승인 처리 중 시간표 항목이 삭제된 경우, 기존 코드는 `if entry is None: return`으로 조용히 종료하여 원인을 추적할 방법이 없었습니다.

**해결 방법**: `logging.getLogger(__name__)`로 모듈 수준 로거를 생성하고, `None` 체크 후 `_logger.error(...)`로 에러 정보를 기록합니다. `swap` 상대 슬롯이 없을 때도 동일하게 처리합니다.

---

### 🟡 중간 — 보안/안정성 개선

#### 4. JWT_SECRET_KEY 미설정 시 운영 환경에서 서버 시작 거부 (`server/auth_utils.py`)

**문제**: `JWT_SECRET_KEY` 미설정 시 임시 uuid4 키를 자동 생성했습니다. 운영 환경에서 서버가 재시작될 때마다 새로운 키가 생성되어 모든 로그인 토큰이 즉시 무효화되는 문제가 있었습니다.

**해결 방법**: `APP_ENV` 환경 변수로 실행 환경을 구분합니다.
- `APP_ENV=production` + `JWT_SECRET_KEY` 미설정 → `RuntimeError`로 서버 시작 거부
- `APP_ENV=development` (기본) → 기존과 동일하게 임시 키 생성, 단 경고 메시지를 더 눈에 띄게 출력

```bash
# 올바른 운영 환경 설정
export JWT_SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
export APP_ENV=production
```

#### 5. Rate Limiter 스레드 안전성 확보 (`server/api/auth.py`)

**문제**: FastAPI는 동기 엔드포인트를 스레드 풀에서 실행합니다. 여러 요청이 동시에 `_failed_attempts` dict를 읽고 쓰면 race condition으로 실패 횟수가 누락될 수 있었습니다.

**해결 방법**: `threading.Lock()`을 추가하여 dict 접근을 직렬화합니다. 단, bcrypt 해시 비교(~100ms)는 Lock 밖에서 수행하여 다른 사용자의 로그인을 차단하지 않도록 했습니다.

```python
_lock = threading.Lock()

def login(...):
    with _lock:
        # dict 읽기/쓰기 (빠름)
        recent = [t for t in _failed_attempts.get(username, []) if t > cutoff]
        _failed_attempts[username] = recent
        too_many = len(recent) >= _MAX_FAILED

    # bcrypt 비교 (느림, Lock 밖)
    if not verify_password(body.password, user.password_hash):
        with _lock:
            _failed_attempts[username].append(now_ts)
```

> ⚠️ **한계**: `uvicorn --workers N` (N > 1) 멀티 프로세스 환경에서는 프로세스별로 dict를 따로 관리하여 차단 효과가 감소합니다. 복수 워커를 사용하는 운영 환경에서는 Redis 기반 분산 rate limiting 도입을 권장합니다.

---

### 🟢 낮음 — 사용성 개선

#### 6. 초기 비밀번호 출력 가시성 개선 (`server/main.py`)

비밀번호가 자동 생성될 때 출력되는 메시지에 `=` 구분선을 추가하여 로그에서 쉽게 찾을 수 있도록 개선했습니다. CI/CD 파이프라인이나 로그 집계 시스템 사용 시 로그 노출에 주의하라는 경고도 추가했습니다.

#### 7. `_migrate_add_change_snapshot()` 자동 마이그레이션 (`server/main.py`)

`change_snapshot` 컬럼이 추가되기 전에 생성된 SQLite/PostgreSQL DB에 자동으로 컬럼을 추가합니다. 서버 시작 시 `ALTER TABLE ... ADD COLUMN`을 시도하고, 이미 컬럼이 있는 경우(`OperationalError`)는 무시합니다(멱등성 보장).

---

### 알려진 미반영 항목

| 항목 | 이유 |
|------|------|
| `SubjectClassAssignment.term_id` NOT NULL 제약 | SQLite에서 `ALTER TABLE ... ALTER COLUMN`이 미지원. 애플리케이션 레벨에서 강제 |
| WebSocket 멀티 서버 지원 | Redis Pub/Sub 도입이 필요한 큰 아키텍처 변경. 단일 서버 환경에서는 무관 |
| DEPRECATED 컬럼 제거 | 기존 운영 DB와의 호환성 유지 필요. 다음 메이저 버전에서 Alembic 마이그레이션과 함께 제거 예정 |

---

## 라이선스

이 프로젝트는 MIT 라이선스를 따릅니다. 자유롭게 사용·수정·배포하실 수 있습니다.

---

## 문의 및 기여

버그 신고, 기능 제안, 기여는 앱 내 "피드백 보내기" 메뉴 또는 GitHub Issues를 통해 부탁드립니다.
