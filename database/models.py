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
)
