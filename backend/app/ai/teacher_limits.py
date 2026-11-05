"""Caps, limits and timings for teacher AI summaries (spec 011). Tune in the pilot."""

from datetime import timedelta

TEACHER_DAILY_CAP = 10  # generations per teacher per IST day
SCHOOL_DAILY_CAP = 50  # generations per school per IST day
COOLDOWN = timedelta(minutes=10)  # same facts hash within this → 409 summary_fresh
STALE_PENDING = timedelta(minutes=5)  # an older pending row is treated as error

TIMEOUT_S = 60.0  # per HTTP request
WALL_CLOCK_S = 150.0  # both attempts together
MAX_TOKENS = 8000  # reasoning tokens count toward it
TEMPERATURE = 0.2

CLAIM_WORDS = 40
OVER_LIMIT = 1.5  # drop a claim longer than 1.5x CLAIM_WORDS
MAX_FACTS_PER_CLAIM = 4
FOCUS_MAX = 80
MAX_REVISIT = 3
MAX_GROUP = 12

CLASS_CLAIMS = (2, 5)
STUDENT_CLAIMS = (2, 4)
CLASS_NOTES = 3
STUDENT_NOTES = 1

# Fact caps (keep the prompt around 6k tokens).
TOP_CONCEPTS = 5
KPS_PER_CONCEPT = 2
MIN_KP_TRIES = 3
TOP_MISCONCEPTIONS = 5
TOP_CAUSES = 5
MAX_AT_RISK = 10
MAX_ASSIGNMENTS = 5
FACT_STUDENTS = 12  # students named in one fact, then "and N more"
MAX_RESOURCES = 15
STUDENT_KP_FAILS = 5
STUDENT_MISCONCEPTIONS = 5
STUDENT_STATES = 8
STUDENT_MEMORY = 5
