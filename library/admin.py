from django.contrib import admin

from .models import DownloadAuditRecord, ReadingProgress

admin.site.register(ReadingProgress)
admin.site.register(DownloadAuditRecord)
