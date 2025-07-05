from allauth.account.adapter import DefaultAccountAdapter
from django.urls import reverse
from django.contrib.auth import login

class StandardAccountAdapter(DefaultAccountAdapter):
    def get_email_verification_redirect_url(self, email_address):
        user = email_address.user
        if getattr(user, "invited_by", None):
            return reverse("account_set_password")
        return super().get_email_verification_redirect_url(email_address)
    
    def confirm_email(self, request, email_address):
        """
        Marks the given email address as confirmed on the db and logs in the user
        if they were invited by someone else.
        """
        # Call the parent method to handle the confirmation
        super().confirm_email(request, email_address)
        
        # Log in the user if they were invited and not already authenticated
        user = email_address.user
        if user.invited_by and not request.user.is_authenticated:
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")

class NoNewUsersAccountAdapter(StandardAccountAdapter):
    def is_open_for_signup(self, request):
        return False
