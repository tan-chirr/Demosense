from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from demosense.api.routers import memberships, org_units, people, role_grants, rollup, surveys
from demosense.auth import auth_backend, fastapi_users
from demosense.config import settings
from demosense.schemas.user import UserCreate, UserRead, UserUpdate

app = FastAPI(title="DemoSense API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_allow_origins.split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(fastapi_users.get_auth_router(auth_backend), prefix="/auth/jwt", tags=["auth"])
app.include_router(
    fastapi_users.get_register_router(UserRead, UserCreate), prefix="/auth", tags=["auth"]
)
app.include_router(fastapi_users.get_reset_password_router(), prefix="/auth", tags=["auth"])
app.include_router(fastapi_users.get_verify_router(UserRead), prefix="/auth", tags=["auth"])
app.include_router(fastapi_users.get_users_router(UserRead, UserUpdate), prefix="/users", tags=["users"])

app.include_router(org_units.router)
app.include_router(people.router)
app.include_router(memberships.router)
app.include_router(role_grants.router)
app.include_router(surveys.router)
app.include_router(rollup.router)
