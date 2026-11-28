"""URL routing for apps.loans (Hybrid Online & Walk-In Loans)."""

from django.urls import path

from apps.loans import views

app_name = "loans"

urlpatterns = [
    path("", views.loan_list_view, name="loan_list"),
    path("request/", views.loan_request_view, name="loan_request"),
    path("walk-in/", views.loan_walk_in_view, name="loan_walk_in"),
    path("<int:pk>/", views.loan_detail_view, name="loan_detail"),
    path("<int:pk>/approve/", views.loan_approve_view, name="loan_approve"),
    path("<int:pk>/reject/", views.loan_reject_view, name="loan_reject"),
    path("<int:pk>/handover/", views.loan_handover_view, name="loan_handover"),
    path("<int:pk>/cancel/", views.loan_cancel_view, name="loan_cancel"),
    path("<int:pk>/return/", views.loan_return_view, name="loan_return"),
]
