import re

from allauth.account.models import EmailAddress
from django.core import mail
from django.test import Client, TransactionTestCase
from django.urls import reverse

from accounts.models import User
from bots.models import Project


class UserSignupIntegrationTest(TransactionTestCase):
    """Integration test for the complete user signup flow"""

    def setUp(self):
        """Set up test environment"""
        # Test data
        self.signup_email = "newuser@example.com"
        self.password = "testpassword123"

        # Create test client
        self.client = Client()

        # Clear any existing emails
        mail.outbox = []

    def test_user_signup_happy_path(self):
        """Test the complete happy path of user signup"""

        # Step 1: Submit signup form
        signup_url = reverse("account_signup")
        response = self.client.post(
            signup_url,
            {
                "email": self.signup_email,
                "password1": self.password,
                "password2": self.password,
            },
        )

        # Should redirect to verification sent page
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("account_email_verification_sent"))

        # Verify user was created but not yet active/verified
        user = User.objects.get(email=self.signup_email)
        self.assertIsNotNone(user)
        self.assertIsNone(user.invited_by)  # Not an invited user
        self.assertIsNotNone(user.organization)  # Organization should be created
        self.assertTrue(user.is_active)  # User should be active

        # Verify organization and project were created
        organization = user.organization
        self.assertIn(self.signup_email, organization.name)

        # Verify default project was created
        project = Project.objects.get(organization=organization)
        self.assertIn(self.signup_email, project.name)

        # Verify verification email was sent
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertEqual(email.to, [self.signup_email])
        self.assertIn("confirm", email.body.lower())
        self.assertNotIn("invited you to join", email.body)  # Should not be invitation email

        # Step 2: Extract confirmation URL from email and visit it
        email_body = email.body
        url_pattern = r"http://testserver(/accounts/confirm-email/[^/\s]+/)"
        match = re.search(url_pattern, email_body)
        self.assertIsNotNone(match, "Email confirmation URL not found in email body")

        confirmation_url = match.group(1)

        # Visit the confirmation URL
        response = self.client.get(confirmation_url)

        # Should redirect to login page since this is a normal signup (not invited)
        self.assertEqual(response.status_code, 302)
        # The StandardAccountAdapter should redirect to parent's get_email_verification_redirect_url
        # which typically redirects to settings.LOGIN_REDIRECT_URL or login page

        # Verify user's last_login is set (since ACCOUNT_LOGIN_ON_EMAIL_CONFIRMATION is True)
        user.refresh_from_db()
        self.assertIsNotNone(user.last_login)

        # Verify user's email is confirmed
        email_address = EmailAddress.objects.get(user=user, email=self.signup_email)
        self.assertTrue(email_address.verified)

        # Step 3: Test that user can log in and is redirected to dashboard
        login_url = reverse("account_login")
        response = self.client.post(
            login_url,
            {
                "login": self.signup_email,
                "password": self.password,
            },
        )

        # Should redirect to home page
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, "/", target_status_code=302)

        # Verify the redirect to home goes to the project dashboard
        response = self.client.get("/")
        expected_dashboard_url = reverse("projects:project-dashboard", kwargs={"object_id": project.object_id})
        self.assertRedirects(response, expected_dashboard_url)

        # Verify user can access the dashboard
        response = self.client.get(expected_dashboard_url)
        self.assertEqual(response.status_code, 200)

    def test_user_signup_password_mismatch(self):
        """Test that signup fails when passwords don't match"""
        signup_url = reverse("account_signup")
        response = self.client.post(
            signup_url,
            {
                "email": self.signup_email,
                "password1": self.password,
                "password2": "differentpassword123",
            },
        )

        # Should return form with error
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "password")

        # No user should be created
        self.assertFalse(User.objects.filter(email=self.signup_email).exists())

        # No email should be sent
        self.assertEqual(len(mail.outbox), 0)

    def test_user_signup_missing_fields(self):
        """Test that signup fails when required fields are missing"""
        signup_url = reverse("account_signup")

        # Test missing email
        response = self.client.post(
            signup_url,
            {
                "password1": self.password,
                "password2": self.password,
            },
        )

        # Should return form with error
        self.assertEqual(response.status_code, 200)

        # No user should be created
        self.assertFalse(User.objects.filter(email=self.signup_email).exists())

        # No email should be sent
        self.assertEqual(len(mail.outbox), 0)

    def test_user_signup_weak_password(self):
        """Test that signup fails with weak password"""
        signup_url = reverse("account_signup")
        weak_password = "123"  # Too short and common

        response = self.client.post(
            signup_url,
            {
                "email": self.signup_email,
                "password1": weak_password,
                "password2": weak_password,
            },
        )

        # Should return form with error
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "password")

        # No user should be created
        self.assertFalse(User.objects.filter(email=self.signup_email).exists())

        # No email should be sent
        self.assertEqual(len(mail.outbox), 0)

    def test_user_signup_invalid_email(self):
        """Test that signup fails with invalid email format"""
        signup_url = reverse("account_signup")

        response = self.client.post(
            signup_url,
            {
                "email": "invalid-email",
                "password1": self.password,
                "password2": self.password,
            },
        )

        # Should return form with error
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "email")

        # No user should be created
        self.assertFalse(User.objects.filter(email="invalid-email").exists())

        # No email should be sent
        self.assertEqual(len(mail.outbox), 0)

    def test_signup_when_disabled(self):
        """Test that signup is disabled when DISABLE_SIGNUP is set"""
        with self.settings(ACCOUNT_ADAPTER="accounts.adapters.NoNewUsersAccountAdapter"):
            signup_url = reverse("account_signup")
            response = self.client.get(signup_url)

            # Should return 200 and show page with signup closed message
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "We are sorry, but the sign up is currently closed")
            self.assertContains(response, "Sign Up Closed")
