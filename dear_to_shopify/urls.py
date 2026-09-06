"""dear_to_shopify URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.1/topics/http/urls/
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "Frankie4 Integration Platform"
admin.site.site_title = "Frankie4 Integration Platform Admin Portal"
admin.site.index_title = "Welcome to Frankie4 Integration Platform"


urlpatterns = [
    path('admin/', admin.site.urls),
    path('dear_cost_sync/', include('dear_cost_sync.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
