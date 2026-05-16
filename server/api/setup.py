"""
편제·교과목·교실 관리 API (관리자 전용)

GET/POST/DELETE /setup/grades
GET/POST/DELETE /setup/classes
GET/POST/DELETE /setup/subjects
GET/POST/DELETE /setup/rooms
GET/POST/DELETE /setup/teachers
GET/POST/DELETE /setup/teachers/{id}/constraints
GET/POST/DELETE /setup/assignments
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from shared.models import (
    Grade, SchoolClass, Subject, Room, Teacher,
    TeacherConstraint, SubjectClassAssignment, User,
)
from shared.schemas import (
    GradeOut, GradeCreate,
    SchoolClassOut, SchoolClassCreate,
    SubjectOut, SubjectCreate,
    RoomOut, RoomCreate,
    TeacherOut, TeacherCreate, TeacherUpdate,
    TeacherConstraintOut, TeacherConstraintCreate,
    AssignmentOut, AssignmentCreate,
)
from server.deps import get_db, require_scheduler, require_admin_or_vice_principal

router = APIRouter(prefix="/setup", tags=["편제·교과·교사 관리"])


# ── 학년 ───────────────────────────────────────────────────────────────────

@router.get("/grades", response_model=list[GradeOut])
def list_grades(db: Session = Depends(get_db), _: User = Depends(require_admin_or_vice_principal)):
    return db.query(Grade).order_by(Grade.grade_number).all()


@router.post("/grades", response_model=GradeOut, status_code=201)
def create_grade(body: GradeCreate, db: Session = Depends(get_db), _: User = Depends(require_scheduler)):
    grade = Grade(grade_number=body.grade_number, name=body.name)
    db.add(grade)
    db.commit()
    db.refresh(grade)
    return grade


@router.delete("/grades/{grade_id}")
def delete_grade(grade_id: int, db: Session = Depends(get_db), _: User = Depends(require_scheduler)):
    grade = db.get(Grade, grade_id)
    if grade is None:
        raise HTTPException(404, "학년을 찾을 수 없습니다.")
    db.delete(grade)
    db.commit()
    return {"ok": True}


# ── 반 ─────────────────────────────────────────────────────────────────────

@router.get("/classes", response_model=list[SchoolClassOut])
def list_classes(db: Session = Depends(get_db), _: User = Depends(require_admin_or_vice_principal)):
    return db.query(SchoolClass).order_by(SchoolClass.grade_id, SchoolClass.class_number).all()


@router.post("/classes", response_model=SchoolClassOut, status_code=201)
def create_class(body: SchoolClassCreate, db: Session = Depends(get_db), _: User = Depends(require_scheduler)):
    sc = SchoolClass(
        grade_id=body.grade_id,
        class_number=body.class_number,
        display_name=body.display_name,
        homeroom_room_id=body.homeroom_room_id,
    )
    db.add(sc)
    db.commit()
    db.refresh(sc)
    return sc


@router.delete("/classes/{class_id}")
def delete_class(class_id: int, db: Session = Depends(get_db), _: User = Depends(require_scheduler)):
    sc = db.get(SchoolClass, class_id)
    if sc is None:
        raise HTTPException(404, "반을 찾을 수 없습니다.")
    db.delete(sc)
    db.commit()
    return {"ok": True}


# ── 교과목 ─────────────────────────────────────────────────────────────────

@router.get("/subjects", response_model=list[SubjectOut])
def list_subjects(db: Session = Depends(get_db), _: User = Depends(require_admin_or_vice_principal)):
    return db.query(Subject).order_by(Subject.name).all()


@router.post("/subjects", response_model=SubjectOut, status_code=201)
def create_subject(body: SubjectCreate, db: Session = Depends(get_db), _: User = Depends(require_scheduler)):
    subj = Subject(
        name=body.name,
        short_name=body.short_name,
        color_hex=body.color_hex,
        needs_special_room=body.needs_special_room,
    )
    db.add(subj)
    db.commit()
    db.refresh(subj)
    return subj


@router.delete("/subjects/{subject_id}")
def delete_subject(subject_id: int, db: Session = Depends(get_db), _: User = Depends(require_scheduler)):
    subj = db.get(Subject, subject_id)
    if subj is None:
        raise HTTPException(404, "교과목을 찾을 수 없습니다.")
    db.delete(subj)
    db.commit()
    return {"ok": True}


# ── 교실 ───────────────────────────────────────────────────────────────────

@router.get("/rooms", response_model=list[RoomOut])
def list_rooms(db: Session = Depends(get_db), _: User = Depends(require_admin_or_vice_principal)):
    return db.query(Room).order_by(Room.name).all()


@router.post("/rooms", response_model=RoomOut, status_code=201)
def create_room(body: RoomCreate, db: Session = Depends(get_db), _: User = Depends(require_scheduler)):
    room = Room(
        name=body.name, room_type=body.room_type,
        capacity=body.capacity, floor=body.floor, notes=body.notes,
    )
    db.add(room)
    db.commit()
    db.refresh(room)
    return room


@router.delete("/rooms/{room_id}")
def delete_room(room_id: int, db: Session = Depends(get_db), _: User = Depends(require_scheduler)):
    room = db.get(Room, room_id)
    if room is None:
        raise HTTPException(404, "교실을 찾을 수 없습니다.")
    db.delete(room)
    db.commit()
    return {"ok": True}


# ── 교사 ───────────────────────────────────────────────────────────────────

@router.get("/teachers", response_model=list[TeacherOut])
def list_teachers(db: Session = Depends(get_db), _: User = Depends(require_admin_or_vice_principal)):
    return db.query(Teacher).order_by(Teacher.name).all()


@router.post("/teachers", response_model=TeacherOut, status_code=201)
def create_teacher(body: TeacherCreate, db: Session = Depends(get_db), _: User = Depends(require_scheduler)):
    teacher = Teacher(
        name=body.name,
        employee_number=body.employee_number,
        is_homeroom=body.is_homeroom,
        homeroom_class_id=body.homeroom_class_id,
        max_daily_classes=body.max_daily_classes,
    )
    db.add(teacher)
    db.commit()
    db.refresh(teacher)
    return teacher


@router.patch("/teachers/{teacher_id}", response_model=TeacherOut)
def update_teacher(
    teacher_id: int, body: TeacherUpdate,
    db: Session = Depends(get_db), _: User = Depends(require_scheduler),
):
    teacher = db.get(Teacher, teacher_id)
    if teacher is None:
        raise HTTPException(404, "교사를 찾을 수 없습니다.")
    for field, val in body.model_dump(exclude_none=True).items():
        setattr(teacher, field, val)
    db.commit()
    db.refresh(teacher)
    return teacher


@router.delete("/teachers/{teacher_id}")
def delete_teacher(teacher_id: int, db: Session = Depends(get_db), _: User = Depends(require_scheduler)):
    teacher = db.get(Teacher, teacher_id)
    if teacher is None:
        raise HTTPException(404, "교사를 찾을 수 없습니다.")
    db.delete(teacher)
    db.commit()
    return {"ok": True}


# ── 교사 불가시간 제약 ──────────────────────────────────────────────────────

@router.get("/teachers/{teacher_id}/constraints", response_model=list[TeacherConstraintOut])
def list_constraints(teacher_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin_or_vice_principal)):
    return db.query(TeacherConstraint).filter_by(teacher_id=teacher_id).all()


@router.post("/teachers/{teacher_id}/constraints", response_model=TeacherConstraintOut, status_code=201)
def add_constraint(
    teacher_id: int, body: TeacherConstraintCreate,
    db: Session = Depends(get_db), _: User = Depends(require_scheduler),
):
    c = TeacherConstraint(
        teacher_id=teacher_id,
        day_of_week=body.day_of_week,
        period=body.period,
        constraint_type=body.constraint_type,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


@router.delete("/teachers/{teacher_id}/constraints")
def clear_constraints(teacher_id: int, db: Session = Depends(get_db), _: User = Depends(require_scheduler)):
    """해당 교사의 모든 제약을 삭제합니다. (저장 전 전체 교체 방식)"""
    db.query(TeacherConstraint).filter_by(teacher_id=teacher_id).delete()
    db.commit()
    return {"ok": True}


# ── 시수 배정 ──────────────────────────────────────────────────────────────

@router.get("/assignments", response_model=list[AssignmentOut])
def list_assignments(db: Session = Depends(get_db), _: User = Depends(require_admin_or_vice_principal)):
    return db.query(SubjectClassAssignment).all()


@router.post("/assignments", response_model=AssignmentOut, status_code=201)
def create_or_update_assignment(
    body: AssignmentCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_scheduler),
):
    """같은 (반, 교과, 교사) 조합이 있으면 시수만 업데이트합니다."""
    existing = db.query(SubjectClassAssignment).filter_by(
        school_class_id=body.school_class_id,
        subject_id=body.subject_id,
        teacher_id=body.teacher_id,
    ).first()
    if existing:
        existing.weekly_hours = body.weekly_hours
        existing.preferred_room_id = body.preferred_room_id
        db.commit()
        db.refresh(existing)
        return existing
    a = SubjectClassAssignment(
        school_class_id=body.school_class_id,
        subject_id=body.subject_id,
        teacher_id=body.teacher_id,
        weekly_hours=body.weekly_hours,
        preferred_room_id=body.preferred_room_id,
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


@router.delete("/assignments/{assignment_id}")
def delete_assignment(assignment_id: int, db: Session = Depends(get_db), _: User = Depends(require_scheduler)):
    a = db.get(SubjectClassAssignment, assignment_id)
    if a is None:
        raise HTTPException(404, "배정 정보를 찾을 수 없습니다.")
    db.delete(a)
    db.commit()
    return {"ok": True}
