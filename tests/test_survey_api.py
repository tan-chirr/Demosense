"""API-level survey tests against the real DB (Neon), same pattern as
test_rbac.py: route handlers commit directly, so each test's fixture tears
down exactly what it created rather than relying on a rolled-back transaction.
"""

import uuid

import pytest_asyncio
from sqlalchemy import delete

from demosense.db import SessionLocal
from demosense.models.org import OrgUnit
from demosense.models.person import Person
from demosense.models.survey import Survey


@pytest_asyncio.fixture
async def survey_world(client, superuser_token):
    """A throwaway national org unit + a 5-question test survey (mirrors the
    real Hometown Survey's question kinds) + two registered members.
    """
    tag = uuid.uuid4().hex[:8]
    headers = {"Authorization": f"Bearer {superuser_token}"}

    resp = await client.post(
        "/org-units",
        headers=headers,
        json={"level": "national", "name": "Survey Test Root", "slug": f"survtest_{tag}"},
    )
    assert resp.status_code == 201, resp.text
    org_unit_id = resp.json()["id"]

    async with SessionLocal() as session:
        survey = Survey(
            title=f"Test Survey {tag}",
            description="throwaway test survey",
            status="open",
            respondent="person",
            target_org_unit_id=org_unit_id,
        )
        session.add(survey)
        await session.flush()
        survey_id = str(survey.id)

        from demosense.models.survey import Question

        questions = {
            "town_name": Question(
                survey_id=survey.id, ordinal=1, kind="text", prompt="Town Name", is_required=True
            ),
            "condition": Question(
                survey_id=survey.id,
                ordinal=2,
                kind="ordinal",
                prompt="Condition (1-5)",
                is_required=True,
                config={"min": 1, "max": 5},
            ),
            "internet": Question(
                survey_id=survey.id,
                ordinal=3,
                kind="multi_choice",
                prompt="Internet provider",
                config={"options": ["satellite", "cable", "other"]},
            ),
            "notes": Question(survey_id=survey.id, ordinal=4, kind="text", prompt="Notes"),
        }
        for q in questions.values():
            session.add(q)
        await session.flush()
        question_ids = {k: str(v.id) for k, v in questions.items()}
        await session.commit()

    async def register(email, password, first, last):
        resp = await client.post(
            "/auth/register",
            json={"email": email, "password": password, "first_name": first, "last_name": last},
        )
        assert resp.status_code == 201, resp.text
        person_id = resp.json()["id"]
        resp = await client.post("/auth/jwt/login", data={"username": email, "password": password})
        assert resp.status_code == 200, resp.text
        return person_id, resp.json()["access_token"]

    person_a_id, token_a = await register(f"survey_a_{tag}@democlub.dev", "PassA123!", "A", "Survey")
    person_b_id, token_b = await register(f"survey_b_{tag}@democlub.dev", "PassB123!", "B", "Survey")

    yield {
        "org_unit_id": org_unit_id,
        "survey_id": survey_id,
        "question_ids": question_ids,
        "token_a": token_a,
        "token_b": token_b,
        "person_a_id": person_a_id,
        "person_b_id": person_b_id,
    }

    async with SessionLocal() as session:
        await session.execute(delete(Person).where(Person.id.in_([person_a_id, person_b_id])))
        await session.execute(delete(Survey).where(Survey.id == survey_id))  # cascades questions/responses
        await session.execute(delete(OrgUnit).where(OrgUnit.id == org_unit_id))
        await session.commit()


async def test_full_fill_and_submit_flow(client, survey_world):
    headers = {"Authorization": f"Bearer {survey_world['token_a']}"}
    q = survey_world["question_ids"]

    resp = await client.post(
        f"/surveys/{survey_world['survey_id']}/responses",
        headers=headers,
        json={"org_unit_id": survey_world["org_unit_id"]},
    )
    assert resp.status_code == 201, resp.text
    response = resp.json()
    assert response["person_id"] == survey_world["person_a_id"]
    assert response["is_complete"] is False
    response_id = response["id"]

    # partial save - only one of two required questions
    resp = await client.patch(
        f"/responses/{response_id}/answers",
        headers=headers,
        json={"answers": [{"question_id": q["town_name"], "value_text": "Goleta"}]},
    )
    assert resp.status_code == 200, resp.text

    # submit before all required questions answered -> rejected
    resp = await client.post(f"/responses/{response_id}/submit", headers=headers)
    assert resp.status_code == 422

    # finish the required question, plus an optional multi_choice one
    resp = await client.patch(
        f"/responses/{response_id}/answers",
        headers=headers,
        json={
            "answers": [
                {"question_id": q["condition"], "value_numeric": 4},
                {"question_id": q["internet"], "value_choice": ["cable", "other"]},
            ]
        },
    )
    assert resp.status_code == 200, resp.text

    resp = await client.post(f"/responses/{response_id}/submit", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["is_complete"] is True
    assert resp.json()["submitted_at"] is not None

    # further edits after submission are rejected
    resp = await client.patch(
        f"/responses/{response_id}/answers",
        headers=headers,
        json={"answers": [{"question_id": q["notes"], "value_text": "too late"}]},
    )
    assert resp.status_code == 422


async def test_out_of_range_ordinal_rejected(client, survey_world):
    headers = {"Authorization": f"Bearer {survey_world['token_a']}"}
    q = survey_world["question_ids"]

    resp = await client.post(
        f"/surveys/{survey_world['survey_id']}/responses",
        headers=headers,
        json={"org_unit_id": survey_world["org_unit_id"]},
    )
    response_id = resp.json()["id"]

    resp = await client.patch(
        f"/responses/{response_id}/answers",
        headers=headers,
        json={"answers": [{"question_id": q["condition"], "value_numeric": 99}]},
    )
    assert resp.status_code == 422


async def test_org_unit_outside_survey_scope_rejected(client, survey_world, superuser_token):
    headers = {"Authorization": f"Bearer {survey_world['token_a']}"}

    # a fresh, unrelated org unit tree (not under this survey's target)
    other = await client.post(
        "/org-units",
        headers={"Authorization": f"Bearer {superuser_token}"},
        json={"level": "national", "name": "Unrelated Root", "slug": f"unrelated_{uuid.uuid4().hex[:8]}"},
    )
    assert other.status_code == 201

    resp = await client.post(
        f"/surveys/{survey_world['survey_id']}/responses",
        headers=headers,
        json={"org_unit_id": other.json()["id"]},
    )
    assert resp.status_code == 422

    async with SessionLocal() as session:
        await session.execute(delete(OrgUnit).where(OrgUnit.id == other.json()["id"]))
        await session.commit()


async def test_person_b_cannot_read_person_as_response(client, survey_world):
    headers_a = {"Authorization": f"Bearer {survey_world['token_a']}"}
    headers_b = {"Authorization": f"Bearer {survey_world['token_b']}"}

    resp = await client.post(
        f"/surveys/{survey_world['survey_id']}/responses",
        headers=headers_a,
        json={"org_unit_id": survey_world["org_unit_id"]},
    )
    response_id = resp.json()["id"]

    resp = await client.get(f"/responses/{response_id}", headers=headers_b)
    assert resp.status_code == 403

    resp = await client.patch(
        f"/responses/{response_id}/answers",
        headers=headers_b,
        json={"answers": []},
    )
    assert resp.status_code == 403


async def test_anonymous_response_has_no_person_id(client, survey_world):
    headers = {"Authorization": f"Bearer {survey_world['token_a']}"}

    resp = await client.post(
        f"/surveys/{survey_world['survey_id']}/responses",
        headers=headers,
        json={"org_unit_id": survey_world["org_unit_id"], "anonymous": True},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["person_id"] is None
    assert resp.json()["group_ids"] == []


async def test_unauthenticated_cannot_start_response(client, survey_world):
    resp = await client.post(
        f"/surveys/{survey_world['survey_id']}/responses",
        json={"org_unit_id": survey_world["org_unit_id"]},
    )
    assert resp.status_code == 401
