"""Production safeguard: no approvals or rejections until verified authentication exists.

Ledgerline does not authenticate anyone yet. The approver's name and the organisation are whatever the caller sends,
so "two approvers" proves two names, not two people (README, "Known limitation"). Until identity and roles come from
Meridian's SSO and are verified on the server, approve and reject are allowed only in local development:
LEDGERLINE_ENV=development AND a request from this machine. Everywhere else they are refused (403), including when
LEDGERLINE_ENV is unset, which counts as production.

There is deliberately no setting that enables approvals in production. Lifting this safeguard requires implementing
verified authentication and role-based authorization, a code change. Note: behind a reverse proxy on the same host,
every caller looks local, so LEDGERLINE_ENV=development must never be set on a shared or production server.
"""
from __future__ import annotations

import os

from fastapi import HTTPException, Request

DEVELOPMENT = "development"
LOCAL_CLIENTS = {"127.0.0.1", "::1", "testclient"}  # "testclient" is FastAPI's in-process test client

REFUSAL = ("Approvals and rejections are disabled: Ledgerline has no verified authentication or role-based "
           "authorization yet, so it cannot tell who is approving. Approve in Meridian's existing process. "
           "(Allowed only in local development; see README, 'Known limitation'.)")


def approvals_allowed(environment: str | None, client_host: str | None) -> bool:
    return environment == DEVELOPMENT and client_host in LOCAL_CLIENTS


def require_local_development(request: Request) -> None:
    """FastAPI dependency on the approve and reject endpoints."""
    host = request.client.host if request.client else None
    if not approvals_allowed(os.getenv("LEDGERLINE_ENV"), host):
        raise HTTPException(status_code=403, detail=REFUSAL)
