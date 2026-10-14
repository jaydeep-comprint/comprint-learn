/** Shapes returned by /api/v1 (see backend/app/schemas/tenancy.py). */

export type Role = "teacher" | "student";
export type UserStatus = "invited" | "active" | "deactivated";
export type Subject = "maths" | "physics" | "python";

export type Me = {
  id: string;
  display_name: string;
  role: Role;
  is_admin: boolean;
  username: string | null;
  must_change_password: boolean;
  org: { name: string; code: string };
};

export type Teacher = {
  id: string;
  display_name: string;
  email: string;
  status: UserStatus;
  is_admin: boolean;
};

export type Student = {
  id: string;
  display_name: string;
  username: string;
  status: UserStatus;
  class_ids: string[];
};

export type ClassStudent = Omit<Student, "class_ids">;

export type SchoolClass = {
  id: string;
  name: string;
  subject: Subject;
  grade: 9 | 10;
  archived: boolean;
  student_count: number;
  teachers: { id: string; display_name: string }[];
};

export type Slip = { display_name: string; username: string; temp_password: string };

export type CreatedStudent = Slip & { id: string };

export const SUBJECT_LABELS: Record<Subject, string> = {
  maths: "Maths",
  physics: "Physics",
  python: "Python",
};
