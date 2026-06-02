# skybot

**Generic SkyPortal API client.** One small dependency-light package for the
baseline interactions with *any* SkyPortal deployment.

```python
from skybot import SkyPortalClient

fritz = SkyPortalClient("https://fritz.science", FRITZ_TOKEN, name="fritz")
icare = SkyPortalClient("https://skyportal-icare.ijclab.in2p3.fr", ICARE_TOKEN, name="icare")

src = icare.get_source("GCN-260117_194305",
                       include_classifications=True, include_comments=True)
icare.set_redshift("GCN-260117_194305", 0.071, redshift_error=0.002)
icare.submit_classification(obj_id="GCN-260117_194305", classification="Ic-BL",
                            taxonomy_id=<icare_taxonomy_id>, probability=0.9,
                            origin="icarebot")
```
