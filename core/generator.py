"""
시간표 자동 생성 알고리즘 — Greedy + Random Restart

입력 데이터 (이 생성기가 의존하는 선행 데이터):
  - SubjectClassAssignment: SubjectSetupWidget 에서 배정된 학반-교과-교사-시수
  - TeacherConstraint (unavailable / preferred / avoid):
      unavailable — TeacherSetupWidget 에서 설정된 교사 불가 시간 (하드 제약)
      preferred   — 교사가 선호하는 슬롯 (소프트 가산점)
      avoid       — 교사가 회피하는 슬롯 (소프트 감점, 가능하면 배제)
  - Teacher.max_daily_classes: TeacherSetupWidget 에서 설정된 교사 일 최대 수업 수
  → 이 데이터들이 모두 입력된 상태에서 GenerateDialog → GenerateWorker 를 통해 실행됩니다.

알고리즘 개요:
  1. SubjectClassAssignment 에서 '수업 인스턴스(lesson)' 목록을 생성합니다.
     예) 수학 주당 3시간 → 동일 lesson 딕셔너리 3개 생성
  2. 월~금, 1~max_periods 의 모든 슬롯을 랜덤하게 섞습니다.
  3. 각 수업 인스턴스를 하나씩 꺼내 하드 제약을 통과하는 슬롯들 중
     '선호/회피 점수'가 가장 높은 슬롯에 배치합니다 (그리디 + 점수 기반).
  4. 어떤 수업 인스턴스도 배치 불가하면 해당 시도를 실패로 처리하고
     처음부터 다시 시도합니다 (랜덤 재시작, 최대 30회).
  5. max_retries 이내에 성공하면 기존 시간표를 삭제(TimetableChangeLog 기록 포함)하고
     새 시간표를 저장합니다.

하드 제약 (위반 시 해당 슬롯 건너뜀):
  - 같은 반이 같은 슬롯에 두 수업을 가질 수 없음 (class_conflict)
  - 같은 교사가 같은 슬롯에 두 수업을 가질 수 없음 (teacher_conflict)
  - 같은 교실이 같은 슬롯에 두 수업에 쓰일 수 없음 (room_conflict)
  - 교사가 '불가' 로 설정한 슬롯에는 배치하지 않음 (teacher_unavailable)
  - 교사의 일 최대 수업 수(max_daily_classes) 초과 불가 (teacher_daily_max)

소프트 제약 (점수 기반 슬롯 선택):
  - preferred 슬롯: +2 가산점 (가능하면 선호 슬롯에 배치)
  - avoid 슬롯: -1 감점 (가능하면 회피, 다른 슬롯이 없으면 배치 허용)
  - 일반 슬롯: 0 점
  - 하드 제약을 통과한 슬롯들 중 최고 점수 슬롯을 선택 (동점은 셔플 순서 우선)

제약 체크는 _try_generate() 내부에서 set 기반 O(1) 조회로 수행되므로
수백 개 수업 인스턴스도 수 초 내에 처리 가능합니다.

알고리즘 한계:
  - 시수 합계가 전체 슬롯 수를 초과하거나 교사 제약이 너무 많으면
    max_retries 이후 실패 메시지를 반환합니다.
  - 교사별 공평한 시간 분배, 특정 과목의 오전/오후 선호 등
  - preferred_room_id 가 설정된 경우 해당 교실로만 배정을 시도하며,
    대체 교실을 자동으로 찾지 않습니다.
"""
import random
from typing import Optional
from sqlalchemy.orm import Session
from database.models import (
    SubjectClassAssignment, TimetableEntry, TeacherConstraint, AcademicTerm,
)

# 요일 목록 (1=월요일 … 5=금요일)
DAYS = [1, 2, 3, 4, 5]
# 기본 최대 교시 수 (GenerateDialog 에서 4~9 사이로 조정 가능)
MAX_PERIODS = 7

# 소프트 제약 점수 가중치
PREFERRED_BONUS = 2   # 선호 슬롯 가산점
AVOID_PENALTY  = -1   # 회피 슬롯 감점 (절대값보다 작게 — 배치 불가 상태는 아님)


def generate_timetable(
    session: Session,
    term_id: int,
    max_periods: int = MAX_PERIODS,
    max_retries: int = 30,
) -> tuple[bool, str]:
    """
    주어진 학기(term_id)의 시간표를 생성합니다.

    Args:
        session    : 열린 SQLAlchemy 세션
        term_id    : 시간표를 생성할 학기 ID
        max_periods: 하루 최대 교시 수 (기본 7)
        max_retries: 랜덤 재시작 최대 횟수 (기본 30)

    Returns:
        (True, 성공 메시지) 또는 (False, 실패 메시지)
    """
    # ── 입력 데이터 수집 ────────────────────────────────────────────────

    # 2026-06-13 변경: 해당 학기(term_id)의 시수 배정만 사용하도록 필터링.
    # 그렇지 않으면 1학기/2학기 데이터가 섞여 잘못된 시간표가 생성됩니다.
    assignments = session.query(SubjectClassAssignment).filter_by(term_id=term_id).all()
    if not assignments:
        return False, "해당 학기에 배정된 교과/시수 정보가 없습니다."

    # 교사별 제약 슬롯을 set 으로 미리 수집합니다.
    # 딕셔너리 키: teacher_id, 값: {(day, period), ...}
    # 2026-06-20: preferred/avoid 도 함께 조회하여 소프트 제약으로 반영합니다.
    unavailable: dict[int, set] = {}
    preferred:   dict[int, set] = {}
    avoid:       dict[int, set] = {}
    for c in session.query(TeacherConstraint).all():
        target = {
            "unavailable": unavailable,
            "preferred":   preferred,
            "avoid":       avoid,
        }.get(c.constraint_type)
        if target is None:
            continue  # 알 수 없는 constraint_type 은 무시
        target.setdefault(c.teacher_id, set()).add((c.day_of_week, c.period))

    # 교사별 일 최대 수업 수를 미리 수집합니다.
    # 2026-06-13 변경: max_daily_classes 가 1 미만이면 안전하게 기본값 5를 사용.
    # (스키마/서버에서 이미 1 이상을 강제하지만, 방어 코드로 남겨둡니다.)
    from database.models import Teacher
    teacher_max: dict[int, int] = {
        t.id: max(t.max_daily_classes, 1)
        for t in session.query(Teacher).all()
    }

    # ── Greedy + Random Restart ─────────────────────────────────────────
    for attempt in range(max_retries):
        result = _try_generate(
            assignments, unavailable, preferred, avoid, teacher_max, max_periods,
        )

        if result is not None:
            # 성공: 기존 시간표를 삭제하고 새 시간표를 저장합니다.
            from core.change_logger import log_entry_create, log_entry_delete

            # 기존 시간표 항목 삭제 (이력 로그도 기록)
            # 이미 ORM 객체를 순회하므로 session.delete()를 사용해 세션 상태를 일관되게 유지합니다.
            old_entries = session.query(TimetableEntry).filter_by(term_id=term_id).all()
            for old_entry in old_entries:
                log_entry_delete(session, old_entry)
                session.delete(old_entry)

            # 새 시간표 항목 삽입
            new_entries = []
            for r in result:
                entry = TimetableEntry(
                    term_id=term_id,
                    school_class_id=r["class_id"],
                    subject_id=r["subject_id"],
                    teacher_id=r["teacher_id"],
                    room_id=r.get("room_id"),
                    day_of_week=r["day"],
                    period=r["period"],
                )
                session.add(entry)
                new_entries.append(entry)

            # flush 로 DB 에 INSERT 해 PK(id)를 확보한 뒤 생성 로그를 기록합니다.
            session.flush()
            for entry in new_entries:
                log_entry_create(session, entry)

            session.commit()
            return True, f"시간표 생성 완료 (시도 {attempt + 1}회)"

    # max_retries 모두 소진
    return False, (
        f"{max_retries}회 시도 후 시간표 생성에 실패했습니다.\n"
        "시수 합계나 교사 배정, 불가 시간 설정을 확인해 주세요."
    )


def _try_generate(
    assignments: list,
    unavailable: dict[int, set],
    preferred: dict[int, set],
    avoid: dict[int, set],
    teacher_max: dict[int, int],
    max_periods: int,
) -> Optional[list[dict]]:
    """
    한 번의 그리디 시도를 실행합니다.

    수업 인스턴스 목록과 슬롯 목록을 모두 랜덤하게 섞은 뒤,
    각 수업에 대해 하드 제약을 통과하는 슬롯들 중 소프트 점수가 가장 높은
    슬롯을 선택해 배치합니다.

    소프트 점수:
      preferred 슬롯: +2
      avoid 슬롯: -1
      일반 슬롯: 0
      (동점은 셔플 순서가 빠른 슬롯이 우선 — random.shuffle 로 무작위화)

    하드 제약을 통과한 슬롯이 하나도 없으면 이번 시도를 실패(None)로 처리합니다.
    avoid 슬롯밖에 남지 않아도 점수가 -1 이라도 배치는 가능(soft)합니다.

    Returns:
        배치 결과 딕셔너리 리스트 또는 None (배치 실패)
    """
    # ── 수업 인스턴스 목록 생성 ─────────────────────────────────────────
    # SubjectClassAssignment.weekly_hours 만큼 동일한 수업을 반복 생성합니다.
    # 예) 1-1반 수학 3시간 → 동일 딕셔너리 3개
    lessons = []
    for a in assignments:
        for _ in range(a.weekly_hours):
            lessons.append({
                "class_id":   a.school_class_id,
                "subject_id": a.subject_id,
                "teacher_id": a.teacher_id,
                "room_id":    a.preferred_room_id,  # None 이면 교실 제약 없음
            })
    random.shuffle(lessons)  # 배치 순서를 무작위화해 재시도마다 다른 결과를 얻습니다.

    # ── 슬롯 목록 생성 ─────────────────────────────────────────────────
    # (요일, 교시) 쌍의 전체 목록. 수업마다 이 목록을 다시 섞어 사용합니다.
    all_slots = [(d, p) for d in DAYS for p in range(1, max_periods + 1)]

    # ── 배치 상태 추적 딕셔너리 ─────────────────────────────────────────
    class_slots: dict[int, set]       = {}   # {class_id: {(day, period), ...}}
    teacher_slots: dict[int, set]     = {}   # {teacher_id: {(day, period), ...}}
    teacher_daily: dict[tuple, int]   = {}   # {(teacher_id, day): count}
    room_slots: dict[int, set]        = {}   # {room_id: {(day, period), ...}}

    placed = []  # 배치 성공한 수업 결과 목록

    pref_set_by_tid = preferred
    avoid_set_by_tid = avoid

    for lesson in lessons:
        cid = lesson["class_id"]
        tid = lesson["teacher_id"]
        rid = lesson.get("room_id")

        random.shuffle(all_slots)  # 이 수업에 대해 슬롯 순서를 다시 무작위화합니다.

        best_slot = None
        best_score = None

        for day, period in all_slots:
            slot = (day, period)

            # ── 하드 제약 검사 ────────────────────────────────────────
            # 1) 같은 반이 이미 이 슬롯에 수업이 있으면 건너뜁니다.
            if slot in class_slots.get(cid, set()):
                continue
            # 2) 같은 교사가 이미 이 슬롯에 다른 수업을 갖고 있으면 건너뜁니다.
            if slot in teacher_slots.get(tid, set()):
                continue
            # 3) 같은 교실이 이미 이 슬롯에 사용 중이면 건너뜁니다.
            if rid and slot in room_slots.get(rid, set()):
                continue
            # 4) 교사가 불가로 설정한 슬롯이면 건너뜁니다.
            if slot in unavailable.get(tid, set()):
                continue
            # 5) 교사의 하루 최대 수업 수를 초과하면 건너뜁니다.
            daily_key = (tid, day)
            if teacher_daily.get(daily_key, 0) >= teacher_max.get(tid, 5):
                continue

            # ── 소프트 제약 점수 계산 ─────────────────────────────────
            score = 0
            if slot in pref_set_by_tid.get(tid, set()):
                score += PREFERRED_BONUS
            if slot in avoid_set_by_tid.get(tid, set()):
                score += AVOID_PENALTY

            # ── 최고 점수 슬롯 갱신 ───────────────────────────────────
            # 동점이면 셔플 순서가 빠른 슬롯(이미 순회상 먼저 나온 슬롯)을 유지.
            if best_score is None or score > best_score:
                best_score = score
                best_slot = slot
                # preferred + avoid 없음(점수 +2)이면 더 이상 탐색할 필요 없음.
                if score >= PREFERRED_BONUS:
                    break

        if best_slot is None:
            # 이 수업에 하드 제약을 통과한 슬롯이 하나도 없음 → 이번 시도 실패
            return None

        day, period = best_slot
        class_slots.setdefault(cid, set()).add(best_slot)
        teacher_slots.setdefault(tid, set()).add(best_slot)
        if rid:
            room_slots.setdefault(rid, set()).add(best_slot)
        teacher_daily[(tid, day)] = teacher_daily.get((tid, day), 0) + 1

        placed.append({**lesson, "day": day, "period": period})

    return placed