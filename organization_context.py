from fastapi import Request
from sqlalchemy import select

from database import SessionLocal
from models import OrganizationMember


def get_current_organization_id(request: Request) -> int | None:
    """
    Return the organization currently associated with the logged-in user.

    The organization_id stored in the session is validated against the
    user's memberships. If it is missing or stale, the first membership
    is selected and stored in the session.
    """
    user_id = request.session.get("user_id")
    if not user_id:
        return None

    session_org_id = request.session.get("organization_id")

    with SessionLocal() as session:
        if session_org_id is not None:
            membership = session.execute(
                select(OrganizationMember).where(
                    OrganizationMember.user_id == user_id,
                    OrganizationMember.organization_id == int(session_org_id),
                )
            ).scalar_one_or_none()

            if membership:
                return membership.organization_id

        membership = session.execute(
            select(OrganizationMember)
            .where(OrganizationMember.user_id == user_id)
            .order_by(OrganizationMember.id)
        ).scalars().first()

        if not membership:
            return None

        request.session["organization_id"] = membership.organization_id
        return membership.organization_id


def user_belongs_to_organization(user_id: int, organization_id: int) -> bool:
    with SessionLocal() as session:
        return session.execute(
            select(OrganizationMember).where(
                OrganizationMember.user_id == user_id,
                OrganizationMember.organization_id == organization_id,
            )
        ).scalar_one_or_none() is not None
