from django.shortcuts import render
from job_config.models import JobConfiguration, AuthUserToken
from django.utils import timezone
from decouple import config
import datetime
import json
import requests

class AuthTokenView:

    def get_token(self):
        auth_token = AuthUserToken.objects.filter(provider='GoBolt')
        if auth_token.exists():
            auth_token = auth_token.first()
            if auth_token.updated_at + datetime.timedelta(seconds=auth_token.expire_time) < timezone.now():
                auth_token = self.refresh_auth_token(auth_token)
                return auth_token.token
            return auth_token.token
        else:
            token_obj = self.create_auth_token()
            if token_obj:
                return token_obj.token
            else:
                return ''

    def auth_post_request(self):
        try:
            GoBolt_URL = JobConfiguration.objects.get(config_name='GOBOLT.GOBOLT_URL').config_value
            GRANT_TYPE = JobConfiguration.objects.get(config_name='GOBOLT.GRANT_TYPE').config_value
            CLIENT_ID = JobConfiguration.objects.get(config_name='GOBOLT.CLIENT_ID').config_value
            CLIENT_SECRET = JobConfiguration.objects.get(config_name='GOBOLT.CLIENT_SECRET').config_value
        except JobConfiguration.DoesNotExist:
            GoBolt_URL = config('GoBolt_URL')
            GRANT_TYPE = config('GRANT_TYPE')
            CLIENT_ID = config('CLIENT_ID')
            CLIENT_SECRET = config('CLIENT_SECRET')

        payload = {
            "grant_type": GRANT_TYPE,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET
        }

        url = GoBolt_URL + 'oauth/token'

        headers = {"content-type": "application/x-www-form-urlencoded"}
        response = requests.request("POST", url, data=payload, headers=headers).json()

        if response.ok:
            return response
        else:
            return ''

    def refresh_auth_token(self, auth_token):
        response = self.auth_post_request()
        if response:
            auth_token.token = response.get('access_token', '')
            auth_token.provider = 'GoBolt'
            auth_token.token_creation_time = timezone.now()
            auth_token.expire_time = response.get('expires_in', 0)
            auth_token.save()
        return auth_token

    def create_auth_token(self):
        response = self.auth_post_request()
        if response:
            return AuthUserToken.objects.create(
                token = response.get('access_token', ''),
                provider='GoBolt',
                token_creation_time = timezone.now(),
                expire_time = response.get('expires_in', 0)  
            )
        else:
            return None
