try:
    from importlib.metadata import PackageNotFoundError, version
    __version__ = version('bazis-permit')
except PackageNotFoundError:
    __version__ = 'dev'


"""
TODO: there is a problem now:
if the add action is available for an object, it can be added with a reference to
an external object that the user does not have access to.
this happens because the object does not have filled selectors at the addition stage.

we need a solution that will allow checking the availability of related objects
at the stage of adding or editing the main object.

that is, we need a solution that will make such a permission work:
'entity.extended_entity.item.add.author_parent', # only those who are the author of the
parent record can add entries

"""
