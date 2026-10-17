"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path , include
from rest_framework_simplejwt.views import(
    TokenObtainPairView,
    TokenRefreshView,
)


urlpatterns = [
    path('admin/', admin.site.urls),
    path("api/", include("core.urls")),
    path("api/", include("events.urls")),
    path(
        "api/auth/",
        include("accounts.urls"),
    ),
    path("api/bookings/", include("bookings.urls")),

    path(
        "api/auth/token",
        TokenObtainPairView.as_view(), 
        # built-in Django view from the Simple JWT library that processes a user's username and password via a POST request and returns two JSON Web Tokens: an Access Token (for authorizing API requests) and a Refresh Token (for generating new access tokens).
        name = "token_obtain_pair",
    ),
    path(
        "api/auth/token/refresh/",
        TokenRefreshView.as_view(),
        name = "token_refresh",
    ),
]
