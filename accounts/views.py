from rest_framework import generics , permissions
# generics (pre-built views to easily Create, Read, Update, or Delete database data) and
#  permissions (security rules to control who can access those views).
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from drf_spectacular.utils import extend_schema
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from config.throttling import SafeScopedRateThrottle
from .serializers import RegisterSerializer, MeSerializer

class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]
    throttle_classes = [SafeScopedRateThrottle]
    throttle_scope = "registration"


class LoginView(TokenObtainPairView):
    permission_classes = [AllowAny]
    throttle_classes = [SafeScopedRateThrottle]
    throttle_scope = "login"


class RefreshTokenView(TokenRefreshView):
    permission_classes = [AllowAny]
    throttle_classes = [SafeScopedRateThrottle]
    throttle_scope = "auth_refresh"


class MeView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        responses={200: MeSerializer},
        description="Retrieve the currently authenticated user's details.",
        tags=["Authentication"],
    )
    def get(self, request):
        return Response({
            "id": request.user.id,
            "username": request.user.username,
            "email": request.user.email,
        })