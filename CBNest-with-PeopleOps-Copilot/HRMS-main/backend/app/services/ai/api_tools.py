"""
Backend API tool wrappers.

CRITICAL ARCHITECTURE RULE: the AI agent must NEVER write to the database
directly. Every mutation goes:

    Agent -> this module -> existing FastAPI endpoint (over HTTP) -> DB

Every function forwards the CURRENT USER's own access_token, so all
existing auth/role/business-rule checks in the real endpoints (leaves.py,
tickets.py, announcements.py, employees.py) apply exactly as if the user
had called the API themselves through the normal UI. The agent gets no
elevated privileges and no bypass.
"""
import httpx

from app.core.config import settings

BASE_URL = settings.internal_api_base_url


def _headers(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}


def _safe_json(resp: httpx.Response) -> dict:
    try:
        return resp.json()
    except Exception:
        return {"detail": "Non-JSON response from backend API"}


async def create_leave_request(payload: dict, access_token: str) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(f"{BASE_URL}/leaves/requests", json=payload, headers=_headers(access_token))
    return {"status_code": resp.status_code, "body": _safe_json(resp)}


async def check_leave_balance(access_token: str) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{BASE_URL}/leaves/balances/me", headers=_headers(access_token))
    return {"status_code": resp.status_code, "body": _safe_json(resp)}


async def check_my_leave_requests(access_token: str) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{BASE_URL}/leaves/requests/me", headers=_headers(access_token))
    return {"status_code": resp.status_code, "body": _safe_json(resp)}


async def approve_leave_request(request_id: int, access_token: str) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(f"{BASE_URL}/leaves/requests/{request_id}/approve", headers=_headers(access_token))
    return {"status_code": resp.status_code, "body": _safe_json(resp)}


async def reject_leave_request(request_id: int, access_token: str) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(f"{BASE_URL}/leaves/requests/{request_id}/reject", headers=_headers(access_token))
    return {"status_code": resp.status_code, "body": _safe_json(resp)}


async def create_ticket(payload: dict, access_token: str) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(f"{BASE_URL}/tickets", json=payload, headers=_headers(access_token))
    return {"status_code": resp.status_code, "body": _safe_json(resp)}


async def check_my_tickets(access_token: str) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{BASE_URL}/tickets", params={"mine": "true"}, headers=_headers(access_token))
    return {"status_code": resp.status_code, "body": _safe_json(resp)}


async def update_ticket_status(ticket_id: int, status_value: str, access_token: str) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{BASE_URL}/tickets/{ticket_id}/status", json={"status": status_value}, headers=_headers(access_token)
        )
    return {"status_code": resp.status_code, "body": _safe_json(resp)}


async def assign_ticket(ticket_id: int, assignee_id: int, access_token: str) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{BASE_URL}/tickets/{ticket_id}/assign", json={"assignee_id": assignee_id}, headers=_headers(access_token)
        )
    return {"status_code": resp.status_code, "body": _safe_json(resp)}


async def create_announcement(payload: dict, access_token: str) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(f"{BASE_URL}/announcements", json=payload, headers=_headers(access_token))
    return {"status_code": resp.status_code, "body": _safe_json(resp)}


async def assign_employee_to_project(employee_id: int, payload: dict, access_token: str) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{BASE_URL}/employees/{employee_id}/projects", json=payload, headers=_headers(access_token)
        )
    return {"status_code": resp.status_code, "body": _safe_json(resp)}
