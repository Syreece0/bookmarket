from django.core.management.base import BaseCommand

from accounts.models import AuthorAgreement
from catalog.models import Category
from core.models import HeroSlide, SiteSettings

FICTION = [
    ("Fantasy", "Fantasy books involve magic, creatures, quests, and battles between good and evil."),
    ("Drama", "Drama often portrays complex and conflicting human emotions, relationships, and situations."),
    ("Mystery & Thriller", "Puzzles, suspense and investigations that keep the pages turning."),
    ("Romance", "Stories of love, longing and connection."),
    ("Science Fiction", "Speculative worlds shaped by science and technology."),
]
NONFICTION = [
    ("Biography", "Biography is an accurate, comprehensive portrayal of subjects in compelling narratives."),
    ("Self-Help", "Practical guidance for growth, habits and wellbeing."),
    ("Business", "Entrepreneurship, leadership, money and careers."),
    ("History", "Events, people and ideas that shaped the world."),
    ("Science & Nature", "Explanations of how the world works."),
]

AGREEMENT_BODY = """DRAFT AUTHOR AGREEMENT: REPLACE WITH LEGALLY REVIEWED TEXT BEFORE LAUNCH.

1. You confirm that you own, or have the right to sell, every book you upload.
2. You grant the platform a non-exclusive licence to host, display, preview and deliver your books to buyers.
3. The platform retains a commission on each sale, as stated in this agreement, before any separately allocated payment-processing fees or adjustments.
4. Earnings become withdrawable after the payout hold period shown in your dashboard, subject to the minimum payout and verification of your payout details.
5. Refunds, chargebacks and policy violations may reverse earnings and remove a buyer's access.
6. Digital content cannot be made completely immune to copying; you accept this limitation.
7. The platform may reject or remove content that breaches the law or its content guidelines.
"""


class Command(BaseCommand):
    help = "Create default site settings, categories, a draft author agreement and a starter hero slide (safe to re-run)."

    def handle(self, *args, **options):
        SiteSettings.load()
        for kind, rows in ((Category.Kind.FICTION, FICTION), (Category.Kind.NONFICTION, NONFICTION)):
            for order, (name, desc) in enumerate(rows):
                Category.objects.get_or_create(name=name, parent=None, defaults={"kind": kind, "description": desc, "order": order, "is_featured": True})
        if not AuthorAgreement.objects.exists():
            AuthorAgreement.objects.create(version=1, body=AGREEMENT_BODY, is_active=True)
        if not HeroSlide.objects.exists():
            HeroSlide.objects.create(title="Discover your next great read", subtitle="Fiction and nonfiction from independent authors, in your library forever.", cta_text="Explore", cta_url="/books/")
        self.stdout.write(self.style.SUCCESS("Bootstrap complete."))
