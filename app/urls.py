from django.contrib import admin
from django.urls import path

from app.views import admin_dashboard


urlpatterns = [

    path(
        'admin/dashboard/',
        admin_dashboard,
        name='admin_dashboard'
    ),

    path(
        'admin/',
        admin.site.urls
    ),
]