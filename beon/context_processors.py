from .models import BeonPresence, BeonSession, BeonSessionMember


def beon_common(request):
    common = {
        "broadcast_status": "待機",
        "event_name": "セッション未選択",
        "operation_status": "待機中",
        "area_navigation": [],
        "progress_items": [],
        "members": [],
        "output_status": "なし",
        "waiting_count": 0,
        "unread_count": 0,
        "roles": [],
        "categories": [],
    }

    current_session = None
    current_role = None
    has_next_session = False

    if request.user.is_authenticated:
        presence = (
            BeonPresence.objects
            .select_related("session", "session__category")
            .filter(user=request.user)
            .first()
        )
        if presence:
            current_session = presence.session
            common["event_name"] = current_session.category.name
            common["broadcast_status"] = current_session.get_status_display()
            common["operation_status"] = current_session.get_status_display()

            assignments = list(
                current_session.assignments.select_related("user")
            )
            for assignment in assignments:
                if assignment.user_id == request.user.pk:
                    current_role = assignment.get_role_display()

            online_user_ids = set(
                BeonPresence.objects.filter(
                    session=current_session
                ).values_list("user_id", flat=True)
            )
            common["members"] = [
                {
                    "name": item.user.get_full_name() or item.user.get_username(),
                    "is_online": item.user_id in online_user_ids,
                    "role": item.get_role_display(),
                }
                for item in assignments
            ]

            next_candidates = BeonSession.objects.filter(
                category=current_session.category,
                order__gt=current_session.order,
                assignments__user=request.user,
                status__in=(
                    BeonSession.Status.READY,
                    BeonSession.Status.RUNNING,
                ),
            ).distinct().order_by("order", "id")

            required_roles = {
                BeonSessionMember.Role.CHIEF,
                BeonSessionMember.Role.DIRECTOR,
                BeonSessionMember.Role.ANNOUNCER,
            }
            has_next_session = any(
                set(candidate.assignments.values_list("role", flat=True)) == required_roles
                for candidate in next_candidates
            )

    return {
        "common": common,
        "beon_current_session": current_session,
        "beon_current_role": current_role,
        "beon_has_next_session": has_next_session,
    }
