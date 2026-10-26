"""File validation, metadata extraction and preview generation for uploaded books."""
import io
import posixpath
import xml.etree.ElementTree as ET
import zipfile

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from PIL import Image
from pypdf import PdfReader, PdfWriter

PDF_MAGIC = b"%PDF-"


def _read_head(upload, n=8):
    upload.seek(0)
    head = upload.read(n)
    upload.seek(0)
    return head


def inspect_book_file(upload):
    """Validate an uploaded PDF/EPUB by content (not just extension). Return (format, page_count)."""
    name = (upload.name or "").lower()
    if name.endswith(".pdf"):
        if not _read_head(upload).startswith(PDF_MAGIC):
            raise ValidationError("This file is not a valid PDF.")
        try:
            upload.seek(0)
            reader = PdfReader(upload)
            if reader.is_encrypted:
                raise ValidationError("Password-protected PDFs are not supported. Please upload an unlocked file.")
            pages = len(reader.pages)
        except ValidationError:
            raise
        except Exception:
            raise ValidationError("We could not read this PDF. It may be corrupted.")
        finally:
            upload.seek(0)
        if pages < 1:
            raise ValidationError("This PDF has no pages.")
        return "pdf", pages
    if name.endswith(".epub"):
        upload.seek(0)
        try:
            with zipfile.ZipFile(upload) as zf:
                names = zf.namelist()
                if "mimetype" not in names or zf.read("mimetype").strip() != b"application/epub+zip":
                    raise ValidationError("This file is not a valid EPUB.")
                if "META-INF/container.xml" not in names:
                    raise ValidationError("This EPUB is missing its container file.")
                container = ET.fromstring(zf.read("META-INF/container.xml"))
                rootfile = next((e for e in container.iter() if e.tag.endswith("rootfile")), None)
                if rootfile is None:
                    raise ValidationError("This EPUB has no package document.")
                opf_path = rootfile.attrib["full-path"]
                opf = ET.fromstring(zf.read(opf_path))
                spine_items = [e for e in opf.iter() if e.tag.endswith("itemref")]
                # EPUBs are reflowable, so a true page count does not exist: we store the section count.
                count = len(spine_items) or 1
                _ = posixpath.dirname(opf_path)
        except ValidationError:
            raise
        except (zipfile.BadZipFile, KeyError, ET.ParseError):
            raise ValidationError("We could not read this EPUB. It may be corrupted.")
        finally:
            upload.seek(0)
        return "epub", count
    raise ValidationError("Only PDF and EPUB files are accepted.")


def build_pdf_preview(upload, pages):
    """Return a ContentFile containing the first `pages` pages of a PDF, or None."""
    if pages <= 0:
        return None
    upload.seek(0)
    reader = PdfReader(upload)
    writer = PdfWriter()
    for page in reader.pages[: min(pages, len(reader.pages))]:
        writer.add_page(page)
    buf = io.BytesIO()
    writer.write(buf)
    upload.seek(0)
    return ContentFile(buf.getvalue())


def optimise_cover(image_field_file, max_side=900):
    """Downscale large covers and convert to RGB JPEG to keep pages fast."""
    img = Image.open(image_field_file)
    img = img.convert("RGB")
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85, optimize=True)
    return ContentFile(buf.getvalue())
