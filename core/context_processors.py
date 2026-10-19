"""Template values shared by every page."""


def company(request):
    """The configured company, used for the name shown in the shell."""
    from identity.models import CompanySettings

    return {"company": CompanySettings.objects.first()}
