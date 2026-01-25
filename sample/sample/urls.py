from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve


urlpatterns = [
    path('admin/permit/', include('bazis.contrib.permit.urls')),
    path('admin/', admin.site.urls),
]

if settings.DEBUG:
    urlpatterns += [
        re_path(r'^media/(?P<path>.*)$', serve, dict(document_root=settings.MEDIA_ROOT)),
        re_path(r'^static/(?P<path>.*)$', serve, dict(document_root=settings.STATIC_ROOT)),
    ]
