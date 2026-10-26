from django import forms
from django.contrib.auth.forms import UserCreationForm

from .models import AuthorApplication, User


class RegisterForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = ("username", "email", "password1", "password2")

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email


class AuthorApplicationForm(forms.ModelForm):
    accept_agreement = forms.BooleanField(
        required=True, label="I have read and accept the current Author Agreement",
        error_messages={"required": "You must accept the Author Agreement to apply."},
    )

    class Meta:
        model = AuthorApplication
        fields = ("pen_name", "bio", "genres", "sample_url")
        labels = {"pen_name": "Author / pen name", "sample_url": "Link to a sample of your work (optional)"}
        widgets = {"bio": forms.Textarea(attrs={"rows": 5})}


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("display_name", "first_name", "last_name", "bio")
        widgets = {"bio": forms.Textarea(attrs={"rows": 4})}
