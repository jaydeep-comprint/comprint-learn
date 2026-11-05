"""AI tutor limits (spec 009). Constants, not teacher settings."""

from datetime import timedelta

DAILY_CAP = 20  # tutor requests per student per IST day, all subjects
HINTS_PER_THREAD = 3
CHAT_PER_THREAD = 10
MAX_MESSAGE = 500  # characters in a student chat message
MAX_DRAFT = 10_000  # characters of the current draft sent with a request
HINT_WORDS = 80
CHAT_WORDS = 120
OVER_LIMIT = 1.5  # a reply over 1.5x its word limit is treated like a leak
AFTER_WINDOW = timedelta(minutes=60)  # after-mode chat after the session ended
TIMEOUT_S = 20.0
MAX_TOKENS = 2000  # reasoning tokens count toward it
STALE_PENDING = timedelta(minutes=2)  # a pending request older than this was lost (crash, redeploy)
RETENTION_DAYS = 180
MAX_EXPRESSION_SPANS = 5
