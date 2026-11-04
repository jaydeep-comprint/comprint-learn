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

/** Learn layer (backend/app/schemas/learn.py). Concept ids are "<course>/<slug>". */
export type LessonStatus = "finished" | "in_progress" | "ready" | "locked";

export type ConceptRef = { id: string; title: string };

export type StudentCourse = {
  slug: string;
  title: string;
  subject: Subject;
  finished: number;
  total: number;
  continue: ConceptRef | null;
};

export type OutlineConcept = {
  id: string;
  title: string;
  summary: string;
  /** null for staff (preview). */
  status: LessonStatus | null;
  prereqs: string[];
};

export type Outline = {
  course: { slug: string; title: string; subject: Subject };
  chapters: { slug: string; title: string; grade: number | null; concepts: OutlineConcept[] }[];
};

export type LockedPrereq = { id: string; title: string; status: LessonStatus };

export type CheckResult = {
  correct: boolean;
  chosen: string;
  correct_option: string;
  explanation_md: string | null;
  misconception: { title: string } | null;
};

export type CheckSubmitted = CheckResult & { already_answered: boolean };

export type LessonProgress = {
  seen_steps: string[];
  last_step: string;
  finished_at: string | null;
};

export type Lesson = {
  id: string;
  title: string;
  summary: string;
  asset_base: string;
  intro_md: string;
  check: { item_id: string; prompt: string; options: { id: string; text: string }[] } | null;
  kps: { slug: string; title: string; worked_example_md: string }[];
  steps: string[];
  progress: LessonProgress | null;
  check_result: CheckResult | null;
  preview: boolean;
};

/** A course from GET /api/v1/courses (global content). */
export type CourseSummary = {
  slug: string;
  title: string;
  subject: Subject;
  chapter_count: number;
  concept_count: number;
};
