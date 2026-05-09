from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Boolean, ForeignKey,
    Date, DateTime, Text, CheckConstraint, func
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class AcademicTerm(Base):
    __tablename__ = "academic_terms"

    id = Column(Integer, primary_key=True)
    year = Column(Integer, nullable=False)
    semester = Column(Integer, nullable=False)   # 1 or 2
    start_date = Column(Date)
    end_date = Column(Date)
    is_current = Column(Boolean, default=False)

    timetable_entries = relationship("TimetableEntry", back_populates="term", cascade="all, delete-orphan")
    school_events = relationship("SchoolEvent", back_populates="term", cascade="all, delete-orphan")

    def __str__(self):
        return f"{self.year}년 {self.semester}학기"


class Room(Base):
    __tablename__ = "rooms"

    id = Column(Integer, primary_key=True)
    name = Column(String(50), nullable=False)
    room_type = Column(String(20), default="일반")  # 일반 / 특별
    capacity = Column(Integer, default=30)
    floor = Column(Integer, default=1)
    notes = Column(Text, default="")

    def __str__(self):
        return self.name


class Grade(Base):
    __tablename__ = "grades"

    id = Column(Integer, primary_key=True)
    grade_number = Column(Integer, nullable=False)   # 1, 2, 3
    name = Column(String(20), nullable=False)         # "1학년"

    classes = relationship("SchoolClass", back_populates="grade", cascade="all, delete-orphan")

    def __str__(self):
        return self.name


class SchoolClass(Base):
    __tablename__ = "school_classes"

    id = Column(Integer, primary_key=True)
    grade_id = Column(Integer, ForeignKey("grades.id"), nullable=False)
    class_number = Column(Integer, nullable=False)   # 1, 2, 3 …
    display_name = Column(String(20), nullable=False)  # "1-1"
    homeroom_room_id = Column(Integer, ForeignKey("rooms.id"), nullable=True)

    grade = relationship("Grade", back_populates="classes")
    homeroom_room = relationship("Room")
    subject_assignments = relationship("SubjectClassAssignment", back_populates="school_class", cascade="all, delete-orphan")
    timetable_entries = relationship("TimetableEntry", back_populates="school_class", cascade="all, delete-orphan")

    def __str__(self):
        return self.display_name


class Subject(Base):
    __tablename__ = "subjects"

    id = Column(Integer, primary_key=True)
    name = Column(String(50), nullable=False)
    short_name = Column(String(20), nullable=False)
    color_hex = Column(String(7), default="#E3F2FD")  # pastel default
    needs_special_room = Column(Boolean, default=False)

    assignments = relationship("SubjectClassAssignment", back_populates="subject")

    def __str__(self):
        return self.name


class Teacher(Base):
    __tablename__ = "teachers"

    id = Column(Integer, primary_key=True)
    name = Column(String(30), nullable=False)
    employee_number = Column(String(20), default="")
    is_homeroom = Column(Boolean, default=False)
    homeroom_class_id = Column(Integer, ForeignKey("school_classes.id"), nullable=True)
    max_daily_classes = Column(Integer, default=5)

    homeroom_class = relationship("SchoolClass", foreign_keys=[homeroom_class_id])
    subject_assignments = relationship("SubjectClassAssignment", back_populates="teacher")
    constraints = relationship("TeacherConstraint", back_populates="teacher", cascade="all, delete-orphan")

    def __str__(self):
        return self.name


class SubjectClassAssignment(Base):
    """어떤 반이 어떤 교과를 누가 몇 시간 담당하는지"""
    __tablename__ = "subject_class_assignments"

    id = Column(Integer, primary_key=True)
    school_class_id = Column(Integer, ForeignKey("school_classes.id"), nullable=False)
    subject_id = Column(Integer, ForeignKey("subjects.id"), nullable=False)
    teacher_id = Column(Integer, ForeignKey("teachers.id"), nullable=False)
    weekly_hours = Column(Integer, nullable=False, default=1)
    preferred_room_id = Column(Integer, ForeignKey("rooms.id"), nullable=True)

    school_class = relationship("SchoolClass", back_populates="subject_assignments")
    subject = relationship("Subject", back_populates="assignments")
    teacher = relationship("Teacher", back_populates="subject_assignments")
    preferred_room = relationship("Room")


class TimetableEntry(Base):
    __tablename__ = "timetable_entries"

    id = Column(Integer, primary_key=True)
    term_id = Column(Integer, ForeignKey("academic_terms.id"), nullable=False)
    school_class_id = Column(Integer, ForeignKey("school_classes.id"), nullable=False)
    subject_id = Column(Integer, ForeignKey("subjects.id"), nullable=False)
    teacher_id = Column(Integer, ForeignKey("teachers.id"), nullable=False)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=True)
    day_of_week = Column(Integer, nullable=False)   # 1=월 … 5=금
    period = Column(Integer, nullable=False)         # 1~7
    is_fixed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    term = relationship("AcademicTerm", back_populates="timetable_entries")
    school_class = relationship("SchoolClass", back_populates="timetable_entries")
    subject = relationship("Subject")
    teacher = relationship("Teacher")
    room = relationship("Room")


class TeacherConstraint(Base):
    __tablename__ = "teacher_constraints"

    id = Column(Integer, primary_key=True)
    teacher_id = Column(Integer, ForeignKey("teachers.id"), nullable=False)
    day_of_week = Column(Integer, nullable=False)
    period = Column(Integer, nullable=False)
    constraint_type = Column(String(20), nullable=False)  # unavailable / preferred / avoid

    teacher = relationship("Teacher", back_populates="constraints")


class SchoolEvent(Base):
    __tablename__ = "school_events"

    id = Column(Integer, primary_key=True)
    term_id = Column(Integer, ForeignKey("academic_terms.id"), nullable=False)
    title = Column(String(100), nullable=False)
    event_type = Column(String(20), nullable=False, default="기타")  # 개교기념일, 시험, 축제, 방학, 공휴일, 행사, 기타
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    description = Column(Text, default="")
    color_hex = Column(String(7), default="#E3F2FD")

    term = relationship("AcademicTerm", back_populates="school_events")

    def __str__(self):
        return self.title


class TimetableChangeLog(Base):
    __tablename__ = "timetable_change_logs"

    id = Column(Integer, primary_key=True)
    timetable_entry_id = Column(Integer, ForeignKey("timetable_entries.id"), nullable=True)
    term_id = Column(Integer, ForeignKey("academic_terms.id"), nullable=False)
    school_class_id = Column(Integer, ForeignKey("school_classes.id"), nullable=False)
    change_type = Column(String(20), nullable=False)  # created, modified, deleted
    details = Column(Text, default="")
    changed_at = Column(DateTime, default=datetime.now)

    term = relationship("AcademicTerm")
    school_class = relationship("SchoolClass")
    timetable_entry = relationship("TimetableEntry")


class TimetableChangeRequest(Base):
    __tablename__ = "timetable_change_requests"

    id = Column(Integer, primary_key=True)
    timetable_entry_id = Column(Integer, ForeignKey("timetable_entries.id"), nullable=False)
    new_subject_id = Column(Integer, ForeignKey("subjects.id"), nullable=True)
    new_teacher_id = Column(Integer, ForeignKey("teachers.id"), nullable=True)
    new_room_id = Column(Integer, ForeignKey("rooms.id"), nullable=True)
    status = Column(String(20), nullable=False, default="pending")  # pending, approved, rejected
    reason = Column(Text, default="")
    requested_by = Column(String(30), default="")
    requested_at = Column(DateTime, default=datetime.now)
    approved_by = Column(String(30), default="")
    approved_at = Column(DateTime, nullable=True)

    timetable_entry = relationship("TimetableEntry")
    new_subject = relationship("Subject", foreign_keys=[new_subject_id])
    new_teacher = relationship("Teacher", foreign_keys=[new_teacher_id])
    new_room = relationship("Room", foreign_keys=[new_room_id])
