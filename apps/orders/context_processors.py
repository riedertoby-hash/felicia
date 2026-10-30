def cart(request):
    org = getattr(request, "org", None)
    if org is None or org.kind != "customer" or not request.user.is_authenticated:
        return {}
    from .services import cart_count

    return {"cart_count": cart_count(org, request.user)}
