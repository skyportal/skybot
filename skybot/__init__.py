"""skybot — generic SkyPortal API client, reusable across instances.

    from skybot import SkyPortalClient
    sp = SkyPortalClient(base_url="https://fritz.science", token=TOKEN)
    sp = SkyPortalClient(base_url="https://skyportal-icare.ijclab.in2p3.fr",
                         token=ICARE_TOKEN, name="icare")
    me = sp.get_user_profile()

Instance-specific policy (taxonomy ids, group/filter ids, science logic) belongs
in the consuming bot (fritzbot for fritz.science, icarebot for ICARE), not here.
"""

from .client import SkyPortalClient, SkyPortalError

__all__ = ["SkyPortalClient", "SkyPortalError"]
__version__ = "0.1.0"
