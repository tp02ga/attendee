from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from bots.models import Bot
from django.http import Http404

@login_required
def home(request):
    # Get the first bot for the user's organization
    bot = Bot.objects.filter(organization=request.user.organization).first()
    if bot:
        return redirect('bots:bot-dashboard', object_id=bot.object_id)
    raise Http404("No bots found for this organization. You need to create a bot first.")
