from fastapi import Request
from sqlalchemy import select

from database import SessionLocal
from models import OrganizationMember


def get_current_organization_id(request: Request) -> int | None:
    """
    Return the authenticated user's active organization.

    A session organization is always validated against OrganizationMember.
    If the user has exactly one membership, it may be selected automatically.
    If the user has multiple memberships and no valid active organization,
    return None so the caller can require an explicit organization choice.
    """
    user_id = request.session.get("user_id")
    if not user_id:
        return None

    session_org_id = request.session.get("organization_id")

    with SessionLocal() as session:
        if session_org_id is not None:
            try:
                organization_id = int(session_org_id)
            except (TypeError, ValueError):
                request.session.pop("organization_id", None)
            else:
                membership = session.execute(
                    select(OrganizationMember).where(
                        OrganizationMember.user_id == user_id,
                        OrganizationMember.organization_id == organization_id,
                    )
                ).scalar_one_or_none()

                if membership:
                    return membership.organization_id

                request.session.pop("organization_id", None)

        memberships = session.execute(
            select(OrganizationMember)
            .where(OrganizationMember.user_id == user_id)
            .order_by(OrganizationMember.id)
        ).scalars().all()

        if len(memberships) == 1:
            organization_id = memberships[0].organization_id
            request.session["organization_id"] = organization_id
            return organization_id

        return None


def user_belongs_to_organization(user_id: int, organization_id: int) -> bool:
    with SessionLocal() as session:
        return session.execute(
            select(OrganizationMember).where(
                OrganizationMember.user_id == user_id,
                OrganizationMember.organization_id == organization_id,
            )
        ).scalar_one_or_none() is not None
