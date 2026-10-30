def organization(request):
    membership = getattr(request, "membership", None)
    perms = set(membership.role.permissions) if membership else set()
    return {
        "current_org": getattr(request, "org", None),
        "current_membership": membership,
        "org_perms": perms,
        "user_memberships": getattr(request, "memberships", []),
    }
