from fastapi import APIRouter

from app.api.v1 import classes, courses, health, me, students, teachers

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(me.router)
api_router.include_router(teachers.router)
api_router.include_router(students.router)
api_router.include_router(classes.router)
api_router.include_router(courses.router)
