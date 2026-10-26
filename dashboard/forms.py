from decimal import Decimal

from django import forms

from finance.models import PayoutAccount, RefundRecord


class PayoutAccountForm(forms.ModelForm):
    class Meta:
        model = PayoutAccount
        fields = ("bank_name", "account_number", "account_name")

    def clean_account_number(self):
        number = self.cleaned_data["account_number"].replace(" ", "")
        if not number.isdigit() or not 6 <= len(number) <= 20:
            raise forms.ValidationError("Enter digits only (6 to 20 characters).")
        return number


class PayoutRequestForm(forms.Form):
    amount = forms.DecimalField(min_value=Decimal("0.01"), max_digits=12, decimal_places=2)


class PayoutActionForm(forms.Form):
    reference = forms.CharField(required=False, max_length=120, label="Transfer reference")
    note = forms.CharField(required=False, max_length=240)


class RejectForm(forms.Form):
    reason = forms.CharField(max_length=500, widget=forms.Textarea(attrs={"rows": 3}), label="Reason (sent to the author)")


class RefundForm(forms.Form):
    kind = forms.ChoiceField(choices=RefundRecord.Kind.choices)
    reason = forms.CharField(max_length=240)
    provider_reference = forms.CharField(required=False, max_length=120, label="Provider refund reference (optional)")


class AdjustmentForm(forms.Form):
    seller_email = forms.EmailField()
    amount = forms.DecimalField(max_digits=12, decimal_places=2, help_text="Use a negative amount to deduct.")
    reason = forms.CharField(max_length=240)
