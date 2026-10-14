# Competitor insights: what to borrow

> Research from October 2026 covering **Math Academy** (including the draft book *The Math Academy Way*), **PhysicsGraph**, and **Vizuara Mu, Vizz AI and Pods**.
> Labels: **[Stated]** means the product or book says it. **[Inferred]** is our reading, or something taken from public client code rather than docs.
> Purpose: decide what to change in docs/ARCHITECTURE.md and the specs **before spec 003 (content model)**, because most of these ideas are content-schema decisions.

---

## TL;DR: the 10 changes we should make

| # | Change | From | Affects |
|---|---|---|---|
| 1 | Split each concept into **3–4 knowledge points (KPs)**. Each KP is a worked example followed by 2–5 adaptive questions. A concept is passed when all of its KPs pass | Math Academy | Spec 003, 004, 005 |
| 2 | **XP ≈ minutes of focused work**, graded by performance: zero for poor work, a small penalty for rushing. Implementation tasks still earn the most because they take longest | Math Academy | Spec 008 (replaces ARCHITECTURE decision 5) |
| 3 | Bloom levels become **item tags**. Unlock and gating happen at **concept level**, not as a separate mastery score per Bloom level | Math Academy | Spec 005 (changes decisions 3 and 4) |
| 4 | Prerequisite edges get an **encompassing weight (0–1)**. Each KP lists its **key prerequisite** | Math Academy | Spec 003 content schema |
| 5 | Run spaced repetition **per concept, not per item**, with **one-level implicit review**: passing a concept gives credit to its prerequisites | Math Academy, PhysicsGraph | Spec 007 (changes decision 9) |
| 6 | **Mixed timed quizzes** every ~150 XP covering everything learned so far, aiming for ~80% scores. Every miss becomes a review | Math Academy | New spec, or part of 007 |
| 7 | Physics answer schema: value, unit, **grading mode (exact, significant figures, or tolerance)**, scientific notation, and SymPy equivalence modes | PhysicsGraph | Spec 003, 006 |
| 8 | **Randomised numbers** per attempt; parameterised items | PhysicsGraph, Math Academy | Spec 003, 006 |
| 9 | Use multiple choice sparingly, and only with **misconception-tagged distractors**. Prefer free input | PhysicsGraph, Mu | Spec 003, 004, 010 |
| 10 | Knowledge-graph UI with **4 node states and a progress fill**, click to highlight prerequisites, and a memory-strength view | PhysicsGraph | Spec 005 |

---

## 1. Math Academy (mathacademy.com)

The most rigorous system of the group: adaptive maths from grade 4 to university, built on a knowledge graph with spaced repetition. Its draft book documents the design in unusual detail.

### Knowledge graph [Stated]
- About 300 topics per course. **Each topic is one lesson of 3–4 KPs** of increasing difficulty, so a course has roughly 1,000 steps where a textbook has about 100.
- The graph has three kinds of link:
  1. **Prerequisites** decide what can be learned next.
  2. **Key prerequisites** are attached to each KP and point to the earlier topic that step really depends on. They drive remediation.
  3. **Encompassings** carry a 0–1 weight for how much of a simpler topic is practised inside an advanced one. They drive implicit review.
- Experts set weights only on direct or key-prerequisite edges, so the effort grows linearly with the number of topics.

### Lessons and mastery [Stated]
- Each lesson is a short intro followed by, for each KP, **a worked example and 2–5 questions**. Wrong answers add more questions.
- **If a student fails a KP**, the lesson stops. They do other topics and retry later with new questions. Lessons pass 95% of the time on the first try and 99% within two.
- **If a student fails twice at the same KP**, they get reviews of its key prerequisites, then the prerequisite lessons if needed.
- New lessons only come from the **knowledge frontier**, where every prerequisite is mastered.
- "Baseline mastery" means the student passed the lesson. "Full mastery" comes only after months of reviews.

### Spaced repetition: FIRe (Fractional Implicit Repetition) [Stated]
- State kept per student per topic: `repNum`, `memory` (decays with a half-life equal to the current interval), and `speed`.
- **Passing** an advanced topic sends fractional credit **down** the encompassing weights. **Failing** a simple topic sends a penalty **up** to everything that encompasses it.
- **Students whose speed is below 1 get no implicit credit**, only explicit reviews, because weaker students don't transfer implicit practice well.
- "Repetition compression": the scheduler picks lessons whose implicit credit covers due reviews, and at least about 25% of tasks are new lessons.
- Reviews have 3–5 mixed questions, and pass or fail is judged on the **trend** of answers, not the raw count.

### Quizzes and interleaving [Stated]
- A timed quiz becomes available every **150 XP**. It has no notes, covers **everything learned so far**, is not announced in advance, and is tuned for an ~80% average. Every missed question immediately becomes a review. There is **no "I don't know" button**, because students abused it.
- Practice is blocked within a lesson, while reviews and quizzes mix question types. Topics are learned breadth-first across units, and similar concepts are spaced apart in time.

### XP [Stated]
- **1 XP ≈ 1 minute of focused work.** A course is about 3,000 XP, and the benchmark pace is 40 XP per weekday.
- XP depends on performance: a bonus for perfect work, zero for poor work, and **negative XP for blowing off a task**. After penalties were added, "XP hackers" went from under 50% to over 90% task pass rates.
- Course progress counts **completed lessons, not XP**, so progress never goes backwards.
- Leagues are optional, and question banks are large enough that classmates get different questions.

### Views that challenge our plan [Stated]
- **They don't use a conversational AI tutor.** They call explanation chatbots a "wild goose chase" and say hints "lower the bar". Their fix for a stuck student is rest, retry, then remediate the prerequisite.
- They see video and long explanations as passive and favour a "minimum effective dose" of explanation. Learning styles are a myth: students differ in speed and working memory, so they need the same practice in different amounts.
- Bloom levels are often misapplied.
- For children, an adult provides accountability. Students can't choose their own tasks or edit their knowledge profile.

### Warning signs for adults [Stated] → our at-risk rules
More than 1 in 10 lessons failed · any negative XP · 0.5 XP per minute or less.

Sources: [The Math Academy Way (draft)](https://www.justinmath.com/books) · [FIRe post](https://www.justinmath.com/individualized-spaced-repetition-in-hierarchical-knowledge-structures) · [How our AI works](https://mathacademy.com/how-our-ai-works) · [How it works](https://mathacademy.com/how-it-works) · [Pedagogy](https://mathacademy.com/pedagogy) · [Sustainable XP](https://justinmath.com/what-is-the-highest-sustainable-daily-xp-on-math-academy/)

---

## 2. PhysicsGraph (physicsgraph.com, formerly Lemnisket)

Mastery learning for physics and chemistry, explicitly modelled on Math Academy. It targets US high school, AP and college students and costs $299–599/year. It has no school or teacher plan, although teachers and parents can assign "threads".

- **Graph UI** [Inferred from the public bundle; built with Cytoscape.js]:
  - Rounded nodes with a **progress-fill bar**.
  - Legend states: **Locked / Ready / Partial / Learned / Coming soon**.
  - Click a node to highlight its prerequisites. A "memory fill" view colours nodes by retention.
  - A public course map doubles as marketing.
- **Navigation** [Stated]:
  - A 30-minute adaptive diagnostic finds the knowledge frontier.
  - The system picks the next units, or the student chooses up to 3.
  - **Focus Mode** prunes the path down to the prerequisites of one target topic, which suits teacher assignments.
- **Lessons** [Stated]: 5–15 minutes, diagram-heavy, with practice right after each chunk (about 5 problems per chunk, according to a student review).
  - **Multi-step guided problems** (4–10 steps) at the end of each unit combine several concepts.
  - Numbers are randomised.
- **Question types** [Inferred from the bundle]:
  - **Numerical input** with `correct_value`, `units_latex`, and a grading mode of **exact, significant figures, or acceptable error**.
  - Scientific notation.
  - **Equation input** (MathLive), graded as exact, equivalent, equivalent-simplified, or with positive exponents.
  - Matching, sorting, diagram hotspots, chart drawing, and rubric-graded free response.
- **Multiple choice is being phased out**, because users reasoned backwards from the options [Stated by users].
- **AI** [Stated]: AI grades AP-style free responses, with a human regrade option. Diagrams are authored with AI help (TikZ and Manim). No student chat tutor was found.
- **Spaced repetition** [Stated]: implicit review (advanced work counts as review of prerequisites), interleaving, and timed practice exams.
- **Complaints to avoid** [Stated by reviewers]:
  - A mandatory leaderboard.
  - No re-attempting past questions.
  - No review reminders.
  - Problems that reward plugging numbers into formulas over reasoning (free-body diagrams are missing).

Sources: [How it works](https://physicsgraph.com/how-it-works) · [Course map](https://physicsgraph.com/course-map) · [Pricing](https://physicsgraph.com/pricing) · [Founder Substack](https://chrissutherland.substack.com) · [Hecker review](https://frankhecker.com/2025/08/17/learning-how-to-teleport-quantum-states-with-physicsgraph/) · [Student review](https://tuck.bearblog.dev/half-of-physicsgraph-thoughts/)

---

## 3. Vizuara: Mu, Vizz AI, Pods

All three teach **AI/ML to college students and professionals**, not school syllabi. Vizuara's K-12 product is a separate site, interactive-ai-courses.vizuara.ai, which we could not read. Note that **vizz.ai is not Vizuara's**; the real product is at vizz.vizuara.ai.

### Mu (mu.vizuara.ai): visual micro-lessons [Stated]
- **Each lesson is a 2-minute visual video, then one immediate question.** The question is "built around the mistake most people make".
- Every lesson also has a text version.
- Streaks pull students back the next day.
- 67 micro-courses. Free starter courses are available, and premium costs ₹2,499/month.

### Vizz AI (vizz.vizuara.ai): conversational tutor [Stated]
- A voice and text tutor that can be interrupted, works in several languages, and sees the video frame on screen.
- **Active Mode** (coming soon): the video pauses every few minutes to ask a question. Missed points become tomorrow's review.
- **Memory profile**: after each session it records misconceptions and preferences.
- **"Review 5"**: a daily deck of 5 cards built from the student's own misses.
- Also: mock exams matched to a syllabus, per-subject "Spaces", flashcards, XP, and a leaderboard ranked by time spent.
- They published a small study (N=58, post-test 91.8 vs 83.5). It has a fixed-order design, so treat it as **weak evidence**.

### Pods (pods.vizuara.ai): Fundamentals → Practicals → Research [Stated]
- Each pod takes 3–5 hours: an illustrated article, Colab notebooks with TODOs, a real-dataset case study, and a certificate.
- One **dependency-ordered path with progress**, viewable through goal "lenses" (from scratch / interview / research). Nothing is locked.
- Small interactive **"poke it" widgets** in the articles.
- The tutor is embedded and answers with experiments to try ("set d=512 and remove the division") rather than giving the answer.

Sources: [mu.vizuara.ai](https://mu.vizuara.ai) · [vizz.vizuara.ai](https://vizz.vizuara.ai) · [pods.vizuara.ai](https://pods.vizuara.ai) · [Vizz paper (ACL 2026)](https://aclanthology.org/2026.teachingnlp-1.15/)

---

## 4. Reconciling the AI tutor tension

Math Academy argues against chat tutors. Vizuara's whole product is a tutor. Our PRD includes one. Our position:

- **The tutor never lowers the bar.** It points to the KP's worked example, to the key prerequisite ("this uses *multiplying negatives*; review it?"), or to an experiment to try (Pods style). It never gives the step or the answer.
- **It's scoped to the current item.** It sees only that item's content and the student's attempts on it.
- **Using hints reduces XP** for that item, and the number of hints per item is capped. A teacher can see how much each student relies on hints.
- **We measure it.** Compare pass rates with and without the tutor during the pilot. If it doesn't help, cut it back to the "point to the worked example" role.
- It's **text only** for minors: no voice or screen-watching, which keeps us DPDP-compliant and the cost low.

---

## 5. Proposed changes to ARCHITECTURE.md (adopted Oct 2026; see ARCHITECTURE decisions 3–16)

| Decision | Current | Proposed |
|---|---|---|
| 3 Mastery | A recency-weighted score per (concept, Bloom level), mastered at ≥ 0.8; unlock when prerequisites reach Apply | **Concept = 3–4 KPs.** A concept is "learned" when every KP passes (worked example → 2–5 questions, extended on errors). Unlock when **all prerequisites are learned** (knowledge frontier). Mastery strength = spaced-repetition memory. Bloom is an item tag that feeds the teacher analytics |
| 4 Layers | Learn = Remember/Understand, Practice = Apply+ | Keep it. Learn = intro + KP worked examples + 1 misconception check. Practice = KP questions, **multi-step problems** and code tasks. Per concept: Fundamentals → Practice → Case study/Create (Pods' three stages) |
| 5 XP | base(Bloom) × difficulty × first-try bonus | **XP ≈ expected minutes** per task × a performance multiplier (perfect 1.2 / pass 1.0 / partial 0.3 / poor 0 / rushed −). Reduced when hints are used. Daily goal ~30–40 XP. Progress = concepts learned, not XP |
| 9 Reviews | FSRS per item, interleaved | **FSRS per concept.** A review is 3–5 mixed questions across that concept's KPs. Passing gives **one-level implicit credit** to its prerequisites via the encompassing weight (off for struggling students). Cap at about **5 reviews a day**. Plus a **mixed quiz every ~150 XP** |
| New | (none) | **Item answer schema**: `numeric{value, unit, mode: exact\|sigfig\|tolerance, tol}`, `expression{sympy_mode: exact\|equivalent\|simplified}`, `mcq{options[{text, misconception_id}]}`, `code{tests}`, `params` for randomised numbers |
| New | (none) | **At-risk rules** for the teacher dashboard: concept fail rate > 10%, negative XP, low XP per minute, falling memory on core concepts |

---

## 6. Roadmap mapping

| Spec | What to add from this research | MVP? |
|---|---|---|
| **003 Content model** | KPs; key prerequisite per KP; encompassing weight per edge; answer schema (numeric/expression/mcq/code); misconception tags; parameterised items | ✅ Must have. Decide before spec 003 |
| **004 Learn layer** | Short intro + worked examples; one misconception check; text-first lessons with diagrams; no long video | ✅ |
| **005 Mastery + graph** | KP pass/fail flow, retry later with new questions, remediate key prerequisites after 2 fails; knowledge frontier; graph UI with 4 states, progress fill, prerequisite highlighting | ✅ |
| **006 Practice** | SymPy grading modes; sig figs and tolerance; units; randomised numbers; multi-step problems; Python tasks | ✅ (start multi-step with physics) |
| **007 Spaced repetition** | FSRS per concept; mixed 3–5 question reviews; one-level implicit credit; daily cap; mixed quiz every ~150 XP | ✅ (quizzes may slip to v1.1) |
| **008 XP** | XP ≈ minutes × performance; no "I don't know"; daily goal; streaks; progress = concepts learned | ✅ |
| **009 AI tutor** | Scoped to the item; points to worked example, prerequisite or experiment; hint cap; less XP with hints; text only | ✅ (scoped down) |
| **010 Teacher dashboard** | At-risk rules; misconception distribution ("40% chose distractor B"); **assignments = Focus Mode** (target concept plus its prerequisites); student graph with a memory view | ✅ |
| **011 Teacher AI assist** | Summaries built from misconception tags and the key-prerequisite causes of being stuck | ✅ |

## 7. Later (v2+)
- An adaptive placement diagnostic (MVP: the teacher sets the starting point, or a short fixed quiz).
- Full multi-level FIRe with learning speeds and repetition compression.
- Interactive "poke it" simulations for physics (sliders, vector drawing, free-body diagrams), and Pause-and-ask checkpoints inside videos.
- Goal lenses on the graph (board exam vs JEE-depth vs deep mastery), and different maths-level versions of the same concept.
- Opt-in leagues among similar students. Never mandatory, never ranked by time spent.
- Analytics per KP and per question to improve content. **Log the data from day one.**
- AI-graded free responses and derivations, and AI-assisted authoring of diagrams and content.

## 8. Avoid
- Mandatory or time-spent leaderboards (PhysicsGraph, Vizz). They're risky for minors and reward farming.
- Multiple choice as the main practice format; it encourages working backwards from the options.
- Hints that hand over the next step.
- Long videos and passive scrolling (the Mu format) as anything more than a small slice of the Learn layer.
- Unlocked free-roam paths for school students (Pods). Use frontier gating, with an optional "recommended next".
- Voice and screen-watching AI, and "upload anything" features (DPDP, cost, scope).
- No way to re-attempt past questions, and no review reminders (PhysicsGraph complaints).
