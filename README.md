# Poynt Event Reports Application

run like this ```uvicorn main:app --reload```

Render Dashboard
https://dashboard.render.com/


Cloudflare Dashboard
https://dash.cloudflare.com/

app url
https://codelian-poynt.onrender.com/database-test

app url 
https://poynteventreports.onrender.com/database-test

Port 5432

## Account email configuration

Set these environment variables in Render:

- `POSTMARK_SERVER_TOKEN`: the Postmark server API token
- `EMAIL_FROM`: a sender address on a Postmark-verified domain
- `APP_BASE_URL`: the public origin, for example `https://foodtruckworks.com`

Before deploying account security changes, run `alembic upgrade head` against
the intended database. Revision `d4a1f6c82b30` creates the security-token table
and marks the accounts that exist at migration time as verified. Revision
`e7b2c4d91a60` adds the pending-email field used by the verified email-change
workflow. Revision `f1c3a8d72b40` adds account-level first and last names and
backfills users already linked to employee records. Review the target database
before running migrations. Do not store the Postmark token in this repository.

## Private organization registration

Production organization registration is closed to the general public. Set
`ORG_REGISTRATION_ACCESS_CODE` in Render to a randomly generated value of at
least 32 characters. Authorized production testing begins at
`/organization-registration-access`; successful entry opens `/register` for
that signed browser session for 30 minutes. Do not put the access code in a URL,
source code, logs, or this repository. Local development registration remains
available without the access code. Generate a suitable value with
`python -c "import secrets; print(secrets.token_urlsafe(32))"`.
