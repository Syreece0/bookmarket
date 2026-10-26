from datetime import date, datetime, time, timedelta

from django.utils import timezone

PERIODS = [
    ("today", "Today"),
    ("7d", "Last 7 days"),
    ("month", "This month"),
    ("prev_month", "Previous month"),
    ("year", "This year"),
    ("custom", "Custom range"),
    ("all", "All time"),
]


def _aware(d, end=False):
    t = time.max if end else time.min
    return timezone.make_aware(datetime.combine(d, t))


def resolve_period(request):
    """Return (key, label, start_dt|None, end_dt|None) from ?period=, ?start=, ?end=."""
    key = request.GET.get("period", "month")
    today = timezone.localdate()
    if key == "today":
        start, end = today, today
    elif key == "7d":
        start, end = today - timedelta(days=6), today
    elif key == "prev_month":
        first_this = today.replace(day=1)
        end = first_this - timedelta(days=1)
        start = end.replace(day=1)
    elif key == "year":
        start, end = date(today.year, 1, 1), today
    elif key == "custom":
        try:
            start = date.fromisoformat(request.GET.get("start", ""))
            end = date.fromisoformat(request.GET.get("end", ""))
        except ValueError:
            key, start, end = "month", today.replace(day=1), today
        if start > end:
            start, end = end, start
    elif key == "all":
        return key, "All time", None, None
    else:
        key, start, end = "month", today.replace(day=1), today
    label = dict(PERIODS)[key]
    return key, label, _aware(start), _aware(end, end=True)
