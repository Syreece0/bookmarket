from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.db import transaction
from django.shortcuts import redirect, render
from django.utils.decorators import method_decorator

from core.ratelimit import client_ip, ratelimit

from .forms import AuthorApplicationForm, ProfileForm, RegisterForm
from .models import AuthorAgreement, AuthorAgreementAcceptance, AuthorApplication


@method_decorator(ratelimit("login", limit=10, window=300), name="dispatch")
class RateLimitedLoginView(LoginView):
    template_name = "registration/login.html"
    redirect_authenticated_user = True


@ratelimit("register", limit=10, window=3600)
def register(request):
    if request.user.is_authenticated:
        return redirect("core:home")
    form = RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, "Welcome! Your account has been created.")
        return redirect("core:home")
    return render(request, "registration/register.html", {"form": form})


@login_required
def profile(request):
    form = ProfileForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Profile updated.")
        return redirect("accounts:profile")
    pending = request.user.author_applications.filter(status=AuthorApplication.Status.PENDING).first()
    return render(request, "accounts/profile.html", {"form": form, "pending_application": pending})


@login_required
def become_author(request):
    user = request.user
    if user.can_sell:
        messages.info(request, "You can already sell books.")
        return redirect("dashboard:home")
    agreement = AuthorAgreement.current()
    pending = user.author_applications.filter(status=AuthorApplication.Status.PENDING).first()
    if pending:
        return render(request, "accounts/application_status.html", {"application": pending})
    if agreement is None:
        return render(request, "accounts/application_unavailable.html")
    form = AuthorApplicationForm(request.POST or None, initial={"pen_name": user.public_name})
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            application = form.save(commit=False)
            application.user = user
            application.save()
            AuthorAgreementAcceptance.objects.get_or_create(
                user=user, agreement=agreement,
                defaults={"application": application, "ip_address": client_ip(request)},
            )
        messages.success(request, "Application submitted. We will notify you once it has been reviewed.")
        return redirect("accounts:become_author")
    return render(request, "accounts/become_author.html", {"form": form, "agreement": agreement})
