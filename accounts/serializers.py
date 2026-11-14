from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers


User = get_user_model()

class MeSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    username = serializers.CharField()
    email = serializers.EmailField()

class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True,
        min_length=8,
        max_length=128,
        trim_whitespace=False,
    )
    email = serializers.EmailField(
        required=True,
        allow_blank=False,
        max_length=254,
    )

    class Meta:
        model = User
        fields = [
            "username",
            "email",
            "password",
        ]
        extra_kwargs = {
            "username": {
                "required": True,
                "allow_blank": False,
                "max_length": 150,
            },
        }

    def validate_password(self, value):
        username = self.initial_data.get("username", "")
        email = self.initial_data.get("email", "")
        user = User(
            username=username if isinstance(username, str) else "",
            email=email if isinstance(email, str) else "",
        )
        try:
            validate_password(value, user=user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(
                exc.messages
            ) from exc
        return value

    def create(self, validated_data):
        return User.objects.create_user(
            username=validated_data["username"],
            email=validated_data["email"],
            password=validated_data["password"],
        )
    