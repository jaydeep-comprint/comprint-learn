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

/** Spec 014: AI-tutor consent (null = not recorded) and a pending erasure. */
export type PrivacyFields = {
  tutor_consent_at: string | null;
  tutor_consent_form: string | null;
  erase_due_at: string | null;
};

export type Student = PrivacyFields & {
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
  /** Spec 007: due, offerable review cards today (uncapped, quiz misses included). */
  reviews_due: number;
  /** The last finished quiz. */
  last_quiz: { score_pct: number; finished_on: string } | null;
  /** Spec 010: at-risk rule codes (empty when not at risk or not in scope). */
  at_risk: AtRiskCode[];
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
  /** Spec 012: learned through a placement check; `conditional`: "check soon". */
  placed?: boolean;
  conditional?: boolean;
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
  /** Spec 012: placed by a placement check; KP steps run as real sessions, as if in progress. */
  placed?: boolean;
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
  /** Spec 007: a quiz question's shared deadline (ISO). */
  deadline?: string | null;
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
  /** Spec 007: set on the answer that ended a scheduled review. */
  review?: ReviewOutcome | null;
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

/** Reviews + quizzes (spec 007: backend/app/schemas/reviews.py, quiz.py). */
export type ReviewOffer = {
  course: string;
  concept: ConceptRef;
  subject: Subject;
  reason: "schedule" | "quiz_miss";
  /** ISO date (IST). */
  due_on: string;
  /** A review session is open for it. */
  active: boolean;
};

export type ReviewQueue = {
  cap: number;
  done_today: number;
  offered: ReviewOffer[];
  /** Due scheduled reviews beyond today's cap (they roll over). */
  more_due: number;
  /** When nothing is offered: the next day a review comes up. */
  next_due_on: string | null;
  /** False: the student has no cards yet (the home card is hidden). */
  has_cards: boolean;
};

export type ReviewOutcome = {
  rating: "again" | "hard" | "good";
  /** Null when a relearn started. */
  next_due: string | null;
  relearn: boolean;
};

export type QuizStatus = "pending" | "active" | "finished" | "cancelled";

export type QuizState = {
  id: string;
  status: QuizStatus;
  total: number;
  minutes: number;
  deadline: string | null;
  /** Active only, computed on the server (client clocks don't matter). */
  seconds_left: number | null;
  answered: number;
};

export type QuizSaved = { saved: true; answered: number; finished: boolean };

export type QuizXp = {
  amount: number;
  base_minutes: string;
  goal_met_today: boolean;
  subjects: { subject: Subject; amount: number; grade: XpGrade }[];
};

export type QuizResultItem = {
  position: number;
  concept: ConceptRef;
  type: QuestionType;
  prompt_md: string;
  /** Null: unanswered. MCQ: the option text. */
  response: string | null;
  correct: boolean;
  /** Expression: LaTeX. MCQ: the option text. */
  display_answer: string;
  explanation_md: string | null;
};

export type QuizResult = {
  correct: number;
  total: number;
  xp: QuizXp | null;
  items: QuizResultItem[];
  review_concepts: ConceptRef[];
};

// --- AI tutor (spec 009) ---

export type TutorMessage = {
  id: string;
  role: "student" | "tutor";
  kind: "hint" | "chat";
  rung: number | null;
  /** Null for a hint request (the student pressed Hint) or after the retention purge. */
  text: string | null;
  link: ConceptRef | null;
  created_at: string;
};

export type TutorThread = {
  enabled: boolean;
  /** Spec 014: a parent/guardian consent form is recorded for this student. */
  consent: boolean;
  mode: "before" | "after";
  closed: boolean;
  hints_used: number;
  hints_left: number;
  next_rung: number | null;
  chat_left: number;
  daily_left: number;
  resets_at: string;
  messages: TutorMessage[];
};

export type TutorReply = { message: TutorMessage; thread: TutorThread };

/** Teacher dashboard (spec 010, backend/app/schemas/dashboard.py). */
export type DashboardWindow = "7d" | "30d" | "all";
export type HeatState = "locked" | "ready" | "in_progress" | "stuck" | "learned";
export type Band = "strong" | "fading" | "weak" | "none";
export type AtRiskCode =
  | "kp_fail_rate"
  | "negative_xp"
  | "low_xp_rate"
  | "falling_memory"
  | "overdue_assignment"
  | "inactive";

export type ConceptStat = {
  concept: string;
  title: string;
  chapter: string;
  tries: number;
  students_tried: number;
  fail_rate: number | null;
  stuck_now: number;
  learned_pct: number;
};

export type AtRiskReason = { code: AtRiskCode; detail: string };
export type AtRiskRow = { student_id: string; display_name: string; reasons: AtRiskReason[] };

export type MisconceptionStat = {
  id: string;
  title: string;
  concept: string | null;
  concept_title: string | null;
  chosen: number;
  offered: number;
  rate: number | null;
  students: number;
  items: { prompt: string; chosen_text: string | null; student_names: string[] }[];
};

export type HintStudent = {
  student_id: string;
  display_name: string;
  hints: number;
  chats: number;
  answered: number;
  hints_per_10: number | null;
};

export type HintUse = {
  hints: number;
  chats: number;
  answered: number;
  hints_per_10: number | null;
  top: HintStudent[];
};

export type FlaggedThread = {
  thread_id: string;
  student_id: string;
  display_name: string;
  concept: string;
  concept_title: string;
  created_at: string;
};

export type ClassOverview = {
  window: DashboardWindow;
  students_in_scope: number;
  has_course: boolean;
  weakest: ConceptStat[];
  at_risk: AtRiskRow[];
  misconceptions: MisconceptionStat[];
  hints: HintUse;
  flagged: FlaggedThread[];
  practice_share: { learn_seconds: number; practice_seconds: number };
  assignments_due: AssignmentSummary[];
  overdue_assignments: number;
};

export type StudentRef = { student_id: string; display_name: string };

export type ConceptDetail = {
  concept: string;
  title: string;
  kps: { title: string; tries: number; fail_rate: number | null; hints: number }[];
  items: {
    prompt: string;
    kind: string;
    type: string;
    answers: number;
    correct_pct: number | null;
    avg_seconds: number | null;
  }[];
  misconceptions: MisconceptionStat[];
  students: {
    stuck: (StudentRef & { reason: string })[];
    in_progress: StudentRef[];
    learned: StudentRef[];
    ready: number;
    locked: number;
  };
};

export type HeatCell = { state: HeatState; band: Band | null };

export type Heatmap = {
  chapters: {
    title: string;
    grade: number | null;
    concepts: { concept: string; title: string; learned_pct: number }[];
  }[];
  students: { student_id: string; display_name: string; cells: HeatCell[] }[];
};

export type StudentDetail = PrivacyFields & {
  student_id: string;
  display_name: string;
  username: string;
  status: UserStatus;
  at_risk: AtRiskReason[];
  week_xp: number;
  streak_days: number;
  reviews_due: number;
  last_quiz: { score_pct: number; finished_on: string } | null;
  stats: {
    learn_seconds: number;
    practice_seconds: number;
    kp_fail_rate: number | null;
    hints_per_10: number | null;
    learned: number;
    total: number;
  };
  assignments: StudentAssignmentRow[];
};

export type Memory = { band: Band; retrievability: number | null; next_due: string | null };

export type TeacherOutlineConcept = OutlineConcept & {
  state: HeatState;
  memory: Memory | null;
  kps: { title: string; status: KpStatus; fail_count: number; reopen_at: string | null }[];
};

export type TeacherOutline = {
  /** null when the class subject has no active course. */
  course: Outline["course"] | null;
  chapters: {
    slug: string;
    title: string;
    grade: number | null;
    concepts: TeacherOutlineConcept[];
  }[];
};

export type ActivityRow = {
  kind: "kp" | "remediation" | "practice" | "review" | "quiz";
  concept: string | null;
  title: string;
  outcome: "passed" | "failed";
  xp: number | null;
  hints: number;
  answered: number;
  seconds: number;
  ended_at: string;
};

export type ThreadRow = {
  id: string;
  concept: string;
  concept_title: string;
  kp_title: string | null;
  created_at: string;
  hints_used: number;
  chat_count: number;
  flagged: boolean;
};

export type ThreadDetail = {
  id: string;
  concept: string;
  concept_title: string;
  messages: {
    role: "student" | "tutor";
    kind: "hint" | "chat";
    text: string | null;
    status: string;
    purged: boolean;
    created_at: string;
  }[];
};

/** Assignments and Focus Mode (spec 010, backend/app/schemas/assignments.py). */
export type AssignmentStatus =
  "done_early" | "done_on_time" | "done_late" | "overdue" | "in_progress" | "not_started";

export type AssignmentSummary = {
  id: string;
  title: string;
  concepts: { concept: string; title: string }[];
  content_available: boolean;
  due_date: string;
  note: string | null;
  all_students: boolean;
  student_ids: string[];
  counts: {
    done: number;
    done_late: number;
    already_learned: number;
    overdue: number;
    in_progress: number;
    not_started: number;
    total: number;
  };
  active: boolean;
  created_at: string;
};

export type NextConcept = { concept: string; title: string };

export type AssignmentDetail = AssignmentSummary & {
  students: {
    student_id: string;
    display_name: string;
    status: AssignmentStatus;
    done_at: string | null;
    learned: number;
    total: number;
    next: NextConcept | null;
  }[];
};

export type StudentAssignmentRow = {
  id: string;
  title: string;
  due_date: string;
  status: AssignmentStatus;
  done_at: string | null;
  learned: number;
  total: number;
  next: NextConcept | null;
};

export type AssignmentInput = {
  concepts: string[];
  due_date: string;
  note: string | null;
  student_ids: string[] | null;
};

export type MyAssignment = {
  id: string;
  title: string;
  class_name: string;
  course: string;
  due_date: string;
  note: string | null;
  status: AssignmentStatus;
  done_at: string | null;
  learned: number;
  total: number;
  path: {
    concept: string;
    course: string;
    title: string;
    status: "in_progress" | "stuck" | "ready" | "locked";
    waiting: boolean;
    target: boolean;
  }[];
  next: { concept: string; course: string; title: string; brush_up_id: string | null } | null;
};

// --- Teacher AI assist (spec 011, backend/app/schemas/teacher_ai.py) ---

export type SummaryBlocked =
  "fresh" | "busy" | "teacher_cap" | "school_cap" | "archived" | "not_enough_data";

export type FactLink = {
  kind:
    "concept" | "misconception" | "student" | "assignment" | "overview_card" | "student_section";
  /** "<course>/<slug>" for `concept`. */
  concept: string | null;
  /** Misconception or assignment id. */
  id: string | null;
  /** Null when the student is no longer in the class. */
  student_id: string | null;
  card: string | null;
  section: string | null;
};

export type SummaryFact = { id: string; text: string; link: FactLink };

export type SummaryClaim = { text: string; citations: string[] };

export type SummaryResource = {
  id: string;
  kind: "lesson" | "worked_example";
  title: string;
  /** "<concept course>/<slug>". */
  concept: string;
  concept_title: string;
  /** KP slug: the lesson opens at `kp:<slug>`. */
  kp: string | null;
  /** False when the content was retired (shown as plain text). */
  available: boolean;
  /** In the class course, so it can be assigned. */
  in_course: boolean;
};

export type SummaryNote = {
  focus: string;
  why: SummaryClaim;
  revisit: SummaryResource[];
  group: { student_id: string; display_name: string }[];
  /** For AssignmentDialog: `student_ids` null = the whole class. */
  assign: { concepts: string[]; student_ids: string[] | null };
};

export type TeacherSummary = {
  id: string;
  kind: "class" | "student";
  window: DashboardWindow;
  status: "ok" | "partial";
  created_at: string;
  created_by_name: string;
  claims: SummaryClaim[];
  notes: SummaryNote[];
  /** Only the cited facts. */
  facts: SummaryFact[];
};

export type SummaryState = {
  enabled: boolean;
  enough_data: boolean;
  summary: TeacherSummary | null;
  stale: boolean;
  can_regenerate: boolean;
  blocked: SummaryBlocked | null;
  daily_left: number;
  resets_at: string;
};

// --- Placement (spec 012) -------------------------------------------------------------------------

export type PlacementStatus = "not_sent" | "sent" | "active" | "finished" | "cancelled";

export type PlacementCounts = { learned: number; conditional: number; demoted: number };

export type PlacementStudentRow = {
  student_id: string;
  display_name: string;
  status: PlacementStatus;
  diagnostic_id: string | null;
  sent_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  answered: number;
  /** The latest finished check (may be older than `status`). */
  result_at: string | null;
  counts: PlacementCounts | null;
};

export type PlacementOverview = {
  course: { slug: string; title: string; subject: Subject } | null;
  archived: boolean;
  chapters: { id: string; slug: string; title: string; grade: number | null; covered: boolean }[];
  range: { concepts: number; prereqs: number; askable: number };
  students: PlacementStudentRow[];
};

export type PlacementOutcome = "learned" | "conditional" | "demoted" | "unchanged";

export type StudentOutcomes = {
  student_id: string;
  display_name: string;
  diagnostic_id: string | null;
  finished_at: string | null;
  concepts: { concept: ConceptRef; outcome: PlacementOutcome }[];
};

export type DiagnosticState = {
  id: string;
  status: "sent" | "active" | "finished" | "cancelled";
  class_name: string;
  course: { slug: string; title: string; subject: Subject } | null;
  answered: number;
  max_questions: number;
  /** Finished at start: nothing to check right now. */
  empty: boolean;
};

export type DiagnosticSaved = { finished: boolean; answered: number };

export type DiagnosticResult = {
  answered: number;
  learned: ConceptRef[];
  conditional: ConceptRef[];
  to_learn: ConceptRef[];
};

/** Spec 014: the consent notice (`body_md` is printed on the form; `/privacy` shows both). */
export type Notice = { version: string; title: string; body_md: string; stores_md: string };

export type AuditAction =
  | "consent_recorded"
  | "consent_withdrawn"
  | "export_downloaded"
  | "erase_requested"
  | "erase_cancelled"
  | "erase_completed"
  | "password_reset"
  | "user_deactivated"
  | "user_reactivated";

export type AuditEvent = {
  id: string;
  action: AuditAction;
  at: string;
  /** null = the system (CLI or scheduled job). */
  actor: { id: string; display_name: string } | null;
  target: { id: string; display_name: string } | null;
  meta: Record<string, string | number | boolean | null>;
};

export type AuditPage = { items: AuditEvent[]; next_before: string | null };
