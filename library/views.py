import json
from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from catalog.models import Book
from core.ratelimit import client_ip, ratelimit
from orders.models import Entitlement

from .models import DownloadAuditRecord, ReadingProgress


def _authorised_book(user, slug):
    """Server-side gate for every private file: authenticated + active entitlement + eligible book.
    Hidden buttons or obscure URLs are never relied upon."""
    book = get_object_or_404(Book, slug=slug)
    if book.status == Book.Status.ARCHIVED and not Entitlement.objects.active().filter(user=user, book=book).exists():
        raise Http404
    owns = Entitlement.objects.active().filter(user=user, book=book).exists()
    if not owns:
        raise PermissionDenied
    return book


@login_required
def home(request):
    ents = (
        Entitlement.objects.active().filter(user=request.user)
        .select_related("book", "book__seller", "book__category").order_by("-granted_at")
    )
    progress = {p.book_id: p for p in ReadingProgress.objects.filter(user=request.user)}
    rows = [{"ent": e, "book": e.book, "progress": progress.get(e.book_id)} for e in ents]
    return render(request, "library/home.html", {"rows": rows})


@login_required
def read(request, slug):
    book = _authorised_book(request.user, slug)
    progress = ReadingProgress.objects.filter(user=request.user, book=book).first()
    return render(request, "library/read_epub.html" if book.file_format == Book.Format.EPUB else "library/read_pdf.html",
                  {"book": book, "progress": progress})


@login_required
def stream(request, slug):
    """Streams the file to the in-browser reader. The real storage path is never revealed."""
    book = _authorised_book(request.user, slug)
    ctype = "application/pdf" if book.file_format == Book.Format.PDF else "application/epub+zip"
    resp = FileResponse(book.file.open("rb"), content_type=ctype)
    resp["Content-Disposition"] = "inline"
    resp["Cache-Control"] = "private, no-store"
    resp["X-Content-Type-Options"] = "nosniff"
    return resp


@login_required
@ratelimit("download", limit=30, window=3600, methods=("GET",))
def download(request, slug):
    book = _authorised_book(request.user, slug)
    DownloadAuditRecord.objects.create(user=request.user, book=book, ip_address=client_ip(request))
    from django.conf import settings

    if settings.USE_S3:
        # Short-lived signed URL (lifetime set by AWS_QUERYSTRING_EXPIRE); the bucket itself stays private.
        return HttpResponseRedirect(book.file.storage.url(book.file.name, expire=120))
    resp = FileResponse(book.file.open("rb"), as_attachment=True, filename=f"{book.slug}.{book.file_format}")
    resp["Cache-Control"] = "private, no-store"
    return resp


@login_required
@require_POST
def save_progress(request, slug):
    book = _authorised_book(request.user, slug)
    try:
        body = json.loads(request.body or b"{}")
        percent = max(Decimal("0"), min(Decimal("100"), Decimal(str(body.get("percent", 0)))))
    except (ValueError, InvalidOperation):
        return JsonResponse({"ok": False}, status=400)
    font = body.get("font_scale", 100)
    font = int(font) if str(font).isdigit() and 70 <= int(font) <= 220 else 100
    ReadingProgress.objects.update_or_create(
        user=request.user, book=book,
        defaults={"location": str(body.get("location", ""))[:300], "percent": percent.quantize(Decimal("0.01")), "font_scale": font},
    )
    return JsonResponse({"ok": True})
