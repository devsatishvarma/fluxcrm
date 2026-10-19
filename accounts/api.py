"""Account, contact, and conversion API."""

from django.core.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.conversion import ConversionChoiceRequired, convert_lead
from accounts.models import Account, Contact
from accounts.services import create_account, create_contact
from core.access import get_scoped, scoped
from core.api import CappedPagination, parse_page_size


def account_payload(account):
    return {
        "id": str(account.pk),
        "external_id": account.external_id,
        "name": account.name,
        "account_type": account.account_type,
        "parent": None if account.parent_id is None else str(account.parent_id),
        "website_url": account.website_url,
        "address": account.address or {},
        "website_domain": account.website_domain,
        "owner": account.owner_id,
        "status": account.status,
        "converted_from_lead": (
            None
            if account.converted_from_lead_id is None
            else str(account.converted_from_lead_id)
        ),
        "version": account.version,
    }


def contact_payload(contact):
    return {
        "id": str(contact.pk),
        "external_id": contact.external_id,
        "first_name": contact.first_name,
        "last_name": contact.last_name,
        "title": contact.title,
        "email": contact.email,
        "work_phone": contact.work_phone,
        "mobile_phone": contact.mobile_phone,
        "address": contact.address or {},
        "account": str(contact.account_id),
        "is_primary": contact.is_primary,
        "reports_to": (
            None if contact.reports_to_id is None else str(contact.reports_to_id)
        ),
        "owner": contact.owner_id,
        "converted_from_lead": (
            None
            if contact.converted_from_lead_id is None
            else str(contact.converted_from_lead_id)
        ),
        "version": contact.version,
    }


class AccountListView(APIView):
    def get(self, request):
        parse_page_size(request.query_params.get("page_size"))
        paginator = CappedPagination()
        page = paginator.paginate_queryset(
            scoped(Account.objects.select_related("owner"), request.user).order_by(
                "name"
            ),
            request,
            view=self,
        )
        return paginator.get_paginated_response(
            [account_payload(account) for account in page]
        )

    def post(self, request):
        account = create_account(
            actor=request.user,
            data=request.data,
            request_id=getattr(request, "request_id", ""),
        )
        return Response(account_payload(account), status=201)


class AccountDetailView(APIView):
    def get(self, request, account_id):
        account = get_scoped(Account, request.user, account_id)
        return Response(account_payload(account))


class ContactListView(APIView):
    def get(self, request):
        parse_page_size(request.query_params.get("page_size"))
        paginator = CappedPagination()
        queryset = scoped(Contact.objects.select_related("owner"), request.user)
        if request.query_params.get("account"):
            queryset = queryset.filter(account_id=request.query_params.get("account"))
        page = paginator.paginate_queryset(queryset, request, view=self)
        return paginator.get_paginated_response(
            [contact_payload(contact) for contact in page]
        )

    def post(self, request):
        contact = create_contact(
            actor=request.user,
            data=request.data,
            request_id=getattr(request, "request_id", ""),
        )
        return Response(contact_payload(contact), status=201)


class LeadConvertView(APIView):
    def post(self, request, lead_id):
        try:
            result = convert_lead(
                actor=request.user,
                lead_id=lead_id,
                version=request.data.get("version"),
                data=request.data,
                request_id=getattr(request, "request_id", ""),
            )
        except ConversionChoiceRequired as exc:
            return Response(exc.payload, status=422)
        except ValidationError:
            raise
        return Response(result, status=200)
