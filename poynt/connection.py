from dataclasses import dataclass
from datetime import datetime

from database import SessionLocal
from models import PoyntConnection


@dataclass
class PoyntCredentials:
    business_id: str
    access_token: str
    refresh_token: str | None
    token_type: str | None
    expires_at: datetime | None


def get_poynt_connection(user_id: int) -> PoyntConnection | None:
    """
    Return the Poynt connection belonging to a Codelian user.

    Returns None if the user has not connected Poynt.
    """

    with SessionLocal() as session:
        return session.query(PoyntConnection).filter(
            PoyntConnection.user_id == user_id
        ).one_or_none()


def get_poynt_credentials(
    user_id: int
) -> PoyntCredentials | None:
    """
    Retrieve the Poynt credentials associated with a Codelian user.

    Returns None if the user has not connected Poynt.
    """

    connection = get_poynt_connection(user_id)

    if not connection:
        return None

    return PoyntCredentials(
        business_id=connection.business_id,
        access_token=connection.access_token,
        refresh_token=connection.refresh_token,
        token_type=connection.token_type,
        expires_at=connection.expires_at,
    )


def save_poynt_connection(
    user_id: int,
    business_id: str,
    access_token: str,
    refresh_token: str | None,
    token_type: str | None,
    expires_at: datetime | None,
) -> None:
    """
    Create or update the Poynt connection for a Codelian user.
    """

    with SessionLocal() as session:

        connection = session.query(PoyntConnection).filter(
            PoyntConnection.user_id == user_id
        ).one_or_none()

        if connection:
            connection.business_id = business_id
            connection.access_token = access_token
            connection.refresh_token = refresh_token
            connection.token_type = token_type
            connection.expires_at = expires_at

        else:
            connection = PoyntConnection(
                user_id=user_id,
                business_id=business_id,
                access_token=access_token,
                refresh_token=refresh_token,
                token_type=token_type,
                expires_at=expires_at,
            )

            session.add(connection)

        session.commit()