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
export type LessonStatus = "learned" | "in_progress" | "ready" | "locked";
export type KpStatus = "not_started" | "in_progress" | "passed" | "failed";

export type ConceptRef = { id: string; title: string };

/** A brush-up owed before `concept`'s failed part reopens (spec 005). */
export type RemediationRef = {
  id: string;
  kind: "review" | "relearn";
  prereq: ConceptRef;
  concept: ConceptRef;
};

export type HomeConcept = {
  id: string;
  title: string;
  kps_passed: number;
  kps_total: number;
  reopen_at: string | null;
};

export type StudentCourse = {
  slug: string;
  title: string;
  subject: Subject;
  learned: number;
  total: number;
  brush_up: RemediationRef[];
  in_progress: HomeConcept[];
  ready: HomeConcept[];
  ready_count: number;
  waiting: HomeConcept[];
};

export type OutlineConcept = {
  id: string;
  title: string;
  summary: string;
  /** null for staff (preview). */
  status: LessonStatus | null;
  prereqs: string[];
  kps_passed: number;
  kps_total: number;
  waiting: { reopen_at: string | null } | null;
  brush_up: boolean;
  /** The due review behind `brush_up` (the map's "Brush up first" button). */
  brush_up_id: string | null;
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
  kps: LessonKp[];
  steps: string[];
  progress: LessonProgress | null;
  check_result: CheckResult | null;
  preview: boolean;
  /** null for staff. */
  concept_status: LessonStatus | null;
  waiting: LessonWaiting | null;
};

export type LessonKp = {
  slug: string;
  title: string;
  worked_example_md: string;
  /** null for staff. */
  status: KpStatus | null;
  open: boolean;
  reopen_at: string | null;
  /** A question session is in progress: resume at its `kpq` step. */
  active: boolean;
};

export type LessonWaiting = {
  kp: string;
  reopen_at: string | null;
  remediations: RemediationRef[];
};

/** KP questions (backend/app/schemas/kp.py). */
export type Question = {
  session_id: string | null;
  position: number;
  item_id: string;
  type: "numeric" | "expression" | "mcq";
  prompt_md: string;
  unit: string | null;
  options: { id: string; text: string }[] | null;
  variables: string[] | null;
  results: boolean[];
  /** Staff preview only: sent back with the answer. */
  preview_seed: number | null;
};

export type AnswerResult = {
  correct: boolean;
  display_answer: string;
  explanation_md: string | null;
  misconception: { title: string } | null;
  note: string | null;
  session_status: "active" | "passed" | "failed";
  already_answered: boolean;
  results: boolean[];
  concept_learned: boolean;
  unlocked: ConceptRef[];
  remediations: RemediationRef[];
  /** Passed brush-up: the part it was for is no longer blocked (null otherwise). */
  kp_open?: boolean | null;
};

export type RemediationInfo = {
  id: string;
  state: "review_due" | "relearn" | "resolved";
  kind: "review" | "relearn";
  prereq: ConceptRef;
  concept: ConceptRef;
  kp_title: string;
};

/** A course from GET /api/v1/courses (global content). */
export type CourseSummary = {
  slug: string;
  title: string;
  subject: Subject;
  chapter_count: number;
  concept_count: number;
};
