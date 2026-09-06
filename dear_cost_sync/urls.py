from django.urls import path

from dear_cost_sync import views

urlpatterns = [
    path("health/", views.health, name="dear_cost_sync_health"),
    path("beat/", views.beat_info, name="dear_cost_sync_beat"),
    path("runs/", views.list_runs, name="dear_cost_sync_runs"),
    path("run/daily/", views.run_daily, name="dear_cost_sync_run_daily"),
    path("run/weekly/", views.run_weekly, name="dear_cost_sync_run_weekly"),
    path("run/manual/", views.run_manual, name="dear_cost_sync_run_manual"),
    path("unlock/", views.unlock, name="dear_cost_sync_unlock"),
]
