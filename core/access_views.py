"""Teams, role grants, audit search, export, and administrator review."""

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from core.policy import ACTIONS, OBJECTS, SCOPES, AccessDenied, allows, require_action
from core.services import (
    authorize_import,
    request_export,
    review_administrators,
    save_team,
    set_user_manager,
    update_role_grants,
    visible_audit_events,
)
from identity.models import Role, Team, User


def _guard(user, object_key, action):
    try:
        require_action(user, object_key, action)
    except AccessDenied:
        return HttpResponse(status=403)
    return None


def _request_id(request):
    return getattr(request, "request_id", "")


def parse_grants(post):
    objects = {}
    for key in OBJECTS:
        selected = set(post.getlist(f"{key}_action"))
        actions = "".join(letter for letter in ACTIONS if letter in selected)
        scope = post.get(f"{key}_scope") or "OWN"
        if scope not in SCOPES:
            raise ValidationError({key: "Choose a valid scope."})
        entry = {"actions": actions, "scope": scope}
        if key == "deal" and post.get("deal_create") == "sql_conversion":
            entry["create"] = "sql_conversion"
        objects[key] = entry
    return {"version": 1, "objects": objects}


def grant_rows(role):
    stored = role.permissions or {}
    if stored.get("version") != 1:
        from core.policy import ROLE_SPECS

        stored = ROLE_SPECS.get(role.key, {}).get("permissions", {})
    objects = stored.get("objects") or {}
    rows = []
    for key in OBJECTS:
        raw = objects.get(key) or {}
        rows.append(
            {
                "key": key,
                "actions": list(ACTIONS),
                "selected": set(raw.get("actions") or ""),
                "scope": raw.get("scope") or "OWN",
                "create": raw.get("create") or "",
            }
        )
    return rows


@login_required
def team_list(request: HttpRequest) -> HttpResponse:
    if not (allows(request.user, "user", "R") or allows(request.user, "user", "A")):
        return _guard(request.user, "user", "R")
    if allows(request.user, "user", "A"):
        teams = Team.objects.select_related("manager").order_by("name")
    else:
        teams = (
            Team.objects.filter(Q(manager=request.user) | Q(members=request.user))
            .select_related("manager")
            .distinct()
            .order_by("name")
        )
    return render(
        request,
        "core/team_list.html",
        {
            "teams": teams,
            "can_administer": allows(request.user, "user", "A"),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def team_edit(request: HttpRequest, team_id=None) -> HttpResponse:
    denied = _guard(request.user, "user", "A")
    if denied:
        return denied
    team = Team() if team_id is None else get_object_or_404(Team, pk=team_id)
    users = User.objects.filter(is_active=True).order_by("display_name")
    error = ""
    if request.method == "POST":
        manager = None
        raw_manager = request.POST.get("manager")
        if raw_manager:
            manager = users.filter(pk=raw_manager).first()
            if manager is None:
                error = "Select an active manager."
        if not error:
            try:
                save_team(
                    actor=request.user,
                    team=team,
                    name=request.POST.get("name", ""),
                    manager=manager,
                    member_ids=request.POST.getlist("members"),
                    active=request.POST.get("active") == "1",
                    request_id=_request_id(request),
                )
            except ValidationError as exc:
                error = "; ".join(exc.messages)
            else:
                return redirect("core:teams")
    selected = set(team.members.values_list("pk", flat=True)) if team.pk else set()
    return render(
        request,
        "core/team_form.html",
        {
            "team": team,
            "users": users,
            "selected": selected,
            "error": error,
        },
    )


@login_required
def role_list(request: HttpRequest) -> HttpResponse:
    denied = _guard(request.user, "settings", "A")
    if denied:
        return denied
    return render(
        request,
        "core/role_list.html",
        {"roles": Role.objects.order_by("name")},
    )


@login_required
@require_http_methods(["GET", "POST"])
def role_edit(request: HttpRequest, role_id: int) -> HttpResponse:
    denied = _guard(request.user, "settings", "A")
    if denied:
        return denied
    role = get_object_or_404(Role, pk=role_id)
    error = ""
    if request.method == "POST":
        try:
            update_role_grants(
                actor=request.user,
                role=role,
                permissions=parse_grants(request.POST),
                request_id=_request_id(request),
            )
        except ValidationError as exc:
            error = "; ".join(exc.messages)
        else:
            return redirect("core:roles")
    return render(
        request,
        "core/role_form.html",
        {
            "role": role,
            "rows": grant_rows(role),
            "scopes": SCOPES,
            "error": error,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def administrator_review(request: HttpRequest) -> HttpResponse:
    denied = _guard(request.user, "user", "A")
    if denied:
        return denied
    admins = (
        User.objects.filter(role__key="ADMIN")
        .select_related("role")
        .order_by("display_name")
    )
    reviewed = False
    if request.method == "POST":
        review_administrators(actor=request.user, request_id=_request_id(request))
        reviewed = True
    return render(
        request,
        "core/administrator_review.html",
        {"admins": admins, "reviewed": reviewed},
    )


@login_required
@require_POST
def user_manager(request: HttpRequest, user_id: int) -> HttpResponse:
    denied = _guard(request.user, "user", "A")
    if denied:
        return denied
    user = get_object_or_404(User, pk=user_id)
    raw = request.POST.get("manager")
    manager = None
    if raw:
        manager = User.objects.filter(pk=raw, is_active=True).first()
        if manager is None:
            return HttpResponse("Select an active manager.", status=422)
    try:
        set_user_manager(
            actor=request.user,
            user=user,
            manager=manager,
            request_id=_request_id(request),
        )
    except ValidationError as exc:
        return HttpResponse("; ".join(exc.messages), status=422)
    return redirect("core:user_list")


@login_required
@require_http_methods(["GET"])
def audit_list(request: HttpRequest) -> HttpResponse:
    denied = _guard(request.user, "audit", "R")
    if denied:
        return denied
    events = visible_audit_events(request.user)
    object_type = str(request.GET.get("object_type") or "").strip()
    object_id = str(request.GET.get("object_id") or "").strip()
    if object_type:
        events = events.filter(object_type=object_type)
    if object_id:
        events = events.filter(object_id=object_id)
    page = Paginator(events, 50).get_page(request.GET.get("page"))
    return render(
        request,
        "core/audit_list.html",
        {
            "page_obj": page,
            "query": request.GET,
            "show_snapshots": allows(request.user, "settings", "A"),
        },
    )


@login_required
@require_POST
def export_request(request: HttpRequest) -> HttpResponse:
    try:
        count = request_export(
            actor=request.user,
            object_key=request.POST.get("object", ""),
            query=request.POST.get("q", ""),
            request_id=_request_id(request),
        )
    except AccessDenied:
        return HttpResponse(status=403)
    except ValidationError as exc:
        return HttpResponse("; ".join(exc.messages), status=422)
    return HttpResponse(f"Export queued for {count} rows.", status=200)


@login_required
@require_POST
def import_authorize(request: HttpRequest) -> HttpResponse:
    try:
        authorize_import(
            actor=request.user,
            object_key=request.POST.get("object", ""),
            request_id=_request_id(request),
        )
    except AccessDenied:
        return HttpResponse(status=403)
    except ValidationError as exc:
        return HttpResponse("; ".join(exc.messages), status=422)
    return HttpResponse(status=204)
