import pytest

from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
#  Imports a simulated browser tool used in testing to send API requests (like POST or GET) to your endpoints.
from django.test import TestCase
# Imports the framework used to write and run automated tests that automatically reset the database after each test run.

User = get_user_model()

@pytest.mark.django_db #grants the test permission to safely interact with a temporary test database.
def test_user_registration(): #This function is an automated test that verifies if your user registration API endpoint works correctly.
    client = APIClient()

    # simulates a frontend user submitting registration details (username, email, password) 
    # as JSON to the /api/auth/register/ URL.
    response = client.post(
        "/api/auth/register/",
        {
             "username": "testuser",
            "email": "test@example.com",
            "password": "strongpassword123",
        },
        format="json",
    )

    assert response.status_code == 201
    #  checks that the server successfully created the new account (HTTP 201 Created).
    assert User.objects.filter(
        username = "testuser"
    ).exists()
    #double-checks the database to confirm the user "testuser" was actually saved.


@pytest.mark.django_db
def test_password_is_hashed():
    #creates a user in the test database with the plain-text password "secretpassword123".
    user = User.objects.create_user(
         username="hasheduser",
        email="hashed@example.com",
        password="secretpassword123",
    )

    assert user.password !=  "secretpassword123"
    #  ensures that the saved password string has been scrambled into an unreadable hash and is no longer stored as raw text.

    assert user.check_password("secretpassword123")
    #  uses Django's built-in cryptographic tool to double-check that the scrambled hash still accurately verifies and matches the original "secretpassword123" during login.

