import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints, field_validator

from app.models import Role, Subject, UserStatus

MAX_NEW_STUDENTS = 60
MAX_ENROLL_IDS = 200

StudentName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]
StaffName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
ClassName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]
# bcrypt (Supabase) ignores bytes past 72.
Password = Annotated[str, Field(min_length=8, max_length=72)]
Grade = Literal[9, 10]


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- me -------------------------------------------------------------------------------------------


class OrgOut(_Out):
    name: str
    code: str


class MeOut(_Out):
    id: uuid.UUID
    display_name: str
    role: Role
    is_admin: bool
    username: str | None
    must_change_password: bool
    org: OrgOut


class PasswordIn(BaseModel):
    new_password: Password


# --- teachers -------------------------------------------------------------------------------------


class TeacherOut(_Out):
    id: uuid.UUID
    display_name: str
    email: str
    status: UserStatus
    is_admin: bool


class TeacherInviteIn(BaseModel):
    email: EmailStr
    display_name: StaffName


class TeacherPatch(BaseModel):
    is_admin: bool | None = None
    status: Literal[UserStatus.active, UserStatus.deactivated] | None = None


# --- students -------------------------------------------------------------------------------------


class StudentOut(_Out):
    id: uuid.UUID
    display_name: str
    username: str
    status: UserStatus
    class_ids: list[uuid.UUID] = []


class StudentPatch(BaseModel):
    display_name: StudentName | None = None
    status: Literal[UserStatus.active, UserStatus.deactivated] | None = None


class TempPasswordOut(BaseModel):
    username: str
    temp_password: str


class CreateStudentsIn(BaseModel):
    display_names: list[Annotated[str, Field(max_length=200)]] = Field(
        max_length=MAX_NEW_STUDENTS * 4
    )

    @field_validator("display_names")
    @classmethod
    def _clean(cls, names: list[str]) -> list[str]:
        # One name per pasted line. Blank lines are ignored; duplicates become different users.
        cleaned = [n.strip() for n in names if n.strip()]
        if not cleaned:
            raise ValueError("Enter at least one name.")
        if len(cleaned) > MAX_NEW_STUDENTS:
            raise ValueError(f"At most {MAX_NEW_STUDENTS} students at a time.")
        too_long = [i + 1 for i, n in enumerate(cleaned) if len(n) > 40]
        if too_long:
            raise ValueError(f"Names must be 40 characters or fewer (line {too_long[0]}).")
        return cleaned


class CreatedStudentOut(BaseModel):
    id: uuid.UUID
    display_name: str
    username: str
    temp_password: str


# --- classes --------------------------------------------------------------------------------------


class ClassIn(BaseModel):
    name: ClassName
    subject: Subject
    grade: Grade


class ClassPatch(BaseModel):
    name: ClassName | None = None
    subject: Subject | None = None
    grade: Grade | None = None
    archived: bool | None = None


class TeacherRef(BaseModel):
    id: uuid.UUID
    display_name: str


class ClassOut(BaseModel):
    id: uuid.UUID
    name: str
    subject: Subject
    grade: int
    archived: bool
    student_count: int
    teachers: list[TeacherRef]


class ClassStudentOut(_Out):
    id: uuid.UUID
    display_name: str
    username: str
    status: UserStatus


class EnrollIn(BaseModel):
    student_ids: list[uuid.UUID] = Field(min_length=1, max_length=MAX_ENROLL_IDS)
