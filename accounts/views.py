from rest_framework import generics , permissions
# generics (pre-built views to easily Create, Read, Update, or Delete database data) and
#  permissions (security rules to control who can access those views).
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import RegisterSerializer

class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer

class MeView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response({
            "id": request.user.id,
            "username": request.user.username,
            "email": request.user.email,
        })