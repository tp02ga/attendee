from django.contrib.auth.models import AbstractUser
from django.db import models
import uuid
class Organization(models.Model):
    name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

class User(AbstractUser):
    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        null=False,
        related_name='users'
    )
        
    def __str__(self):
        return self.email

# Only added this to create an org for the admin user
from django.db.models.signals import pre_save
from django.dispatch import receiver
@receiver(pre_save, sender=User)
def create_default_organization(sender, instance, **kwargs):
    # Only run this for new users (not updates)
    if not instance.pk and not instance.organization_id:
        from bots.models import Bot

        default_org = Organization.objects.create(
            name=f"{instance.email}'s organization"
        )

        # Create default bot for the organization
        Bot.objects.create(
            name=f"{instance.email}'s Bot",
            organization=default_org
        )

        # There's some weird stuff going on with username field
        # we don't need it for anything, so we'll just set it to a random uuid
        # that will avoid violating the unique constraint
        instance.username = str(uuid.uuid4())

        instance.organization = default_org