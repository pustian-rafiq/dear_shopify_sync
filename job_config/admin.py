from django.contrib import admin
from job_config.models import JobConfiguration, AuthUserToken
# Register your models here.
class AuthUserTokenAdmin(admin.ModelAdmin):
    list_display = ['token', 'provider', 'token_creation_time', 'expire_time','updated_at']
    search_fields = ['provider']

admin.site.register(AuthUserToken, AuthUserTokenAdmin) 

class JobConfigurationAdmin(admin.ModelAdmin):
	list_display = ['config_name', 'config_value']
	search_fields = ['config_name']
	# readonly_fields=('config_name', )



admin.site.register(JobConfiguration, JobConfigurationAdmin)
