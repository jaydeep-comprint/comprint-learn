from fastapi import APIRouter

from app.api.v1 import (
    classes,
    courses,
    health,
    kp,
    learn,
    me,
    quiz,
    reviews,
    students,
    teachers,
    xp,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(me.router)
api_router.include_router(teachers.router)
api_router.include_router(students.router)
api_router.include_router(classes.router)
api_router.include_router(courses.router)
api_router.include_router(learn.router)
api_router.include_router(kp.router)
api_router.include_router(xp.router)
api_router.include_router(reviews.router)
api_router.include_router(quiz.router)
