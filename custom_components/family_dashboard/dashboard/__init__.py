"""Dashboard generation/registration system.

See `registry.py` (template + registry system - builds the multi-view Lovelace config from
each module's dashboard-template contribution function) and `register.py` (storage-mode
Lovelace dashboard registration - see its module docstring for a correction to an earlier
session's wrong assumption about the registration API). Wired into `__init__.py`'s
`async_setup_entry`, run at the end of every entry setup.

Being filled in one view per session - see `registry.py`'s module docstring for what's built
so far and what's still deliberately deferred.
"""
