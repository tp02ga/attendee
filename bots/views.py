from django.shortcuts import render, get_object_or_404, redirect
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from .models import BotSession, BotSessionStates, BotSessionEvent, BotSessionEventManager, AnalysisTask, AnalysisTaskTypes, AnalysisTaskSubTypes, Utterance, Participant, Bot, BotCredentials
from .serializers import CreateSessionSerializer, SessionSerializer
from .authentication import ApiKeyAuthentication
from .tasks import run_bot_session
import redis
import json
import os
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views import View
from django.urls import reverse
from django.template.loader import render_to_string
from django.http import HttpResponse
from .models import ApiKey

class BotUrlContextMixin:
    def get_bot_context(self, object_id, bot):
        return {
            'bot': bot,
        }

class BotDashboardView(LoginRequiredMixin, BotUrlContextMixin, View):
    def get(self, request, object_id):
        try:
            bot = get_object_or_404(Bot, 
                object_id=object_id,
                organization=request.user.organization
            )
        except:
            return redirect('/')
            
        # Quick start guide status checks
        zoom_credentials = BotCredentials.objects.filter(
            bot=bot,
            credential_type=BotCredentials.CredentialTypes.ZOOM_OAUTH
        ).exists()
        
        deepgram_credentials = BotCredentials.objects.filter(
            bot=bot,
            credential_type=BotCredentials.CredentialTypes.DEEPGRAM
        ).exists()
        
        has_api_keys = ApiKey.objects.filter(bot=bot).exists()
        
        has_completed_sessions = BotSession.objects.filter(
            bot=bot,
            state=BotSessionStates.ENDED
        ).exists()
        
        context = self.get_bot_context(object_id, bot)
        context.update({
            'quick_start': {
                'has_credentials': zoom_credentials and deepgram_credentials,
                'has_api_keys': has_api_keys,
                'has_completed_sessions': has_completed_sessions,
            }
        })
        
        return render(request, 'bots/bot_dashboard.html', context)

class BotLogsView(LoginRequiredMixin, BotUrlContextMixin, View):
    def get(self, request, object_id):
        bot = get_object_or_404(Bot, 
            object_id=object_id,
            organization=request.user.organization
        )
        return render(request, 'bots/bot_logs.html', self.get_bot_context(object_id, bot))

class BotApiKeysView(LoginRequiredMixin, BotUrlContextMixin, View):
    def get(self, request, object_id):
        bot = get_object_or_404(Bot, 
            object_id=object_id,
            organization=request.user.organization
        )
        context = self.get_bot_context(object_id, bot)
        context['api_keys'] = ApiKey.objects.filter(bot=bot).order_by('-created_at')
        return render(request, 'bots/bot_api_keys.html', context)

class CreateApiKeyView(LoginRequiredMixin, View):
    def post(self, request, object_id):
        bot = get_object_or_404(Bot, 
            object_id=object_id,
            organization=request.user.organization
        )
        name = request.POST.get('name')
        
        if not name:
            return HttpResponse("Name is required", status=400)
            
        api_key_instance, api_key = ApiKey.create(bot=bot, name=name)
        
        # Render the success modal content
        return render(request, 'bots/partials/api_key_created_modal.html', {
            'api_key': api_key,
            'name': name
        })

class DeleteApiKeyView(LoginRequiredMixin, BotUrlContextMixin, View):
    def delete(self, request, object_id, key_object_id):
        api_key = get_object_or_404(ApiKey, 
            object_id=key_object_id,
            bot__organization=request.user.organization
        )
        api_key.delete()
        context = self.get_bot_context(object_id, api_key.bot)
        context['api_keys'] = ApiKey.objects.filter(bot=api_key.bot).order_by('-created_at')
        return render(request, 'bots/bot_api_keys.html', context)

class RedirectToDashboardView(LoginRequiredMixin, View):
    def get(self, request, object_id, extra=None):
        return redirect('bots:bot-dashboard', object_id=object_id)

class CreateBotCredentialsView(LoginRequiredMixin, BotUrlContextMixin, View):
    def post(self, request, object_id):
        bot = get_object_or_404(Bot, 
            object_id=object_id,
            organization=request.user.organization
        )

        try:
            credential_type = int(request.POST.get('credential_type'))
            if credential_type not in [choice[0] for choice in BotCredentials.CredentialTypes.choices]:
                return HttpResponse('Invalid credential type', status=400)

            # Get or create the credential instance
            credential, created = BotCredentials.objects.get_or_create(
                bot=bot,
                credential_type=credential_type
            )

            # Parse the credentials data based on type
            if credential_type == BotCredentials.CredentialTypes.ZOOM_OAUTH:
                credentials_data = {
                    'client_id': request.POST.get('client_id'),
                    'client_secret': request.POST.get('client_secret')
                }
                
                if not all(credentials_data.values()):
                    return HttpResponse('Missing required credentials data', status=400)

            elif credential_type == BotCredentials.CredentialTypes.DEEPGRAM:
                credentials_data = {
                    'api_key': request.POST.get('api_key')
                }
                
                if not all(credentials_data.values()):
                    return HttpResponse('Missing required credentials data', status=400)

            else:
                return HttpResponse('Unsupported credential type', status=400)

            # Store the encrypted credentials
            credential.set_credentials(credentials_data)

            # Return the entire settings page with updated context
            context = self.get_bot_context(object_id, bot)
            context['credentials'] = credential.get_credentials()
            context['credential_type'] = credential.credential_type
            if credential.credential_type == BotCredentials.CredentialTypes.ZOOM_OAUTH:
                return render(request, 'bots/partials/zoom_credentials.html', context)
            elif credential.credential_type == BotCredentials.CredentialTypes.DEEPGRAM:
                return render(request, 'bots/partials/deepgram_credentials.html', context)

        except Exception as e:
            return HttpResponse(str(e), status=400)

class BotSettingsView(LoginRequiredMixin, BotUrlContextMixin, View):
    def get(self, request, object_id):
        bot = get_object_or_404(Bot, 
            object_id=object_id,
            organization=request.user.organization
        )
        
        # Try to get existing credentials
        zoom_credentials = BotCredentials.objects.filter(
            bot=bot,
            credential_type=BotCredentials.CredentialTypes.ZOOM_OAUTH
        ).first()

        deepgram_credentials = BotCredentials.objects.filter(
            bot=bot,
            credential_type=BotCredentials.CredentialTypes.DEEPGRAM
        ).first()

        context = self.get_bot_context(object_id, bot)
        context.update({
            'zoom_credentials': zoom_credentials.get_credentials() if zoom_credentials else None,
            'zoom_credential_type': BotCredentials.CredentialTypes.ZOOM_OAUTH,
            'deepgram_credentials': deepgram_credentials.get_credentials() if deepgram_credentials else None,
            'deepgram_credential_type': BotCredentials.CredentialTypes.DEEPGRAM,
        })
        
        return render(request, 'bots/bot_settings.html', context)