# Book marketplace (Django)

Worldwide e-book marketplace: admin + approved authors sell PDF/EPUB books, customers preview, buy, read online and download. Fiction/Nonfiction separation, 20% commission ledger, payouts, dashboards.
Site name is configurable (Admin > Site settings).

**Status: code written but NOT yet executed.** It was produced in an environment that could not install Django, so migrations are not generated and tests have not run. Python files compile; everything else needs your first run.

## First run (local development)
```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                    # then edit values
python manage.py makemigrations accounts core catalog orders payments finance library engagement
python manage.py migrate
python manage.py bootstrap          # default categories, draft agreement, hero slide
python manage.py createsuperuser    # becomes the Administrator role automatically
python manage.py test               # run the automated tests first and fix anything that fails
python manage.py runserver
```
If `.env` has no DATABASE_URL, SQLite is used. For PostgreSQL set `DATABASE_URL=postgres://user:pass@localhost:5432/dbname`.

## Roles
- Customer: default. Apply at /accounts/become-an-author/.
- Author: approved by admin at Dashboard > Author applications.
- Administrator: superuser. Their own books publish instantly, carry no commission, and show in the separate "My book sales" dashboard.

## Payments (Paystack)
Set `PAYSTACK_SECRET_KEY` / `PAYSTACK_PUBLIC_KEY`. In the Paystack dashboard set the webhook URL to `https://YOURDOMAIN/payments/webhook/paystack/`. Orders become paid only after the server verifies the transaction with Paystack (status, amount, currency, reference). Check Paystack's current docs before launch; only NGN is enabled (`PAYMENT_SUPPORTED_CURRENCIES`).
Refunds: use Dashboard > Sales & refunds to reverse a sale (revokes access, reverses ledger), then complete the refund in Paystack.

## Money rules
Decimal only. Commission and fee shares are snapshotted per order item. Ledger is append-only (corrections are new entries). Payment-fee allocation (platform / seller / split) and commission rate are in Site settings; changes affect future sales only.

## Deployment
- `DJANGO_DEBUG=False`, strong `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS=https://yourdomain`.
- Paid book files must NOT live on a temporary disk: set `USE_S3=True` with a PRIVATE bucket (S3/R2/Spaces). Covers/logos in `media/` also need persistent storage in production.
- Commands for deployment: `pip install -r requirements.txt`, `python manage.py collectstatic --noinput`, `python manage.py migrate --noinput`, start with `gunicorn config.wsgi`. (`Procfile` included.)
- Use Redis/Memcached as the Django cache in multi-process production so rate limits are shared.
- Back up the database daily and the file bucket (versioning enabled).
- Never run destructive DB commands (flush, reset) on production.

## Smoke test after deploy
Register, log in, upload a book as author, approve as admin, buy with a Paystack test card, confirm library access, read, download, refund from the admin dashboard.

## Not built yet (future)
Book-poster generator, subscriptions (Entitlement.source is ready for it), more currencies/providers, email beyond console backend, automated provider payouts (payouts are admin-managed and recorded manually).

## Needs your attention before launch
Replace the draft author agreement and policy texts with legally reviewed ones. Commission/fee policy, tax, and privacy rules need legal review. The Paystack field names (`fees`, header names) should be checked against current docs.
