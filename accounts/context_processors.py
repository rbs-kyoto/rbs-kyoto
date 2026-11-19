from .audience import audience_of, is_club_editor, is_club_member


def audience(request):
    """テンプレートで立場を見るための変数。{% if is_club_member %} や {% if is_club_editor %} のように使う。"""
    user = getattr(request, "user", None)
    is_revise_proofreader = False
    if getattr(user, "is_authenticated", False):
        try:
            from revise.models import ProofreadRole

            is_revise_proofreader = ProofreadRole.objects.filter(user=user).exists()
        except Exception:
            is_revise_proofreader = False
    return {
        "viewer_audience": audience_of(user),
        "is_club_member": is_club_member(user),
        "is_club_editor": is_club_editor(user),
        "is_revise_proofreader": is_revise_proofreader,
    }
