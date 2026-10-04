"""
하위 호환성 유지용 재수출 모듈.

모든 ORM 모델은 shared/models.py 에서 관리됩니다.
기존 코드(core/, ui/)가 from database.models import ... 로 임포트하는 경우를
수정 없이 계속 동작하도록 모든 심볼을 그대로 재수출합니다.
"""
from shared.models import (  # noqa: F401
    Base,
    AcademicTerm,
    Room,
    Grade,
    SchoolClass,
    Subject,
    Teacher,
    SubjectClassAssignment,
    TimetableEntry,
    TeacherConstraint,
    SchoolEvent,
    TimetableChangeLog,
    TimetableChangeRequest,
    User,
    ChatMessage,
    Notification,
    ApprovalWorkflow,
    ApprovalStep,
    ChangeRequestStep,  # 2026-06-20 추가: 연쇄 교체 단계 모델
    Exam,               # 2026-09-19 추가: 시험 시간표 + 감독 시간표 지원
    ExamPeriod,
    ExamEntry,
    InvigilationAssignment,
    InvigilationConstraint,
    ExamRoom,                # 2026-10-04 추가: 혼합 시험실(선택과목 등)
    ExamRoomStudent,         # 2026-10-04 추가: 혼합 시험실 수강 학생 명단(선택)
    CorridorDutyAssignment,  # 2026-10-04 추가: 복도감독
    ExamGradeDateExclusion,  # 2026-10-04 추가: 학년별 시험 미참여 날짜
)
