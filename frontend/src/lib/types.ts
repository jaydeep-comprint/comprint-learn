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

export type ClassStudent = Omit<Student, "class_ids"> & {
  /** This week's XP in the class's subject (spec 008). */
  week_xp: number;
  streak_days: number;
};

export type SchoolClass = {
  id: string;
  name: string;
  subject: Subject;
  grade: 9 | 10;
  archived: boolean;
  student_count: number;
  teachers: { id: string; display_name: string }[];
  /** Spec 008: the class's daily XP goal and the opt-in weekly leaderboard. */
  daily_goal: number;
  leaderboard_enabled: boolean;
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

export type PracticeStatus = "none" | "pending" | "passed";

export type HomeConcept = {
  id: string;
  title: string;
  kps_passed: number;
  kps_total: number;
  /** KPs passed + Practice passed, out of KPs + 1 when the concept has Practice (spec 006). */
  parts_passed: number;
  parts_total: number;
  /** Every KP passed; only Practice is left. */
  practice_left?: boolean;
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
  /** KPs passed + Practice passed, out of KPs + 1 when the concept has Practice (spec 006). */
  parts_passed: number;
  parts_total: number;
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
  /** The Practice step (spec 006); `none` when the concept has no practice items. */
  practice: { status: PracticeStatus; active: boolean };
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

/** KP questions, reviews and practice (backend/app/schemas/kp.py). */
export type QuestionType = "numeric" | "expression" | "mcq" | "multistep" | "code";
export type StepType = "numeric" | "expression" | "mcq";
export type Option = { id: string; text: string };

/** One step of a multi-step problem, rendered with this attempt's numbers. */
export type StepPublic = {
  prompt_md: string;
  type: StepType;
  unit: string | null;
  options: Option[] | null;
  variables: string[] | null;
};

export type StepResult = {
  correct: boolean;
  display_answer: string;
  note: string | null;
  misconception: { title: string } | null;
};

/** A code test in authored order. `args` / `expected` are JSON text (Python's `json.dumps`). */
export type CodeTestPublic = {
  visible: boolean;
  returns: "value" | "stdout";
  args: string;
  stdin: string | null;
  /** Visible tests only. */
  expected: string | null;
  expected_stdout: string | null;
};

export type CodePublic = {
  entry: string;
  starter: string;
  /** Practice: the student's last submitted code. */
  prefill: string | null;
  time_limit_ms: number;
  tests: CodeTestPublic[];
};

export type Question = {
  session_id: string | null;
  position: number;
  item_id: string;
  type: QuestionType;
  /** Multi-step: the problem stem. */
  prompt_md: string;
  unit: string | null;
  /** Numeric with a unit: show the unit box. */
  unit_required?: boolean;
  options: Option[] | null;
  variables: string[] | null;
  steps?: StepPublic[] | null;
  /** Multi-step: the step to answer now. */
  step?: number | null;
  step_results?: StepResult[] | null;
  code?: CodePublic | null;
  results: boolean[];
  /** Staff preview only: sent back with the answer. */
  preview_seed: number | null;
};

/** One test's output as the browser sends it (`backend/app/grading/code.py`). */
export type TestOutput =
  { json: string } | { stdout: string } | { error: string } | { timeout: true };

export type CodeTestResult = {
  visible: boolean;
  passed: boolean;
  status: "passed" | "failed" | "error" | "timeout";
  args: string;
  stdin: string | null;
  /** Visible tests only. */
  expected: string | null;
  got: string;
};

export type AnswerResult = {
  /** This answer (multi-step: this step; see `item_correct`). */
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
  step?: number | null;
  step_results?: StepResult[] | null;
  /** Multi-step: false until the last step is answered. */
  item_done?: boolean;
  item_correct?: boolean | null;
  tests?: CodeTestResult[] | null;
  solution?: string | null;
  /** Spec 008: set on the answer that ended the session (and on a resend of it). */
  xp?: XpAward | null;
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

/** XP & gamification (backend/app/schemas/xp.py). Displayed totals are floored at 0. */
export type XpGrade = "perfect" | "passed" | "partial" | "poor" | "rushed";

export type XpAward = {
  amount: number;
  grade: XpGrade;
  base_minutes: string;
  hints: number;
  /** This award made today met (the first time). */
  goal_met_today: boolean;
};

export type XpSummary = {
  today: { subject: Subject; xp: number; goal: number | null; met: boolean }[];
  streak: { days: number; today_met: boolean };
  week_xp: number;
  total_xp: number;
  goals: { subject: Subject; class_goal: number; own_goal: number | null; effective: number }[];
  leaderboards: { class_id: string; class_name: string; subject: Subject }[];
};

export type Leaderboard = {
  class_name: string;
  subject: Subject;
  enabled: boolean;
  week_start: string;
  rows: {
    rank: number;
    display_name: string;
    week_xp: number;
    is_me: boolean;
    student_id?: string;
  }[];
};
