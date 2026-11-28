"""URL routing for accounts module (docs/05-Architecture-dan-API.md §3.1)."""

from django.urls import path

from apps.accounts import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.LabTrackLoginView.as_view(), name="login"),
    path("logout/", views.LabTrackLogoutView.as_view(), name="logout"),
    path("register/", views.register_view, name="register"),
    path("profile/", views.profile_view, name="profile"),
    path("users/", views.user_list_view, name="user_list"),
    path("users/create/", views.user_create_view, name="user_create"),
    path("users/<int:pk>/edit/", views.user_edit_view, name="user_edit"),
]
