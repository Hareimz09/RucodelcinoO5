from django.urls import path

from . import views


urlpatterns = [
    path('', views.home, name='home'),
    path('hats/', views.hats_constructor, name='hats_constructor'),
    path('jewelry/', views.jewelry_constructor, name='jewelry_constructor'),
    path('api/tryon/', views.tryon_api, name='tryon_api'),
    path('contact/', views.contact, name='contact'),
    path('registration/', views.registration, name='registration'),
    path('login/', views.login, name='login'),
    path('forgot-password/', views.forgot_password, name='forgot_password'),
    path('logout/', views.logout, name='logout'),
    path('about05/', views.about05, name='about05'),
    path('aboutstore/', views.aboutstore, name='aboutstore'),
    path('account/', views.account, name='account'),
    path('extra-generations/', views.extra_generations, name='extra_generations'),
    path('master-chat/', views.master_chat, name='master_chat'),
    path('master-recovery-requests/', views.master_recovery_requests, name='master_recovery_requests'),
    path('privacy/', views.privacy, name='privacy'),
]
