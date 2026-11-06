from django.urls import path

from . import views

app_name = "equipment"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("list/", views.equipment_list, name="list"),
    path("register/", views.equipment_create, name="register"),
    path("import/", views.equipment_import, name="import"),
    path("search/", views.scan, name="scan"),
    path("scan/", views.scan, name="scan_camera"),
    path("q/<str:token>/", views.qr_lookup, name="qr_lookup"),
    path("item/<int:pk>/", views.equipment_detail, name="detail"),
    path("item/<int:pk>/edit/", views.equipment_edit, name="edit"),
    path("item/<int:pk>/history/", views.equipment_history, name="history"),
    path("item/<int:pk>/unregister/", views.unregister_equipment, name="unregister"),
    path("item/<int:pk>/reactivate/", views.reactivate_equipment, name="reactivate"),
    path("item/<int:pk>/qr/", views.qr_display, name="qr"),
    path("item/<int:pk>/qr.png", views.qr_download, name="qr_png"),
    path(
        "item/<int:pk>/qr.svg",
        views.qr_download,
        {"output_format": "svg"},
        name="qr_svg",
    ),
    path("lending/", views.usage_list, name="lending"),
    path("lending/register/", views.usage_create, name="lending_register"),
    path("lending/cart/add/", views.cart_add, name="cart_add"),
    path("lending/cart/add/<int:pk>/", views.cart_add, name="cart_add_item"),
    path("lending/cart/remove/<int:pk>/", views.cart_remove, name="cart_remove"),
    path("lending/<int:pk>/", views.usage_detail, name="usage_detail"),
    path("lending/<int:pk>/return-all/", views.loan_return_all, name="return_all"),
    path("activity/", views.activity, name="activity"),
    path("lending/<int:pk>/return/", views.return_usage, name="return"),
    path("categories/", views.category_list, name="categories"),
    path("locations/", views.location_list, name="locations"),
    path("locations/register/", views.location_create, name="location_register"),
    path("locations/<int:pk>/edit/", views.location_edit, name="location_edit"),
    path("settings/", views.settings_view, name="settings"),
]
